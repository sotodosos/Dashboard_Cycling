"""Galería temporal para revisar representaciones de los gráficos del dashboard."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import altair as alt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from . import analytics as an
from . import streams as stream_tools


THEMES: dict[str, dict[str, Any]] = {
    "Carbón refinado": {
        "background": "#111827", "panel": "#1F2937", "text": "#F1F5F9",
        "muted": "#B6C2D1", "grid": "#38465A",
        "colors": ["#38BDF8", "#FB923C", "#34D399", "#FB7185", "#A78BFA", "#FBBF24", "#E879F9"],
    },
    "Rendimiento deportivo": {
        "background": "#0B1017", "panel": "#151F2B", "text": "#F8FAFC",
        "muted": "#D0D9E4", "grid": "#405063",
        "colors": ["#22D3EE", "#A3E635", "#FB923C", "#F472B6", "#A78BFA", "#FACC15", "#60A5FA"],
    },
    "Minimalista claro": {
        "background": "#F4F7FB", "panel": "#FFFFFF", "text": "#172033",
        "muted": "#526174", "grid": "#D9E1EA",
        "colors": ["#087EA4", "#D45D00", "#198754", "#C2415D", "#7554B8", "#A66A00", "#A33BA8"],
    },
}

FONTS = {
    "DM Sans + Space Grotesk": {
        "body": "'DM Sans', 'Segoe UI', sans-serif",
        "heading": "'Space Grotesk', 'Segoe UI', sans-serif",
        "sample": "Una salida constante suma temporada",
    },
    "IBM Plex Sans + Barlow Condensed": {
        "body": "'IBM Plex Sans', 'Segoe UI', sans-serif",
        "heading": "'Barlow Condensed', 'Arial Narrow', sans-serif",
        "sample": "Una salida constante suma temporada",
    },
    "Manrope": {
        "body": "'Manrope', 'Segoe UI', sans-serif",
        "heading": "'Manrope', 'Segoe UI', sans-serif",
        "sample": "Una salida constante suma temporada",
    },
}

FONT_IMPORTS = {
    "DM Sans + Space Grotesk": "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap",
    "IBM Plex Sans + Barlow Condensed": "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap",
    "Manrope": "https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap",
}

# Comparisons of marks are kept orthogonal to the renderer tabs: one selection
# is applied to Plotly, Vega-Lite and ECharts so the user can compare libraries
# without also changing the visual grammar.
REPRESENTATION_OPTIONS = {
    "forma_carga_semanal": ["Columnas", "Lollipop", "Línea"],
    "ciclismo_volumen_semanal": [
        "Columnas apiladas", "Área apilada", "Líneas por tipo", "Dona del periodo",
    ],
    "ciclismo_potencia_semanal": ["Líneas", "Áreas", "Columnas agrupadas"],
    "ciclismo_reparto_deporte": ["Barras", "Lollipop", "Tarta", "Dona"],
    "ciclismo_rodillo_exterior": ["Barras", "Lollipop", "Tarta", "Dona"],
    "ciclismo_zonas_hr": ["Barras", "Lollipop", "Tarta", "Dona"],
    "ciclismo_zonas_power": ["Barras", "Lollipop", "Tarta", "Dona"],
    "actividad_zonas_hr": ["Barras", "Lollipop", "Tarta", "Dona"],
    "actividad_zonas_power": ["Barras", "Lollipop", "Tarta", "Dona"],
    "plan_seguimiento_semanal": ["Barras", "Lollipop", "Línea"],
}

PIE_REPRESENTATIONS = {"Tarta", "Dona", "Dona del periodo"}


def _pie_data(spec: dict[str, Any]) -> pd.DataFrame:
    """Agrega por categoría para una comparación de composición del periodo."""
    frame: pd.DataFrame = spec["data"]
    category = spec.get("series") if spec["kind"] == "stacked_bar" else spec["x"]
    if frame.empty or category not in frame or spec["y"] not in frame:
        return _empty(("category", "value"))
    result = frame.groupby(category, dropna=False, as_index=False)[spec["y"]].sum()
    return result.rename(columns={category: "category", spec["y"]: "value"})


def _representation_options(spec: dict[str, Any]) -> list[str]:
    return REPRESENTATION_OPTIONS.get(spec["key"], [])


def _empty(columns: tuple[str, ...] = ()) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _numeric(frame: pd.DataFrame, field: str) -> pd.Series:
    if field not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[field], errors="coerce")


def _safe_plan(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return result if isinstance(result, list) else []


def _focus_filter(frame: pd.DataFrame, focus_mask: Callable[[pd.DataFrame, str], pd.Series], focus: str) -> pd.DataFrame:
    if frame.empty or "is_cycling" not in frame:
        return frame.copy()
    return frame.loc[focus_mask(frame, focus)].copy()


def _date_filter(frame: pd.DataFrame, start: date | None, end: date | None, *, field: str = "date") -> pd.DataFrame:
    if frame.empty or field not in frame:
        return frame.copy()
    dates = pd.to_datetime(frame[field], errors="coerce")
    mask = dates.notna()
    if start is not None:
        mask &= dates.dt.date >= start
    if end is not None:
        mask &= dates.dt.date <= end
    return frame.loc[mask].copy()


def _week_series(frame: pd.DataFrame, date_field: str = "start") -> pd.Series:
    dates = pd.to_datetime(frame[date_field], errors="coerce")
    return dates.dt.to_period("W-SUN").dt.start_time


def _metric_spec(
    key: str, section: str, title: str, kind: str, frame: pd.DataFrame,
    *, x: str = "date", y: str = "value", unit: str = "", description: str = "",
    representation: dict[str, str] | None = None, **extra: Any,
) -> dict[str, Any]:
    return {
        "key": key, "section": section, "title": title, "kind": kind,
        "data": frame.copy(), "x": x, "y": y, "unit": unit,
        "description": description,
        "representations": representation or {
            "Plotly": "Línea interactiva", "Altair / Vega-Lite": "Capa declarativa",
            "Apache ECharts": "Serie con interacción nativa",
        },
        **extra,
    }


def build_catalog(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Prepara gráficos desde los mismos marcos filtrados que consume la app."""
    activities: pd.DataFrame = data.get("filtered_activities", _empty())
    full_activities: pd.DataFrame = data.get("all_activities", activities)
    wellness: pd.DataFrame = data.get("wellness", _empty())
    daily: pd.DataFrame = data.get("daily", _empty())
    intervals_wellness: pd.DataFrame = data.get("intervals_wellness", _empty())
    garmin: pd.DataFrame = data.get("garmin", _empty())
    intervals_activities: pd.DataFrame = data.get("intervals_activities", _empty())
    settings = data.get("settings")
    focus_mask = data.get("focus_mask", lambda frame, _focus: pd.Series(True, index=frame.index))
    focus = data.get("focus", "Ciclismo y rodillo")
    start_date: date = data.get("start_date", date.today() - timedelta(days=90))
    end_date: date = data.get("end_date", date.today())
    specs: list[dict[str, Any]] = []

    # Recuperación · Forma
    form = wellness.copy() if not wellness.empty else _empty()
    form_fields = [column for column in ("ctl", "atl") if column in form]
    form = form.dropna(subset=form_fields) if form_fields else _empty()
    if not form.empty:
        form = form.sort_values("date")
    specs.append(_metric_spec(
        "forma_evolucion", "Forma", "Evolución de la forma", "form", form,
        x="date", y="ctl", unit="carga / TSB",
        description="CTL y ATL comparten panel; TSB mantiene su escala separada. Se conservan fechas, valores y unidades.",
        representations={"Plotly": "Dos paneles coordinados", "Altair / Vega-Lite": "Small multiples declarativos", "Apache ECharts": "Doble eje temporal coordinado"},
    ))

    load = activities.dropna(subset=["training_load"]).copy() if "training_load" in activities else _empty()
    if not load.empty:
        load["week"] = _week_series(load)
        load = load.groupby("week", as_index=False)["training_load"].sum().sort_values("week")
        threshold = load["training_load"].quantile(0.75)
        load["level"] = np.where(load["training_load"] >= threshold, "Cuartil superior", "Carga habitual")
    specs.append(_metric_spec(
        "forma_carga_semanal", "Forma", "Carga semanal de las sesiones", "bar", load,
        x="week", y="training_load", unit="carga", series="level",
        description="Suma semanal de carga registrada y distinción del cuartil superior.",
        representations={"Plotly": "Columnas por semana", "Altair / Vega-Lite": "Lollipop semanal", "Apache ECharts": "Columnas con umbral interactivo"},
    ))

    ramp = form.dropna(subset=["ramp_rate"]).copy() if "ramp_rate" in form else _empty()
    specs.append(_metric_spec(
        "forma_ramp_rate", "Forma", "Ramp rate", "line", ramp,
        x="date", y="ramp_rate", unit="CTL / semana",
        description="Variación de la carga crónica registrada por intervals.icu.",
        representations={"Plotly": "Área suave", "Altair / Vega-Lite": "Línea con puntos", "Apache ECharts": "Área interactiva"},
    ))

    # Entrenamiento · Ciclismo
    cycling = activities.loc[activities.get("is_cycling", pd.Series(False, index=activities.index)).fillna(False)].copy()
    source_choice = data.get("source_choice", "Ambas fuentes")
    curve_source = garmin if source_choice != "Solo intervals.icu" else intervals_activities
    curve_source = _date_filter(curve_source, end_date - timedelta(days=182), end_date)
    curve_source = _focus_filter(curve_source, focus_mask, focus)
    curve_source = curve_source.loc[curve_source.get("is_cycling", pd.Series(False, index=curve_source.index)).fillna(False)].copy() if not curve_source.empty else curve_source
    historical_curve = stream_tools.power_curve_from_summary(curve_source)
    recent_curve_source = _date_filter(curve_source, end_date - timedelta(days=29), end_date)
    recent_curve = stream_tools.power_curve_from_summary(recent_curve_source)
    if not historical_curve.empty:
        historical_curve = historical_curve.rename(columns={"watts": "Últimos 6 meses"})[["duration_s", "Últimos 6 meses"]]
        if not recent_curve.empty:
            recent_curve = recent_curve.rename(columns={"watts": "Últimos 30 días"})[["duration_s", "Últimos 30 días"]]
            power_curve = historical_curve.merge(recent_curve, on="duration_s", how="outer").sort_values("duration_s")
        else:
            power_curve = historical_curve
        power_curve["duration_label"] = power_curve["duration_s"].map(lambda s: f"{s}s" if s < 60 else (f"{s // 60} min" if s < 3600 else f"{s // 3600} h"))
    else:
        power_curve = _empty(("duration_s", "duration_label", "Últimos 6 meses", "Últimos 30 días"))
    curve_long = power_curve.melt(id_vars=[c for c in ("duration_s", "duration_label") if c in power_curve], var_name="series", value_name="value") if not power_curve.empty else _empty(("duration_s", "duration_label", "series", "value"))
    specs.append(_metric_spec(
        "ciclismo_curva_potencia", "Ciclismo", "Curva de potencia", "curve", curve_long,
        x="duration_s", y="value", unit="W", series="series",
        description="Mejor potencia media disponible por duración; compara los últimos 30 días con seis meses.",
        x_label="Duración del esfuerzo", x_scale="log",
    ))

    if not cycling.empty:
        cycling["duration_h"] = _numeric(cycling, "duration_min") / 60
    volume = an.weekly_volume(cycling, "duration_h") if not cycling.empty else _empty(("week", "sport", "duration_h"))
    volume_mode = data.get("volume_mode", "Horas")
    volume_field = "duration_h" if volume_mode == "Horas" else "distance_km"
    if volume_mode != "Horas":
        volume = an.weekly_volume(cycling, "distance_km") if not cycling.empty else _empty(("week", "sport", "distance_km"))
    specs.append(_metric_spec(
        "ciclismo_volumen_semanal", "Ciclismo", "Volumen semanal", "stacked_bar", volume,
        x="week", y=volume_field, unit="h" if volume_mode == "Horas" else "km", series="sport",
        description=f"Volumen semanal de ciclismo apilado por tipo de actividad ({volume_mode.lower()}).",
        representations={"Plotly": "Columnas apiladas", "Altair / Vega-Lite": "Área apilada", "Apache ECharts": "Columnas apiladas"},
    ))

    power = an.weekly_power(cycling) if not cycling.empty else _empty(("week", "avg_power_w", "weighted_avg_power_w"))
    if not power.empty:
        power_long = power.melt(id_vars=["week"], value_vars=[c for c in ("avg_power_w", "weighted_avg_power_w") if c in power], var_name="series", value_name="value")
        power_long["series"] = power_long["series"].map({"avg_power_w": "Potencia media", "weighted_avg_power_w": "Potencia normalizada"}).fillna(power_long["series"])
    else:
        power_long = _empty(("week", "series", "value"))
    specs.append(_metric_spec(
        "ciclismo_potencia_semanal", "Ciclismo", "Potencia media y normalizada", "multi_line", power_long,
        x="week", y="value", unit="W", series="series",
        description="Medias semanales de potencia media y normalizada; colores separados para distinguirlas.",
        representations={"Plotly": "Líneas con puntos", "Altair / Vega-Lite": "Líneas diferenciadas", "Apache ECharts": "Líneas suavizadas"},
    ))

    scatter = cycling.dropna(subset=[c for c in ("avg_hr", "speed_kmh") if c in cycling]).copy() if not cycling.empty else _empty()
    if not scatter.empty:
        scatter["tipo"] = scatter["indoor"].map({True: "Rodillo", False: "Exterior"}) if "indoor" in scatter else "Actividad"
    specs.append(_metric_spec(
        "ciclismo_velocidad_fc", "Ciclismo", "Velocidad y FC", "scatter", scatter,
        x="avg_hr", y="speed_kmh", unit="", color="tipo", size="duration_min",
        description="Cada punto es una salida. El tamaño representa duración y el color diferencia rodillo y exterior.",
        x_label="FC media (ppm)", y_label="Velocidad media (km/h)",
        representations={"Plotly": "Dispersión con tamaño por duración", "Altair / Vega-Lite": "Dispersión con selección", "Apache ECharts": "Dispersión con zoom"},
    ))

    sport_share = an.sport_breakdown(cycling, "distance_km") if not cycling.empty else _empty(("sport", "distance_km", "sessions"))
    specs.append(_metric_spec(
        "ciclismo_reparto_deporte", "Ciclismo", "Reparto por deporte · distancia", "bar", sport_share,
        x="sport", y="distance_km", unit="km",
        description="Distancia acumulada por disciplina en el periodo y foco seleccionados.",
        representations={"Plotly": "Barras horizontales", "Altair / Vega-Lite": "Lollipop ordenado", "Apache ECharts": "Barras horizontales"},
        orientation="horizontal",
    ))

    if not cycling.empty:
        indoor = cycling["indoor"].fillna(False) if "indoor" in cycling else pd.Series(False, index=cycling.index)
        indoor_outdoor = cycling.assign(tipo=np.where(indoor, "Rodillo", "Exterior")).groupby("tipo", as_index=False).agg(horas=("duration_min", lambda values: _numeric(pd.DataFrame({"v": values}), "v").sum() / 60))
    else:
        indoor_outdoor = _empty(("tipo", "horas"))
    specs.append(_metric_spec(
        "ciclismo_rodillo_exterior", "Ciclismo", "Horas de rodillo y exterior", "bar", indoor_outdoor,
        x="tipo", y="horas", unit="h",
        description="Tiempo total separado entre rodillo y ciclismo exterior.",
        representations={"Plotly": "Columnas comparativas", "Altair / Vega-Lite": "Puntos con regla de cero", "Apache ECharts": "Barras comparativas"},
    ))

    # Los gráficos de zonas siguen la prioridad de fuente de la pestaña Ciclismo.
    zone_garmin = _date_filter(garmin, start_date, end_date)
    zone_intervals = _date_filter(intervals_activities, start_date, end_date)
    zone_garmin = _focus_filter(zone_garmin, focus_mask, focus)
    zone_intervals = _focus_filter(zone_intervals, focus_mask, focus)
    zone_garmin = zone_garmin.loc[zone_garmin.get("is_cycling", pd.Series(False, index=zone_garmin.index)).fillna(False)].copy() if not zone_garmin.empty else zone_garmin
    zone_intervals = zone_intervals.loc[zone_intervals.get("is_cycling", pd.Series(False, index=zone_intervals.index)).fillna(False)].copy() if not zone_intervals.empty else zone_intervals
    hr_zone_source = zone_intervals if source_choice == "Solo intervals.icu" or zone_garmin.empty or an.zone_minutes(zone_garmin, "hr")["minutes"].sum() <= 0 else zone_garmin
    power_zone_source = zone_intervals if not zone_intervals.empty else cycling
    for kind, title, source, zone_kind in (
        ("zones", "Zonas de frecuencia cardiaca · 5 zonas LTHR", hr_zone_source, "hr"),
        ("zones", "Zonas de potencia · Coggan 7 zonas", power_zone_source, "power"),
    ):
        zone_data = an.zone_minutes(source, zone_kind) if not source.empty else _empty(("zone", "label", "minutes"))
        zone_data = zone_data.loc[zone_data.get("minutes", pd.Series(dtype=float)) > 0].copy() if not zone_data.empty else zone_data
        specs.append(_metric_spec(
            f"ciclismo_zonas_{zone_kind}", "Ciclismo", title, "zones", zone_data,
            x="label", y="minutes", unit="min", zone_kind=zone_kind,
            description="Tiempo registrado en cada zona; lollipop y barras conservan rangos y minutos.",
            representations={"Plotly": "Barras por zona", "Altair / Vega-Lite": "Lollipop por zona", "Apache ECharts": "Barras con paleta por zona"},
            orientation="horizontal",
        ))

    # Actividades · seleccionar actividad real; streams solo cuando se abre este grupo.
    selected_activity = data.get("selected_activity")

    activity_context = activities.dropna(subset=[column for column in ("avg_power_w", "avg_hr") if column in activities]).copy() if not activities.empty else _empty()
    if not activity_context.empty and {"avg_power_w", "avg_hr"}.issubset(activity_context.columns):
        if selected_activity is not None:
            selected_id = str(selected_activity.get("activity_id", ""))
            activity_context["seleccion"] = np.where(
                activity_context["activity_id"].astype(str) == selected_id,
                "Actividad elegida", "Otras salidas",
            )
        else:
            activity_context["seleccion"] = "Salidas del periodo"
    else:
        activity_context = _empty(("avg_power_w", "avg_hr", "seleccion", "duration_min", "activity_name"))
    specs.append(_metric_spec(
        "actividad_contexto", "Actividades", "Actividad frente al periodo", "scatter", activity_context,
        x="avg_power_w", y="avg_hr", unit="", color="seleccion", size="duration_min",
        description="Relación entre potencia y frecuencia cardiaca de las salidas filtradas; resalta la sesión elegida sin depender de streams.",
        x_label="Potencia media (W)", y_label="FC media (ppm)",
        representations={"Plotly": "Dispersión con duración", "Altair / Vega-Lite": "Dispersión interactiva", "Apache ECharts": "Dispersión con zoom"},
    ))
    for key, title, field, unit in (
        ("actividad_potencia_resumen", "Potencia media por salida", "avg_power_w", "W"),
        ("actividad_velocidad_resumen", "Velocidad media por salida", "speed_kmh", "km/h"),
        ("actividad_desnivel_resumen", "Desnivel por salida", "elevation_gain_m", "m+"),
    ):
        summary = activities.dropna(subset=[field]).copy() if field in activities else _empty()
        if not summary.empty:
            selected_id = str(selected_activity.get("activity_id", "")) if selected_activity is not None else ""
            summary["seleccion"] = np.where(
                summary["activity_id"].astype(str) == selected_id,
                "Actividad elegida", "Otras salidas",
            )
        specs.append(_metric_spec(
            key, "Actividades", title, "activity_summary", summary,
            x="start", y=field, unit=unit, color="seleccion",
            description="Un punto por salida con datos locales; el color de acento identifica la actividad elegida. No requiere descargar streams.",
            x_label="Fecha", y_label=unit,
            representations={"Plotly": "Puntos cronológicos", "Altair / Vega-Lite": "Dot plot temporal", "Apache ECharts": "Dispersión temporal"},
        ))

    stream_result: dict[str, Any] = {"streams": [], "error": None}
    activity_detail = selected_activity.copy() if selected_activity is not None else None
    if selected_activity is not None:
        activity_start = pd.to_datetime(selected_activity.get("start"), errors="coerce")
        interval_match = None
        if not intervals_activities.empty and pd.notna(activity_start):
            candidates = intervals_activities.copy()
            candidates["_gap"] = (pd.to_datetime(candidates["start"], errors="coerce") - activity_start).abs().dt.total_seconds()
            candidates = candidates.loc[candidates["_gap"] <= 90].sort_values("_gap")
            if not candidates.empty:
                interval_match = candidates.iloc[0]

        # La tabla combinada conserva la fuente que ganó la deduplicación. Para
        # las zonas y la curva de potencia aprovechamos campos de la otra fuente
        # local si existen, sin volver a descargar la actividad.
        source_matches = [row for row in (interval_match,) if row is not None]
        garmin_match = None
        if not garmin.empty and pd.notna(activity_start):
            candidates = garmin.copy()
            candidates["_gap"] = (pd.to_datetime(candidates["start"], errors="coerce") - activity_start).abs().dt.total_seconds()
            candidates = candidates.loc[candidates["_gap"] <= 90].sort_values("_gap")
            if not candidates.empty:
                garmin_match = candidates.iloc[0]
                source_matches.append(garmin_match)
        if activity_detail is not None:
            raw_summary: dict[str, Any] = {}
            for candidate in (activity_detail, *source_matches):
                try:
                    parsed = json.loads(candidate.get("raw_json") or "{}")
                except (TypeError, json.JSONDecodeError):
                    parsed = {}
                if isinstance(parsed, dict):
                    for key, value in parsed.items():
                        if value is not None:
                            raw_summary.setdefault(key, value)
                for column, value in candidate.items():
                    if column.startswith(("hr_zone_", "power_zone_")) and value is not None and pd.notna(value):
                        if column not in activity_detail or pd.isna(activity_detail.get(column)):
                            activity_detail[column] = value
            activity_detail["raw_json"] = json.dumps(raw_summary, ensure_ascii=False)
        if interval_match is not None and data.get("intervals_configured", False) and data.get("load_activity_streams", False):
            fetcher = data.get("streams_fetcher")
            if fetcher:
                try:
                    stream_result = fetcher(str(interval_match["activity_id"]))
                except Exception as exc:  # la galería no debe interrumpir el resto del dashboard
                    stream_result = {"streams": [], "error": str(exc)}

    activity_streams = stream_result.get("streams", []) or []
    activity_stream_error = stream_result.get("error")
    time_s = stream_tools.stream_values(activity_streams, "time")
    distance_m = stream_tools.stream_values(activity_streams, "distance")
    altitude_m = stream_tools.stream_values(activity_streams, "altitude")
    speed_mps = stream_tools.stream_values(activity_streams, "velocity_smooth")
    watts = stream_tools.stream_values(activity_streams, "watts")

    altitude_profile = _empty(("Distancia", "Altitud"))
    if distance_m and altitude_m:
        altitude_profile = stream_tools.profile_frame(distance_m, altitude_m, "Distancia", "Altitud")
        altitude_profile["Distancia"] /= 1000
        altitude_profile = altitude_profile.iloc[::max(len(altitude_profile) // 2500, 1)]
    specs.append(_metric_spec(
        "actividad_perfil_altitud", "Actividades", "Perfil de altitud", "profile", altitude_profile,
        x="Distancia", y="Altitud", unit="m", x_label="Distancia (km)", y_label="Altitud (m)",
        description="Perfil de altitud muestreado del stream original. Para esta alternativa se muestran solo puntos recibidos.", stream_error=activity_stream_error,
        representations={"Plotly": "Área de perfil", "Altair / Vega-Lite": "Línea con selección de tramo", "Apache ECharts": "Línea con zoom"},
    ))

    speed_profile = _empty(("Distancia", "Velocidad"))
    speed_x = "Distancia"
    if distance_m and speed_mps:
        speed_profile = stream_tools.profile_frame(distance_m, speed_mps, "Distancia", "Velocidad")
        speed_profile["Distancia"] /= 1000
        speed_profile["Velocidad"] *= 3.6
    elif time_s and speed_mps:
        speed_profile = stream_tools.profile_frame(time_s, speed_mps, "Tiempo", "Velocidad")
        speed_profile["Tiempo"] /= 60
        speed_profile["Velocidad"] *= 3.6
        speed_x = "Tiempo"
    if not speed_profile.empty:
        speed_profile = speed_profile.iloc[::max(len(speed_profile) // 2500, 1)]
    specs.append(_metric_spec(
        "actividad_velocidad", "Actividades", "Velocidad durante la actividad", "profile", speed_profile,
        x=speed_x, y="Velocidad", unit="km/h", x_label="Distancia (km)" if speed_x == "Distancia" else "Tiempo (min)", y_label="Velocidad (km/h)",
        description="Usa la distancia cuando existe; si falta, utiliza el tiempo de actividad.", stream_error=activity_stream_error,
        representations={"Plotly": "Área de ritmo", "Altair / Vega-Lite": "Línea con selección de tramo", "Apache ECharts": "Línea con zoom"},
    ))

    power_profile = stream_tools.profile_frame(time_s, watts, "Tiempo", "Potencia") if time_s and watts else _empty(("Tiempo", "Potencia"))
    if not power_profile.empty:
        power_profile["Tiempo"] /= 60
        power_profile = power_profile.iloc[::max(len(power_profile) // 2500, 1)]
    specs.append(_metric_spec(
        "actividad_potencia_tiempo", "Actividades", "Potencia durante la actividad", "profile", power_profile,
        x="Tiempo", y="Potencia", unit="W", x_label="Tiempo (min)", y_label="Potencia (W)",
        description="Potencia segundo a segundo según las muestras disponibles.", stream_error=activity_stream_error,
    ))

    activity_curve = stream_tools.power_duration_curve(watts, times=time_s) if time_s and watts else _empty(("duration_s", "watts"))
    if not activity_curve.empty:
        activity_curve["duration_label"] = activity_curve["duration_s"].map(lambda s: f"{s}s" if s < 60 else (f"{s // 60} min" if s < 3600 else f"{s // 3600} h"))
    elif activity_detail is not None:
        activity_curve = stream_tools.power_curve_from_summary(pd.DataFrame([activity_detail]))
        if not activity_curve.empty:
            activity_curve["duration_label"] = activity_curve["duration_s"].map(lambda s: f"{s}s" if s < 60 else (f"{s // 60} min" if s < 3600 else f"{s // 3600} h"))
    specs.append(_metric_spec(
        "actividad_curva_potencia", "Actividades", "Curva de potencia de la actividad", "curve", activity_curve.rename(columns={"watts": "value"}),
        x="duration_s", y="value", unit="W", description="Mejor potencia media sostenida para duraciones habituales de la actividad.", stream_error=activity_stream_error,
        representations={"Plotly": "Curva logarítmica", "Altair / Vega-Lite": "Línea con puntos seleccionables", "Apache ECharts": "Línea logarítmica con zoom"},
    ))

    for zone_kind, title in (("hr", "Zonas FC de la actividad"), ("power", "Zonas de potencia de la actividad")):
        zone_data = an.activity_zone_minutes(activity_detail, zone_kind) if activity_detail is not None else _empty(("zone", "label", "minutes"))
        zone_data = zone_data.loc[zone_data.get("minutes", pd.Series(dtype=float)) > 0].copy() if not zone_data.empty else zone_data
        specs.append(_metric_spec(
            f"actividad_zonas_{zone_kind}", "Actividades", title, "zones", zone_data,
            x="label", y="minutes", unit="min", zone_kind=zone_kind,
            description="Minutos registrados en cada zona de esta actividad.",
            representations={"Plotly": "Barras por zona", "Altair / Vega-Lite": "Lollipop por zona", "Apache ECharts": "Barras por zona"},
        ))

    # Recuperación · Salud
    health = wellness if not wellness.empty else daily
    sleep = health.dropna(subset=["sleep_h"]).sort_values("date").copy() if not health.empty and "sleep_h" in health else _empty()
    if not sleep.empty:
        sleep["Media 7 días"] = _numeric(sleep, "sleep_h").rolling(7, min_periods=2).mean()
        sleep_long = sleep.melt(id_vars=["date"], value_vars=["sleep_h", "Media 7 días"], var_name="series", value_name="value")
        sleep_long["series"] = sleep_long["series"].replace({"sleep_h": "Horas de sueño"})
    else:
        sleep_long = _empty(("date", "series", "value"))
    specs.append(_metric_spec(
        "salud_sueno", "Salud", "Sueño", "multi_line", sleep_long,
        x="date", y="value", unit="h", series="series",
        description="Horas de sueño y media móvil de siete registros, con el mismo calendario.",
        representations={"Plotly": "Columnas más línea", "Altair / Vega-Lite": "Área más tendencia", "Apache ECharts": "Columnas más línea"},
    ))

    vitals_rows = []
    for field, label, unit in (("resting_hr", "FC en reposo", "ppm"), ("hrv", "HRV", "ms")):
        candidates = ("hrv", "hrv_last_night", "hrv_weekly_avg") if field == "hrv" else (field,)
        column = next((candidate for candidate in candidates if candidate in health and _numeric(health, candidate).notna().any()), None)
        if column is None:
            continue
        values = health[["date", column]].copy()
        values["value"] = _numeric(values, column)
        values = values.dropna(subset=["value"]).sort_values("date")
        if values.empty:
            continue
        mean_value = float(values["value"].mean())
        for row in values.itertuples():
            vitals_rows.append({"date": row.date, "metric": label, "value": row.value, "mean": mean_value, "lower": mean_value - 5, "upper": mean_value + 5, "unit": unit})
    vitals = pd.DataFrame(vitals_rows, columns=["date", "metric", "value", "mean", "lower", "upper", "unit"])
    specs.append(_metric_spec(
        "salud_fc_hrv", "Salud", "FC en reposo y HRV", "health_vitals", vitals,
        x="date", y="value", unit="ppm / ms",
        description="Dos paneles temporales. Cada uno conserva su media del periodo y la franja sombreada de ±5.",
        representations={"Plotly": "Small multiples con banda ±5", "Altair / Vega-Lite": "Facetas con área y media", "Apache ECharts": "Paneles coordinados con banda ±5"},
    ))

    battery = daily.copy() if not daily.empty else _empty()
    battery_fields = [column for column in ("body_battery_min", "body_battery_max") if column in battery]
    battery = battery.dropna(subset=battery_fields) if battery_fields else _empty()
    if not battery.empty:
        battery_long = battery.melt(id_vars=["date"], value_vars=[c for c in ("body_battery_min", "body_battery_max") if c in battery], var_name="series", value_name="value")
        battery_long["series"] = battery_long["series"].map({"body_battery_min": "Mínimo", "body_battery_max": "Máximo"})
    else:
        battery_long = _empty(("date", "series", "value"))
    specs.append(_metric_spec(
        "salud_body_battery", "Salud", "Body Battery", "multi_line", battery_long,
        x="date", y="value", unit="puntos", series="series",
        description="Mínimo y máximo diarios de Garmin.",
        representations={"Plotly": "Dos líneas", "Altair / Vega-Lite": "Banda entre mínimo y máximo", "Apache ECharts": "Área entre extremos"},
    ))

    # Planificación · objetivos de temporada y cumplimiento.
    season_start = date(end_date.year if end_date.month >= 8 else end_date.year - 1, 8, 1)
    season = _date_filter(full_activities, season_start, end_date, field="date")
    season = _focus_filter(season, focus_mask, focus)
    if not season.empty and "is_cycling" in season:
        season = season.loc[season["is_cycling"].fillna(False)]
    rides = season.copy()
    rides["_distance"] = _numeric(rides, "distance_km") if not rides.empty else pd.Series(dtype=float)
    rides = rides.dropna(subset=["_distance"]) if not rides.empty else rides
    best = rides.loc[rides["_distance"].idxmax()] if not rides.empty else None
    goals = []
    if best is not None:
        for metric, current_field, unit, targets in (
            ("Distancia", "distance_km", "km", (("Bloque", 100.0), ("Lagos", 111.0))),
            ("Desnivel", "elevation_gain_m", "m+", (("Bloque", 1500.0), ("Lagos", 2400.0))),
        ):
            current_value = pd.to_numeric(pd.Series([best.get(current_field)]), errors="coerce").iloc[0]
            if pd.isna(current_value):
                continue
            for target_name, target in targets:
                goals.append({"goal": f"{target_name} · {metric}", "metric": metric, "current": float(current_value), "target": target, "progress": float(current_value) / target * 100, "unit": unit})
    goal_frame = pd.DataFrame(goals, columns=["goal", "metric", "current", "target", "progress", "unit"])
    for metric, title, key in (("Distancia", "Progreso hacia el objetivo · distancia", "plan_objetivo_distancia"), ("Desnivel", "Progreso hacia el objetivo · desnivel", "plan_objetivo_desnivel")):
        goal_subset = goal_frame.loc[goal_frame.get("metric", pd.Series(dtype=str)) == metric].copy() if not goal_frame.empty else _empty(("goal", "current", "target", "progress", "unit"))
        specs.append(_metric_spec(
            key, "Planificación", title, "goal", goal_subset,
            x="goal", y="progress", unit="km" if metric == "Distancia" else "m+",
            description=f"Mejor salida de la temporada desde {season_start:%d/%m/%Y}, comparada con el bloque y Lagos.",
            representations={"Plotly": "Barras horizontales de avance", "Altair / Vega-Lite": "Bullet chart con marcas de objetivo", "Apache ECharts": "Barras de progreso con regla al 100 %"},
        ))

    plan_items = _safe_plan(data.get("plan_path"))
    plan_activities = data.get("plan_activities", full_activities)
    weekly_rows: dict[pd.Timestamp, dict[str, int]] = {}
    if not plan_activities.empty and "start" in plan_activities:
        activity_dates = pd.to_datetime(plan_activities["start"], errors="coerce")
        valid_ids = {str(value): pd.Timestamp(day).date() for value, day in zip(plan_activities.get("activity_id", []), activity_dates) if pd.notna(day)}
    else:
        valid_ids = {}
        activity_dates = pd.Series(dtype="datetime64[ns]")
    all_days = list(valid_ids.values())
    for item in plan_items:
        planned_day = pd.to_datetime(item.get("fecha"), errors="coerce")
        if pd.isna(planned_day):
            continue
        monday = planned_day.to_period("W-SUN").start_time
        row = weekly_rows.setdefault(monday, {"planned": 0, "completed": 0})
        row["planned"] += 1
        linked_id = str(item.get("activity_link_id", "")).strip()
        actual_day = valid_ids.get(linked_id) if linked_id else None
        if actual_day is None and all_days:
            candidate_days = [day for day in all_days if abs((day - planned_day.date()).days) <= 1]
            actual_day = min(candidate_days, key=lambda day: abs((day - planned_day.date()).days)) if candidate_days else None
        if actual_day is not None:
            row["completed"] += 1
    weekly_plan = pd.DataFrame([{"week": week, **counts, "completion": counts["completed"] / counts["planned"] * 100 if counts["planned"] else 0} for week, counts in sorted(weekly_rows.items())])
    specs.append(_metric_spec(
        "plan_seguimiento_semanal", "Planificación", "Seguimiento de planificación por semana", "completion", weekly_plan,
        x="week", y="completion", unit="%", description="Sesiones realizadas frente a las planificadas por semana.",
        representations={"Plotly": "Barras al 25/50/75/100 %", "Altair / Vega-Lite": "Puntos con línea de objetivo", "Apache ECharts": "Barras de progreso con marcas fijas"},
    ))
    return specs


def _series_color(name: Any, theme: dict[str, Any], index: int = 0) -> str:
    key = str(name).casefold()
    semantic = {
        "ctl": 2, "atl": 3, "tsb": 4, "potencia media": 0,
        "potencia normalizada": 1, "máximo": 4, "mínimo": 0,
        "horas de sueño": 6, "media 7 días": 0, "media": 0,
        "fc en reposo": 5, "hrv": 4,
        "rodillo": 4, "exterior": 0, "bloque": 2, "lagos": 4,
        "carga semanal alta": 3, "carga habitual": 0,
        "actividad elegida": 1, "otras salidas": 6,
    }
    for token, color_index in semantic.items():
        if token in key:
            return theme["colors"][color_index]
    return theme["colors"][index % len(theme["colors"])]


def _plotly_layout(fig: go.Figure, theme: dict[str, Any], font: str, height: int = 420) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=18, r=18, t=42, b=28),
        paper_bgcolor=theme["background"], plot_bgcolor=theme["panel"],
        font=dict(family=font, color=theme["text"], size=12),
        hovermode="x unified", colorway=theme["colors"],
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(gridcolor=theme["grid"], linecolor=theme["grid"], tickfont_color=theme["muted"], zeroline=False)
    fig.update_yaxes(gridcolor=theme["grid"], linecolor=theme["grid"], tickfont_color=theme["muted"], zeroline=False)
    return fig


def _plotly_comparison_figure(spec: dict[str, Any], theme: dict[str, Any], font: str) -> go.Figure:
    frame: pd.DataFrame = spec["data"]
    kind, x, y = spec["kind"], spec["x"], spec["y"]
    mode = spec.get("display_type", "Barras")
    fig = go.Figure()

    if mode in PIE_REPRESENTATIONS:
        pie = _pie_data(spec)
        hole = .58 if mode != "Tarta" else 0
        fig.add_trace(go.Pie(
            labels=pie["category"], values=pie["value"], hole=hole,
            sort=False, textinfo="label+percent", textposition="inside",
            marker=dict(colors=[_series_color(value, theme, i) for i, value in enumerate(pie["category"])]),
            hovertemplate="%{label}<br>%{value:.1f} " + spec["unit"] + " · %{percent}<extra></extra>",
        ))
        fig.update_layout(uniformtext_minsize=11, uniformtext_mode="hide")
    elif kind == "stacked_bar":
        series_field = spec["series"]
        for index, name in enumerate(frame[series_field].dropna().unique()):
            part = frame.loc[frame[series_field] == name]
            if mode in {"Área apilada", "Líneas por tipo"}:
                fig.add_trace(go.Scatter(
                    x=part[x], y=part[y], name=str(name), mode="lines",
                    line=dict(color=_series_color(name, theme, index), width=2.2),
                    stackgroup="volumen" if mode == "Área apilada" else None,
                    fill="tozeroy" if mode == "Área apilada" else None,
                ))
            else:
                fig.add_trace(go.Bar(x=part[x], y=part[y], name=str(name), marker_color=_series_color(name, theme, index)))
        fig.update_layout(barmode="stack" if mode == "Columnas apiladas" else "group")
    elif mode == "Lollipop":
        horizontal = kind == "zones" or spec.get("orientation") == "horizontal"
        categories = frame[x].astype(str).tolist()
        values = _numeric(frame, y).fillna(0).tolist()
        stem_x, stem_y = [], []
        for category, value in zip(categories, values):
            if horizontal:
                stem_x.extend([0, value, None]); stem_y.extend([category, category, None])
            else:
                stem_x.extend([category, category, None]); stem_y.extend([0, value, None])
        fig.add_trace(go.Scatter(x=stem_x, y=stem_y, mode="lines", line=dict(color=theme["grid"], width=2.4), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(
            x=values if horizontal else categories, y=categories if horizontal else values,
            mode="markers", marker=dict(size=11, color=[_series_color(value, theme, i) for i, value in enumerate(categories)]),
            name=spec["title"], text=categories, customdata=values,
            hovertemplate="%{text}<br>%{customdata:.1f} " + spec["unit"] + "<extra></extra>",
        ))
        if horizontal:
            fig.update_yaxes(autorange="reversed")
    elif kind == "completion" and mode == "Línea":
        fig.add_trace(go.Scatter(x=frame[x], y=frame[y], mode="lines+markers", name="Cumplimiento", line=dict(color=theme["colors"][0], width=2.5), marker=dict(size=8)))
    elif kind == "completion":
        fig.add_trace(go.Bar(x=frame[x], y=frame[y], marker_color=theme["colors"][0], name="Cumplimiento"))
    elif kind == "forma_carga_semanal" and mode == "Línea":
        fig.add_trace(go.Scatter(x=frame[x], y=frame[y], mode="lines+markers", name=spec["title"], line=dict(color=theme["colors"][0], width=2.4)))
    elif kind == "ciclismo_potencia_semanal" and mode in {"Líneas", "Áreas"}:
        for index, name in enumerate(frame[spec["series"]].dropna().unique()):
            part = frame.loc[frame[spec["series"]] == name]
            fig.add_trace(go.Scatter(
                x=part[x], y=part[y], name=str(name), mode="lines+markers",
                line=dict(color=_series_color(name, theme, index), width=2.5), marker=dict(size=5),
                fill="tozeroy" if mode == "Áreas" else None,
            ))
    elif kind == "ciclismo_potencia_semanal" or (kind == "forma_carga_semanal" and mode == "Columnas"):
        series_field = spec.get("series")
        if series_field and series_field in frame:
            for index, name in enumerate(frame[series_field].dropna().unique()):
                part = frame.loc[frame[series_field] == name]
                fig.add_trace(go.Bar(x=part[x], y=part[y], name=str(name), marker_color=_series_color(name, theme, index)))
            fig.update_layout(barmode="group")
        else:
            fig.add_trace(go.Bar(x=frame[x], y=frame[y], name=spec["title"], marker_color=theme["colors"][0]))
    else:
        horizontal = kind == "zones" or spec.get("orientation") == "horizontal"
        fig.add_trace(go.Bar(
            x=frame[y] if horizontal else frame[x], y=frame[x] if horizontal else frame[y],
            orientation="h" if horizontal else "v",
            marker_color=[_series_color(value, theme, i) for i, value in enumerate(frame[x])] if kind == "zones" else theme["colors"][0],
            name=spec["title"],
        ))
        if horizontal:
            fig.update_yaxes(autorange="reversed")

    if kind == "completion":
        for tick in (25, 50, 75, 100):
            fig.add_hline(y=tick, line_dash="dot" if tick != 100 else "dash", line_color=theme["colors"][2] if tick == 100 else theme["grid"], annotation_text=f"{tick}%" if tick == 100 else None)
        fig.update_yaxes(range=[0, 100], tickmode="array", tickvals=[25, 50, 75, 100], ticktext=["25%", "50%", "75%", "100%"])
    if kind == "forma_carga_semanal":
        fig.update_xaxes(title_text="Semana")
    if kind in {"bar", "zones", "stacked_bar"}:
        fig.update_xaxes(title_text=spec.get("unit", ""))
    if x in frame and pd.api.types.is_datetime64_any_dtype(frame[x]):
        fig.update_xaxes(tickformat="%d %b %y")
    return _plotly_layout(fig, theme, font, 390)


def _plotly_figure(spec: dict[str, Any], theme: dict[str, Any], font: str) -> go.Figure:
    frame = spec["data"]
    kind, x, y = spec["kind"], spec["x"], spec["y"]
    if spec.get("display_type") and kind in {"bar", "stacked_bar", "zones", "completion", "multi_line"}:
        return _plotly_comparison_figure(spec, theme, font)
    fig = go.Figure()
    if kind == "form":
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.12, row_heights=[.66, .34], subplot_titles=("CTL y ATL · carga", "TSB · forma"))
        for field, label, color_index in (("ctl", "CTL", 2), ("atl", "ATL", 3)):
            if field in frame:
                fig.add_trace(go.Scatter(x=frame["date"], y=frame[field], name=label, mode="lines", line=dict(color=theme["colors"][color_index], width=2.6)), row=1, col=1)
        if "tsb" in frame:
            fig.add_trace(go.Scatter(x=frame["date"], y=frame["tsb"], name="TSB", mode="lines", line=dict(color=theme["colors"][4], width=2.2), fill="tozeroy", fillcolor="rgba(167,139,250,.14)"), row=2, col=1)
            fig.add_hline(y=0, line_dash="dash", line_color=theme["colors"][0], row=2, col=1)
        fig.update_yaxes(title_text="carga", row=1, col=1)
        fig.update_yaxes(title_text="TSB", row=2, col=1)
    elif kind == "health_vitals":
        metrics = frame["metric"].drop_duplicates().tolist() if "metric" in frame else []
        fig = make_subplots(rows=max(len(metrics), 1), cols=1, shared_xaxes=True, vertical_spacing=.12, subplot_titles=metrics)
        metric_units = frame.drop_duplicates("metric").set_index("metric")["unit"].to_dict() if metrics else {}
        for row_index, metric in enumerate(metrics, start=1):
            part = frame.loc[frame["metric"] == metric]
            color = _series_color(metric, theme)
            fig.add_trace(go.Scatter(x=part[x], y=part["upper"], mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False), row=row_index, col=1)
            fig.add_trace(go.Scatter(x=part[x], y=part["lower"], mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(56,189,248,.24)", hoverinfo="skip", showlegend=False), row=row_index, col=1)
            fig.add_trace(go.Scatter(x=part[x], y=part["mean"], mode="lines", line=dict(color=theme["colors"][1], width=1.8, dash="dash"), name=f"Media · {metric}", showlegend=False), row=row_index, col=1)
            fig.add_trace(go.Scatter(x=part[x], y=part[y], mode="lines+markers", marker=dict(size=5), line=dict(color=color, width=2.1), name=metric, showlegend=False), row=row_index, col=1)
            fig.update_yaxes(title_text=metric_units.get(metric, ""), row=row_index, col=1)
        if metrics:
            fig.update_xaxes(tickformat="%d %b %y", row=len(metrics), col=1)
    elif kind == "band":
        if {"lower", "upper"}.issubset(frame.columns):
            fig.add_trace(go.Scatter(x=frame[x], y=frame["upper"], mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False))
            fig.add_trace(go.Scatter(x=frame[x], y=frame["lower"], mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(56,189,248,.20)", hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=frame[x], y=frame[y], name=spec["title"], mode="lines+markers", line=dict(color=spec.get("color", theme["colors"][0]), width=2), marker=dict(size=6)))
        if "mean" in frame and pd.notna(frame["mean"]).any():
            mean = float(frame["mean"].dropna().iloc[0])
            fig.add_hline(y=mean, line_dash="dash", line_color=theme["colors"][1], annotation_text=f"Media {mean:.1f}")
    elif kind in {"profile", "line"}:
        fig.add_trace(go.Scatter(x=frame[x], y=frame[y], mode="lines", name=spec["title"], line=dict(color=theme["colors"][0], width=2.1), fill="tozeroy", fillcolor="rgba(56,189,248,.13)" if kind == "profile" or spec["key"] == "forma_ramp_rate" else None))
    elif kind in {"multi_line", "curve"}:
        if kind == "curve":
            for index, series_name in enumerate(frame.get("series", pd.Series(dtype=str)).dropna().unique()):
                part = frame.loc[frame["series"] == series_name]
                fig.add_trace(go.Scatter(x=part[x], y=part[y], name=series_name, mode="lines+markers", line=dict(color=_series_color(series_name, theme, index), width=2.5), marker=dict(size=7)))
            if "duration_s" in frame and "duration_label" in frame:
                durations = sorted(frame["duration_s"].dropna().unique().tolist())
                labels = [frame.loc[frame["duration_s"] == d, "duration_label"].iloc[0] for d in durations]
                fig.update_xaxes(type="log", tickvals=durations, ticktext=labels)
        elif spec["key"] == "salud_body_battery" and {"series", "value"}.issubset(frame.columns):
            battery_wide = frame.pivot_table(index=x, columns="series", values=y, aggfunc="mean").sort_index()
            maximum = battery_wide.get("Máximo", pd.Series(dtype=float))
            minimum = battery_wide.get("Mínimo", pd.Series(dtype=float))
            fig.add_trace(go.Scatter(x=battery_wide.index, y=maximum, name="Máximo", mode="lines", line=dict(color=_series_color("Máximo", theme), width=1.5)))
            fig.add_trace(go.Scatter(x=battery_wide.index, y=minimum, name="Mínimo", mode="lines", line=dict(color=_series_color("Mínimo", theme), width=1.5), fill="tonexty", fillcolor="rgba(56,189,248,.18)"))
        else:
            for index, series_name in enumerate(frame.get(spec.get("series", "series"), pd.Series(dtype=str)).dropna().unique()):
                part = frame.loc[frame[spec.get("series", "series")] == series_name]
                is_bar = series_name == "Horas de sueño"
                if is_bar:
                    fig.add_trace(go.Bar(x=part[x], y=part[y], name=series_name, marker_color=_series_color(series_name, theme, index), opacity=.62))
                else:
                    fig.add_trace(go.Scatter(x=part[x], y=part[y], name=series_name, mode="lines+markers", line=dict(color=_series_color(series_name, theme, index), width=2.6), marker=dict(size=5)))
    elif kind == "scatter":
        color_field, size_field = spec.get("color"), spec.get("size")
        for index, category in enumerate(frame[color_field].dropna().unique() if color_field in frame else [None]):
            part = frame.loc[frame[color_field] == category] if category is not None else frame
            fig.add_trace(go.Scatter(x=part[x], y=part[y], mode="markers", name=str(category or "Actividad"), marker=dict(size=np.clip(_numeric(part, size_field).fillna(45) / 8, 7, 20) if size_field in part else 10, color=_series_color(category, theme, index), opacity=.82), text=part.get("activity_name"), hovertemplate=f"{spec.get('x_label', x)}: %{{x}}<br>{spec.get('y_label', y)}<br>%{{y}}<br>%{{text}}<extra></extra>"))
    elif kind == "activity_summary":
        color_field = spec.get("color", "seleccion")
        for index, category in enumerate(frame[color_field].dropna().unique()):
            part = frame.loc[frame[color_field] == category]
            emphasized = category == "Actividad elegida"
            fig.add_trace(go.Scatter(
                x=part[x], y=part[y], mode="markers", name=str(category),
                marker=dict(size=12 if emphasized else 7, color=_series_color(category, theme, index), opacity=.95 if emphasized else .68, line=dict(width=1, color=theme["background"])),
                text=part.get("activity_name"), hovertemplate=f"%{{x|%d/%m/%Y}}<br>{spec.get('y_label', y)}: %{{y:.1f}} {spec['unit']}<br>%{{text}}<extra></extra>",
            ))
    elif kind == "goal":
        if not frame.empty:
            max_value = max(125, float(frame["progress"].max()) + 20)
            for index, row in frame.reset_index(drop=True).iterrows():
                fig.add_trace(go.Bar(x=[row["progress"]], y=[row["goal"]], orientation="h", name=row["goal"], marker_color=_series_color(row["goal"], theme, index), customdata=[[row["current"], row["target"], row["unit"]]], hovertemplate="%{y}<br>%{customdata[0]:.1f} / %{customdata[1]:.0f} %{customdata[2]} · %{x:.0f}%<extra></extra>"))
            fig.add_vline(x=100, line_dash="dash", line_color=theme["text"], annotation_text="Objetivo")
            fig.update_xaxes(range=[0, max_value], title="Progreso del objetivo (%)")
            fig.update_yaxes(autorange="reversed")
    elif kind == "completion":
        if not frame.empty:
            fig.add_trace(go.Bar(x=frame[x], y=frame[y], marker_color=theme["colors"][0], name="Cumplimiento"))
            for tick in (25, 50, 75, 100):
                fig.add_hline(y=tick, line_dash="dot" if tick != 100 else "dash", line_color=theme["colors"][2] if tick == 100 else theme["grid"], annotation_text=f"{tick}%" if tick == 100 else None)
            fig.update_yaxes(range=[0, 100], tickmode="array", tickvals=[25, 50, 75, 100], ticktext=["25%", "50%", "75%", "100%"])
    elif kind in {"bar", "stacked_bar", "zones"}:
        series_field = spec.get("series")
        if kind == "zones" and not frame.empty:
            if st.session_state.get("visual_lab_renderer", "Plotly") == "Altair / Vega-Lite":
                fig.add_trace(go.Scatter(x=frame[y], y=frame[x], mode="markers", marker=dict(size=13, color=theme["colors"][0]), name="Minutos"))
                stem_x, stem_y = [], []
                for row in frame.itertuples():
                    stem_x.extend([0, getattr(row, y), None])
                    stem_y.extend([getattr(row, x), getattr(row, x), None])
                fig.add_trace(go.Scatter(x=stem_x, y=stem_y, mode="lines", line=dict(color=theme["grid"], width=3), hoverinfo="skip", showlegend=False))
                fig.update_yaxes(autorange="reversed")
            else:
                colors = an.HR_ZONE_COLORS if spec.get("zone_kind") == "hr" else an.POWER_ZONE_COLORS
                fig.add_trace(go.Bar(x=frame[y], y=frame[x], orientation="h", marker_color=[theme["colors"][i % len(theme["colors"])] for i, _ in enumerate(frame[x])], text=frame[y].round(0), textposition="outside", customdata=frame[[c for c in ("label", "range") if c in frame]], hovertemplate="%{y}<br>%{x:.1f} min<extra></extra>"))
                fig.update_yaxes(autorange="reversed")
        elif kind == "bar" and st.session_state.get("visual_lab_renderer", "Plotly") == "Altair / Vega-Lite" and spec.get("representations", {}).get("Altair / Vega-Lite", "").startswith("Lollipop"):
            sorted_frame = frame.sort_values(y)
            fig.add_trace(go.Scatter(x=sorted_frame[y], y=sorted_frame[x], mode="markers", marker=dict(size=12, color=theme["colors"][0]), name="Valor"))
            stem_x, stem_y = [], []
            for row in sorted_frame.itertuples():
                value = getattr(row, y)
                category = getattr(row, x)
                stem_x.extend([0, value, None])
                stem_y.extend([category, category, None])
            fig.add_trace(go.Scatter(x=stem_x, y=stem_y, mode="lines", line=dict(color=theme["grid"], width=3), hoverinfo="skip", showlegend=False))
            fig.update_yaxes(autorange="reversed")
        elif kind == "bar" and spec.get("orientation") == "horizontal":
            fig.add_trace(go.Bar(x=frame[y], y=frame[x], orientation="h", marker_color=theme["colors"][0], name=spec["title"]))
            fig.update_yaxes(autorange="reversed")
        elif series_field and series_field in frame:
            for index, group in enumerate(frame[series_field].dropna().unique()):
                part = frame.loc[frame[series_field] == group]
                fig.add_trace(go.Bar(x=part[x], y=part[y], name=str(group), marker_color=_series_color(group, theme, index)))
            fig.update_layout(barmode="stack" if kind == "stacked_bar" or spec.get("representations", {}).get(st.session_state.get("visual_lab_renderer", "Plotly")) == "Columnas apiladas" else "group")
        else:
            fig.add_trace(go.Bar(x=frame[x] if x in frame else [], y=frame[y] if y in frame else [], marker_color=theme["colors"][0], name=spec["title"]))
            if kind in {"zones"} or (x in frame and frame[x].dtype == object and len(frame) > 5):
                fig.update_layout(barmode="group")
    if spec.get("x_label"):
        fig.update_xaxes(title_text=spec["x_label"])
    elif spec.get("x_scale") == "log":
        fig.update_xaxes(title_text=spec.get("x_label", "Duración"))
    if spec.get("y_label"):
        fig.update_yaxes(title_text=spec["y_label"])
    elif spec.get("unit") and kind not in {"goal", "completion"}:
        fig.update_yaxes(title_text=spec["unit"])
    if kind == "completion":
        fig.update_xaxes(tickformat="%d %b")
    elif x in frame and pd.api.types.is_datetime64_any_dtype(frame[x]):
        fig.update_xaxes(tickformat="%d %b %y")
    if kind in {"bar", "stacked_bar"} and x in frame and frame[x].dtype == object and spec.get("orientation") != "horizontal":
        fig.update_yaxes(title_text=spec["unit"], autorange="reversed")
    return _plotly_layout(fig, theme, font, 440 if kind == "form" else 390)


def _altair_comparison_chart(spec: dict[str, Any], theme: dict[str, Any], font: str) -> alt.TopLevelMixin:
    frame: pd.DataFrame = spec["data"]
    kind, x, y = spec["kind"], spec["x"], spec["y"]
    mode = spec.get("display_type", "Barras")
    axis_color = theme["muted"]
    common = alt.Chart(frame)
    config = lambda chart: chart.configure(background=theme["background"]).configure_view(stroke=theme["grid"]).configure_axis(labelFont=font, titleFont=font, labelColor=axis_color, titleColor=axis_color, gridColor=theme["grid"])
    x_temporal = x in frame and pd.api.types.is_datetime64_any_dtype(frame[x])
    tooltip = [alt.Tooltip(f"{field}:Q" if field in frame and pd.api.types.is_numeric_dtype(frame[field]) else f"{field}:N") for field in (x, y, spec.get("series"), "label") if field and field in frame]

    if mode in PIE_REPRESENTATIONS:
        pie = _pie_data(spec)
        chart = alt.Chart(pie).mark_arc(innerRadius=72 if mode != "Tarta" else 0, outerRadius=145).encode(
            theta=alt.Theta("value:Q", aggregate="sum", title=spec["unit"]),
            color=alt.Color("category:N", scale=alt.Scale(range=theme["colors"]), legend=alt.Legend(title=None)),
            tooltip=[alt.Tooltip("category:N", title="Categoría"), alt.Tooltip("value:Q", title=spec["unit"], format=".1f")],
        ).properties(height=330)
        return config(chart)

    if mode == "Lollipop":
        horizontal = kind == "zones" or spec.get("orientation") == "horizontal"
        color = alt.Color(f"{x}:N", scale=alt.Scale(range=theme["colors"]), legend=None) if kind == "zones" else alt.value(theme["colors"][0])
        if horizontal:
            category = alt.Y(f"{x}:N", sort="-x", axis=alt.Axis(labelColor=axis_color))
            stem = common.mark_rule(color=theme["grid"], strokeWidth=3).encode(x=alt.X(f"{y}:Q", title=spec["unit"]), x2=alt.value(0), y=category, tooltip=tooltip)
            point = common.mark_point(filled=True, size=150).encode(x=alt.X(f"{y}:Q"), y=category, color=color, tooltip=tooltip)
        else:
            time_type = "T" if x_temporal else "N"
            stem = common.mark_rule(color=theme["grid"], strokeWidth=2.5).encode(x=alt.X(f"{x}:{time_type}", axis=alt.Axis(labelColor=axis_color)), y=alt.Y(f"{y}:Q", title=spec["unit"]), y2=alt.value(0), tooltip=tooltip)
            point = common.mark_point(filled=True, size=130).encode(x=alt.X(f"{x}:{time_type}"), y=alt.Y(f"{y}:Q"), color=color, tooltip=tooltip)
        return config((stem + point).properties(height=320))

    if kind == "stacked_bar":
        color = alt.Color(f"{spec['series']}:N", scale=alt.Scale(range=theme["colors"]), legend=alt.Legend(title=None))
        x_enc = alt.X(f"{x}:T", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"]))
        y_enc = alt.Y(f"sum({y}):Q", title=spec["unit"], axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"]))
        if mode == "Área apilada":
            chart = common.mark_area(opacity=.82).encode(x=x_enc, y=y_enc, color=color, tooltip=tooltip)
        elif mode == "Líneas por tipo":
            chart = common.mark_line(point=True, strokeWidth=2.5).encode(x=x_enc, y=alt.Y(f"{y}:Q", title=spec["unit"]), color=color, tooltip=tooltip)
        else:
            chart = common.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(x=x_enc, y=alt.Y(f"{y}:Q", stack="zero", title=spec["unit"]), color=color, tooltip=tooltip)
        return config(chart.properties(height=320))

    if kind == "completion" and mode == "Línea":
        chart = common.mark_line(point=alt.OverlayMarkDef(filled=True, size=100), strokeWidth=2.5).encode(
            x=alt.X(f"{x}:T", axis=alt.Axis(labelColor=axis_color)),
            y=alt.Y(f"{y}:Q", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(title="Cumplimiento (%)", values=[25, 50, 75, 100], labelExpr="datum.value + '%'")),
            color=alt.value(theme["colors"][0]), tooltip=tooltip,
        )
        rules = alt.Chart(pd.DataFrame({"nivel": [25, 50, 75, 100]})).mark_rule(color=theme["grid"], strokeDash=[4, 4]).encode(y="nivel:Q")
        return config((chart + rules).properties(height=300))

    if kind == "completion" and mode == "Barras":
        chart = common.mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(x=alt.X(f"{x}:T"), y=alt.Y(f"{y}:Q", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(title="Cumplimiento (%)", values=[25, 50, 75, 100], labelExpr="datum.value + '%'")), color=alt.value(theme["colors"][0]), tooltip=tooltip)
        rules = alt.Chart(pd.DataFrame({"nivel": [25, 50, 75, 100]})).mark_rule(color=theme["grid"], strokeDash=[4, 4]).encode(y="nivel:Q")
        return config((chart + rules).properties(height=300))

    if kind == "ciclismo_potencia_semanal" and mode in {"Líneas", "Áreas"}:
        mark = common.mark_area(opacity=.15, line=True) if mode == "Áreas" else common.mark_line(point=True, strokeWidth=2.5)
        chart = mark.encode(x=alt.X(f"{x}:T"), y=alt.Y(f"{y}:Q", scale=alt.Scale(zero=False), title=spec["unit"]), color=alt.Color(f"{spec['series']}:N", scale=alt.Scale(range=theme["colors"])), tooltip=tooltip)
        return config(chart.properties(height=320))

    if kind == "forma_carga_semanal" and mode == "Línea":
        chart = common.mark_line(point=True, strokeWidth=2.5).encode(x=alt.X(f"{x}:T"), y=alt.Y(f"{y}:Q", title=spec["unit"]), color=alt.Color(f"{spec['series']}:N", scale=alt.Scale(range=theme["colors"])), tooltip=tooltip)
        return config(chart.properties(height=320))

    horizontal = kind == "zones" or spec.get("orientation") == "horizontal"
    if horizontal:
        chart = common.mark_bar(cornerRadiusEnd=5).encode(
            x=alt.X(f"{y}:Q", title=spec["unit"]),
            y=alt.Y(f"{x}:N", sort="-x", axis=alt.Axis(labelColor=axis_color)),
            color=alt.Color(f"{x}:N", scale=alt.Scale(range=theme["colors"]), legend=None) if kind == "zones" else alt.value(theme["colors"][0]),
            tooltip=tooltip,
        )
    elif kind == "ciclismo_potencia_semanal":
        chart = common.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X(f"{x}:T", axis=alt.Axis(labelColor=axis_color)),
            xOffset=alt.XOffset(f"{spec['series']}:N"),
            y=alt.Y(f"{y}:Q", scale=alt.Scale(zero=False), title=spec["unit"]),
            color=alt.Color(f"{spec['series']}:N", scale=alt.Scale(range=theme["colors"])), tooltip=tooltip,
        )
    elif kind == "forma_carga_semanal":
        chart = common.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(x=alt.X(f"{x}:T"), y=alt.Y(f"{y}:Q", title=spec["unit"]), color=alt.Color(f"{spec['series']}:N", scale=alt.Scale(range=theme["colors"])), tooltip=tooltip)
    else:
        chart = common.mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X(f"{x}:{'T' if x_temporal else 'N'}", axis=alt.Axis(labelColor=axis_color)),
            y=alt.Y(f"{y}:Q", title=spec["unit"]), color=alt.value(theme["colors"][0]), tooltip=tooltip,
        )
    return config(chart.properties(height=320))


def _altair_chart(spec: dict[str, Any], theme: dict[str, Any], font: str, renderer: str) -> alt.TopLevelMixin:
    frame: pd.DataFrame = spec["data"]
    kind, x, y = spec["kind"], spec["x"], spec["y"]
    if spec.get("display_type") and kind in {"bar", "stacked_bar", "zones", "completion", "multi_line"}:
        return _altair_comparison_chart(spec, theme, font)
    base = alt.Chart(frame).properties(height=280)
    color_scale = alt.Scale(range=theme["colors"])
    tooltips = [field for field in (x, y, spec.get("series"), spec.get("color"), "goal", "current", "target", "unit", "activity_name", "label") if field and field in frame]
    axis_color = theme["muted"]

    def xy(enc_x: str, enc_y: str) -> alt.Chart:
        return base.encode(
            x=alt.X(enc_x, title=spec.get("x_label", spec.get("x_title", enc_x)), axis=alt.Axis(labelColor=axis_color, titleColor=axis_color, gridColor=theme["grid"])),
            y=alt.Y(enc_y, title=spec.get("y_label", spec.get("unit", enc_y)), axis=alt.Axis(labelColor=axis_color, titleColor=axis_color, gridColor=theme["grid"])),
            tooltip=tooltips,
        )

    if kind == "form":
        top = alt.Chart(frame).transform_fold([f for f in ("ctl", "atl") if f in frame], as_=["series", "value"]).mark_line(strokeWidth=2.6).encode(
            x=alt.X("date:T", axis=alt.Axis(title=None, labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y("value:Q", title="Carga", axis=alt.Axis(labelColor=axis_color, titleColor=axis_color, gridColor=theme["grid"])), color=alt.Color("series:N", scale=color_scale), tooltip=["date:T", "series:N", "value:Q"]
        ).properties(height=240, title="CTL y ATL · carga")
        bottom = alt.Chart(frame).mark_area(line=True, opacity=.2).encode(x=alt.X("date:T", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y("tsb:Q", title="TSB", axis=alt.Axis(labelColor=axis_color, titleColor=axis_color, gridColor=theme["grid"])), color=alt.value(theme["colors"][4]), tooltip=["date:T", "tsb:Q"])
        zero = alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(color=theme["colors"][0], strokeDash=[5, 4]).encode(y="zero:Q")
        return alt.vconcat(top, bottom + zero, spacing=10).resolve_scale(x="shared", y="independent").configure(background=theme["background"]).configure_view(stroke=theme["grid"]).configure_axis(labelFont=font, titleFont=font, domainColor=theme["grid"])
    if kind == "health_vitals":
        vital_colors = alt.Scale(domain=["FC en reposo", "HRV"], range=[_series_color("FC en reposo", theme), _series_color("HRV", theme)])
        color_enc = alt.Color("metric:N", scale=vital_colors, legend=None)
        band = base.mark_area(opacity=.24).encode(x=alt.X("date:T", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y("lower:Q", scale=alt.Scale(zero=False), axis=alt.Axis(labelColor=axis_color, titleColor=axis_color, gridColor=theme["grid"])), y2="upper:Q", color=color_enc)
        line = base.mark_line(point=True, strokeWidth=2.1).encode(x="date:T", y=alt.Y("value:Q", scale=alt.Scale(zero=False)), color=color_enc, tooltip=["date:T", "metric:N", "value:Q", "mean:Q", "lower:Q", "upper:Q"])
        mean_line = base.mark_line(strokeDash=[6, 4], strokeWidth=1.7).encode(x="date:T", y=alt.Y("mean:Q", scale=alt.Scale(zero=False)), color=alt.value(theme["colors"][1]))
        return (band + line + mean_line).facet(row=alt.Row("metric:N", sort=["FC en reposo", "HRV"], title=None)).resolve_scale(x="shared", y="independent").configure(background=theme["background"]).configure_view(stroke=theme["grid"]).configure_axis(labelFont=font, titleFont=font, labelColor=axis_color, titleColor=axis_color)
    if kind == "band":
        chart = base
        if {"lower", "upper"}.issubset(frame.columns):
            chart = chart.mark_area(opacity=.18, color=theme["colors"][0]).encode(x=alt.X(f"{x}:T"), y=alt.Y("lower:Q", scale=alt.Scale(zero=False)), y2="upper:Q")
        line = alt.Chart(frame).mark_line(point=True, strokeWidth=2).encode(x=alt.X(f"{x}:T", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y(f"{y}:Q", scale=alt.Scale(zero=False), title=spec["unit"], axis=alt.Axis(labelColor=axis_color, titleColor=axis_color, gridColor=theme["grid"])), color=alt.value(spec.get("color", theme["colors"][0])), tooltip=tooltips)
        layer = chart + line if {"lower", "upper"}.issubset(frame.columns) else line
        if "mean" in frame and pd.notna(frame["mean"]).any():
            mean_df = pd.DataFrame({"mean": [float(frame["mean"].dropna().iloc[0])]})
            rule = alt.Chart(mean_df).mark_rule(color=theme["colors"][1], strokeDash=[6, 4]).encode(y="mean:Q")
            layer = layer + rule
        return layer.properties(height=300).configure(background=theme["background"]).configure_view(stroke=theme["grid"]).configure_axis(labelFont=font, titleFont=font, labelColor=axis_color, titleColor=axis_color)
    if kind in {"bar", "stacked_bar", "zones"}:
        if renderer == "Altair / Vega-Lite" and (kind == "zones" or spec.get("representations", {}).get(renderer, "").startswith("Lollipop")):
            horizontal = base.mark_rule(color=theme["grid"], strokeWidth=3).encode(x=alt.X(f"{y}:Q", title=spec["unit"], axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y(f"{x}:N", sort="-x", axis=alt.Axis(labelColor=axis_color)), x2=alt.value(0), tooltip=tooltips)
            points = base.mark_point(filled=True, size=150).encode(x=f"{y}:Q", y=alt.Y(f"{x}:N", sort="-x"), color=alt.Color(f"{x}:N", scale=color_scale, legend=None), tooltip=tooltips)
            return (horizontal + points).properties(height=max(250, 34 * max(len(frame), 1))).configure(background=theme["background"]).configure_view(stroke=theme["grid"]).configure_axis(labelFont=font, titleFont=font)
        if kind == "stacked_bar" and renderer == "Altair / Vega-Lite":
            return base.mark_area().encode(x=alt.X(f"{x}:T", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y(f"sum({y}):Q", stack="zero", title=spec["unit"], axis=alt.Axis(labelColor=axis_color, titleColor=axis_color, gridColor=theme["grid"])), color=alt.Color(f"{spec['series']}:N", scale=color_scale), tooltip=[alt.Tooltip(f"{x}:T"), alt.Tooltip(f"sum({y}):Q"), alt.Tooltip(f"{spec['series']}:N")]).properties(height=300).configure(background=theme["background"]).configure_axis(labelFont=font, titleFont=font)
        enc = xy(f"{x}:T" if x in frame and pd.api.types.is_datetime64_any_dtype(frame[x]) else f"{x}:N", f"{y}:Q")
        return enc.mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(color=alt.Color(f"{spec['series']}:N", scale=color_scale) if spec.get("series") and spec["series"] in frame else alt.value(theme["colors"][0])).properties(height=300).configure(background=theme["background"]).configure_view(stroke=theme["grid"]).configure_axis(labelFont=font, titleFont=font)
    if kind == "goal":
        if frame.empty:
            return base.mark_text(text="Sin datos de objetivos").encode()
        goal_frame = frame.copy()
        goal_frame["track"] = max(125, float(frame["progress"].max()) + 15)
        tracks = alt.Chart(goal_frame).mark_bar(color=theme["grid"], size=20).encode(y=alt.Y("goal:N", sort=None, axis=alt.Axis(labelColor=axis_color)), x=alt.X("track:Q", scale=alt.Scale(domain=[0, float(goal_frame["track"].max())]), title="Progreso (%)", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])))
        bars = alt.Chart(frame).mark_bar(size=20, cornerRadiusEnd=5).encode(y=alt.Y("goal:N", sort=None), x=alt.X("progress:Q"), color=alt.Color("goal:N", scale=color_scale, legend=None), tooltip=["goal:N", "current:Q", "target:Q", "unit:N", "progress:Q"])
        threshold = alt.Chart(pd.DataFrame({"target": [100]})).mark_rule(color=theme["text"], strokeDash=[5, 4]).encode(x="target:Q")
        return (tracks + bars + threshold).properties(height=180).configure(background=theme["background"]).configure_axis(labelFont=font, titleFont=font)
    if kind == "completion":
        points = base.mark_line(point=alt.OverlayMarkDef(filled=True, size=110), strokeWidth=2.5).encode(x=alt.X(f"{x}:T", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y(f"{y}:Q", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(title="Cumplimiento (%)", values=[25, 50, 75, 100], labelExpr="datum.value + '%'", labelColor=axis_color, gridColor=theme["grid"])), color=alt.value(theme["colors"][0]), tooltip=tooltips)
        rules = alt.Chart(pd.DataFrame({"nivel": [25, 50, 75, 100]})).mark_rule(color=theme["grid"], strokeDash=[4, 4]).encode(y="nivel:Q")
        return (points + rules).properties(height=290).configure(background=theme["background"]).configure_axis(labelFont=font, titleFont=font)
    if kind == "scatter":
        size_field = spec.get("size")
        chart = xy(f"{x}:Q", f"{y}:Q").mark_circle(opacity=.8, stroke="white", strokeWidth=.4)
        encodings = {"tooltip": tooltips}
        if spec.get("color") in frame:
            encodings["color"] = alt.Color(f"{spec['color']}:N", scale=color_scale)
        if size_field in frame:
            encodings["size"] = alt.Size(f"{size_field}:Q", scale=alt.Scale(range=[35, 300]))
        return chart.encode(**encodings).properties(height=300).interactive().configure(background=theme["background"]).configure_axis(labelFont=font, titleFont=font)
    if kind == "activity_summary":
        color_scale = alt.Scale(domain=["Otras salidas", "Actividad elegida"], range=[theme["muted"], theme["colors"][1]])
        points = base.mark_circle(filled=True, stroke=theme["background"], strokeWidth=1).encode(
            x=alt.X(f"{x}:T", title="Fecha", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])),
            y=alt.Y(f"{y}:Q", title=spec["unit"], scale=alt.Scale(zero=False), axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])),
            color=alt.Color(f"{spec['color']}:N", scale=color_scale, legend=alt.Legend(title=None)),
            size=alt.Size(f"{spec['color']}:N", scale=alt.Scale(domain=["Otras salidas", "Actividad elegida"], range=[60, 170]), legend=None),
            tooltip=tooltips,
        )
        return points.properties(height=300).interactive().configure(background=theme["background"]).configure_axis(labelFont=font, titleFont=font)
    if kind in {"profile", "line"}:
        x_type = "T" if kind == "line" or (x in frame and pd.api.types.is_datetime64_any_dtype(frame[x])) else "Q"
        mark = base.mark_area(line=alt.MarkConfig(color=theme["colors"][0], strokeWidth=2), opacity=.14, color=theme["colors"][0]) if kind == "profile" or spec["key"] == "forma_ramp_rate" else base.mark_line(point=True, strokeWidth=2.5, color=theme["colors"][0])
        return mark.encode(x=alt.X(f"{x}:{x_type}", title=spec.get("x_label"), axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y(f"{y}:Q", title=spec.get("y_label", spec["unit"]), scale=alt.Scale(zero=False), axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), tooltip=tooltips).properties(height=300).interactive().configure(background=theme["background"]).configure_view(stroke=theme["grid"]).configure_axis(labelFont=font, titleFont=font)
    if kind in {"multi_line", "curve"}:
        if kind == "curve":
            line = base.mark_line(point=True, strokeWidth=2.5).encode(x=alt.X(f"{x}:Q", scale=alt.Scale(type="log"), axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y(f"{y}:Q", title=spec["unit"], axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), color=alt.Color(f"{spec['series']}:N", scale=color_scale) if spec.get("series") in frame else alt.value(theme["colors"][0]), tooltip=tooltips)
            return line.properties(height=300).interactive().configure(background=theme["background"]).configure_axis(labelFont=font, titleFont=font)
        if kind == "multi_line" and spec["key"] == "salud_body_battery":
            wide = frame.pivot_table(index=x, columns="series", values=y, aggfunc="mean").reset_index()
            area = alt.Chart(wide).mark_area(opacity=.18, color=theme["colors"][0]).encode(x=alt.X(f"{x}:T", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y("Mínimo:Q", scale=alt.Scale(zero=False), title=spec["unit"]), y2="Máximo:Q", tooltip=[f"{x}:T", "Mínimo:Q", "Máximo:Q"])
            lines = alt.Chart(frame).mark_line(point=True, strokeWidth=2).encode(x=alt.X(f"{x}:T", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y(f"{y}:Q", scale=alt.Scale(zero=False), title=spec["unit"]), color=alt.Color(f"{spec['series']}:N", scale=color_scale), tooltip=tooltips)
            return (area + lines).properties(height=300).configure(background=theme["background"]).configure_view(stroke=theme["grid"]).configure_axis(labelFont=font, titleFont=font)
        if kind == "multi_line" and spec["key"] == "salud_sueno":
            sleep = frame.loc[frame[spec["series"]] == "Horas de sueño"]
            mean = frame.loc[frame[spec["series"]] == "Media 7 días"]
            bars = alt.Chart(sleep).mark_bar(opacity=.56, color=theme["colors"][6]).encode(x=alt.X(f"{x}:T", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y(f"{y}:Q", title=spec["unit"], axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), tooltip=tooltips)
            trend = alt.Chart(mean).mark_line(point=True, strokeWidth=2.6, color=theme["colors"][0]).encode(x=f"{x}:T", y=f"{y}:Q", tooltip=tooltips)
            return (bars + trend).properties(height=300).configure(background=theme["background"]).configure_view(stroke=theme["grid"]).configure_axis(labelFont=font, titleFont=font)
        if spec.get("series") in frame:
            if renderer == "Altair / Vega-Lite" and spec["key"] == "ciclismo_potencia_semanal":
                area = base.mark_area(opacity=.12).encode(x=alt.X(f"{x}:T"), y=alt.Y(f"{y}:Q", scale=alt.Scale(zero=False)), color=alt.Color(f"{spec['series']}:N", scale=color_scale), tooltip=tooltips)
                line = base.mark_line(point=True, strokeWidth=2).encode(x=f"{x}:T", y=f"{y}:Q", color=alt.Color(f"{spec['series']}:N", scale=color_scale), tooltip=tooltips)
                return (area + line).properties(height=300).configure(background=theme["background"]).configure_axis(labelFont=font, titleFont=font)
            mark = base.mark_line(point=True, strokeWidth=2.5).encode(x=alt.X(f"{x}:T" if pd.api.types.is_datetime64_any_dtype(frame[x]) else f"{x}:N", axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), y=alt.Y(f"{y}:Q", title=spec["unit"], axis=alt.Axis(labelColor=axis_color, gridColor=theme["grid"])), color=alt.Color(f"{spec['series']}:N", scale=color_scale), tooltip=tooltips)
            return mark.properties(height=300).interactive().configure(background=theme["background"]).configure_view(stroke=theme["grid"]).configure_axis(labelFont=font, titleFont=font)
    return base.mark_line(point=True).encode(x=f"{x}:T", y=f"{y}:Q", tooltip=tooltips).properties(height=300)


def _json_records(frame: pd.DataFrame, fields: list[str]) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    out = frame.copy()
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].map(lambda value: value.isoformat() if pd.notna(value) else None)
    out = out.astype(object).where(pd.notna(out), None)
    return out[[field for field in fields if field in out]].to_dict("records")


def _echarts_comparison_option(spec: dict[str, Any], theme: dict[str, Any]) -> dict[str, Any]:
    frame: pd.DataFrame = spec["data"]
    kind, x, y = spec["kind"], spec["x"], spec["y"]
    mode = spec.get("display_type", "Barras")
    text_color, grid_color = theme["text"], theme["grid"]
    tooltip = {"trigger": "axis", "axisPointer": {"type": "shadow"}}
    grid = {"left": 62, "right": 24, "top": 36, "bottom": 54, "containLabel": True}
    x_labels = [value.isoformat() if isinstance(value, (pd.Timestamp, date)) else str(value) for value in frame.get(x, [])]

    if mode in PIE_REPRESENTATIONS:
        pie = _pie_data(spec)
        tooltip_value = "{c} min" if kind == "zones" else "{c}"
        return {
            "backgroundColor": theme["background"],
            "tooltip": {"trigger": "item", "formatter": f"{{b}}<br/>{tooltip_value} · {{d}}%"},
            "legend": {"bottom": 0, "textStyle": {"color": text_color}},
            "series": [{
                "name": spec["title"], "type": "pie",
                "radius": ["42%", "70%"] if mode != "Tarta" else "70%",
                "center": ["50%", "46%"], "avoidLabelOverlap": True,
                "label": {"color": text_color, "formatter": "{b}  {d}%"}, "labelLayout": {"hideOverlap": True}, "minShowLabelAngle": 9,
                "data": [{"name": str(row["category"]), "value": round(float(row["value"]), 2), "itemStyle": {"color": _series_color(row["category"], theme, index)}} for index, row in pie.iterrows()],
                "emphasis": {"scale": True, "scaleSize": 6},
            }],
        }

    if mode == "Lollipop":
        horizontal = kind == "zones" or spec.get("orientation") == "horizontal"
        values = _numeric(frame, y).fillna(0).tolist()
        point_colors = [_series_color(category, theme, index) for index, category in enumerate(frame.get(x, []))]
        if horizontal:
            x_axis = {"type": "value", "name": spec["unit"], "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}
            y_axis = {"type": "category", "data": x_labels, "inverse": True, "axisLabel": {"color": text_color}}
            points = [[value, category] for value, category in zip(values, x_labels)]
        else:
            x_axis = {"type": "category", "data": x_labels, "axisLabel": {"color": text_color}}
            y_axis = {"type": "value", "name": spec["unit"], "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}
            points = [[category, value] for category, value in zip(x_labels, values)]
        return {
            "backgroundColor": theme["background"], "tooltip": tooltip, "grid": grid,
            "xAxis": x_axis, "yAxis": y_axis,
            "series": [
                {"type": "bar", "data": values, "barWidth": 3, "itemStyle": {"color": grid_color}, "silent": True, "z": 1},
                {"type": "scatter", "data": [{"value": point, "itemStyle": {"color": color}} for point, color in zip(points, point_colors)], "symbolSize": 12, "z": 3, "name": spec["title"]},
            ],
            "dataZoom": [{"type": "inside"}] if not horizontal else [],
        }

    if kind in {"stacked_bar", "ciclismo_potencia_semanal", "forma_carga_semanal"}:
        series_field = spec.get("series")
        series_data = []
        if series_field and series_field in frame:
            names = frame[series_field].dropna().unique().tolist()
            for index, name in enumerate(names):
                part = frame.loc[frame[series_field] == name].copy()
                part_labels = [value.isoformat() if isinstance(value, (pd.Timestamp, date)) else str(value) for value in part[x]]
                by_label = dict(zip(part_labels, _numeric(part, y).fillna(0).tolist()))
                chart_type = "line" if (kind == "stacked_bar" and mode in {"Área apilada", "Líneas por tipo"}) or (kind == "ciclismo_potencia_semanal" and mode in {"Líneas", "Áreas"}) or (kind == "forma_carga_semanal" and mode == "Línea") else "bar"
                item = {"name": str(name), "type": chart_type, "data": [by_label.get(label, 0) for label in x_labels], "itemStyle": {"color": _series_color(name, theme, index)}, "lineStyle": {"width": 2.5}}
                if kind == "stacked_bar" and mode in {"Columnas apiladas", "Área apilada"}:
                    item["stack"] = "volumen"
                if chart_type == "line" and (kind != "stacked_bar" or mode == "Líneas por tipo"):
                    item["showSymbol"] = True
                if mode == "Área apilada" and kind == "stacked_bar":
                    item["areaStyle"] = {"opacity": .24}
                if mode == "Áreas" and kind == "ciclismo_potencia_semanal":
                    item["areaStyle"] = {"opacity": .14}
                series_data.append(item)
        else:
            series_data = [{"name": spec["title"], "type": "line" if mode == "Línea" else "bar", "data": _numeric(frame, y).fillna(0).tolist(), "itemStyle": {"color": theme["colors"][0]}, "lineStyle": {"width": 2.5}, "showSymbol": True}]
        if kind == "completion":
            pass
        return {
            "backgroundColor": theme["background"], "tooltip": tooltip, "legend": {"top": 4, "textStyle": {"color": text_color}} if len(series_data) > 1 else {"show": False}, "grid": grid,
            "xAxis": {"type": "category", "data": x_labels, "axisLabel": {"color": text_color}},
            "yAxis": {"type": "value", "name": spec["unit"], "scale": kind == "ciclismo_potencia_semanal", "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}},
            "series": series_data,
        }

    if kind == "completion":
        line_mode = mode == "Línea"
        series = {"name": "Cumplimiento", "type": "line" if line_mode else "bar", "data": frame.get(y, pd.Series(dtype=float)).fillna(0).round(1).tolist(), "itemStyle": {"color": theme["colors"][0]}, "lineStyle": {"color": theme["colors"][0], "width": 2.5}, "showSymbol": line_mode, "symbolSize": 8, "markLine": {"symbol": "none", "data": [{"yAxis": value, "label": {"formatter": f"{value}%"}} for value in (25, 50, 75, 100)], "lineStyle": {"color": grid_color, "type": "dashed"}}}
        return {"backgroundColor": theme["background"], "tooltip": tooltip, "grid": grid, "xAxis": {"type": "category", "data": x_labels, "axisLabel": {"color": text_color}}, "yAxis": {"type": "value", "min": 0, "max": 100, "interval": 25, "axisLabel": {"color": text_color, "formatter": "{value}%"}, "splitLine": {"lineStyle": {"color": grid_color}}}, "series": [series]}

    return {"backgroundColor": theme["background"], "title": {"text": spec["title"], "textStyle": {"color": text_color}}}


def _echarts_option(spec: dict[str, Any], theme: dict[str, Any], renderer: str) -> dict[str, Any]:
    frame: pd.DataFrame = spec["data"]
    kind, x, y = spec["kind"], spec["x"], spec["y"]
    if spec.get("display_type") and kind in {"bar", "stacked_bar", "zones", "completion", "multi_line"}:
        return _echarts_comparison_option(spec, theme)
    text_color, grid_color = theme["text"], theme["grid"]
    tooltip: dict[str, Any] = {"trigger": "axis"}
    grid = {"left": 58, "right": 24, "top": 56, "bottom": 56, "containLabel": True}
    if kind == "form":
        return {
            "backgroundColor": theme["background"], "animationDuration": 450,
            "tooltip": {"trigger": "axis"}, "legend": {"top": 5, "textStyle": {"color": text_color}},
            "grid": [{"left": 58, "right": 20, "top": 48, "height": "43%"}, {"left": 58, "right": 20, "top": "62%", "height": "25%"}],
            "xAxis": [{"type": "time", "gridIndex": 0, "axisLabel": {"show": False, "color": text_color}, "splitLine": {"show": False}}, {"type": "time", "gridIndex": 1, "axisLabel": {"color": text_color}, "splitLine": {"show": False}}],
            "yAxis": [{"type": "value", "gridIndex": 0, "name": "CTL / ATL", "nameTextStyle": {"color": text_color}, "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}, {"type": "value", "gridIndex": 1, "name": "TSB", "nameTextStyle": {"color": text_color}, "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}],
            "series": [
                {"name": "CTL", "type": "line", "smooth": True, "showSymbol": False, "xAxisIndex": 0, "yAxisIndex": 0, "data": [[row["date"], row.get("ctl")] for row in _json_records(frame, ["date", "ctl"])], "lineStyle": {"width": 3, "color": theme["colors"][2]}},
                {"name": "ATL", "type": "line", "smooth": True, "showSymbol": False, "xAxisIndex": 0, "yAxisIndex": 0, "data": [[row["date"], row.get("atl")] for row in _json_records(frame, ["date", "atl"])], "lineStyle": {"width": 2.4, "color": theme["colors"][3]}},
                {"name": "TSB", "type": "line", "smooth": True, "showSymbol": False, "xAxisIndex": 1, "yAxisIndex": 1, "data": [[row["date"], row.get("tsb")] for row in _json_records(frame, ["date", "tsb"])], "lineStyle": {"width": 2.2, "color": theme["colors"][4]}, "areaStyle": {"opacity": .12}, "markLine": {"symbol": "none", "data": [{"yAxis": 0}], "lineStyle": {"color": theme["colors"][0], "type": "dashed"}}},
            ],
        }
    if kind == "goal":
        categories = frame.get("goal", pd.Series(dtype=str)).tolist()
        maximum = max(125, float(frame["progress"].max()) + 15) if not frame.empty else 125
        return {
            "backgroundColor": theme["background"], "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": {"left": 105, "right": 24, "top": 38, "bottom": 44, "containLabel": True},
            "xAxis": {"type": "value", "max": maximum, "name": "Progreso (%)", "axisLabel": {"color": text_color, "formatter": "{value}%"}, "splitLine": {"lineStyle": {"color": grid_color}}, "markLine": {"data": [{"xAxis": 100}]}},
            "yAxis": {"type": "category", "data": categories, "inverse": True, "axisLabel": {"color": text_color}},
            "series": [{"type": "bar", "data": [{"value": row["progress"], "itemStyle": {"color": _series_color(row["goal"], theme, index)}, "current": row["current"], "target": row["target"], "unit": row["unit"]} for index, row in enumerate(_json_records(frame, ["goal", "progress", "current", "target", "unit"]))], "barWidth": 22, "label": {"show": True, "position": "right", "color": text_color, "formatter": "{c}%"}, "markLine": {"symbol": "none", "data": [{"xAxis": 100}], "lineStyle": {"color": theme["text"], "type": "dashed"}}}],
        }
    if kind == "completion":
        return {
            "backgroundColor": theme["background"], "tooltip": {"trigger": "axis"}, "grid": grid,
            "xAxis": {"type": "category", "data": [str(value)[:10] for value in frame.get(x, [])], "axisLabel": {"color": text_color}},
            "yAxis": {"type": "value", "min": 0, "max": 100, "interval": 25, "axisLabel": {"color": text_color, "formatter": "{value}%", "showMinLabel": False}, "splitLine": {"lineStyle": {"color": grid_color}}},
            "series": [{"name": "Cumplimiento", "type": "bar", "data": frame.get(y, pd.Series(dtype=float)).fillna(0).round(1).tolist(), "itemStyle": {"color": theme["colors"][0]}, "markLine": {"symbol": "none", "data": [{"yAxis": value, "label": {"formatter": f"{value}%"}} for value in (25, 50, 75, 100)], "lineStyle": {"color": grid_color, "type": "dashed"}}}],
        }
    if kind == "health_vitals":
        metrics = frame["metric"].drop_duplicates().tolist() if "metric" in frame else []
        count = max(len(metrics), 1)
        grid_items, x_axes, y_axes, series = [], [], [], []
        panel_height = 78 / count
        for index, metric in enumerate(metrics):
            part = frame.loc[frame["metric"] == metric]
            top = 8 + index * (90 / count)
            grid_items.append({"left": 58, "right": 20, "top": f"{top}%", "height": f"{panel_height}%", "containLabel": True})
            x_axes.append({"type": "time", "gridIndex": index, "axisLabel": {"color": text_color, "show": index == count - 1}, "splitLine": {"show": False}})
            y_axes.append({"type": "value", "gridIndex": index, "name": str(part["unit"].iloc[0]), "scale": True, "axisLabel": {"color": text_color}, "nameTextStyle": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}})
            color = _series_color(metric, theme, index)
            points = [[row["date"], row["value"]] for row in _json_records(part, ["date", "value"])]
            series.append({"name": str(metric), "type": "line", "smooth": True, "showSymbol": True, "xAxisIndex": index, "yAxisIndex": index, "data": points, "lineStyle": {"color": color, "width": 2.3}, "itemStyle": {"color": color}, "markArea": {"silent": True, "itemStyle": {"color": theme["colors"][0], "opacity": .24}, "data": [[{"yAxis": float(part["lower"].iloc[0])}, {"yAxis": float(part["upper"].iloc[0])}]]}, "markLine": {"symbol": "none", "data": [{"yAxis": float(part["mean"].iloc[0]), "name": "Media"}], "lineStyle": {"color": theme["colors"][1], "type": "dashed"}}})
        return {"backgroundColor": theme["background"], "tooltip": {"trigger": "axis"}, "legend": {"show": False}, "grid": grid_items, "xAxis": x_axes, "yAxis": y_axes, "series": series, "dataZoom": [{"type": "inside"}, {"type": "slider", "height": 16, "bottom": 4}]}
    if kind == "band":
        records = _json_records(frame, [x, y, "lower", "upper", "mean"])
        series = [{"name": "Banda ±5", "type": "line", "data": [[row.get(x), row.get("upper")] for row in records], "lineStyle": {"opacity": 0}, "areaStyle": {"color": theme["colors"][0], "opacity": .18}, "stack": "range", "symbol": "none", "tooltip": {"show": False}}]
        # markArea mantiene la banda centrada en la media incluso con huecos temporales.
        mean = spec.get("mean")
        if pd.notna(mean) and renderer == "Apache ECharts":
            series = [{"name": spec["title"], "type": "line", "smooth": True, "showSymbol": True, "data": [[row.get(x), row.get(y)] for row in records], "lineStyle": {"color": spec.get("color", theme["colors"][0]), "width": 2.5}, "itemStyle": {"color": spec.get("color", theme["colors"][0])}, "markArea": {"silent": True, "itemStyle": {"color": theme["colors"][0], "opacity": .16}, "data": [[{"yAxis": mean - 5}, {"yAxis": mean + 5}]]}, "markLine": {"symbol": "none", "data": [{"yAxis": mean, "name": "Media"}], "lineStyle": {"color": theme["colors"][1], "type": "dashed"}}}]
        else:
            series.append({"name": spec["title"], "type": "line", "smooth": True, "data": [[row.get(x), row.get(y)] for row in records], "lineStyle": {"color": spec.get("color", theme["colors"][0]), "width": 2.5}, "markLine": {"symbol": "none", "data": [{"yAxis": mean}] if pd.notna(mean) else [], "lineStyle": {"color": theme["colors"][1], "type": "dashed"}}})
        return {"backgroundColor": theme["background"], "tooltip": tooltip, "grid": grid, "xAxis": {"type": "time", "axisLabel": {"color": text_color}}, "yAxis": {"type": "value", "scale": True, "name": spec["unit"], "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}, "series": series, "dataZoom": [{"type": "inside"}, {"type": "slider", "height": 18, "bottom": 8}]}
    if kind == "scatter":
        series = []
        color_field = spec.get("color")
        for index, category in enumerate(frame[color_field].dropna().unique() if color_field in frame else [None]):
            part = frame.loc[frame[color_field] == category] if category is not None else frame
            series.append({"name": str(category or "Actividad"), "type": "scatter", "data": [[row[x], row[y], row.get(spec.get("size")), row.get("activity_name")] for row in _json_records(part, [x, y, spec.get("size"), "activity_name"])], "symbolSize": 10, "itemStyle": {"color": _series_color(category, theme, index), "opacity": .8}})
        return {"backgroundColor": theme["background"], "tooltip": {"trigger": "item", "formatter": "{a}<br/>X: {c0}<br/>Y: {c1}"}, "grid": grid, "xAxis": {"type": "value", "name": spec.get("x_label"), "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}, "yAxis": {"type": "value", "name": spec.get("y_label"), "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}, "series": series, "dataZoom": [{"type": "inside"}, {"type": "slider", "height": 18, "bottom": 8}]}
    if kind == "activity_summary":
        series = []
        color_field = spec.get("color", "seleccion")
        for index, category in enumerate(frame[color_field].dropna().unique()):
            part = frame.loc[frame[color_field] == category]
            data = [[row[x], row[y], row.get("activity_name")] for row in _json_records(part, [x, y, "activity_name"])]
            emphasized = category == "Actividad elegida"
            series.append({"name": str(category), "type": "scatter", "data": data, "symbolSize": 12 if emphasized else 8, "itemStyle": {"color": _series_color(category, theme, index), "opacity": .95 if emphasized else .68}})
        return {"backgroundColor": theme["background"], "tooltip": {"trigger": "item", "formatter": "{a}<br/>{b}<br/>{c}"}, "grid": grid, "xAxis": {"type": "time", "name": "Fecha", "axisLabel": {"color": text_color}, "splitLine": {"show": False}}, "yAxis": {"type": "value", "name": spec["unit"], "scale": True, "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}, "series": series, "dataZoom": [{"type": "inside"}]}
    if kind in {"bar", "stacked_bar", "zones"}:
        is_category = x in frame and not pd.api.types.is_datetime64_any_dtype(frame[x])
        categories = []
        if x in frame:
            categories = [value.isoformat() if isinstance(value, (pd.Timestamp, date)) else str(value) for value in frame[x].drop_duplicates().tolist()]
        series_field = spec.get("series")
        series = []
        if series_field and series_field in frame:
            for index, name in enumerate(frame[series_field].dropna().unique()):
                part = frame.loc[frame[series_field] == name]
                values = part.set_index(x)[y].to_dict()
                item = {"name": str(name), "type": "bar", "data": [round(float(values.get(value, 0) or 0), 2) for value in frame[x].drop_duplicates()], "itemStyle": {"color": _series_color(name, theme, index), "borderRadius": [4, 4, 0, 0]}}
                if kind == "stacked_bar":
                    item["stack"] = "total"
                series.append(item)
        elif kind == "zones" and renderer == "Altair / Vega-Lite":
            series = [{"name": "Minutos", "type": "scatter", "symbolSize": 15, "data": [[row[y], row[x]] for row in _json_records(frame, [x, y])], "itemStyle": {"color": theme["colors"][0]}}]
            return {"backgroundColor": theme["background"], "tooltip": {"trigger": "item"}, "grid": {"left": 110, "right": 30, "top": 32, "bottom": 42}, "xAxis": {"type": "value", "name": spec["unit"], "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}, "yAxis": {"type": "category", "data": categories, "inverse": True, "axisLabel": {"color": text_color}}, "series": series}
        else:
            records = _json_records(frame, [x, y])
            vals = [row.get(y) or 0 for row in records]
            item_colors = [_series_color(row.get(x), theme, i) if kind == "zones" else theme["colors"][0] for i, row in enumerate(records)]
            series = [{"name": spec["title"], "type": "bar", "data": [{"value": value, "itemStyle": {"color": color}} for value, color in zip(vals, item_colors)], "itemStyle": {"borderRadius": [4, 4, 0, 0]}}]
        horizontal = kind == "zones" or spec.get("orientation") == "horizontal"
        if horizontal and series and "data" in series[0]:
            x_axis = {"type": "value", "name": spec["unit"], "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}
            y_axis = {"type": "category", "data": categories, "inverse": True, "axisLabel": {"color": text_color}}
        else:
            x_axis = {"type": "category", "data": categories, "axisLabel": {"color": text_color}}
            y_axis = {"type": "value", "name": spec["unit"], "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}
        if kind == "stacked_bar":
            for item in series:
                item["stack"] = "total"
        return {"backgroundColor": theme["background"], "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}}, "legend": {"top": 4, "textStyle": {"color": text_color}} if len(series) > 1 else {"show": False}, "grid": grid, "xAxis": x_axis, "yAxis": y_axis, "series": series, "dataZoom": [{"type": "inside"}] if not spec.get("orientation") else []}
    if kind in {"profile", "line"} or kind in {"multi_line", "curve"}:
        series = []
        series_field = spec.get("series")
        if series_field and series_field in frame:
            for index, name in enumerate(frame[series_field].dropna().unique()):
                part = frame.loc[frame[series_field] == name]
                if kind == "multi_line" and spec["key"] == "salud_body_battery":
                    continue
                if kind == "multi_line" and spec["key"] == "salud_sueno" and name == "Horas de sueño":
                    series.append({"name": str(name), "type": "bar", "data": [[row[x], row[y]] for row in _json_records(part, [x, y])], "itemStyle": {"color": _series_color(name, theme, index), "opacity": .55}})
                else:
                    series.append({"name": str(name), "type": "line", "smooth": True, "showSymbol": kind == "curve", "data": [[row[x], row[y]] for row in _json_records(part, [x, y])], "lineStyle": {"color": _series_color(name, theme, index), "width": 2.5}, "itemStyle": {"color": _series_color(name, theme, index)}, "areaStyle": {"opacity": .1} if kind == "profile" or spec["key"] == "forma_ramp_rate" else None})
        else:
            series = [{"name": spec["title"], "type": "line", "smooth": True, "showSymbol": False, "data": [[row.get(x), row.get(y)] for row in _json_records(frame, [x, y])], "lineStyle": {"color": theme["colors"][0], "width": 2.5}, "areaStyle": {"color": theme["colors"][0], "opacity": .13} if kind == "profile" or spec["key"] == "forma_ramp_rate" else None}]
        if kind == "multi_line" and spec["key"] == "salud_body_battery":
            wide = frame.pivot_table(index=x, columns="series", values=y, aggfunc="mean").sort_index()
            dates = [value.isoformat() if isinstance(value, pd.Timestamp) else str(value) for value in wide.index]
            lower = pd.to_numeric(wide.get("Mínimo"), errors="coerce").fillna(0).tolist()
            upper = pd.to_numeric(wide.get("Máximo"), errors="coerce").fillna(0).tolist()
            spread = [max(hi - lo, 0) for lo, hi in zip(lower, upper)]
            series = [
                {"name": "Mínimo", "type": "line", "stack": "battery_range", "data": [[day, value] for day, value in zip(dates, lower)], "lineStyle": {"color": _series_color("Mínimo", theme), "width": 1.5}, "areaStyle": {"opacity": 0}},
                {"name": "Rango", "type": "line", "stack": "battery_range", "data": [[day, value] for day, value in zip(dates, spread)], "lineStyle": {"opacity": 0}, "areaStyle": {"color": theme["colors"][0], "opacity": .18}, "tooltip": {"show": False}},
                {"name": "Máximo", "type": "line", "data": [[day, value] for day, value in zip(dates, upper)], "lineStyle": {"color": _series_color("Máximo", theme), "width": 1.5}},
            ]
        x_type = "log" if spec.get("x_scale") == "log" else ("value" if kind == "profile" or kind == "curve" else "time")
        return {"backgroundColor": theme["background"], "tooltip": {"trigger": "axis"}, "legend": {"top": 4, "textStyle": {"color": text_color}} if len(series) > 1 else {"show": False}, "grid": grid, "xAxis": {"type": x_type, "name": spec.get("x_label", ""), "axisLabel": {"color": text_color}, "splitLine": {"show": False}}, "yAxis": {"type": "value", "name": spec.get("y_label", spec["unit"]), "scale": True, "axisLabel": {"color": text_color}, "splitLine": {"lineStyle": {"color": grid_color}}}, "series": series, "dataZoom": [{"type": "inside"}, {"type": "slider", "height": 16, "bottom": 8}]}
    return {"backgroundColor": theme["background"], "title": {"text": spec["title"], "textStyle": {"color": text_color}}}


def _icon_svg(name: str, color: str) -> str:
    paths = {
        "Bicicleta": '<circle cx="5.5" cy="17.5" r="3.5"/><circle cx="18.5" cy="17.5" r="3.5"/><path d="M15 6h2l3 11.5M5.5 17.5 10 9l4 8.5h-8l5-8h4"/>',
        "Tendencia": '<path d="M3 17l6-6 4 4 8-9"/><path d="M15 6h6v6"/>',
        "Recuperación": '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z"/><path d="M3 12h5l2-3 3.5 6 2-3H21"/>',
    }
    return f'<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths[name]}</svg>'


def _icon_preview(icon_set: str, icon_name: str, color: str) -> str:
    if icon_set == "Emojis actuales":
        return {"Bicicleta": "🚴", "Tendencia": "📈", "Recuperación": "💚"}[icon_name]
    if icon_set == "Lucide SVG":
        return _icon_svg(icon_name, color)
    return {"Bicicleta": "directions_bike", "Tendencia": "trending_up", "Recuperación": "monitor_heart"}[icon_name]


def _chart_renderer(spec: dict[str, Any], library: str, theme: dict[str, Any], font: str) -> None:
    frame: pd.DataFrame = spec["data"]
    if frame.empty:
        st.info("Este gráfico no tiene muestras suficientes con el periodo y filtros actuales.")
        return
    if library == "Plotly":
        st.plotly_chart(_plotly_figure(spec, theme, font), width="stretch", key=f"visual_lab_{spec['key']}_plotly")
    elif library == "Altair / Vega-Lite":
        chart = _altair_chart(spec, theme, font, library)
        st.altair_chart(chart, width="stretch", key=f"visual_lab_{spec['key']}_altair")
    else:
        option = _echarts_option(spec, theme, library)
        option.setdefault("textStyle", {})["fontFamily"] = font
        st.echarts_chart(option, width="stretch", height=430, theme="streamlit", key=f"visual_lab_{spec['key']}_echarts", alt=spec["title"])


def _trend_prediction(spec: dict[str, Any]) -> tuple[list[list[Any]], list[list[Any]]]:
    metric = "ctl" if spec["key"] == "forma_evolucion" else "ramp_rate"
    values = spec["data"].dropna(subset=[metric]).sort_values("date")
    if values.empty:
        return [], []
    recent = values.loc[values["date"] >= values["date"].max() - pd.Timedelta(days=30)]
    if len(recent) < 3:
        return [], []
    days = (recent["date"] - recent["date"].min()).dt.total_seconds().to_numpy() / 86400
    slope, intercept = np.polyfit(days, pd.to_numeric(recent[metric]).to_numpy(), 1)
    trend = [[pd.Timestamp(row.date).isoformat(), float(intercept + slope * day)] for row, day in zip(recent.itertuples(), days)]
    last_date = pd.Timestamp(recent.iloc[-1]["date"])
    last_value = float(recent.iloc[-1][metric])
    forecast_date = last_date + pd.Timedelta(days=7)
    prediction = [[last_date.isoformat(), last_value], [forecast_date.isoformat(), last_value + float(slope) * 7]]
    return trend, prediction


def render_approved_chart(spec: dict[str, Any], library: str, *, height: int = 390) -> None:
    """Renderiza una selección aprobada con el tema global del dashboard."""
    theme = THEMES["Rendimiento deportivo"]
    font = FONTS["Manrope"]["body"]
    if spec["data"].empty:
        st.info("No hay datos suficientes para este gráfico con los filtros actuales.")
        return
    key = f"approved_{spec['key']}"
    if library == "Altair / Vega-Lite":
        st.altair_chart(_altair_chart(spec, theme, font, library), width="stretch", key=key)
    elif library == "Apache ECharts":
        option = _echarts_option(spec, theme, library)
        if spec["key"] in {"forma_evolucion", "forma_ramp_rate"}:
            trend, prediction = _trend_prediction(spec)
            if trend and prediction:
                if spec["key"] == "forma_evolucion":
                    # A high-contrast overlay keeps the CTL trend easy to distinguish
                    # from the CTL/ATL lines, even on small screens.
                    option.setdefault("series", []).extend([
                        {
                            "name": "Tendencia CTL · 30 días",
                            "type": "line",
                            "xAxisIndex": 0,
                            "yAxisIndex": 0,
                            "data": trend,
                            "showSymbol": True,
                            "symbol": "circle",
                            "symbolSize": 6,
                            "z": 20,
                            "lineStyle": {"color": "#22D3EE", "width": 4, "type": "dashed"},
                            "itemStyle": {"color": "#22D3EE", "borderColor": theme["background"], "borderWidth": 1},
                            "emphasis": {"focus": "series", "lineStyle": {"width": 5}},
                        },
                        {
                            "name": "CTL proyectado · +7 días",
                            "type": "line",
                            "xAxisIndex": 0,
                            "yAxisIndex": 0,
                            "data": prediction,
                            "showSymbol": True,
                            "symbol": "emptyCircle",
                            "symbolSize": 9,
                            "z": 21,
                            "lineStyle": {"color": "#F8FAFC", "width": 3, "type": "dotted"},
                            "itemStyle": {"color": "#F8FAFC"},
                            "emphasis": {"focus": "series", "lineStyle": {"width": 4}},
                        },
                    ])
                else:
                    option.setdefault("series", []).extend([
                        {"name": "Tendencia · 30 días", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": trend, "showSymbol": False, "z": 20, "lineStyle": {"color": "#22D3EE", "width": 3, "type": "dashed"}},
                        {"name": "Predicción lineal · +7 días", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": prediction, "showSymbol": True, "symbolSize": 8, "z": 21, "lineStyle": {"color": "#F8FAFC", "width": 3, "type": "dotted"}},
                    ])
        option.setdefault("textStyle", {})["fontFamily"] = font
        try:
            st.echarts_chart(option, width="stretch", height=height, theme="streamlit", key=key, alt=spec["title"])
        except Exception as exc:
            st.warning(f"No se pudo representar con ECharts ({exc}). Se muestra una alternativa Plotly.")
            fallback = _plotly_figure(spec, theme, font)
            if spec["key"] in {"forma_evolucion", "forma_ramp_rate"}:
                trend, prediction = _trend_prediction(spec)
                if trend:
                    if spec["key"] == "forma_evolucion":
                        fallback.add_trace(go.Scatter(x=[point[0] for point in trend], y=[point[1] for point in trend], mode="lines", name="Tendencia · 30 días", line={"color": theme["colors"][5], "dash": "dash"}), row=1, col=1)
                        fallback.add_trace(go.Scatter(x=[point[0] for point in prediction], y=[point[1] for point in prediction], mode="lines+markers", name="Predicción lineal · +7 días", line={"color": theme["text"], "dash": "dot"}), row=1, col=1)
                    else:
                        fallback.add_trace(go.Scatter(x=[point[0] for point in trend], y=[point[1] for point in trend], mode="lines", name="Tendencia · 30 días", line={"color": theme["colors"][5], "dash": "dash"}))
                        fallback.add_trace(go.Scatter(x=[point[0] for point in prediction], y=[point[1] for point in prediction], mode="lines+markers", name="Predicción lineal · +7 días", line={"color": theme["text"], "dash": "dot"}))
            st.plotly_chart(fallback, width="stretch", key=f"{key}_fallback")
    else:
        st.plotly_chart(_plotly_figure(spec, theme, font), width="stretch", key=key)


def render_visual_lab(data: dict[str, Any]) -> None:
    """Renderiza la galería aislada; no cambia los gráficos de producción."""
    st.header("Laboratorio visual")
    st.caption("Compara representaciones con los datos locales y los filtros activos. Cada aprobación posterior se aplicará solo al gráfico que elijas.")

    controls = st.columns([1.15, 1.15, 1.15])
    with controls[0]:
        style_name = st.selectbox("Dirección visual", list(THEMES), index=1, key="visual_lab_theme_v2")
    with controls[1]:
        font_name = st.selectbox("Tipografía", list(FONTS), key="visual_lab_font_v2")
    with controls[2]:
        icon_sets = ["Emojis actuales", "Lucide SVG", "Material Symbols outlined"]
        icon_set = st.selectbox("Iconos", icon_sets, index=2, key="visual_lab_icons_v2")
    theme = THEMES[style_name]
    font = FONTS[font_name]["body"]
    google_font_imports = "".join(f"@import url('{url}');" for url in FONT_IMPORTS.values())
    st.markdown(f"<style>{google_font_imports} @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0'); .visual-lab-sample {{ font-family: {font}; }}</style>", unsafe_allow_html=True)

    preview_cols = st.columns(3)
    for column, (name, candidate) in zip(preview_cols, THEMES.items()):
        selected = name == style_name
        column.markdown(
            f'<div style="border:1px solid {candidate["grid"]};border-radius:10px;padding:10px;background:{candidate["panel"]};color:{candidate["text"]};outline:{"2px solid #38BDF8" if selected else "none"};"><div style="font-weight:700">{name}</div><div style="display:flex;gap:6px;margin-top:8px">' + "".join(f'<span style="display:inline-block;width:22px;height:8px;border-radius:8px;background:{color}"></span>' for color in candidate["colors"][:5]) + '</div><small style="color:' + candidate["muted"] + '">Jerarquía · contraste · acentos</small></div>',
            unsafe_allow_html=True,
        )
    font_cols = st.columns(3)
    for column, (name, candidate) in zip(font_cols, FONTS.items()):
        column.markdown(f'<div class="visual-lab-sample" style="padding:8px 2px;font-family:{candidate["body"]};"><small>{name}</small><div style="font-family:{candidate["heading"]};font-size:19px;font-weight:700">{candidate["sample"]}</div></div>', unsafe_allow_html=True)
    icon_cols = st.columns(3)
    icon_names = ("Bicicleta", "Tendencia", "Recuperación")
    icon_colors = (theme["colors"][0], theme["colors"][2], theme["colors"][4])
    for column, icon_name, icon_color in zip(icon_cols, icon_names, icon_colors):
        icon = _icon_preview(icon_set, icon_name, icon_color)
        if icon_set == "Material Symbols outlined":
            content = f'<span class="material-symbols-outlined" style="font-size:25px;color:{icon_color}">{icon}</span>'
        else:
            content = icon
        column.markdown(f'<div style="display:flex;align-items:center;gap:10px;padding:6px 2px">{content}<span>{icon_name}</span></div>', unsafe_allow_html=True)

    sections = ["Forma", "Ciclismo", "Actividades", "Salud", "Planificación"]
    graph_names = {
        "Forma": ["Evolución de la forma", "Carga semanal de las sesiones", "Ramp rate"],
        "Ciclismo": ["Curva de potencia", "Volumen semanal", "Potencia media y normalizada", "Velocidad y FC", "Reparto por deporte · distancia", "Horas de rodillo y exterior", "Zonas de frecuencia cardiaca · 5 zonas LTHR", "Zonas de potencia · Coggan 7 zonas"],
        "Actividades": ["Actividad frente al periodo", "Potencia media por salida", "Velocidad media por salida", "Desnivel por salida", "Perfil de altitud", "Velocidad durante la actividad", "Potencia durante la actividad", "Curva de potencia de la actividad", "Zonas FC de la actividad", "Zonas de potencia de la actividad"],
        "Salud": ["Sueño", "FC en reposo y HRV", "Body Battery"],
        "Planificación": ["Progreso hacia el objetivo · distancia", "Progreso hacia el objetivo · desnivel", "Seguimiento de planificación por semana"],
    }
    section_col, graph_col = st.columns([1, 2])
    with section_col:
        selected_section = st.selectbox("Vista", sections, index=0, key="visual_lab_section_v2")
    with graph_col:
        graph_title = st.selectbox("Gráfico", graph_names[selected_section], index=0, key=f"visual_lab_graph_v2_{selected_section}")

    selected_activity = None
    if selected_section == "Actividades":
        activity_options = data.get("filtered_activities", pd.DataFrame())
        if not activity_options.empty and "start" in activity_options:
            activity_options = activity_options.sort_values("start", ascending=False).copy()
            activity_labels = {}
            for _, row in activity_options.iterrows():
                stamp = pd.to_datetime(row.get("start"), errors="coerce")
                label = f"{stamp:%d/%m/%Y %H:%M} · {row.get('sport', 'Actividad')} · {row.get('activity_name') or 'Sin nombre'} · {row.get('activity_id')}"
                activity_labels[label] = str(row.get("activity_id"))
            selected_label = st.selectbox("Actividad", list(activity_labels), key="visual_lab_activity_v2")
            activity_match = activity_options.loc[activity_options["activity_id"].astype(str) == activity_labels[selected_label]]
            selected_activity = activity_match.iloc[0] if not activity_match.empty else None
            if not data.get("intervals_configured", False):
                st.info("La comparativa y la curva de potencia resumen usan datos locales. Los perfiles segundo a segundo requieren acceso a streams de intervals.icu.")
        else:
            st.info("No hay actividades en el periodo y foco seleccionados.")

    graph_keys = {
        "Evolución de la forma": "forma_evolucion",
        "Carga semanal de las sesiones": "forma_carga_semanal",
        "Ramp rate": "forma_ramp_rate",
        "Curva de potencia": "ciclismo_curva_potencia",
        "Volumen semanal": "ciclismo_volumen_semanal",
        "Potencia media y normalizada": "ciclismo_potencia_semanal",
        "Velocidad y FC": "ciclismo_velocidad_fc",
        "Reparto por deporte · distancia": "ciclismo_reparto_deporte",
        "Horas de rodillo y exterior": "ciclismo_rodillo_exterior",
        "Zonas de frecuencia cardiaca · 5 zonas LTHR": "ciclismo_zonas_hr",
        "Zonas de potencia · Coggan 7 zonas": "ciclismo_zonas_power",
        "Actividad frente al periodo": "actividad_contexto",
        "Potencia media por salida": "actividad_potencia_resumen",
        "Velocidad media por salida": "actividad_velocidad_resumen",
        "Desnivel por salida": "actividad_desnivel_resumen",
        "Perfil de altitud": "actividad_perfil_altitud",
        "Velocidad durante la actividad": "actividad_velocidad",
        "Potencia durante la actividad": "actividad_potencia_tiempo",
        "Curva de potencia de la actividad": "actividad_curva_potencia",
        "Zonas FC de la actividad": "actividad_zonas_hr",
        "Zonas de potencia de la actividad": "actividad_zonas_power",
        "Sueño": "salud_sueno",
        "FC en reposo y HRV": "salud_fc_hrv",
        "Body Battery": "salud_body_battery",
        "Progreso hacia el objetivo · distancia": "plan_objetivo_distancia",
        "Progreso hacia el objetivo · desnivel": "plan_objetivo_desnivel",
        "Seguimiento de planificación por semana": "plan_seguimiento_semanal",
    }
    load_streams_for = {"actividad_perfil_altitud", "actividad_velocidad", "actividad_potencia_tiempo", "actividad_curva_potencia"}
    local_data = {
        **data,
        "selected_activity": selected_activity,
        "load_activity_streams": graph_keys[graph_title] in load_streams_for,
    }
    if graph_keys[graph_title] == "ciclismo_volumen_semanal":
        local_data["volume_mode"] = st.segmented_control("Métrica de volumen", ["Horas", "Distancia"], default="Horas", key="visual_lab_volume_mode", label_visibility="collapsed")
    catalog = build_catalog(local_data)
    selected_spec = next(spec for spec in catalog if spec["key"] == graph_keys[graph_title])
    st.subheader(selected_spec["title"])
    st.caption(selected_spec["description"])
    if selected_spec["key"] == "ciclismo_volumen_semanal":
        st.caption(f"Métrica comparada: {selected_spec['unit']} · usa el selector global de periodo, fuente y foco.")
    if selected_spec["key"] in load_streams_for:
        stream_error = selected_spec.get("stream_error")
        if stream_error:
            st.caption(f"No se pudieron cargar los perfiles de esta actividad: {stream_error}")
        elif not selected_spec["data"].empty:
            st.caption("Streams de la actividad seleccionada; puntos muestreados para que el gráfico siga respondiendo con fluidez.")

    representation_options = _representation_options(selected_spec)
    if representation_options:
        selected_spec = dict(selected_spec)
        selected_spec["display_type"] = st.selectbox(
            "Tipo de gráfico",
            representation_options,
            key=f"visual_lab_representation_{selected_spec['key']}",
            help="La misma representación se aplica a Plotly, Altair y ECharts para comparar las bibliotecas en igualdad de condiciones.",
        )
        if selected_spec["display_type"] == "Dona del periodo":
            st.caption("La dona agrega las semanas y muestra la proporción acumulada por tipo de actividad; las opciones de líneas y áreas mantienen la evolución semanal.")

    st.markdown("**Representación y biblioteca**")
    tabs = st.tabs(["Plotly", "Altair / Vega-Lite", "Apache ECharts"])
    for tab, library in zip(tabs, ("Plotly", "Altair / Vega-Lite", "Apache ECharts")):
        with tab:
            representation_label = selected_spec.get("display_type") or selected_spec["representations"].get(library, "Interacción nativa")
            st.caption(f"{representation_label} · estilo: {style_name}")
            st.session_state["visual_lab_renderer"] = library
            _chart_renderer(selected_spec, library, theme, font)
    st.caption("Los tres renderers reciben la misma serie de valores. La galería no guarda preferencias ni modifica las vistas de producción.")
