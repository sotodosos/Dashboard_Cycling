"""Componentes visuales compartidos del dashboard."""

from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from . import analytics as an

CHART_HEIGHT = 360
PALETTE = an.APP_PALETTE


def apply_theme() -> None:
    """CSS del dashboard. Se llama una vez al principio de la app."""
    P = PALETTE
    st.markdown(
        f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
    html, body, [class*="css"], button, input, textarea, select {{
        font-family: 'DM Sans', 'Segoe UI', sans-serif;
    }}
    .stApp {{
        background: {P["background"]};
        color: {P["text"]};
    }}
    section[data-testid="stSidebar"] {{
        background: #0F172A;
        border-right: 1px solid #273244;
    }}
    div[data-testid="stMetric"] {{
        background: #192331;
        border: 1px solid #2B3748;
        border-radius: 10px;
        padding: 10px 14px;
        box-shadow: none;
    }}
    div[data-testid="stMetricLabel"] p {{
        color: {P["muted"]};
        font-weight: 600;
    }}
    div[data-testid="stPlotlyChart"] {{
        background: transparent;
        border: 0;
        border-radius: 0;
        padding: 2px 0;
        box-shadow: none;
    }}
    .stTabs [data-baseweb="tab-list"] {{
        gap: 6px;
        background: #151E2B;
        border-radius: 10px;
        padding: 4px;
        border: 1px solid #273244;
    }}
    .stTabs [data-baseweb="tab"] {{
        border-radius: 10px;
        padding: 6px 14px;
    }}
    .stTabs [aria-selected="true"] {{
        background: #263348;
        color: {P["primary"]};
        box-shadow: none;
    }}
    h1, h2, h3 {{
        color: {P["text"]};
        font-family: 'Space Grotesk', 'Segoe UI', sans-serif;
        font-weight: 600;
    }}
    [data-testid="stCaptionContainer"], .stMarkdown small {{ color: {P["muted"]}; }}
    a {{ color: #7DD3FC; }}
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div,
    textarea, input {{
        background-color: {P["panel"]};
        border-color: {P["border"]};
        color: {P["text"]};
    }}
    div[data-testid="stDataFrame"] {{ border: 0; }}
    .soft-note {{
        background: #192331;
        border-left: 3px solid {P["primary"]};
        border-radius: 6px;
        padding: 8px 12px;
        color: {P["muted"]};
    }}
    </style>
    """,
        unsafe_allow_html=True,
    )


def style_figure(fig: go.Figure, height: int = CHART_HEIGHT) -> go.Figure:
    P = PALETTE
    fig.update_layout(
        height=height,
        margin=dict(l=12, r=12, t=42, b=12),
        hovermode="x unified",
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=P["panel"],
        font=dict(
            color=P["text"], family="DM Sans, Segoe UI, sans-serif", size=13
        ),
        colorway=[
            P["ctl"],
            P["atl"],
            P["tsb"],
            P["sleep"],
            P["resting_hr"],
            P["load"],
        ],
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0,
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    fig.update_xaxes(
        gridcolor=P["border"],
        zeroline=False,
        linecolor="#526174",
        tickfont=dict(color=P["muted"]),
        title=dict(font=dict(color=P["muted"])),
    )
    fig.update_yaxes(
        gridcolor=P["border"],
        zeroline=False,
        linecolor="#526174",
        tickfont=dict(color=P["muted"]),
        title=dict(font=dict(color=P["muted"])),
    )
    return fig


def empty_figure(message: str, height: int = CHART_HEIGHT) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=14, color=PALETTE["muted"]),
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style_figure(fig, height=height)


def metric_row(items: list[tuple[str, str, str | None]]) -> None:
    columns = st.columns(len(items))
    for column, (label, value, help_text) in zip(columns, items):
        with column:
            st.metric(label, value, help=help_text, border=True)


def fmt_date(value: object) -> str:
    if value is None or pd.isna(value):
        return "–"
    return pd.to_datetime(value).strftime("%d/%m/%Y")


def fmt(value: float | None, decimals: int = 0) -> str:
    return an.format_number(value, decimals)


def fmt_signed(value: float | None, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "–"
    return f"{float(value):+.{decimals}f}".replace(".", ",")


def form_status(tsb: float | None) -> str:
    if tsb is None or pd.isna(tsb):
        return "Sin datos de forma"
    if tsb < -10:
        return "Fatiga reciente por encima de la forma"
    if tsb <= 5:
        return "Carga reciente y forma en equilibrio"
    return "Forma por encima de la fatiga reciente"


def zone_frame(
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


def zone_bar(
    zone_df: pd.DataFrame,
    kind: str,
    settings_row: pd.Series | None,
    height: int = 340,
    *,
    indoor: bool = False,
) -> go.Figure:
    zone_df = zone_frame(zone_df, settings_row, kind, indoor=indoor)
    colors = (
        an.HR_ZONE_COLORS if kind == "hr" else an.POWER_ZONE_COLORS
    )
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
    return style_figure(fig, height=height)


def wellness_figure(
    wellness: pd.DataFrame,
    daily: pd.DataFrame,
    start: date,
    end: date,
    visible_metrics: list[str] | None = None,
) -> go.Figure:
    """Gráfico de portada: carga, forma, sueño y FC en reposo."""
    P = PALETTE
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
                fillcolor="rgba(56, 189, 248, 0.14)",
            ),
            row=2,
            col=1,
        )

    sleep_source = wellness if not wellness.empty else daily
    if (
        "Sueño" in visible
        and not sleep_source.empty
        and "sleep_h" in sleep_source.columns
    ):
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
    if (
        "FC reposo" in visible
        and not rhr_source.empty
        and "resting_hr" in rhr_source.columns
    ):
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
    fig.update_yaxes(
        title_text="TSB", row=2, col=1, zeroline=True, zerolinecolor="#526174"
    )
    fig.update_yaxes(title_text="horas", row=3, col=1)
    fig.update_yaxes(title_text="ppm", row=4, col=1)
    fig.update_xaxes(range=[start, end], tickformat="%d %b %y", row=4, col=1)
    fig.update_annotations(font=dict(size=12, color=P["muted"]))
    return style_figure(fig, height=620)
