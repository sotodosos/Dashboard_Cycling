"""Resumen estructurado y textual de una actividad para otra IA."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import pandas as pd

from . import planning
from . import streams as st

FEEL_LABELS = {
    1: "Muy buenas",
    2: "Buenas",
    3: "Normales",
    4: "Malas",
    5: "Muy malas",
}


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _fmt(value: object, decimals: int = 0) -> str:
    number = _number(value)
    if number is None:
        return "–"
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _duration(minutes: float | None) -> str:
    number = _number(minutes)
    if number is None:
        return "–"
    total = int(round(number))
    hours, mins = divmod(total, 60)
    if hours:
        return f"{hours} h {mins:02d} min"
    return f"{mins} min"


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if value is None:
        return None
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return number if math.isfinite(number) else None


def metric_rows(metrics: dict) -> list[dict[str, str]]:
    """Filas de la tabla «Resumen de la sesión» (sin índices frágiles)."""
    elapsed = _number(metrics.get("elapsed_s"))
    moving = _number(metrics.get("moving_s"))
    moving_hours = moving / 3600 if moving else 0
    fluid = _number(metrics.get("fluid_ml"))
    fluid_estimated = _number(metrics.get("estimated_fluid_ml"))
    carbs = _number(metrics.get("carbs_g"))
    carbs_used = _number(metrics.get("carbs_used_g"))
    rpe = _number(metrics.get("rpe"))
    feel = _number(metrics.get("feel"))

    fluid_text = "No registrado"
    if fluid is not None or fluid_estimated is not None:
        fluid_text = (
            f"{_fmt(fluid / 1000 if fluid is not None else None, 2)} / "
            f"{_fmt(fluid_estimated / 1000 if fluid_estimated is not None else None, 2)} L"
        )
    fluid_rate = "No disponible"
    if moving_hours and (fluid is not None or fluid_estimated is not None):
        fluid_rate = (
            f"{_fmt(fluid / moving_hours if fluid is not None else None)} / "
            f"{_fmt(fluid_estimated / moving_hours if fluid_estimated is not None else None)} ml/h"
        )
    carbs_text = "No registrado"
    if carbs is not None:
        carbs_text = f"{_fmt(carbs)} g"
        if moving_hours:
            carbs_text += f" · {_fmt(carbs / moving_hours)} g/h"
    feel_text = "No registrado"
    if feel is not None:
        label = FEEL_LABELS.get(int(feel), "") if float(feel).is_integer() else ""
        feel_text = f"{int(feel)}/5 · {label}" if label else f"{int(feel)}/5"

    rows = [
        {
            "Métrica": "Tiempo total",
            "Valor": _duration(elapsed / 60) if elapsed is not None else "No registrado",
        },
        {
            "Métrica": "Tiempo en movimiento",
            "Valor": _duration(moving / 60) if moving is not None else "No registrado",
        },
        {"Métrica": "Distancia", "Valor": f"{_fmt(metrics.get('distance_km'), 2)} km"},
        {
            "Métrica": "VAM",
            "Valor": (
                f"{_fmt(metrics.get('vam_m_h'))} m/h"
                if _number(metrics.get("vam_m_h")) is not None
                else "No disponible"
            ),
        },
        {
            "Métrica": "Potencia media / normalizada",
            "Valor": (
                f"{_fmt(metrics.get('avg_power_w'))} / "
                f"{_fmt(metrics.get('weighted_avg_power_w'))} W"
            ),
        },
        {
            "Métrica": "Potencia máxima",
            "Valor": (
                f"{_fmt(metrics.get('max_power_w'))} W"
                if _number(metrics.get("max_power_w")) is not None
                else "No registrada"
            ),
        },
        {
            "Métrica": "Cadencia media",
            "Valor": f"{_fmt(metrics.get('avg_cadence'))} rpm",
        },
        {
            "Métrica": "Desnivel acumulado",
            "Valor": f"{_fmt(metrics.get('elevation_gain_m'))} m",
        },
        {
            "Métrica": "FC media / máxima",
            "Valor": (
                f"{_fmt(metrics.get('avg_hr'))} / "
                f"{_fmt(metrics.get('max_hr'))} ppm"
            ),
        },
        {"Métrica": "Líquido ingerido / estimado", "Valor": fluid_text},
        {"Métrica": "Líquido por hora (ingerido / estimado)", "Valor": fluid_rate},
        {
            "Métrica": "Hidratos usados (estimados)",
            "Valor": f"{_fmt(carbs_used)} g" if carbs_used is not None else "No disponible",
        },
        {"Métrica": "Hidratos ingeridos", "Valor": carbs_text},
        {
            "Métrica": "RPE · intervals.icu",
            "Valor": f"{_fmt(rpe)}/10" if rpe is not None else "No registrado",
        },
        {"Métrica": "Sensaciones · intervals.icu", "Valor": feel_text},
    ]
    return rows


def _zone_list(zone_df: pd.DataFrame | None) -> list[dict]:
    if zone_df is None or zone_df.empty:
        return []
    frame = zone_df.copy()
    frame["minutes"] = pd.to_numeric(frame["minutes"], errors="coerce").fillna(0)
    total = float(frame["minutes"].sum())
    zones = []
    for _, row in frame.iterrows():
        minutes = float(row["minutes"])
        zones.append(
            {
                "zone": str(row.get("zone", "")),
                "label": str(row.get("label", "")),
                "range": str(row.get("rango") or row.get("range") or ""),
                "minutes": round(minutes, 1),
                "share_pct": round(minutes / total * 100, 1) if total else 0.0,
            }
        )
    return zones


def build_activity_report(
    *,
    activity: dict,
    metrics: dict,
    health: dict | None = None,
    zones_hr: pd.DataFrame | None,
    zones_power: pd.DataFrame | None,
    plan: dict | None = None,
    plan_comparison: list[dict] | None = None,
    intervals: list | None = None,
    streams_available: bool = False,
    streams_error: str | None = None,
    ftp: float | None = None,
    lthr: float | None = None,
) -> dict:
    """Diccionario completo y serializable de la sesión."""
    plan_data = None
    if plan is not None:
        plan_data = {
            "semana": plan.get("semana"),
            "sesion": plan.get("sesion"),
            "fecha": plan.get("fecha"),
            "modalidad": plan.get("modalidad"),
            "duracion": plan.get("duracion"),
            "estructura": plan.get("estructura"),
            "objetivo": plan.get("objetivo"),
            "potencia": plan.get("potencia"),
            "pulso": plan.get("pulso"),
            "observaciones": plan.get("observaciones"),
            "bloques": planning.normalize_blocks(plan.get("bloques")),
        }

    report = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "activity": activity,
        "metrics": metrics,
        "health": health or {},
        "zones": {
            "hr": _zone_list(zones_hr),
            "power": _zone_list(zones_power),
        },
        "plan": plan_data,
        "plan_comparison": plan_comparison or [],
        "intervals": intervals or [],
        "streams": {
            "available": bool(streams_available),
            "error": streams_error,
        },
        "references": {
            "ftp_w": ftp,
            "lthr_ppm": lthr,
        },
        "disclaimer": (
            "Resumen descriptivo de los datos registrados; no es consejo "
            "médico ni una prescripción de entrenamiento."
        ),
    }
    return _json_safe(report)


def report_text(report: dict) -> str:
    """Texto plano listo para copiar o descargar."""
    activity = report.get("activity") or {}
    metrics = report.get("metrics") or {}
    plan = report.get("plan")
    lines = [
        f"Actividad: {activity.get('name') or activity.get('sport') or 'Sin nombre'}",
        f"Fecha: {activity.get('start') or '–'}",
        f"Fuente: {activity.get('source') or '–'} · tipo: {activity.get('type') or '–'}"
        + (" · rodillo" if activity.get("indoor") else ""),
        f"Identificador: {activity.get('id') or '–'}",
    ]
    elapsed = _number(metrics.get("elapsed_s"))
    moving = _number(metrics.get("moving_s"))
    lines.append(
        f"Distancia: {_fmt(metrics.get('distance_km'), 2)} km | "
        f"Tiempo total: {_duration(elapsed / 60) if elapsed is not None else '–'} | "
        f"En movimiento: {_duration(moving / 60) if moving is not None else '–'}"
    )
    lines.append(
        f"VAM: {_fmt(metrics.get('vam_m_h'))} m/h | "
        f"Potencia media: {_fmt(metrics.get('avg_power_w'))} W | "
        f"Normalizada: {_fmt(metrics.get('weighted_avg_power_w'))} W | "
        f"Máxima: {_fmt(metrics.get('max_power_w'))} W"
    )
    lines.append(
        f"Cadencia: {_fmt(metrics.get('avg_cadence'))} rpm | "
        f"Desnivel: {_fmt(metrics.get('elevation_gain_m'))} m | "
        f"FC media/máxima: {_fmt(metrics.get('avg_hr'))}/"
        f"{_fmt(metrics.get('max_hr'))} ppm | "
        f"Calorías: {_fmt(metrics.get('calories'))} kcal"
    )
    health = report.get("health") or {}
    lines.append(
        "Salud del día: "
        f"sueño {_fmt(health.get('sleep_h'), 1)} h | "
        f"calidad del sueño {_fmt(health.get('sleep_score'))}/100 | "
        f"FC en reposo {_fmt(health.get('resting_hr'))} ppm | "
        f"HRV {_fmt(health.get('hrv'))} ms"
    )
    lines.append(
        "Media de salud de los 7 días hasta la actividad: "
        f"sueño {_fmt(health.get('sleep_h_7d_avg'), 1)} h "
        f"(n={health.get('sleep_h_7d_days', 0)}) | "
        f"calidad {_fmt(health.get('sleep_score_7d_avg'))}/100 "
        f"(n={health.get('sleep_score_7d_days', 0)}) | "
        f"FC reposo {_fmt(health.get('resting_hr_7d_avg'))} ppm "
        f"(n={health.get('resting_hr_7d_days', 0)}) | "
        f"HRV {_fmt(health.get('hrv_7d_avg'))} ms "
        f"(n={health.get('hrv_7d_days', 0)})"
    )
    fluid = _number(metrics.get("fluid_ml"))
    fluid_estimated = _number(metrics.get("estimated_fluid_ml"))
    moving_hours = moving / 3600 if moving else 0
    lines.append(
        "Líquido ingerido/estimado: "
        f"{_fmt(fluid / 1000 if fluid is not None else None, 2)} / "
        f"{_fmt(fluid_estimated / 1000 if fluid_estimated is not None else None, 2)} L"
        + (
            f" | Por hora: {_fmt(fluid / moving_hours if fluid is not None else None)} / "
            f"{_fmt(fluid_estimated / moving_hours if fluid_estimated is not None else None)} ml/h"
            if moving_hours
            else ""
        )
        + f" | Hidratos usados (estimados): {_fmt(metrics.get('carbs_used_g'))} g"
        + f" | Hidratos ingeridos: {_fmt(metrics.get('carbs_g'))} g"
    )
    feel = _number(metrics.get("feel"))
    lines.append(
        f"RPE intervals.icu: {_fmt(metrics.get('rpe'))}/10 | "
        "Sensaciones: "
        + (
            f"{int(feel)}/5 · {FEEL_LABELS.get(int(feel), '')}"
            if feel is not None and float(feel).is_integer()
            else "No registrado"
        )
    )

    if plan:
        lines.append(
            f"Planificación vinculada: semana {plan.get('semana') or 'sin indicar'} · "
            f"sesión {plan.get('sesion') or 'sin indicar'}."
        )
        lines.extend(planning.plan_field_lines(plan))
        blocks = planning.blocks_text(
            plan.get("bloques"),
            ftp=_number((report.get("references") or {}).get("ftp_w")),
            lthr=_number((report.get("references") or {}).get("lthr_ppm")),
        )
        if blocks:
            lines.append("Bloques estructurados del plan:")
            lines.extend(f"- {block}" for block in blocks)
    else:
        lines.append(
            "Planificación: no hay una sesión vinculada explícitamente a esta actividad."
        )

    comparisons = report.get("plan_comparison") or []
    if comparisons:
        lines.append("Comparación planificación vs actividad:")
        for comparison in comparisons:
            lines.append(
                f"{comparison.get('Métrica')}: planificado "
                f"{comparison.get('Planificado')} · real {comparison.get('Real')} · "
                f"{comparison.get('Diferencia')}"
            )

    intervals = report.get("intervals") or []
    if intervals:
        lines.append(
            "Intervalos disponibles: "
            + " | ".join(str(item) for item in intervals)
        )
    else:
        lines.append(
            "Intervalos detallados: no disponibles en los datos sincronizados."
        )

    for kind, label in (("hr", "FC"), ("power", "Potencia")):
        zones = [
            zone
            for zone in (report.get("zones") or {}).get(kind, [])
            if _number(zone.get("minutes")) and float(zone["minutes"]) > 0
        ]
        if zones:
            lines.append(
                label
                + ": "
                + "; ".join(
                    f"{zone.get('zone')} {_fmt(zone.get('minutes'), 1)} min "
                    f"({_fmt(zone.get('share_pct'), 1)}%)"
                    f"{' [' + zone['range'] + ']' if zone.get('range') else ''}"
                    for zone in zones
                )
            )
        else:
            lines.append(f"{label}: sin tiempos de zona disponibles.")

    stream_state = report.get("streams") or {}
    if stream_state.get("error"):
        lines.append(f"Streams: no disponibles ({stream_state['error']}).")
    elif stream_state.get("available"):
        lines.append("Streams: disponibles para esta sesión.")
    else:
        lines.append("Streams: no descargados.")

    lines.append(f"Generado: {report.get('generated_at') or '–'}")
    if report.get("disclaimer"):
        lines.append(str(report["disclaimer"]))
    return "\n".join(lines)


def report_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def report_filename(report: dict, suffix: str = ".txt") -> str:
    activity = report.get("activity") or {}
    start = str(activity.get("start_date") or "actividad").replace("/", "-")
    identifier = str(activity.get("id") or "sin_id").replace("/", "-")
    return f"resumen_{start}_{identifier}{suffix}"
