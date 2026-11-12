"""Dashboard Streamlit de ciclismo con datos de Garmin e intervals.icu.

Arranque:

    streamlit run app.py

La primera vez (o cuando caduque la sesión) hay que ejecutar antes:

    python main.py login
    python main.py sync-intervals --days 365
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from garmin_dashboard import analytics as an
from garmin_dashboard import health as health_analysis
from garmin_dashboard import (
    auth,
    config,
    db,
    health,
    intervals,
    planning,
    reports,
    streams,
    sync,
    ui,
)

st.set_page_config(
    page_title="Ciclismo Dashboard",
    page_icon="🚴",
    layout="wide",
    initial_sidebar_state="expanded",
)

CHART_HEIGHT = 360
PERIODS = [
    "Última semana",
    "Último mes",
    "Último trimestre",
    "6 meses",
    "Último año",
    "2 años",
    "Todo",
    "Personalizado",
]
FOCUS_OPTIONS = [
    "Ciclismo y rodillo",
    "Solo rodillo",
    "Solo ciclismo exterior",
    "Todos los deportes",
]

P = ui.PALETTE

# --------------------------------------------------------------------------- #
# Estilo y helpers compartidos
# --------------------------------------------------------------------------- #

ui.apply_theme()

_style = ui.style_figure
_empty_fig = ui.empty_figure
_metric_row = ui.metric_row
_fmt_date = ui.fmt_date
_fmt = ui.fmt
_fmt_signed = ui.fmt_signed
_zone_frame = ui.zone_frame
_zone_bar = ui.zone_bar
_form_status = ui.form_status
_wellness_figure = ui.wellness_figure
_stream_values = streams.stream_values
_plan_comparison_rows = planning.comparison_rows


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_activity_streams(activity_id: str) -> dict:
    """Descarga streams y cachea también el error para no repetirlo cada rerun.

    La API key actual recibe un 403 en este recurso. Sin esta caché, cada
    rerun de la pestaña Actividades volvía a pedir los streams y a fallar.
    """
    try:
        return {
            "streams": intervals.create_client().get_activity_streams(activity_id),
            "error": None,
        }
    except intervals.IntervalsError as exc:
        return {"streams": [], "error": str(exc)}


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_activity_fit(activity_id: str) -> dict:
    """Descarga y cachea el FIT generado de una actividad de intervals.icu."""
    try:
        return {"data": intervals.create_client().get_activity_fit_file(activity_id), "error": None}
    except intervals.IntervalsError as exc:
        return {"data": None, "error": str(exc)}
    except AttributeError:
        # A long-running Streamlit process can keep an older imported module
        # after this client method has been added on disk.
        return {
            "data": None,
            "error": "El cliente de intervals.icu cargado no incluye la descarga FIT. Reinicia la app para recargarlo.",
        }


# --------------------------------------------------------------------------- #
# Sincronización
# --------------------------------------------------------------------------- #


def _get_api() -> tuple[object | None, str | None]:
    if "garmin_api" not in st.session_state:
        with st.spinner("Conectando con Garmin..."):
            api, error = auth.try_login(interactive=False)
        st.session_state["garmin_api"] = api
        st.session_state["garmin_api_error"] = error
    return st.session_state.get("garmin_api"), st.session_state.get("garmin_api_error")


def _run_garmin_sync(kind: str, days: int) -> None:
    api, error = _get_api()
    if api is None:
        st.sidebar.error(error or "No hay sesión de Garmin.")
        return

    bar = st.sidebar.progress(0.0, text="Preparando...")

    def progress(done: int, total: int, message: str) -> None:
        bar.progress(min(done / max(total, 1), 1.0), text=message)

    conn = db.connect()
    try:
        if kind == "activities":
            result = sync.sync_activities(api, conn, progress=progress)
            st.sidebar.success(
                f"{result['saved']} actividades guardadas "
                f"({result['since']} → {result['until']})."
            )
        else:
            result = sync.sync_daily(api, conn, days=days, progress=progress)
            st.sidebar.success(f"{result['saved']} días de salud guardados.")
    except sync.SyncError as exc:
        st.sidebar.error(str(exc))
        return
    except Exception as exc:  # red de seguridad para no romper la app
        st.sidebar.error(f"Error inesperado: {exc}")
        return

    bar.empty()
    _load_frames.clear()
    st.rerun()


def _run_intervals_sync(days: int) -> None:
    bar = st.sidebar.progress(0.0, text="Preparando...")

    def progress(done: int, total: int, message: str) -> None:
        bar.progress(min(done / max(total, 1), 1.0), text=message)

    conn = db.connect()
    try:
        client = intervals.create_client()
        result = sync.sync_intervals(client, conn, days=days, progress=progress)
        st.sidebar.success(
            f"intervals.icu: {result['wellness']} días de wellness y "
            f"{result['activities']} actividades."
        )
    except (sync.SyncError, intervals.IntervalsError) as exc:
        st.sidebar.error(str(exc))
        return
    except Exception as exc:
        st.sidebar.error(f"Error inesperado: {exc}")
        return

    bar.empty()
    _load_frames.clear()
    st.rerun()


# --------------------------------------------------------------------------- #
# Periodo y filtros
# --------------------------------------------------------------------------- #


def _period_bounds(
    preset: str,
    activities: pd.DataFrame,
    wellness: pd.DataFrame,
    daily: pd.DataFrame,
) -> tuple[date, date]:
    today = date.today()
    known_dates: list[date] = []
    if not activities.empty:
        known_dates.extend([activities["date"].min(), activities["date"].max()])
    if not wellness.empty:
        known_dates.extend(
            [wellness["date"].min().date(), wellness["date"].max().date()]
        )
    if not daily.empty:
        known_dates.extend([daily["date"].min().date(), daily["date"].max().date()])

    if preset == "Última semana":
        return today - timedelta(days=6), today
    if preset == "Último mes":
        return today - timedelta(days=29), today
    if preset == "Último trimestre":
        return today - timedelta(days=89), today
    if preset == "90 días":
        return today - timedelta(days=89), today
    if preset == "6 meses":
        return today - timedelta(days=182), today
    if preset == "Último año":
        return today - timedelta(days=364), today
    if preset == "2 años":
        return today - timedelta(days=729), today
    if preset == "Todo":
        if known_dates:
            return min(known_dates), max(known_dates + [today])
        return today - timedelta(days=364), today
    return today - timedelta(days=364), today


def _focus_mask(df: pd.DataFrame, focus: str) -> pd.Series:
    if focus == "Solo rodillo":
        return df["is_cycling"] & df["indoor"]
    if focus == "Solo ciclismo exterior":
        return df["is_cycling"] & ~df["indoor"]
    if focus == "Ciclismo y rodillo":
        return df["is_cycling"]
    return pd.Series(True, index=df.index)


def _cycling_settings(settings: pd.DataFrame) -> pd.Series | None:
    if settings is None or settings.empty:
        return None
    for _, row in settings.iterrows():
        try:
            types = json.loads(row.get("types_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            types = []
        if any(item in an.CYCLING_TYPES for item in types):
            return row
    return settings.iloc[0]


@st.cache_data(ttl=300, show_spinner=False)
def _combined_activities(
    garmin_frame: pd.DataFrame, intervals_frame: pd.DataFrame
) -> pd.DataFrame:
    return an.combine_activities(garmin_frame, intervals_frame)


def _setting_value(settings_row: pd.Series | None, key: str) -> float | None:
    if settings_row is None:
        return None
    value = pd.to_numeric(
        pd.Series([settings_row.get(key)]), errors="coerce"
    ).iloc[0]
    if pd.isna(value) or value <= 0:
        return None
    return float(value)


def _zone_frame(
    zone_df: pd.DataFrame,
    settings_row: pd.Series | None,
    kind: str,
    *,
    indoor: bool = False,
) -> pd.DataFrame:
    """Añade a la tabla de zonas la etiqueta y el rango del modelo."""
    if zone_df.empty:
        return zone_df
    out = zone_df.copy()
    out["rango"] = ""
    zones = an.zone_model(settings_row, kind, indoor=indoor)
    for index, row in out.iterrows():
        try:
            position = int(str(row["zone"]).lstrip("Z")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= position < len(zones):
            out.at[index, "label"] = zones[position]["label"]
            out.at[index, "rango"] = zones[position]["range"]
    return out


def _zone_bar(
    zone_df: pd.DataFrame,
    kind: str,
    settings_row: pd.Series | None,
    height: int = 340,
    *,
    indoor: bool = False,
) -> go.Figure:
    zone_df = _zone_frame(zone_df, settings_row, kind, indoor=indoor)
    colors = an.HR_ZONE_COLORS if kind == "hr" else an.POWER_ZONE_COLORS
    fig = px.bar(
        zone_df,
        x="zone",
        y="minutes",
        color="zone",
        color_discrete_sequence=colors,
        text="minutes",
        custom_data=["label", "rango"],
        labels={"zone": "", "minutes": "minutos"},
    )
    fig.update_traces(
        texttemplate="%{text:.0f}",
        textposition="outside",
        hovertemplate=(
            "%{custom_data[0]}<br>%{custom_data[1]}<br>"
            "%{y:.0f} min<extra></extra>"
        ),
    )
    fig.update_layout(showlegend=False)
    return _style(fig, height=height)


def _form_status(tsb: float | None) -> str:
    if tsb is None or pd.isna(tsb):
        return "Sin datos de forma"
    if tsb < -10:
        return "Fatiga reciente por encima de la forma"
    if tsb <= 5:
        return "Carga reciente y forma en equilibrio"
    return "Forma por encima de la fatiga reciente"


def _wellness_figure(
    wellness: pd.DataFrame,
    daily: pd.DataFrame,
    start: date,
    end: date,
    visible_metrics: list[str] | None = None,
) -> go.Figure:
    """Gráfico de portada: carga, forma, sueño y FC en reposo."""
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.34, 0.22, 0.22, 0.22],
        specs=[[{}], [{}], [{}], [{}]],
        subplot_titles=(
            "Carga: CTL (aptitud) y ATL (fatiga)",
            "Forma: TSB",
            "Sueño",
            "FC en reposo",
        ),
    )

    visible = set(
        visible_metrics
        if visible_metrics is not None
        else ["CTL y ATL", "TSB", "Sueño", "FC reposo"]
    )
    has_wellness = not wellness.empty and wellness["ctl"].notna().any()
    if has_wellness and "CTL y ATL" in visible:
        fig.add_trace(
            go.Scatter(
                x=wellness["date"],
                y=wellness["ctl"],
                name="CTL · fitness",
                mode="lines",
                line=dict(color=P["ctl"], width=3.4),
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=wellness["date"],
                y=wellness["atl"],
                name="ATL · fatiga",
                mode="lines",
                line=dict(color=P["atl"], width=2.2),
            ),
            row=1,
            col=1,
        )
    if has_wellness and "TSB" in visible:
        fig.add_trace(
            go.Scatter(
                x=wellness["date"],
                y=wellness["tsb"],
                name="TSB · forma",
                mode="lines",
                line=dict(color=P["tsb"], width=2.0, dash="dot"),
                fill="tozeroy",
                fillcolor="rgba(167, 139, 250, 0.14)",
            ),
            row=2,
            col=1,
        )

    sleep_source = wellness if not wellness.empty else daily
    if "Sueño" in visible and not sleep_source.empty and "sleep_h" in sleep_source.columns:
        sleep = sleep_source.dropna(subset=["sleep_h"])
        if not sleep.empty:
            fig.add_trace(
                go.Bar(
                    x=sleep["date"],
                    y=sleep["sleep_h"],
                    name="Sueño (h)",
                    marker_color=P["sleep"],
                    opacity=0.55,
                ),
                row=3,
                col=1,
            )
            trend = sleep["sleep_h"].rolling(7, min_periods=2).mean()
            fig.add_trace(
                go.Scatter(
                    x=sleep["date"],
                    y=trend,
                    name="Media 7 días",
                    mode="lines",
                    line=dict(color=P["primary"], width=2.4),
                ),
                row=3,
                col=1,
            )

    rhr_source = wellness if not wellness.empty else daily
    if "FC reposo" in visible and not rhr_source.empty and "resting_hr" in rhr_source.columns:
        rhr = rhr_source.dropna(subset=["resting_hr"])
        if not rhr.empty:
            fig.add_trace(
                go.Scatter(
                    x=rhr["date"],
                    y=rhr["resting_hr"],
                    name="FC reposo (ppm)",
                    mode="lines+markers",
                    marker=dict(size=3.5),
                    line=dict(color=P["resting_hr"], width=1.8),
                ),
                row=4,
                col=1,
            )
            trend = rhr["resting_hr"].rolling(7, min_periods=2).mean()
            fig.add_trace(
                go.Scatter(
                    x=rhr["date"],
                    y=trend,
                    name="Media 7 días",
                    mode="lines",
                    line=dict(color=P["resting_hr"], width=2.2, dash="dash"),
                ),
                row=4,
                col=1,
            )

    fig.update_yaxes(title_text="CTL / ATL", row=1, col=1)
    fig.update_yaxes(title_text="TSB", row=2, col=1, zeroline=False)
    fig.add_hline(
        y=-30,
        row=2,
        col=1,
        line=dict(color="#EF4444", width=1.7, dash="dash"),
        annotation_text="−30",
        annotation_position="top right",
        annotation_font_color="#EF4444",
        annotation_font_size=11,
    )
    fig.add_hline(
        y=0,
        row=2,
        col=1,
        line=dict(color=P["primary"], width=1.8),
        annotation_text="0",
        annotation_position="top right",
        annotation_font_color=P["primary"],
        annotation_font_size=11,
    )
    fig.update_yaxes(title_text="horas", row=3, col=1)
    fig.update_yaxes(title_text="ppm", row=4, col=1)
    fig.update_xaxes(range=[start, end], tickformat="%d %b %y", row=4, col=1)
    fig.update_annotations(font=dict(size=12, color=P["muted"]))
    return _style(fig, height=620)


# --------------------------------------------------------------------------- #
# Datos
# --------------------------------------------------------------------------- #

AUTO_SYNC_META_KEY = "last_auto_sync"
AUTO_SYNC_STATUS_KEY = "last_auto_sync_status"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _last_auto_sync(conn) -> datetime | None:
    value = db.get_meta(conn, AUTO_SYNC_META_KEY)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _auto_sync_reason(conn, *, force: bool = False) -> tuple[bool, str]:
    """¿Toca sincronizar al arrancar? Devuelve ``(due, motivo)``."""
    if config.is_demo():
        return False, "Modo demo: sincronización automática omitida."
    if force:
        return True, ""
    if not config.AUTO_SYNC_ENABLED:
        return False, "Sincronización automática desactivada (GARMIN_AUTO_SYNC=0)."
    if config.AUTO_SYNC_TTL_MINUTES <= 0:
        return True, ""
    last = _last_auto_sync(conn)
    if last is None:
        return True, ""
    age_minutes = (_utc_now() - last).total_seconds() / 60
    if age_minutes >= config.AUTO_SYNC_TTL_MINUTES:
        return True, ""
    return False, (
        f"Última sincronización automática hace {age_minutes:.0f} min "
        f"(TTL {config.AUTO_SYNC_TTL_MINUTES} min)."
    )


def _mark_auto_sync(conn, message: str) -> None:
    db.set_meta(conn, AUTO_SYNC_META_KEY, _utc_now().isoformat(timespec="seconds"))
    db.set_meta(conn, AUTO_SYNC_STATUS_KEY, message)


def _run_startup_sync(conn) -> None:
    due, reason = _auto_sync_reason(
        conn, force=bool(st.session_state.pop("force_startup_sync", False))
    )
    if not due:
        st.session_state["startup_sync_messages"] = [reason] if reason else []
        return

    messages: list[str] = []
    days = config.AUTO_SYNC_DAYS
    sync_start = (date.today() - timedelta(days=days - 1)).isoformat()
    with st.spinner(f"Actualizando los últimos {days} días de Garmin e intervals.icu…"):
        api, login_error = auth.try_login(interactive=False)
        if api is not None:
            try:
                activity_result = sync.sync_activities(api, conn, since=sync_start)
                health_result = sync.sync_daily(api, conn, days=days, pause=0.1)
                messages.append(
                    f"Garmin actualizado: {activity_result['saved']} actividades y "
                    f"{health_result['saved']} días de salud."
                )
            except Exception as exc:
                messages.append(
                    f"No se pudo completar la sincronización Garmin: {exc}"
                )
        else:
            messages.append(
                f"Garmin no sincronizado: {login_error or 'sin sesión disponible'}"
            )

        if intervals.is_configured():
            try:
                result = sync.sync_intervals(
                    intervals.create_client(), conn, days=days
                )
                messages.append(
                    f"intervals.icu actualizado: {result['activities']} actividades y "
                    f"{result['wellness']} días de wellness."
                )
            except Exception as exc:
                messages.append(
                    f"No se pudo completar la sincronización intervals.icu: {exc}"
                )
        else:
            messages.append("intervals.icu sin sincronizar: falta INTERVALS_API_KEY.")
    _mark_auto_sync(conn, " · ".join(messages))
    _load_frames.clear()
    st.session_state["startup_sync_messages"] = messages


@st.cache_data(ttl=300, show_spinner=False)
def _load_frames(revision: str) -> tuple[pd.DataFrame, ...]:
    """Lee la BD una sola vez por revisión de datos; el TTL es una red extra."""
    del revision  # forma parte de la clave de caché, no se usa dentro
    cache_conn = db.connect()
    try:
        return (
            db.load_activities(cache_conn),
            db.load_intervals_activities(cache_conn),
            db.load_daily(cache_conn),
            db.load_intervals_wellness(cache_conn),
            db.load_intervals_settings(cache_conn),
        )
    finally:
        cache_conn.close()


@st.cache_data(ttl=300, show_spinner=False)
def _prepare_frames(revision: str) -> tuple[pd.DataFrame, ...]:
    """Evita volver a parsear el JSON y fusionar salud en cada rerun."""
    garmin_raw, intervals_raw, daily_raw, wellness_raw, settings_raw = _load_frames(
        revision
    )
    garmin_frame = an.prepare_activities(garmin_raw)
    intervals_frame = an.prepare_intervals_activities(intervals_raw)
    daily_frame = an.prepare_daily(daily_raw)
    intervals_wellness_frame = an.prepare_wellness(wellness_raw)
    wellness_frame = an.merge_health(intervals_wellness_frame, daily_frame)
    if not wellness_frame.empty and "weight" in wellness_frame.columns:
        wellness_frame["weight_observed"] = wellness_frame["weight"]
        wellness_frame["weight"] = wellness_frame["weight"].ffill()
    return (
        garmin_frame,
        intervals_frame,
        daily_frame,
        intervals_wellness_frame,
        wellness_frame,
        _cycling_settings(settings_raw),
    )


conn = db.connect()
if not st.session_state.get("startup_sync_done"):
    st.session_state["startup_sync_done"] = True
    _run_startup_sync(conn)

info = db.counts(conn)

(
    garmin,
    intervals_acts,
    daily,
    intervals_wellness,
    wellness,
    cycling_settings,
) = _prepare_frames(db.data_revision(conn))

has_garmin = not garmin.empty
has_intervals = not intervals_acts.empty or not intervals_wellness.empty


# --------------------------------------------------------------------------- #
# Barra lateral
# --------------------------------------------------------------------------- #

st.sidebar.title("🚴 Ciclismo Dashboard")
for startup_message in st.session_state.get("startup_sync_messages", []):
    st.sidebar.caption(startup_message)
st.sidebar.caption(
    f"{info['activities']} actividades Garmin · "
    f"{info['intervals_activities']} intervals.icu"
)
st.sidebar.caption(
    f"{info['intervals_wellness']} días de aptitud/salud intervals.icu"
)
last_auto_status = db.get_meta(conn, AUTO_SYNC_STATUS_KEY)
if last_auto_status:
    with st.sidebar.expander("Estado de sincronización"):
        st.caption(last_auto_status)
if not config.is_demo() and st.sidebar.button(
    "Sincronizar ahora", key="force_sync_now", width="stretch"
):
    st.session_state["force_startup_sync"] = True
    st.session_state["startup_sync_done"] = False
    st.rerun()

if config.DB_PATH.resolve() != (config.DATA_DIR / "garmin.db").resolve():
    st.sidebar.caption(f"BD: `{config.DB_PATH}`")

with st.sidebar.expander("Sincronizar", expanded=has_garmin is False):
    st.write("Garmin Connect")
    if st.button("Actividades Garmin", type="primary", width="stretch"):
        _run_garmin_sync("activities", 0)
    health_days = st.number_input(
        "Días de salud Garmin", min_value=1, max_value=365, value=30, step=7
    )
    if st.button("Salud y recuperación", width="stretch"):
        _run_garmin_sync("health", int(health_days))

    st.divider()
    st.write("intervals.icu")
    if intervals.is_configured():
        st.caption("`INTERVALS_API_KEY` configurada")
    else:
        st.caption("Añade `INTERVALS_API_KEY` al `.env`")
    intervals_days = st.number_input(
        "Días de intervals.icu",
        min_value=30,
        max_value=3650,
        value=365,
        step=30,
    )
    if st.button("Aptitud, zonas y actividades", width="stretch"):
        _run_intervals_sync(int(intervals_days))

    if st.button("Reconectar Garmin", width="stretch"):
        st.session_state.pop("garmin_api", None)
        st.session_state.pop("garmin_api_error", None)
        st.rerun()
    st.caption(
        "Si la sesión de Garmin caduca: `python main.py login` en una terminal."
    )

st.sidebar.divider()

if has_garmin and has_intervals:
    source_choice = st.sidebar.radio(
        "Actividades de",
        ["Ambas fuentes", "Solo Garmin", "Solo intervals.icu"],
        help="Filtra las actividades. Salud y forma usan la fuente disponible; verás su procedencia en cada vista.",
    )
elif has_intervals:
    source_choice = "Solo intervals.icu"
else:
    source_choice = "Solo Garmin"

if source_choice == "Solo Garmin":
    activities = garmin.copy()
elif source_choice == "Solo intervals.icu":
    activities = intervals_acts.copy()
else:
    activities = _combined_activities(garmin, intervals_acts)

if not activities.empty or not wellness.empty or not daily.empty:
    preset = st.sidebar.selectbox(
        "Periodo", PERIODS, index=PERIODS.index("Último trimestre"), key="global_period_v2"
    )
else:
    preset = "Todo"

if preset == "Personalizado":
    known_start = date.today() - timedelta(days=364)
    if not activities.empty:
        known_start = activities["date"].min()
    elif not wellness.empty:
        known_start = wellness["date"].min().date()
    picked = st.sidebar.date_input(
        "Rango de fechas",
        value=(max(known_start, date.today() - timedelta(days=730)), date.today()),
    )
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        start_date, end_date = picked
    else:
        start_date, end_date = picked, date.today()
else:
    start_date, end_date = _period_bounds(preset, activities, wellness, daily)

focus = st.sidebar.radio("Foco", FOCUS_OPTIONS, index=0)

filtered = an.filter_activities(activities, start_date, end_date)
if not filtered.empty:
    filtered = filtered[_focus_mask(filtered, focus)].copy()

filtered_daily = an.filter_daily(daily, start_date, end_date)
filtered_intervals_wellness = intervals_wellness[
    (intervals_wellness["date"] >= pd.Timestamp(start_date))
    & (intervals_wellness["date"] <= pd.Timestamp(end_date))
].copy()
filtered_wellness = wellness[
    (wellness["date"] >= pd.Timestamp(start_date))
    & (wellness["date"] <= pd.Timestamp(end_date))
].copy()
wellness_available = not filtered_wellness.empty


# --------------------------------------------------------------------------- #
# Cabecera
# --------------------------------------------------------------------------- #

st.title("🚴 Panel de ciclismo")
source_label = {
    "Ambas fuentes": "Garmin + intervals.icu",
    "Solo Garmin": "Garmin",
    "Solo intervals.icu": "intervals.icu",
}[source_choice]
st.caption(
    f"Del {start_date:%d/%m/%Y} al {end_date:%d/%m/%Y} · {source_label} · "
    f"{len(filtered)} sesiones · datos locales en SQLite"
)

if activities.empty and wellness.empty and daily.empty:
    st.info(
        "Todavía no hay datos.\n\n"
        "1. Crea un `.env` a partir de `.env.example`.\n"
        "2. Para Garmin: `python main.py login` y pulsa **Actividades Garmin**.\n"
        "3. Para intervals.icu: añade `INTERVALS_API_KEY` y pulsa "
        "**Aptitud, zonas y actividades**.\n\n"
        "También puedes probar con datos de ejemplo: "
        "`python scripts/seed_demo.py --force`."
    )
    st.stop()


# --------------------------------------------------------------------------- #
# Navegación del dashboard
# --------------------------------------------------------------------------- #

main_section = st.segmented_control(
    "Sección",
    ["Entrenamiento", "Recuperación", "Planificación"],
    default="Recuperación",
    key="main_section_v3",
    label_visibility="collapsed",
    width="stretch",
)
training_view = None
recovery_view = None
if main_section == "Entrenamiento":
    training_view = st.segmented_control(
        "Entrenamiento",
        ["Ciclismo", "Actividades"],
        default="Ciclismo",
        key="training_view_v3",
        label_visibility="collapsed",
        width="stretch",
    )
elif main_section == "Recuperación":
    recovery_view = st.segmented_control(
        "Recuperación",
        ["Forma", "Salud"],
        default="Forma",
        key="recovery_view_v3",
        label_visibility="collapsed",
        width="stretch",
    )


if main_section == "Recuperación" and recovery_view == "Forma":
    with st.container():
        recovery_source = (
            filtered_wellness if not filtered_wellness.empty else filtered_daily
        )
        st.caption(
            "La forma (CTL/ATL/TSB) procede de intervals.icu; Garmin puede completar sueño y recuperación."
            if not filtered_intervals_wellness.empty
            else "Fuente de sueño y recuperación: Garmin. No hay datos de forma de intervals.icu en este periodo."
        )
        recent_recovery = recovery_source[
            recovery_source["date"] >= pd.Timestamp(end_date - timedelta(days=6))
        ] if not recovery_source.empty else recovery_source
        sleep_mean = (
            pd.to_numeric(recent_recovery.get("sleep_h"), errors="coerce").mean()
            if "sleep_h" in recent_recovery else float("nan")
        )
        sleep_score_mean = (
            pd.to_numeric(recent_recovery.get("sleep_score"), errors="coerce").mean()
            if "sleep_score" in recent_recovery else float("nan")
        )
        resting_hr_mean = (
            pd.to_numeric(recent_recovery.get("resting_hr"), errors="coerce").mean()
            if "resting_hr" in recent_recovery else float("nan")
        )
        recovery_hrv_column = (
            "hrv" if "hrv" in recent_recovery else "hrv_last_night"
        )
        hrv_mean = (
            pd.to_numeric(recent_recovery[recovery_hrv_column], errors="coerce").mean()
            if recovery_hrv_column in recent_recovery else float("nan")
        )
        effective_ftp = (
            _setting_value(cycling_settings, "indoor_ftp")
            or _setting_value(cycling_settings, "ftp")
        )
        _metric_row(
            [
                ("Sueño medio · 7 días", f"{_fmt(sleep_mean, 1)} h", None),
                ("Calidad de sueño · 7 días", _fmt(sleep_score_mean), None),
                ("FC reposo · 7 días", f"{_fmt(resting_hr_mean)} ppm", None),
                ("HRV · 7 días", f"{_fmt(hrv_mean)} ms", None),
                ("FTP utilizado", f"{_fmt(effective_ftp)} W" if effective_ftp else "–", "Se prioriza el FTP interior; si no existe, se usa el FTP general."),
            ]
        )
        st.markdown(
            """**CTL (42 días)** resume la carga crónica y suele cambiar despacio. """
            "**ATL (7 días)** responde más rápido a la carga reciente. "
            "**TSB = CTL − ATL** compara ambas: un TSB negativo indica que la carga reciente "
            "supera la forma acumulada; uno positivo indica menor carga reciente. Son "
            "indicadores descriptivos, no una recomendación automática de entrenar o descansar." 
        )
        if not wellness_available:
            st.info(
                "No hay datos de aptitud de intervals.icu en el periodo. "
                "Pulsa **Sincronizar → Aptitud, zonas y actividades**."
            )
        else:
            form = filtered_wellness.dropna(subset=["ctl", "atl"])
            if form.empty:
                st.info(
                    "No hay CTL ni ATL en el periodo. intervals.icu no aporta "
                    "datos de carga para estas fechas; el resto de pestañas sigue "
                    "disponible."
                )
            else:
                latest = form.tail(1)
                first = form.head(1)
                ctl_delta = (
                    float(latest.iloc[0]["ctl"]) - float(first.iloc[0]["ctl"])
                    if not latest.empty and not first.empty
                    else None
                )
                _metric_row(
                    [
                        ("CTL actual", _fmt(latest.iloc[0]["ctl"], 1), None),
                        (
                            "Cambio CTL",
                            f"{ctl_delta:+.1f}".replace(".", ",")
                            if ctl_delta is not None
                            else "–",
                            "Diferencia en el periodo",
                        ),
                        ("ATL actual", _fmt(latest.iloc[0]["atl"], 1), None),
                        ("TSB actual", _fmt(latest.iloc[0]["tsb"], 1), None),
                        ("Ramp rate", _fmt(latest.iloc[0]["ramp_rate"], 1), "CTL por semana"),
                    ]
                )

                fig = make_subplots(
                    rows=2,
                    cols=1,
                    shared_xaxes=True,
                    vertical_spacing=0.12,
                    row_heights=[0.66, 0.34],
                    subplot_titles=("CTL y ATL · carga", "TSB · forma"),
                )
                fig.add_trace(
                    go.Scatter(
                        x=form["date"],
                        y=form["ctl"],
                        name="CTL · fitness",
                        line=dict(color=P["ctl"], width=3.2),
                    ),
                    row=1,
                    col=1,
                )
                recent_ctl = form[
                    form["date"] >= pd.Timestamp(end_date - timedelta(days=29))
                ].dropna(subset=["ctl"])
                ctl_week_estimate = None
                if len(recent_ctl) >= 3:
                    trend_days = (
                        recent_ctl["date"] - recent_ctl["date"].min()
                    ).dt.days.to_numpy()
                    ctl_slope, ctl_intercept = np.polyfit(
                        trend_days, recent_ctl["ctl"].to_numpy(), 1
                    )
                    fitted_ctl = ctl_intercept + ctl_slope * trend_days
                    ctl_week_estimate = float(
                        recent_ctl.iloc[-1]["ctl"] + ctl_slope * 7
                    )
                    fig.add_trace(go.Scatter(
                        x=recent_ctl["date"],
                        y=fitted_ctl,
                        mode="lines",
                        name="Tendencia CTL · 30 días",
                        line=dict(color=P["primary"], width=2, dash="dash"),
                    ), row=1, col=1)
                    fig.add_trace(go.Scatter(
                        x=[recent_ctl.iloc[-1]["date"], recent_ctl.iloc[-1]["date"] + pd.Timedelta(days=7)],
                        y=[float(recent_ctl.iloc[-1]["ctl"]), ctl_week_estimate],
                        mode="lines+markers",
                        name="CTL según tendencia · +7 días",
                        line=dict(color=P["primary"], width=2.5, dash="dot"),
                        marker=dict(size=7),
                    ), row=1, col=1)
                fig.add_trace(
                    go.Scatter(
                        x=form["date"],
                        y=form["atl"],
                        name="ATL · fatiga",
                        line=dict(color=P["atl"], width=2.2),
                    ),
                    row=1,
                    col=1,
                )
                fig.add_trace(
                    go.Scatter(
                        x=form["date"],
                        y=form["tsb"],
                        name="TSB · forma",
                        line=dict(color=P["tsb"], width=2, dash="dot"),
                        fill="tozeroy",
                        fillcolor="rgba(167, 139, 250, 0.14)",
                    ),
                    row=2,
                    col=1,
                )
                fig.update_yaxes(title_text="CTL / ATL", row=1, col=1)
                fig.update_yaxes(title_text="TSB", zeroline=False, row=2, col=1)
                fig.add_hline(
                    y=-30,
                    row=2,
                    col=1,
                    line=dict(color="#EF4444", width=1.7, dash="dash"),
                    annotation_text="−30",
                    annotation_position="top right",
                    annotation_font_color="#EF4444",
                    annotation_font_size=11,
                )
                fig.add_hline(
                    y=0,
                    row=2,
                    col=1,
                    line=dict(color=P["primary"], width=1.8),
                    annotation_text="0",
                    annotation_position="top right",
                    annotation_font_color=P["primary"],
                    annotation_font_size=11,
                )
                fig.update_xaxes(tickformat="%d %b %y", row=2, col=1)
                st.subheader("Evolución de la forma")
                if ctl_week_estimate is not None:
                    st.caption(
                        f"La línea discontinua resume la tendencia lineal del CTL en los últimos 30 días. "
                        f"Si esa tendencia continuara una semana, el CTL sería aproximadamente "
                        f"{_fmt(ctl_week_estimate, 1)}. Es una extrapolación descriptiva; "
                        "no incorpora entrenamientos futuros."
                    )
                fig.update_annotations(font=dict(size=12, color=P["muted"]))
                st.plotly_chart(_style(fig, height=500), width="stretch")

                forecast_rows = []
                latest_ctl_row = form.dropna(subset=["ctl", "atl"]).iloc[-1]
                projected_ctl = float(latest_ctl_row["ctl"])
                projected_atl = float(latest_ctl_row["atl"])
                missing_days = max((pd.Timestamp(end_date) - latest_ctl_row["date"]).days, 0)
                for _ in range(missing_days):
                    projected_ctl += (0.0 - projected_ctl) / 42.0
                    projected_atl += (0.0 - projected_atl) / 7.0
                for days_ahead in (1, 2, 3):
                    # Modelo de carga exponencial (CTL 42 días, ATL 7 días), suponiendo TSS=0.
                    # No extrapola tendencias ni incorpora sesiones futuras.
                    projected_ctl += (0.0 - projected_ctl) / 42.0
                    projected_atl += (0.0 - projected_atl) / 7.0
                    forecast_rows.append({
                        "Fecha": (end_date + timedelta(days=days_ahead)).strftime("%d/%m/%Y"),
                        "CTL estimado": round(projected_ctl, 1),
                        "ATL estimado": round(projected_atl, 1),
                        "TSB estimado": round(projected_ctl - projected_atl, 1),
                        "Peso (kg)": latest_ctl_row["weight"],
                    })
                st.subheader("Estimación para los próximos 3 días")
                st.caption("Escenario sin actividad (TSS=0): CTL y ATL decaen según el modelo de intervals.icu (42 y 7 días). El TSB se calcula como CTL − ATL. No extrapola tendencias ni añade entrenamientos; el peso mantiene el último valor registrado.")
                st.dataframe(pd.DataFrame(forecast_rows), hide_index=True, width="stretch")

                with st.expander("Simulador de CTL a partir de TSS", expanded=False):
                    sim_col, days_col = st.columns(2)
                    with sim_col:
                        simulated_tss = st.number_input("TSS medio diario previsto", min_value=0.0, max_value=1000.0, value=100.0, step=5.0)
                    with days_col:
                        simulated_days = st.number_input("Días con esa carga", min_value=1, max_value=42, value=1, step=1)
                    simulated_ctl = float(latest.iloc[0]["ctl"])
                    for _ in range(int(simulated_days)):
                        simulated_ctl += (float(simulated_tss) - simulated_ctl) / 42
                    st.metric("CTL estimado al final", _fmt(simulated_ctl, 1), delta=f"{simulated_ctl - float(latest.iloc[0]['ctl']):+.1f}".replace(".", ","))
                    st.caption("Modelo exponencial simplificado con constante de 42 días. Mantiene el TSS diario indicado durante el número de días seleccionado.")

                left, right = st.columns(2)
                with left:
                    st.subheader("Carga semanal de las sesiones")
                    load_df = (
                        filtered.dropna(subset=["training_load"])
                        .groupby("week", as_index=False)["training_load"]
                        .sum()
                        .sort_values("week")
                    )
                    if load_df.empty:
                        st.plotly_chart(_empty_fig("Sin carga registrada"), width="stretch")
                    else:
                        high_load = load_df["training_load"] >= load_df["training_load"].quantile(0.75)
                        fig = px.bar(
                            load_df,
                            x="week",
                            y="training_load",
                            color=high_load.map({True: "Carga semanal alta", False: "Carga habitual"}),
                            color_discrete_map={"Carga semanal alta": P["atl"], "Carga habitual": P["load"]},
                            labels={"week": "", "training_load": "carga"},
                        )
                        fig.update_traces(opacity=0.78)
                        fig.update_xaxes(tickformat="%d %b %y")
                        st.plotly_chart(_style(fig), width="stretch")
                        busiest = load_df.loc[high_load, "week"].dt.strftime("%d/%m").tolist()
                        if busiest:
                            st.caption("Semanas con carga en el cuartil superior del periodo: " + ", ".join(busiest[-4:]) + ".")

                if not filtered.empty:
                    complete_week_end = end_date - timedelta(days=end_date.weekday() + 1)
                    last_12_start = pd.Timestamp(complete_week_end - timedelta(days=83))
                    recent_activities = filtered[filtered["start"] >= last_12_start]
                    weekly_sessions = recent_activities.assign(
                        week=recent_activities["start"].dt.to_period("W-SUN").dt.start_time
                    ).groupby("week")["activity_id"].count()
                    weeks = pd.date_range(last_12_start.to_period("W-SUN").start_time, pd.Timestamp(complete_week_end).to_period("W-SUN").start_time, freq="W-MON")
                    low_weeks = [week.strftime("%d/%m") for week in weeks if weekly_sessions.get(week, 0) < 2]
                    if low_weeks:
                        st.info("Semanas completas con menos de 2 sesiones en el tramo reciente: " + ", ".join(low_weeks[-4:]) + ".")
                health_source = filtered_wellness if wellness_available else filtered_daily
                if health_source.empty:
                    st.warning("Sin registros de salud en el periodo seleccionado.")
                else:
                    health_recent = health_source[health_source["date"] >= pd.Timestamp(end_date - timedelta(days=29))]
                    health_columns = [column for column in ("sleep_h", "resting_hr", "hrv") if column in health_recent]
                    if health_columns and not health_recent.empty:
                        missing_share = health_recent[health_columns].isna().mean(axis=1).mean()
                        if missing_share >= 0.35:
                            st.warning(f"Datos de salud incompletos: faltan métricas en aproximadamente {missing_share:.0%} de los registros recientes.")

                with right:
                    st.subheader("Ramp rate")
                    ramp = form.dropna(subset=["ramp_rate"])
                    if ramp.empty:
                        st.plotly_chart(_empty_fig("Sin ramp rate"), width="stretch")
                    else:
                        fig = px.area(
                            ramp,
                            x="date",
                            y="ramp_rate",
                            labels={"date": "", "ramp_rate": "CTL / semana"},
                        )
                        fig.update_traces(line_color=P["tsb"], fillcolor="rgba(167,139,250,0.18)")
                        fig.update_xaxes(tickformat="%d %b %y")
                        st.plotly_chart(_style(fig), width="stretch")

                st.subheader("Últimos 30 días")
                recent = form.sort_values("date", ascending=False).head(30).copy()
                recent["Fecha"] = recent["date"].dt.strftime("%d/%m/%Y")
                view = recent[
                    ["Fecha", "ctl", "atl", "tsb", "ramp_rate", "sleep_h", "resting_hr", "hrv", "weight"]
                ].rename(
                    columns={
                        "ctl": "CTL",
                        "atl": "ATL",
                        "tsb": "TSB",
                        "ramp_rate": "Ramp rate",
                        "sleep_h": "Sueño (h)",
                        "resting_hr": "FC reposo",
                        "hrv": "HRV",
                        "weight": "Peso (kg)",
                    }
                )
                st.dataframe(view, hide_index=True, width="stretch")


    # ------------------------------- Ciclismo --------------------------------- #

if main_section == "Entrenamiento" and training_view == "Ciclismo":
    with st.container():
        cycling = filtered[filtered["is_cycling"]].copy()
        if cycling.empty:
            st.info("No hay sesiones de ciclismo en el periodo seleccionado.")
        else:
            bike_kpis = an.kpis(cycling)
            _metric_row(
                [
                    ("Salidas", f"{bike_kpis['sessions']}", None),
                    ("Distancia", f"{_fmt(bike_kpis['distance_km'], 1)} km", None),
                    ("Tiempo", an.format_duration(bike_kpis["duration_h"] * 60), None),
                    ("Desnivel +", f"{_fmt(bike_kpis['elevation_m'])} m", None),
                    (
                        "Potencia media",
                        f"{_fmt(bike_kpis['avg_power'])} W"
                        if pd.notna(bike_kpis["avg_power"])
                        else "–",
                        None,
                    ),
                ]
            )
            period_days = max((end_date - start_date).days + 1, 1)
            previous_end = start_date - timedelta(days=1)
            previous_start = previous_end - timedelta(days=period_days - 1)
            previous_cycling = activities[
                (activities["start"].dt.date >= previous_start)
                & (activities["start"].dt.date <= previous_end)
                & activities["is_cycling"]
            ].copy()
            if not previous_cycling.empty:
                previous_cycling = previous_cycling[
                    _focus_mask(previous_cycling, focus)
                ]
            previous_bike_kpis = (
                an.kpis(previous_cycling) if not previous_cycling.empty else None
            )
            compare_rows = []
            for label, field, unit in (
                ("Distancia", "distance_km", "km"),
                ("Tiempo", "duration_h", "h"),
                ("Desnivel +", "elevation_m", "m"),
            ):
                prior = previous_bike_kpis.get(field) if previous_bike_kpis else None
                current_value = bike_kpis[field]
                if prior is None:
                    delta = "Sin periodo anterior"
                    prior_label = "–"
                else:
                    diff = current_value - prior
                    percent = diff / abs(prior) * 100 if prior else None
                    delta = f"{diff:+.1f} {unit}".replace(".", ",")
                    if percent is not None:
                        delta += f" ({percent:+.0f}%)"
                    prior_label = f"{prior:.1f} {unit}".replace(".", ",")
                compare_rows.append({
                    "Métrica": label,
                    "Periodo anterior": prior_label,
                    "Cambio": delta,
                })
            st.caption(
                f"Comparación de ciclismo con los {period_days} días anteriores al periodo seleccionado."
            )
            st.dataframe(pd.DataFrame(compare_rows), hide_index=True, width="stretch")

            st.subheader("Curva de potencia")
            st.caption(
                "Compara la mejor potencia media de los últimos 30 días con el "
                "récord de cada duración de los últimos 6 meses. No es una predicción de rendimiento."
            )
            curve_source = garmin if source_choice != "Solo intervals.icu" else intervals_acts
            if not curve_source.empty:
                curve_start = (
                    pd.Timestamp(end_date) - pd.DateOffset(months=6)
                ).date()
                curve_source = curve_source[
                    (curve_source["date"] <= end_date)
                    & (curve_source["date"] >= curve_start)
                    & curve_source["is_cycling"]
                ].copy()
                curve_source = curve_source[_focus_mask(curve_source, focus)]
            recent_start = end_date - timedelta(days=29)
            recent_curve_source = curve_source[
                curve_source["date"] >= recent_start
            ] if not curve_source.empty else curve_source
            historical_curve = streams.power_curve_from_summary(curve_source)
            recent_curve = streams.power_curve_from_summary(recent_curve_source)
            if not historical_curve.empty:
                durations = historical_curve["duration_s"]
                duration_labels = durations.map(
                    lambda seconds: f"{seconds}s" if seconds < 60 else (
                        f"{seconds // 60} min" if seconds < 3600
                        else f"{seconds // 3600} h"
                    )
                )
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=durations,
                    y=historical_curve["watts"],
                    name="Últimos 6 meses",
                    mode="lines+markers",
                    customdata=duration_labels,
                    line={"color": P["muted"], "width": 2},
                    hovertemplate="%{customdata}<br>%{y:.0f} W<extra>Histórico</extra>",
                ))
                if not recent_curve.empty:
                    recent_labels = recent_curve["duration_s"].map(
                        lambda seconds: f"{seconds}s" if seconds < 60 else (
                            f"{seconds // 60} min" if seconds < 3600
                            else f"{seconds // 3600} h"
                        )
                    )
                    fig.add_trace(go.Scatter(
                        x=recent_curve["duration_s"],
                        y=recent_curve["watts"],
                        name="Últimos 30 días",
                        mode="lines+markers",
                        customdata=recent_labels,
                        line={"color": P["primary"], "width": 2.8},
                        hovertemplate="%{customdata}<br>%{y:.0f} W<extra>Últimos 30 días</extra>",
                    ))
                fig.update_xaxes(
                    type="log",
                    tickvals=durations,
                    ticktext=duration_labels,
                    title_text="Duración del esfuerzo",
                )
                fig.update_yaxes(title_text="Mejor potencia media (W)")
                fig.update_layout(legend={"orientation": "h", "y": 1.12})
                st.plotly_chart(_style(fig, height=340), width="stretch")
            else:
                st.info("No hay registros de mejor potencia por duración en el histórico. Garmin solo permite comparar esta curva si esos valores están incluidos en el resumen de actividad.")

            cycling["duration_h"] = cycling["duration_min"] / 60
            st.subheader("Volumen semanal")
            volume_mode = st.segmented_control(
                "Métrica de volumen",
                ["Horas", "Distancia"],
                default="Horas",
                key="weekly_volume_metric",
                label_visibility="collapsed",
            )
            volume_field = "duration_h" if volume_mode == "Horas" else "distance_km"
            volume_label = "horas" if volume_mode == "Horas" else "km"
            weekly_volume = an.weekly_volume(cycling, volume_field)
            if weekly_volume.empty:
                st.plotly_chart(_empty_fig("Sin datos"), width="stretch")
            else:
                fig = px.bar(
                    weekly_volume,
                    x="week",
                    y=volume_field,
                    color="sport",
                    color_discrete_map=an.SPORT_COLORS,
                    labels={"week": "", volume_field: volume_label, "sport": "Disciplina"},
                )
                fig.update_layout(barmode="stack")
                fig.update_xaxes(tickformat="%d %b %y")
                st.plotly_chart(_style(fig), width="stretch")

            left, right = st.columns(2)
            with left:
                st.subheader("Potencia media y normalizada")
                power = an.weekly_power(cycling)
                if power.empty:
                    st.plotly_chart(
                        _empty_fig("Sin datos de potencia. Sincroniza intervals.icu."),
                        width="stretch",
                    )
                else:
                    fig = go.Figure()
                    fig.add_trace(
                        go.Scatter(
                            x=power["week"],
                            y=power["avg_power_w"],
                            name="Potencia media",
                            mode="lines+markers",
                            line=dict(color=P["power_avg"], width=2.4),
                        )
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=power["week"],
                            y=power["weighted_avg_power_w"],
                            name="Potencia normalizada",
                            mode="lines+markers",
                            line=dict(color=P["power_normalized"], width=2.4),
                        )
                    )
                    fig.update_xaxes(tickformat="%d %b %y")
                    fig.update_yaxes(title="vatios")
                    st.plotly_chart(_style(fig), width="stretch")

            with right:
                st.subheader("Velocidad y FC")
                scatter = cycling.dropna(subset=["speed_kmh", "avg_hr"])
                if scatter.empty:
                    st.plotly_chart(_empty_fig("Sin datos suficientes"), width="stretch")
                else:
                    scatter = scatter.copy()
                    scatter["tipo"] = scatter["indoor"].map(
                        {True: "Rodillo", False: "Exterior"}
                    )
                    fig = px.scatter(
                        scatter,
                        x="avg_hr",
                        y="speed_kmh",
                        color="tipo",
                        size="duration_min",
                        color_discrete_map={
                            "Rodillo": an.SPORT_COLORS["Rodillo"],
                            "Exterior": an.SPORT_COLORS["Ciclismo"],
                        },
                        labels={
                            "avg_hr": "FC media (ppm)",
                            "speed_kmh": "velocidad media (km/h)",
                            "tipo": "",
                        },
                        hover_data=["activity_name"],
                    )
                    st.plotly_chart(_style(fig), width="stretch")

            st.subheader("Reparto por deporte y rodillo vs exterior")
            cycling["tipo"] = cycling["indoor"].map({True: "Rodillo", False: "Exterior"})
            compare = (
                cycling.groupby("tipo", as_index=False)
                .agg(
                    sesiones=("activity_id", "count"),
                    horas=("duration_min", lambda s: s.sum() / 60),
                    km=("distance_km", "sum"),
                    carga=("training_load", "sum"),
                    fc_media=("avg_hr", "mean"),
                    potencia_media=("avg_power_w", "mean"),
                )
                .sort_values("horas", ascending=False)
            )
            share_col, split_col = st.columns(2)
            with share_col:
                st.markdown("**Reparto por deporte · distancia**")
                sport_share = an.sport_breakdown(cycling, "distance_km")
                if sport_share.empty or sport_share["distance_km"].sum() <= 0:
                    st.plotly_chart(_empty_fig("Sin datos de distancia"), width="stretch")
                else:
                    fig = px.bar(
                        sport_share,
                        x="distance_km",
                        y="sport",
                        orientation="h",
                        color="sport",
                        color_discrete_map=an.SPORT_COLORS,
                        labels={"sport": "", "distance_km": "km"},
                    )
                    fig.update_layout(showlegend=False)
                    fig.update_yaxes(autorange="reversed")
                    st.plotly_chart(_style(fig), width="stretch")
            with split_col:
                st.markdown("**Horas de rodillo y exterior**")
                fig = px.bar(
                    compare,
                    x="tipo",
                    y="horas",
                    color="tipo",
                    text="horas",
                    color_discrete_map={
                        "Rodillo": an.SPORT_COLORS["Rodillo"],
                        "Exterior": an.SPORT_COLORS["Ciclismo"],
                    },
                    labels={"tipo": "", "horas": "horas"},
                )
                fig.update_traces(texttemplate="%{text:.1f} h", textposition="outside")
                fig.update_layout(showlegend=False)
                st.plotly_chart(_style(fig), width="stretch")
            st.dataframe(
                compare.rename(
                    columns={
                        "tipo": "Tipo",
                        "sesiones": "Sesiones",
                        "horas": "Horas",
                        "km": "Km",
                        "carga": "Carga",
                        "fc_media": "FC media",
                        "potencia_media": "Potencia media",
                    }
                ),
                hide_index=True,
                width="stretch",
            )


        with st.expander("Distribución por zonas", expanded=False):
            cycling = filtered[filtered["is_cycling"]].copy()
            garmin_zone_activities = garmin[
                (garmin["date"] >= start_date) & (garmin["date"] <= end_date)
            ].copy() if not garmin.empty else garmin.copy()
            intervals_zone_activities = intervals_acts[
                (intervals_acts["date"] >= start_date) & (intervals_acts["date"] <= end_date)
            ].copy() if not intervals_acts.empty else intervals_acts.copy()
            if not garmin_zone_activities.empty:
                garmin_zone_activities = garmin_zone_activities[_focus_mask(garmin_zone_activities, focus)]
                garmin_zone_activities = garmin_zone_activities[garmin_zone_activities["is_cycling"]]
            if not intervals_zone_activities.empty:
                intervals_zone_activities = intervals_zone_activities[_focus_mask(intervals_zone_activities, focus)]
                intervals_zone_activities = intervals_zone_activities[intervals_zone_activities["is_cycling"]]
            garmin_hr_available = (
                not garmin_zone_activities.empty
                and an.zone_minutes(garmin_zone_activities, "hr")["minutes"].sum() > 0
            )
            prefer_intervals_hr = (
                source_choice == "Solo intervals.icu" or not garmin_hr_available
            )
            if prefer_intervals_hr and not intervals_zone_activities.empty:
                hr_zone_source = intervals_zone_activities
                hr_source_label = "intervals.icu · tiempos registrados en sus zonas"
            else:
                hr_zone_source = garmin_zone_activities
                hr_source_label = (
                    "Garmin · tiempos registrados en 5 zonas"
                    if garmin_hr_available
                    else "Sin tiempos de zona de FC en este rango"
                )
            power_zone_source = (
                intervals_zone_activities
                if not intervals_zone_activities.empty
                else cycling
            )
            power_source_label = (
                "intervals.icu · distribución registrada"
                if power_zone_source is intervals_zone_activities
                else "Distribución disponible"
            )
            ftp_for_zones = (
                _setting_value(cycling_settings, "indoor_ftp")
                or _setting_value(cycling_settings, "ftp")
            )
            if cycling_settings is not None:
                _metric_row(
                    [
                        (
                            "FTP para zonas",
                            f"{_fmt(ftp_for_zones)} W"
                            if ftp_for_zones
                            else "–",
                            "FTP interior; general como fallback",
                        ),
                        (
                            "LTHR",
                            f"{_fmt(_setting_value(cycling_settings, 'lthr'))} ppm"
                            if _setting_value(cycling_settings, "lthr")
                            else "–",
                            "Frecuencia cardiaca de umbral",
                        ),
                        (
                            "FC máx",
                            f"{_fmt(_setting_value(cycling_settings, 'max_hr'))} ppm"
                            if _setting_value(cycling_settings, "max_hr")
                            else "–",
                            None,
                        ),
                    ]
                )

            lthr = _setting_value(cycling_settings, "lthr")
            hr_model = an.zone_model(cycling_settings, "hr")
            power_model = an.zone_model(cycling_settings, "power")
            with st.expander("Zonas de entrenamiento de referencia", expanded=False):
                zone_hr_col, zone_power_col = st.columns(2)
                with zone_hr_col:
                    if hr_model:
                        st.caption(
                            f"FC con LTHR de {lthr:.0f} ppm y límites Friel "
                            "85/90/95/100 %. Los minutos proceden de los contadores de "
                            "zona de la fuente elegida; no se reclasifican sin datos "
                            "segundo a segundo."
                        )
                        st.dataframe(
                            pd.DataFrame(
                                {
                                    "Zona FC": [zone["label"] for zone in hr_model],
                                    "Rango": [zone["range"] for zone in hr_model],
                                }
                            ),
                            hide_index=True,
                            width="stretch",
                        )
                    else:
                        st.warning(
                            "Sin LTHR configurado en intervals.icu: no se pueden "
                            "calcular las 5 zonas de FC. Añade LTHR en los ajustes "
                            "del deporte."
                        )
                with zone_power_col:
                    if power_model:
                        st.caption(
                            f"Potencia Coggan con FTP de {ftp_for_zones:.0f} W. Se "
                            "usan los bordes de potencia de intervals.icu cuando "
                            "llegan como porcentaje de FTP; si no, los límites "
                            "Coggan 55/75/90/105/120/150 %."
                        )
                        st.dataframe(
                            pd.DataFrame(
                                {
                                    "Zona Coggan": [
                                        zone["label"] for zone in power_model
                                    ],
                                    "Rango": [zone["range"] for zone in power_model],
                                }
                            ),
                            hide_index=True,
                            width="stretch",
                        )
                    else:
                        st.warning(
                            "Sin FTP configurado en intervals.icu: no se pueden "
                            "calcular las 7 zonas de potencia."
                        )


            if cycling.empty:
                st.info("No hay sesiones de ciclismo en el periodo seleccionado.")
            else:
                hr_zones = an.zone_minutes(hr_zone_source, "hr")
                power_zones = an.zone_minutes(power_zone_source, "power")

                left, right = st.columns(2)
                with left:
                    st.subheader("Zonas de frecuencia cardiaca · 5 zonas LTHR")
                    st.caption(hr_source_label)
                    if hr_zones["minutes"].sum() == 0:
                        st.caption("Sin tiempos de zona de FC en las actividades.")
                    else:
                        st.plotly_chart(
                            _zone_bar(hr_zones, "hr", cycling_settings), width="stretch"
                        )
                        hr_view = _zone_frame(hr_zones, cycling_settings, "hr")
                        hr_view["minutos"] = hr_view["minutes"].round(0)
                        hr_view["%"] = (hr_view["share"] * 100).round(1)
                        with st.expander("Ver rangos y minutos exactos · FC", expanded=False):
                            st.dataframe(
                                hr_view[["label", "rango", "minutos", "%"]].rename(
                                    columns={
                                        "label": "Zona",
                                        "rango": "Rango",
                                        "minutos": "Minutos",
                                    }
                                ),
                                hide_index=True,
                                width="stretch",
                            )

                with right:
                    st.subheader("Zonas de potencia · Coggan 7 zonas")
                    st.caption(power_source_label)
                    if power_zones["minutes"].sum() == 0:
                        st.caption(
                            "Sin zonas de potencia. Sincroniza intervals.icu para "
                            "obtenerlas."
                        )
                    else:
                        st.plotly_chart(
                            _zone_bar(
                                power_zones,
                                "power",
                                cycling_settings,
                            ),
                            width="stretch",
                        )
                        power_view = _zone_frame(
                            power_zones,
                            cycling_settings,
                            "power",
                        )
                        power_view["minutos"] = power_view["minutes"].round(0)
                        power_view["%"] = (power_view["share"] * 100).round(1)
                        with st.expander("Ver rangos y minutos exactos · potencia", expanded=False):
                            st.dataframe(
                                power_view[["label", "rango", "minutos", "%"]].rename(
                                    columns={
                                        "label": "Zona",
                                        "rango": "Rango",
                                        "minutos": "Minutos",
                                    }
                                ),
                                hide_index=True,
                                width="stretch",
                            )


    # ------------------------------ Actividades ------------------------------- #

if main_section == "Entrenamiento" and training_view == "Actividades":
    with st.container():
        table = filtered.sort_values("start", ascending=False).copy()
        if table.empty:
            st.info("No hay actividades en el periodo y foco seleccionados.")
        else:
            filter_cols = st.columns([1, 1, 1, 1.3])
            with filter_cols[0]:
                sport_filter = st.multiselect("Tipo de salida", sorted(table["sport"].dropna().unique()), key="activity_sport_filter")
            with filter_cols[1]:
                source_filter = st.multiselect("Fuente", sorted(table["source"].dropna().unique()), key="activity_source_filter")
            with filter_cols[2]:
                min_distance = st.number_input("Distancia mínima (km)", min_value=0.0, max_value=500.0, value=0.0, step=5.0, key="activity_min_distance")
            with filter_cols[3]:
                sort_choice = st.selectbox(
                    "Ordenar por",
                    ["Fecha · reciente", "Fecha · antigua", "Distancia", "Duración", "Potencia", "Tipo"],
                    key="activity_sort",
                )
            if sport_filter:
                table = table[table["sport"].isin(sport_filter)]
            if source_filter:
                table = table[table["source"].isin(source_filter)]
            table = table[table["distance_km"].fillna(0) >= min_distance]
            sort_columns = {
                "Fecha · reciente": ("start", False), "Fecha · antigua": ("start", True),
                "Distancia": ("distance_km", False), "Duración": ("duration_min", False),
                "Potencia": ("avg_power_w", False), "Tipo": ("sport", True),
            }
            sort_col, sort_ascending = sort_columns[sort_choice]
            table = table.sort_values(sort_col, ascending=sort_ascending, na_position="last")
            if table.empty:
                st.info("Ninguna actividad coincide con esos filtros.")
            else:
                table["Fecha"] = table["start"].dt.strftime("%d/%m/%Y %H:%M")
                table["Rodillo"] = table["indoor"].map({True: "Sí", False: "No"})
                display = table[
                    [
                        "Fecha",
                        "source",
                        "sport",
                        "activity_name",
                        "duration_min",
                        "distance_km",
                        "speed_kmh",
                        "avg_hr",
                        "avg_power_w",
                        "weighted_avg_power_w",
                        "training_load",
                        "intensity",
                        "Rodillo",
                    ]
                ].rename(
                    columns={
                        "source": "Fuente",
                        "sport": "Deporte",
                        "activity_name": "Nombre",
                        "duration_min": "Duración (min)",
                        "distance_km": "Distancia (km)",
                        "speed_kmh": "Vel. media (km/h)",
                        "avg_hr": "FC media",
                        "avg_power_w": "Potencia media (W)",
                        "weighted_avg_power_w": "Potencia normalizada (W)",
                        "training_load": "Carga",
                        "intensity": "Intensidad",
                    }
                )
    
                st.subheader(f"{len(display)} actividades")
                st.dataframe(
                    display,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Duración (min)": st.column_config.NumberColumn(format="%.0f"),
                        "Distancia (km)": st.column_config.NumberColumn(format="%.2f"),
                        "Vel. media (km/h)": st.column_config.NumberColumn(format="%.1f"),
                        "FC media": st.column_config.NumberColumn(format="%.0f"),
                        "Potencia media (W)": st.column_config.NumberColumn(format="%.0f"),
                        "Potencia normalizada (W)": st.column_config.NumberColumn(
                            format="%.0f"
                        ),
                        "Carga": st.column_config.NumberColumn(format="%.0f"),
                        "Intensidad": st.column_config.NumberColumn(format="%.0f"),
                    },
                )
    
                st.download_button(
                    "Descargar CSV",
                    data=display.to_csv(index=False).encode("utf-8"),
                    file_name=f"ciclismo_{start_date}_{end_date}.csv",
                    mime="text/csv",
                )
    
                st.subheader("Ficha de la sesión seleccionada")
                options = {
                    f"{row.Fecha} · {row.sport} · "
                    f"{row.activity_name if isinstance(row.activity_name, str) else 'Sin nombre'}": row.activity_id
                    for row in table.itertuples()
                }
                selected_label = st.selectbox("Actividad", list(options), key="detail_activity")
                selected = table[table["activity_id"] == options[selected_label]].iloc[0]
                matched_garmin = None
                if not garmin.empty and pd.notna(selected.get("start")):
                    candidates = garmin[garmin["is_cycling"]].copy()
                    candidates["start_gap_s"] = (candidates["start"] - selected["start"]).abs().dt.total_seconds()
                    candidates = candidates[candidates["start_gap_s"] <= 90]
                    if not candidates.empty:
                        matched_garmin = candidates.sort_values("start_gap_s").iloc[0]
    
                _metric_row(
                    [
                        (
                            "Distancia",
                            f"{an.format_number(selected['distance_km'], 2)} km",
                            None,
                        ),
                        ("Duración", an.format_duration(selected["duration_min"]), None),
                        ("FC media", f"{_fmt(selected['avg_hr'])} ppm", None),
                        (
                            "Potencia media",
                            f"{_fmt(selected['avg_power_w'])} W"
                            if pd.notna(selected["avg_power_w"])
                            else "–",
                            None,
                        ),
                        (
                            "Potencia normalizada",
                            f"{_fmt(selected['weighted_avg_power_w'])} W"
                            if pd.notna(selected["weighted_avg_power_w"])
                            else "–",
                            None,
                        ),
                        ("Carga", _fmt(selected["training_load"]), None),
                    ]
                )
                st.caption(
                    f"Fuente: {selected['source']} · tipo: {selected['activity_type']} · "
                    f"intensidad: {_fmt(selected['intensity'], 1)} · "
                    f"desnivel: {_fmt(selected['elevation_gain_m'])} m"
                )
                try:
                    raw_activity = json.loads(selected.get("raw_json") or "{}")
                except (TypeError, json.JSONDecodeError):
                    raw_activity = {}
                if matched_garmin is not None:
                    try:
                        raw_garmin = json.loads(matched_garmin.get("raw_json") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        raw_garmin = {}
                    for field in ("waterConsumed", "waterEstimated", "maxPower", "normPower", "maxAvgPower_1", "maxAvgPower_2", "maxAvgPower_5", "maxAvgPower_10", "maxAvgPower_20", "maxAvgPower_30", "maxAvgPower_60", "maxAvgPower_120", "maxAvgPower_300", "maxAvgPower_600", "maxAvgPower_1200", "maxAvgPower_1800", "maxAvgPower_3600", "maxAvgPower_7200"):
                        if raw_activity.get(field) is None and raw_garmin.get(field) is not None:
                            raw_activity[field] = raw_garmin[field]

                intervals_activity_id = None
                matched_intervals = None
                if not intervals_acts.empty and pd.notna(selected.get("start")):
                    stream_candidates = intervals_acts.copy()
                    stream_candidates["start_gap_s"] = (
                        stream_candidates["start"] - selected["start"]
                    ).abs().dt.total_seconds()
                    stream_candidates = stream_candidates[
                        stream_candidates["start_gap_s"] <= 90
                    ]
                    if not stream_candidates.empty:
                        matched_intervals = stream_candidates.sort_values("start_gap_s").iloc[0]
                        intervals_activity_id = str(matched_intervals["activity_id"])

                if matched_intervals is not None:
                    try:
                        intervals_raw = json.loads(matched_intervals.get("raw_json") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        intervals_raw = {}
                    for field in ("icu_rpe", "feel"):
                        if raw_activity.get(field) is None and intervals_raw.get(field) is not None:
                            raw_activity[field] = intervals_raw[field]

                activity_streams = []
                streams_error = None
                st.subheader("Perfiles de la actividad")
                if not intervals.is_configured():
                    st.info("Configura intervals.icu para descargar los perfiles de esta sesión.")
                elif intervals_activity_id is None:
                    st.info("No se encontró la actividad correspondiente en intervals.icu.")
                else:
                    try:
                        with st.spinner("Descargando streams de la actividad..."):
                            stream_result = _fetch_activity_streams(intervals_activity_id)
                            activity_streams = stream_result.get("streams", [])
                            streams_error = stream_result.get("error")
                    except intervals.IntervalsError as exc:
                        activity_streams = []
                        streams_error = str(exc)

                    if streams_error:
                        st.warning(f"No se pudieron descargar los streams: {streams_error}")

                    if st.button("Reintentar descarga de streams", key=f"retry_streams_{intervals_activity_id}"):
                        _fetch_activity_streams.clear()
                        st.rerun()

                    if activity_streams:
                        time_s = _stream_values(activity_streams, "time")
                        distance_m = _stream_values(activity_streams, "distance")
                        altitude_m = _stream_values(activity_streams, "altitude")
                        watts = _stream_values(activity_streams, "watts")
                        speed_mps = _stream_values(activity_streams, "velocity_smooth")

                        st.markdown("**Perfil de la sesión**")
                        if distance_m and altitude_m:
                            altitude_profile = streams.profile_frame(
                                distance_m, altitude_m, "Distancia", "Altitud"
                            )
                            altitude_profile["Distancia"] /= 1000
                            stride = max(len(altitude_profile) // 3000, 1)
                            fig = px.line(
                                altitude_profile.iloc[::stride],
                                x="Distancia",
                                y="Altitud",
                                color_discrete_sequence=[P["elevation"]],
                            )
                            fig.update_xaxes(title_text="Distancia (km)")
                            fig.update_yaxes(title_text="Altitud (m)")
                            st.plotly_chart(_style(fig, height=300), width="stretch")
                            if speed_mps:
                                speed_profile = streams.profile_frame(
                                    distance_m, speed_mps, "Distancia", "Velocidad"
                                )
                                speed_profile["Distancia"] /= 1000
                                speed_profile["Velocidad"] *= 3.6
                                speed_stride = max(len(speed_profile) // 3000, 1)
                                st.markdown("**Velocidad por distancia**")
                                speed_fig = px.line(
                                    speed_profile.iloc[::speed_stride],
                                    x="Distancia",
                                    y="Velocidad",
                                    color_discrete_sequence=[P["primary"]],
                                )
                                speed_fig.update_xaxes(title_text="Distancia (km)")
                                speed_fig.update_yaxes(title_text="Velocidad (km/h)")
                                st.plotly_chart(_style(speed_fig, height=300), width="stretch")
                        elif time_s and speed_mps:
                            speed_profile = streams.profile_frame(
                                time_s, speed_mps, "Tiempo", "Velocidad"
                            )
                            speed_profile["Tiempo"] /= 60
                            speed_profile["Velocidad"] *= 3.6
                            stride = max(len(speed_profile) // 3000, 1)
                            fig = px.line(
                                speed_profile.iloc[::stride],
                                x="Tiempo",
                                y="Velocidad",
                                title="Altitud no disponible · velocidad durante la sesión",
                                color_discrete_sequence=[P["primary"]],
                            )
                            fig.update_xaxes(title_text="Tiempo (min)")
                            fig.update_yaxes(title_text="Velocidad (km/h)")
                            st.plotly_chart(_style(fig, height=340), width="stretch")
                        else:
                            st.caption("No hay muestras suficientes para dibujar el perfil de altitud y velocidad.")

                        st.markdown("**Potencia durante la sesión**")
                        if time_s and watts:
                            power_profile = streams.profile_frame(
                                time_s, watts, "Tiempo", "Potencia"
                            )
                            power_profile["Tiempo"] /= 60
                            stride = max(len(power_profile) // 3000, 1)
                            fig = px.line(
                                power_profile.iloc[::stride],
                                x="Tiempo",
                                y="Potencia",
                                color_discrete_sequence=[P["power_avg"]],
                            )
                            fig.update_xaxes(title_text="Tiempo (min)")
                            fig.update_yaxes(title_text="Potencia (W)")
                            st.plotly_chart(_style(fig, height=340), width="stretch")
                            st.markdown("**Curva de potencia de la sesión**")
                            st.caption(
                                "Muestra la mejor potencia media que se sostuvo para "
                                "cada duración; depende de que intervals.icu entregue streams."
                            )
                            power_curve = streams.power_duration_curve(watts, times=time_s)
                            if power_curve.empty:
                                st.caption("No hay suficientes muestras para calcular la curva.")
                            else:
                                power_curve["Duración"] = power_curve["duration_s"].apply(
                                    lambda seconds: (
                                        f"{seconds // 60} min" if seconds >= 60
                                        else f"{seconds} s"
                                    )
                                )
                                curve_fig = px.line(
                                    power_curve,
                                    x="Duración",
                                    y="watts",
                                    markers=True,
                                    color_discrete_sequence=[P["power_best"]],
                                )
                                curve_fig.update_yaxes(title_text="Mejor media (W)")
                                curve_fig.update_xaxes(title_text="Duración")
                                st.plotly_chart(_style(curve_fig, height=300), width="stretch")
                        else:
                            st.caption("Esta sesión no contiene muestras de potencia.")
                    else:
                        st.info("intervals.icu no devolvió streams para esta sesión.")

                garmin_calories = (
                    matched_garmin.get("calories")
                    if matched_garmin is not None
                    else selected.get("calories")
                )
                garmin_calories = pd.to_numeric(
                    pd.Series([garmin_calories]), errors="coerce"
                ).iloc[0]
                elapsed_s = pd.to_numeric(pd.Series([selected.get("elapsed_duration_s")]), errors="coerce").iloc[0]
                moving_s = pd.to_numeric(pd.Series([selected.get("moving_duration_s")]), errors="coerce").iloc[0]
                if pd.isna(elapsed_s):
                    elapsed_s = selected.get("duration_s")
                if pd.isna(moving_s):
                    moving_s = selected.get("duration_s")
                moving_hours = float(moving_s) / 3600 if pd.notna(moving_s) and moving_s else 0
                fluid_ml = raw_activity.get("waterConsumed")
                estimated_fluid_ml = raw_activity.get("waterEstimated")
                carbs_g = raw_activity.get("carbs_ingested")
                rpe_value = pd.to_numeric(
                    pd.Series([raw_activity.get("icu_rpe")]), errors="coerce"
                ).iloc[0]
                feel_value = pd.to_numeric(
                    pd.Series([raw_activity.get("feel")]), errors="coerce"
                ).iloc[0]
                feel_labels = {
                    1: "Muy buenas",
                    2: "Buenas",
                    3: "Normales",
                    4: "Malas",
                    5: "Muy malas",
                }
                feel_label = (
                    feel_labels.get(int(feel_value), "")
                    if pd.notna(feel_value) and float(feel_value).is_integer()
                    else ""
                )
                carbs_used_g = (
                    (float(garmin_calories) - 500) * 25 / 100 * 0.8
                    if pd.notna(garmin_calories)
                    else None
                )
                fluid_ml = pd.to_numeric(pd.Series([fluid_ml]), errors="coerce").iloc[0]
                estimated_fluid_ml = pd.to_numeric(pd.Series([estimated_fluid_ml]), errors="coerce").iloc[0]
                carbs_g = pd.to_numeric(pd.Series([carbs_g]), errors="coerce").iloc[0]
                carbs_used_g = pd.to_numeric(pd.Series([carbs_used_g]), errors="coerce").iloc[0]
                vam = float(selected["elevation_gain_m"]) / moving_hours if moving_hours else None
                max_power = next((raw_activity.get(key) for key in ("maxPower", "max_power", "icu_pm_p_max") if raw_activity.get(key) is not None), None)
                report_metrics = {
                    "elapsed_s": float(elapsed_s) if pd.notna(elapsed_s) else None,
                    "moving_s": float(moving_s) if pd.notna(moving_s) else None,
                    "distance_km": selected.get("distance_km"),
                    "vam_m_h": vam,
                    "avg_power_w": selected.get("avg_power_w"),
                    "weighted_avg_power_w": selected.get("weighted_avg_power_w"),
                    "max_power_w": max_power,
                    "avg_cadence": selected.get("avg_cadence"),
                    "elevation_gain_m": selected.get("elevation_gain_m"),
                    "avg_hr": selected.get("avg_hr"),
                    "max_hr": selected.get("max_hr"),
                    "fluid_ml": fluid_ml,
                    "estimated_fluid_ml": estimated_fluid_ml,
                    "carbs_used_g": carbs_used_g,
                    "carbs_g": carbs_g,
                    "rpe": rpe_value,
                    "feel": feel_value,
                    "calories": garmin_calories,
                }
                detail_rows = reports.metric_rows(report_metrics)
                st.subheader("Resumen de la sesión")
                st.dataframe(pd.DataFrame(detail_rows), hide_index=True, width="stretch")
                hr_session = matched_garmin if matched_garmin is not None else None
                activity_hr_zones = (
                    an.activity_zone_minutes(hr_session, "hr")
                    if hr_session is not None
                    else pd.DataFrame(columns=["zone", "label", "minutes"])
                )
                activity_power_zones = an.activity_zone_minutes(selected, "power")
                activity_hr_zones = _zone_frame(activity_hr_zones, cycling_settings, "hr")
                activity_power_zones = _zone_frame(
                    activity_power_zones,
                    cycling_settings,
                    "power",
                    indoor=bool(selected.get("indoor")),
                )
                for zone_data in (activity_hr_zones, activity_power_zones):
                    if not zone_data.empty:
                        zone_data["rango"] = zone_data["rango"].fillna("")
                        zone_data["label"] = zone_data.apply(lambda row: f"{row['label']} ({row['rango']})" if row["rango"] else row["label"], axis=1)
                zone_text = []
                for label, zone_data in (("FC", activity_hr_zones), ("Potencia", activity_power_zones)):
                    recorded_zones = zone_data[zone_data["minutes"] > 0]
                    if not recorded_zones.empty:
                        zone_text.append(label + ": " + "; ".join(f"{row.zone} {row.minutes:.1f} min" for row in recorded_zones.itertuples()))
                interval_summary = raw_activity.get("interval_summary") or raw_activity.get("splitSummaries") or []
                linked_activity_ids = {
                    str(value).strip()
                    for value in (
                        selected.get("activity_id"),
                        matched_garmin.get("activity_id") if matched_garmin is not None else None,
                        matched_intervals.get("activity_id") if matched_intervals is not None else None,
                    )
                    if value is not None and str(value).strip()
                }
                plan_path = Path(__file__).with_name("planning_bloque_1.json")
                try:
                    plan_items_for_summary = json.loads(plan_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    plan_items_for_summary = []
                linked_plan = next(
                    (
                        item for item in plan_items_for_summary
                        if str(item.get("activity_link_id", "")).strip() in linked_activity_ids
                        and str(item.get("activity_link_id", "")).strip()
                    ),
                    None,
                )
                plan_comparison_rows = []
                plan_comparison_rows = (
                    _plan_comparison_rows(linked_plan, selected, activity_streams)
                    if linked_plan is not None else []
                )
                activity_health = {}
                if not wellness.empty and pd.notna(selected.get("start")):
                    activity_day = pd.Timestamp(selected["start"]).normalize()
                    previous_week = wellness[
                        (wellness["date"].dt.normalize() >= activity_day - pd.Timedelta(days=6))
                        & (wellness["date"].dt.normalize() <= activity_day)
                    ]
                    same_day_health = wellness[
                        wellness["date"].dt.normalize() == activity_day
                    ]
                    if not same_day_health.empty:
                        health_row = same_day_health.iloc[-1]
                        activity_health = {
                            field: (
                                float(health_row[field])
                                if field in health_row and pd.notna(health_row[field])
                                else None
                            )
                            for field in (
                                "sleep_h", "sleep_score", "resting_hr", "hrv"
                            )
                        }
                    for field in ("sleep_h", "sleep_score", "resting_hr", "hrv"):
                        if field in previous_week:
                            values = pd.to_numeric(previous_week[field], errors="coerce").dropna()
                            activity_health[f"{field}_7d_avg"] = (
                                float(values.mean()) if not values.empty else None
                            )
                            activity_health[f"{field}_7d_days"] = int(values.size)
                report = reports.build_activity_report(
                    activity={
                        "id": selected.get("activity_id"),
                        "name": selected.get("activity_name"),
                        "sport": selected.get("sport"),
                        "type": selected.get("activity_type"),
                        "source": selected.get("source"),
                        "start": selected.get("start"),
                        "start_date": selected.get("date"),
                        "indoor": bool(selected.get("indoor")),
                    },
                    metrics=report_metrics,
                    health=activity_health,
                    zones_hr=activity_hr_zones,
                    zones_power=activity_power_zones,
                    plan=linked_plan,
                    plan_comparison=plan_comparison_rows,
                    intervals=interval_summary if isinstance(interval_summary, list) else [],
                    streams_available=bool(activity_streams),
                    streams_error=streams_error,
                    ftp=(
                        _setting_value(cycling_settings, "indoor_ftp")
                        or _setting_value(cycling_settings, "ftp")
                    ),
                    lthr=_setting_value(cycling_settings, "lthr"),
                )
                with st.expander("Compartir y exportar", expanded=False):
                    st.caption("Texto listo para copiar y compartir con otra IA:")
                    st.code(reports.report_text(report), language="text")
                    report_col1, report_col2, report_col3 = st.columns(3)
                    with report_col1:
                        st.download_button(
                            "Descargar resumen .txt",
                            reports.report_text(report),
                            file_name=reports.report_filename(report),
                            mime="text/plain",
                        )
                    with report_col2:
                        st.download_button(
                            "Descargar datos .json",
                            reports.report_json(report),
                            file_name=reports.report_filename(report, ".json"),
                            mime="application/json",
                        )
                    with report_col3:
                        if intervals_activity_id and intervals.is_configured():
                            fit_result = _fetch_activity_fit(intervals_activity_id)
                            if fit_result["data"]:
                                st.download_button(
                                    "Descargar actividad .fit",
                                    data=fit_result["data"],
                                    file_name=reports.report_filename(report, ".fit"),
                                    mime="application/vnd.ant.fit",
                                    help="FIT generado por intervals.icu; puedes adjuntarlo al chat de IA junto al resumen.",
                                )
                            else:
                                st.button(
                                    "Actividad .fit no disponible",
                                    disabled=True,
                                    help=fit_result["error"] or "intervals.icu no devolvió el archivo FIT.",
                                )
                        else:
                            st.button(
                                "Actividad .fit no disponible",
                                disabled=True,
                                help="Se necesita una actividad enlazada en intervals.icu para descargar el FIT.",
                            )
                if linked_plan is not None:
                    st.subheader("Planificado vs real")
                    st.caption(
                        f"Semana {linked_plan.get('semana') or '–'} · "
                        f"{linked_plan.get('sesion') or 'Sesión sin nombre'}"
                    )
                    st.dataframe(
                        pd.DataFrame(plan_comparison_rows),
                        hide_index=True,
                        width="stretch",
                    )
                st.subheader("Tiempo en zonas de la sesión")
                zone_chart_specs = (
                    ("Frecuencia cardiaca", activity_hr_zones, an.HR_ZONE_COLORS),
                    ("Potencia", activity_power_zones, an.POWER_ZONE_COLORS),
                )
                for title, zone_data, palette in zone_chart_specs:
                    st.markdown(f"**{title}**")
                    available = zone_data[zone_data["minutes"] > 0].copy()
                    if available.empty:
                        st.caption(f"No hay tiempos de {title.lower()} disponibles para esta sesión.")
                        continue
                    available["tiempo"] = available["minutes"].apply(an.format_duration)
                    fig = go.Figure(
                        go.Bar(
                            x=available["minutes"],
                            y=available["label"],
                            orientation="h",
                            text=available["tiempo"],
                            textposition="outside",
                            cliponaxis=False,
                            marker_color=[
                                palette[int(str(zone).removeprefix("Z")) - 1]
                                if str(zone).startswith("Z")
                                and str(zone).removeprefix("Z").isdigit()
                                and int(str(zone).removeprefix("Z")) <= len(palette)
                                else palette[0]
                                for zone in available["zone"]
                            ],
                            hovertemplate="%{y}<br>%{text}<extra></extra>",
                        )
                    )
                    fig.update_layout(
                        height=max(210, 42 * len(available)),
                        showlegend=False,
                        margin={"l": 12, "r": 90, "t": 16, "b": 38},
                    )
                    fig.update_xaxes(title_text="Minutos", rangemode="tozero")
                    fig.update_yaxes(title_text="", autorange="reversed")
                    st.plotly_chart(_style(fig, height=max(210, 42 * len(available))), width="stretch")
    

    # -------------------------------- Salud ----------------------------------- #

if main_section == "Recuperación" and recovery_view == "Salud":
    with st.container():
        health = filtered_wellness if not filtered_wellness.empty else filtered_daily
        if health.empty:
            st.info(
                "No hay datos de salud en el periodo. Sincroniza Garmin o "
                "intervals.icu."
            )
        else:
            st.caption(
                "Fuente de salud: intervals.icu y Garmin cuando están disponibles; Garmin completa huecos."
                if not filtered_intervals_wellness.empty
                else "Fuente de salud: Garmin."
            )
            latest_sleep = health.dropna(subset=["sleep_h"]).tail(1)
            health_bands = health_analysis.reference_bands(filtered_wellness)
            hrv_source = health
            hrv_column = "hrv" if "hrv" in hrv_source.columns else "hrv_last_night"
            hrv_avg = (
                hrv_source[hrv_column].mean()
                if hrv_column in hrv_source.columns
                else float("nan")
            )
            weight_info = an.weight_trend(filtered_wellness)
            weight_help = "Sin pesajes registrados"
            if weight_info["latest"] is not None:
                weight_help = (
                    f"Media de {_fmt(weight_info['mean'], 1)} kg con "
                    f"{weight_info['count']} pesajes · 7 días "
                    f"{_fmt_signed(weight_info['delta7'])} kg · 30 días "
                    f"{_fmt_signed(weight_info['delta30'])} kg"
                )
            _metric_row(
                [
                    (
                        "Sueño medio",
                        f"{an.format_number(health['sleep_h'].mean(), 1)} h"
                        if "sleep_h" in health.columns
                        else "–",
                        None,
                    ),
                    (
                        "FC reposo media",
                        f"{_fmt(health['resting_hr'].mean())} ppm"
                        if "resting_hr" in health.columns
                        else "–",
                        None,
                    ),
                    ("HRV media", f"{_fmt(hrv_avg)} ms", None),
                    (
                        "Último peso",
                        f"{_fmt(weight_info['latest'], 1)} kg"
                        if weight_info["latest"] is not None
                        else "–",
                        weight_help,
                    ),
                ]
            )
            st.subheader("Último dato frente a la media del periodo")
            st.caption(
                "El último valor registrado de cada métrica se compara con su "
                "media en el periodo seleccionado. La diferencia es descriptiva."
            )
            comparison_specs = (
                (("sleep_h",), "Sueño", "h", 1),
                (("sleep_score",), "Calidad del sueño", "puntos", 0),
                (("resting_hr",), "FC en reposo", "ppm", 0),
                (("hrv", "hrv_last_night", "hrv_weekly_avg"), "HRV", "ms", 0),
            )
            health_comparison_rows = []
            for candidates, label, unit, decimals in comparison_specs:
                column = next(
                    (
                        name for name in candidates
                        if name in health.columns
                        and pd.to_numeric(health[name], errors="coerce").notna().any()
                    ),
                    None,
                )
                if column is None:
                    continue
                metric_data = health[["date", column]].copy()
                metric_data[column] = pd.to_numeric(metric_data[column], errors="coerce")
                metric_data = metric_data.dropna(subset=[column]).sort_values("date")
                if metric_data.empty:
                    continue
                latest_metric = float(metric_data.iloc[-1][column])
                period_mean = float(metric_data[column].mean())
                difference = latest_metric - period_mean
                change_pct = difference / abs(period_mean) * 100 if period_mean else None
                health_comparison_rows.append({
                    "Métrica": label,
                    "Último dato": f"{_fmt(latest_metric, decimals)} {unit}",
                    "Fecha": _fmt_date(metric_data.iloc[-1]["date"]),
                    "Media del periodo": f"{_fmt(period_mean, decimals)} {unit}",
                    "Diferencia": f"{_fmt_signed(difference, decimals)} {unit}",
                    "% vs media": f"{change_pct:+.1f}%".replace(".", ",") if change_pct is not None else "–",
                })
            if health_comparison_rows:
                st.dataframe(
                    pd.DataFrame(health_comparison_rows),
                    hide_index=True,
                    width="stretch",
                )
            band_lines = []
            for key, label, unit in (
                ("sleep", "Sueño", "h"),
                ("resting_hr", "FC en reposo", "ppm"),
                ("hrv", "HRV", "ms"),
            ):
                band = health_bands[key]
                latest_value = band.get("latest")
                if latest_value is not None:
                    status = band.get("status") or "sin referencia personal"
                    band_lines.append(
                        f"{label}: {_fmt(latest_value, 1)} {unit} · {status} · "
                        f"referencia {band.get('label')}"
                    )
            if band_lines:
                st.caption(" · ".join(band_lines))
            st.caption(
                "Estas bandas son referencias descriptivas, no diagnósticos ni "
                "prescripciones; sueño usa una referencia general y FC/HRV tu historial."
            )
            if weight_info["latest"] is not None:
                st.caption(
                    f"Último pesaje: {_fmt_date(weight_info['date'])} · "
                    f"7 días {_fmt_signed(weight_info['delta7'])} kg · "
                    f"30 días {_fmt_signed(weight_info['delta30'])} kg · "
                    f"media {_fmt(weight_info['mean'], 1)} kg."
                )
            if not latest_sleep.empty:
                last = latest_sleep.iloc[0]
                st.caption(
                    f"Último registro de sueño: {_fmt_date(last['date'])} · "
                    f"{an.format_number(last['sleep_h'], 1)} h"
                )

            left, right = st.columns(2)
            with left:
                st.subheader("Sueño")
                sleep_df = health.dropna(subset=["sleep_h"])
                if sleep_df.empty:
                    st.plotly_chart(_empty_fig("Sin datos de sueño"), width="stretch")
                else:
                    fig = go.Figure()
                    fig.add_trace(
                        go.Bar(
                            x=sleep_df["date"],
                            y=sleep_df["sleep_h"],
                            name="Horas",
                            marker_color=P["sleep"],
                            opacity=0.65,
                        )
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=sleep_df["date"],
                            y=sleep_df["sleep_h"].rolling(7, min_periods=2).mean(),
                            name="Media 7 días",
                            line=dict(color=P["primary"], width=2.4),
                        )
                    )
                    fig.update_xaxes(tickformat="%d %b %y")
                    fig.update_yaxes(title="horas")
                    st.plotly_chart(_style(fig), width="stretch")

            with right:
                st.subheader("FC en reposo y HRV")
                health_series = []
                rhr_df = health.dropna(subset=["resting_hr"])
                if not rhr_df.empty:
                    health_series.append(
                        ("FC reposo", rhr_df, "resting_hr", "ppm", P["resting_hr"])
                    )
                if hrv_column in health.columns and health[hrv_column].notna().any():
                    health_series.append(
                        (
                            "HRV",
                            health.dropna(subset=[hrv_column]),
                            hrv_column,
                            "ms",
                            P["hrv"],
                        )
                    )
                if not health_series:
                    st.plotly_chart(
                        _empty_fig("Sin datos de FC en reposo o HRV"), width="stretch"
                    )
                else:
                    fig = make_subplots(
                        rows=len(health_series),
                        cols=1,
                        shared_xaxes=True,
                        vertical_spacing=0.12,
                        subplot_titles=[series[0] for series in health_series],
                    )
                    reference_labels = []
                    for row_index, (series_name, series_df, field, unit, color) in enumerate(
                        health_series, start=1
                    ):
                        values = pd.to_numeric(series_df[field], errors="coerce").dropna()
                        mean_value = float(values.mean())
                        dates = series_df["date"]
                        fig.add_trace(
                            go.Scatter(
                                x=dates,
                                y=[mean_value + 5] * len(dates),
                                mode="lines",
                                line=dict(width=0),
                                hoverinfo="skip",
                                showlegend=False,
                            ),
                            row=row_index,
                            col=1,
                        )
                        fig.add_trace(
                            go.Scatter(
                                x=dates,
                                y=[mean_value - 5] * len(dates),
                                mode="lines",
                                line=dict(width=0),
                                fill="tonexty",
                                fillcolor="rgba(56, 189, 248, 0.24)",
                                hoverinfo="skip",
                                showlegend=False,
                            ),
                            row=row_index,
                            col=1,
                        )
                        fig.add_trace(
                            go.Scatter(
                                x=dates,
                                y=[mean_value] * len(dates),
                                mode="lines",
                                line=dict(color=color, width=1.8, dash="dash"),
                                hoverinfo="skip",
                                showlegend=False,
                            ),
                            row=row_index,
                            col=1,
                        )
                        reference_labels.append(
                            f"{series_name}: media {_fmt(mean_value, 1)} {unit} "
                            f"(franja {_fmt(mean_value - 5, 1)}–{_fmt(mean_value + 5, 1)} {unit})"
                        )
                        fig.add_trace(
                            go.Scatter(
                                x=series_df["date"],
                                y=series_df[field],
                                mode="lines+markers",
                                marker=dict(size=3),
                                line=dict(color=color, width=2),
                                showlegend=False,
                            ),
                            row=row_index,
                            col=1,
                        )
                        fig.update_yaxes(title_text=unit, row=row_index, col=1)
                    fig.update_xaxes(tickformat="%d %b %y", row=len(health_series), col=1)
                    fig.update_annotations(font=dict(size=12, color=P["muted"]))
                    st.caption(
                        "Línea discontinua = media del periodo; franja sombreada = media ±5. "
                        + " · ".join(reference_labels)
                    )
                    st.plotly_chart(_style(fig), width="stretch")

            if wellness_available:
                st.subheader("Sueño, HRV y peso")
                recent = filtered_wellness.sort_values("date", ascending=False).head(30).copy()
                recent["Fecha"] = recent["date"].dt.strftime("%d/%m/%Y")
                st.dataframe(
                    recent[
                        [
                            "Fecha",
                            "sleep_h",
                            "sleep_score",
                            "resting_hr",
                            "hrv",
                            "weight",
                            "ctl",
                            "atl",
                            "tsb",
                        ]
                    ].rename(
                        columns={
                            "sleep_h": "Sueño (h)",
                            "sleep_score": "Score sueño",
                            "resting_hr": "FC reposo",
                            "hrv": "HRV",
                            "weight": "Peso (kg)",
                            "ctl": "CTL",
                            "atl": "ATL",
                            "tsb": "TSB",
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )

            battery = filtered_daily.dropna(subset=["body_battery_min", "body_battery_max"])
            if not battery.empty:
                st.subheader("Body Battery (Garmin)")
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=battery["date"],
                        y=battery["body_battery_max"],
                        name="Máximo",
                        line=dict(color=P["battery_max"], width=1.8),
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=battery["date"],
                        y=battery["body_battery_min"],
                        name="Mínimo",
                        line=dict(color=P["battery_min"], width=1.8),
                    )
                )
                fig.update_xaxes(tickformat="%d %b %y")
                st.plotly_chart(_style(fig, height=300), width="stretch")


    # ---------------------------- Planificación ------------------------------ #

if main_section == "Planificación":
    with st.container():
        plan_path = Path(__file__).with_name("planning_bloque_1.json")
        st.subheader("Objetivo · Desafío Lagos de Covadonga · junio de 2027")
        _metric_row([
            ("Bloque actual", "Base y fondo · S1–S9", "Plan aportado por el deportista"),
            ("Disponibilidad", "5–7 h / semana", None),
            ("Sesiones principales", "Martes · jueves · fin de semana", None),
            ("Objetivo de diciembre", "Hasta 100 km · 1.500 m+", "Condicionado a la progresión y recuperación"),
        ])
        st.caption("Puedes editar las sesiones, fechas, objetivos y notas directamente en la tabla. Asocia cada fila con la salida registrada correspondiente y pulsa Guardar planificación.")
        try:
            plan_items = json.loads(plan_path.read_text(encoding="utf-8"))
            if not isinstance(plan_items, list):
                raise ValueError("el contenido no es una lista de sesiones")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            st.error(
                f"No se pudo leer `{plan_path.name}`: {exc}. Se muestra un plan "
                "vacío; al guardar se creará de nuevo si hay filas con fecha."
            )
            plan_items = []
        plan_activities = _combined_activities(garmin, intervals_acts)
        if not plan_activities.empty:
            activity_options_frame = plan_activities[plan_activities["is_cycling"]].sort_values("start", ascending=False)
        else:
            activity_options_frame = plan_activities
        activity_labels = {}
        for _, activity_row in activity_options_frame.iterrows():
            label = (
                f"{activity_row['start']:%d/%m/%Y %H:%M} · {activity_row['sport']} · "
                f"{activity_row.get('activity_name') or 'Sin nombre'} · {activity_row['activity_id']}"
            )
            activity_labels[label] = str(activity_row["activity_id"])
        activity_id_to_label = {activity_id: label for label, activity_id in activity_labels.items()}
        activity_by_id = {
            str(activity_row["activity_id"]): activity_row
            for _, activity_row in activity_options_frame.iterrows()
        }
        editor_rows = []
        for item in plan_items:
            planned_date = pd.to_datetime(item.get("fecha"), errors="coerce")
            editor_rows.append({
                "Semana": item.get("semana", ""),
                "Fecha": planned_date.date() if pd.notna(planned_date) else None,
                "Sesión": item.get("sesion", ""),
                "Modalidad": item.get("modalidad", ""),
                "Duración": item.get("duracion", ""),
                "Estructura": item.get("estructura", ""),
                "Objetivo": item.get("objetivo", ""),
                "Potencia objetivo": item.get("potencia", ""),
                "Pulso / esfuerzo": item.get("pulso", ""),
                "Observaciones": item.get("observaciones", ""),
                "Actividad asociada": activity_id_to_label.get(str(item.get("activity_link_id", "")), ""),
            })
        editor_columns = [
            "Semana",
            "Fecha",
            "Sesión",
            "Modalidad",
            "Duración",
            "Estructura",
            "Objetivo",
            "Potencia objetivo",
            "Pulso / esfuerzo",
            "Observaciones",
            "Actividad asociada",
        ]
        editor_frame = pd.DataFrame(editor_rows, columns=editor_columns)
        editor_frame["Fecha"] = pd.to_datetime(editor_frame["Fecha"], errors="coerce")
        edited_plan = st.data_editor(
            editor_frame,
            hide_index=True,
            width="stretch",
            height=560,
            key="plan_editor",
            column_config={
                "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Semana": st.column_config.TextColumn(width="small"),
                "Sesión": st.column_config.TextColumn(width="medium"),
                "Estructura": st.column_config.TextColumn(width="large"),
                "Objetivo": st.column_config.TextColumn(width="large"),
                "Observaciones": st.column_config.TextColumn(width="large"),
                "Actividad asociada": st.column_config.SelectboxColumn(
                    options=[""] + list(activity_labels),
                    required=False,
                    width="large",
                    help="Selecciona la actividad registrada que cumple esta sesión.",
                ),
            },
        )
        if st.button("Guardar planificación", type="primary", key="save_plan"):
            saved_items = []
            invalid_rows = 0
            field_map = {
                "Semana": "semana", "Sesión": "sesion", "Modalidad": "modalidad",
                "Duración": "duracion", "Estructura": "estructura", "Objetivo": "objetivo",
                "Potencia objetivo": "potencia", "Pulso / esfuerzo": "pulso",
                "Observaciones": "observaciones",
            }
            for row in edited_plan.to_dict("records"):
                planned_date = pd.to_datetime(row.get("Fecha"), errors="coerce")
                if pd.isna(planned_date):
                    invalid_rows += 1
                    continue
                saved = {target: str(row.get(column, "") or "") for column, target in field_map.items()}
                saved["fecha"] = planned_date.date().isoformat()
                selected_activity = row.get("Actividad asociada") or ""
                saved["activity_link_id"] = activity_labels.get(selected_activity, "")
                previous = next(
                    (
                        item for item in plan_items
                        if str(item.get("fecha", "")) == saved["fecha"]
                        and str(item.get("sesion", "")) == saved["sesion"]
                    ),
                    None,
                )
                if previous:
                    saved = {**previous, **saved}
                saved_items.append(saved)
            if invalid_rows:
                st.warning(
                    f"{invalid_rows} fila(s) sin fecha válida no se guardaron."
                )
            if not saved_items:
                st.error("No hay ninguna fila con fecha válida que guardar.")
            else:
                planning.save_plan(plan_path, saved_items)
                st.success("Planificación guardada.")
                st.rerun()

        if plan_items:
            plan_choices = {
                f"{item.get('semana', 'Semana –')} · {item.get('sesion', 'Sesión')} · {item.get('fecha', 'sin fecha')}": index
                for index, item in enumerate(plan_items)
            }
            with st.expander("Editar bloques estructurados de una sesión"):
                selected_plan_label = st.selectbox(
                    "Sesión del plan", list(plan_choices), key="structured_plan_choice"
                )
                plan_index = plan_choices[selected_plan_label]
                selected_plan_item = plan_items[plan_index]
                block_frame = planning.blocks_frame(selected_plan_item.get("bloques"))
                st.caption(
                    "Potencia en %FTP y frecuencia cardiaca en ppm. "
                    "Los objetivos solo se convierten a W/ppm si hay FTP/LTHR configurados."
                )
                edited_blocks = st.data_editor(
                    block_frame,
                    num_rows="dynamic",
                    hide_index=True,
                    width="stretch",
                    key=f"blocks_editor_{plan_index}",
                    column_config={
                        "Nombre": st.column_config.TextColumn(),
                        "Notas": st.column_config.TextColumn(width="large"),
                    },
                )
                if st.button("Guardar bloques de la sesión", key="save_blocks", type="primary"):
                    blocks, invalid_blocks = planning.blocks_from_records(
                        edited_blocks.to_dict("records")
                    )
                    updated_plan = [dict(item) for item in plan_items]
                    updated_plan[plan_index]["bloques"] = blocks
                    planning.save_plan(plan_path, updated_plan)
                    if invalid_blocks:
                        st.warning(f"Se omitieron {invalid_blocks} bloque(s) con valores fuera de rango.")
                    st.success("Bloques guardados en la planificación.")
                    st.rerun()

        plan_rows = []
        invalid_plan_dates = 0
        for row in edited_plan.to_dict("records"):
            planned_date = pd.to_datetime(row.get("Fecha"), errors="coerce")
            if pd.isna(planned_date):
                invalid_plan_dates += 1
                continue
            planned_day = planned_date.date()
            selected_label = row.get("Actividad asociada") or ""
            linked_id = activity_labels.get(selected_label, "")
            actual = activity_by_id.get(linked_id) if linked_id else None
            if actual is None and not plan_activities.empty:
                candidates = plan_activities[
                    plan_activities["start"].dt.date.isin([planned_day, planned_day + timedelta(days=1)])
                    & plan_activities["is_cycling"]
                ].copy()
                if not candidates.empty:
                    candidates["day_gap"] = candidates["start"].dt.date.map(lambda actual_day: abs((actual_day - planned_day).days))
                    actual = candidates.sort_values("day_gap").iloc[0]
            if actual is not None:
                state = "Realizada"
                actual_distance = float(actual["distance_km"]) if pd.notna(actual["distance_km"]) else None
                actual_elevation = float(actual["elevation_gain_m"]) if pd.notna(actual["elevation_gain_m"]) else None
                actual_summary = f"{actual['duration_min']:.0f} min · {actual_distance:.1f} km" if actual_distance is not None else f"{actual['duration_min']:.0f} min"
                actual_summary += f" · {actual_elevation:.0f} m+" if actual_elevation is not None else " · desnivel sin dato"
                actual_link = f"{actual['start']:%d/%m/%Y} · {actual.get('activity_name') or actual['sport']}"
            else:
                state = "Pendiente" if planned_day >= date.today() else "Sin actividad enlazada"
                actual_distance = actual_elevation = None
                actual_summary = actual_link = "–"
            observations = str(row.get("Observaciones") or "")
            elevation_match = re.search(r"(\d{3,4})\s*[-–]\s*(\d{3,4})\s*m", observations)
            distance_match = re.search(r"(\d{2,3})\s*km", observations)
            elevation_single = re.search(r"(\d{3,4})\s*m\s*(?:positivos|\+)", observations, flags=re.IGNORECASE)
            plan_rows.append({
                "Semana": row["Semana"],
                "Fecha": planned_day.strftime("%d/%m/%Y"),
                "Sesión": row["Sesión"],
                "Modalidad": row["Modalidad"],
                "Duración prevista": row["Duración"],
                "Distancia objetivo (km)": distance_match.group(1) if distance_match else "–",
                "Desnivel objetivo (m+)": f"{elevation_match.group(1)}–{elevation_match.group(2)}" if elevation_match else (f"≤{elevation_single.group(1)}" if elevation_single else "–"),
                "Realización": state,
                "Distancia realizada (km)": round(actual_distance, 1) if actual_distance is not None else None,
                "Desnivel realizado (m+)": round(actual_elevation) if actual_elevation is not None else None,
                "Actividad asociada": actual_link,
                "Actividad registrada": actual_summary,
            })
        if invalid_plan_dates:
            st.warning(
                f"{invalid_plan_dates} fila(s) sin fecha válida se omiten del "
                "seguimiento. Corrige la fecha y vuelve a guardar."
            )
        plan_view = pd.DataFrame(plan_rows)
        if not plan_view.empty:
            for column in ("Distancia realizada (km)", "Desnivel realizado (m+)"):
                plan_view[column] = pd.to_numeric(
                    plan_view[column], errors="coerce"
                )
        if plan_view.empty:
            st.info(
                "No hay sesiones de planificación con fecha válida para mostrar."
            )
        else:
            state_filter = st.multiselect("Mostrar estado", ["Pendiente", "Realizada", "Sin actividad enlazada"], default=["Pendiente", "Realizada", "Sin actividad enlazada"], key="plan_status_filter")
            st.subheader("Plan y seguimiento de distancia y desnivel")
            st.dataframe(
                plan_view[plan_view["Realización"].isin(state_filter)],
                hide_index=True,
                width="stretch",
                height=420,
                column_config={
                    "Distancia realizada (km)": st.column_config.NumberColumn(
                        format="%.1f"
                    ),
                    "Desnivel realizado (m+)": st.column_config.NumberColumn(
                        format="%.0f"
                    ),
                },
            )
            plan_summary = plan_view.groupby("Semana", as_index=False).agg(
                sesiones_previstas=("Sesión", "count"),
                realizadas=("Realización", lambda values: int((values == "Realizada").sum())),
            )
            plan_summary["% completado"] = (plan_summary["realizadas"] / plan_summary["sesiones_previstas"] * 100).round(0)
            st.subheader("Seguimiento por semana")
            plan_summary["sesiones_texto"] = plan_summary.apply(
                lambda row: f"{int(row['realizadas'])}/{int(row['sesiones_previstas'])} sesiones",
                axis=1,
            )
            fig = px.bar(
                plan_summary,
                x="% completado",
                y="Semana",
                orientation="h",
                text="sesiones_texto",
                labels={"% completado": "Sesiones completadas (%)", "Semana": ""},
                color_discrete_sequence=[P["ctl"]],
            )
            fig.update_traces(textposition="outside", cliponaxis=False)
            fig.update_xaxes(
                range=[0, 100],
                tickmode="array",
                tickvals=[25, 50, 75, 100],
                ticktext=["25%", "50%", "75%", "100%"],
            )
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(
                _style(fig, height=max(280, 44 * len(plan_summary))),
                width="stretch",
            )
