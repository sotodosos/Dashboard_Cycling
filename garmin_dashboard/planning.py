"""Lectura, escritura y comparación del plan de entrenamiento.

El plan se guarda como una lista de sesiones en JSON. Cada sesión puede
incluir ``bloques`` con objetivos estructurados (duración, potencia y FC),
de forma que el resumen para otra IA no dependa de texto libre.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from . import analytics as an
from . import streams as st

BLOCK_FIELDS = (
    "nombre",
    "repeticiones",
    "duracion_min",
    "potencia_min_pct",
    "potencia_max_pct",
    "fc_min",
    "fc_max",
    "cadencia",
    "notas",
)

BLOCK_COLUMNS = {
    "Nombre": "nombre",
    "Repeticiones": "repeticiones",
    "Duración (min)": "duracion_min",
    "Potencia desde (%)": "potencia_min_pct",
    "Potencia hasta (%)": "potencia_max_pct",
    "FC desde (ppm)": "fc_min",
    "FC hasta (ppm)": "fc_max",
    "Cadencia (rpm)": "cadencia",
    "Notas": "notas",
}

PLAN_FIELDS = (
    ("fecha", "Fecha prevista"),
    ("modalidad", "Modalidad"),
    ("duracion", "Duración prevista"),
    ("estructura", "Estructura"),
    ("objetivo", "Objetivo"),
    ("potencia", "Potencia objetivo"),
    ("pulso", "Pulso / esfuerzo"),
    ("observaciones", "Observaciones"),
)


# --------------------------------------------------------------------------- #
# Lectura y escritura
# --------------------------------------------------------------------------- #


def load_plan(path: str | Path) -> tuple[list[dict], str | None]:
    """Carga el plan y devuelve ``(sesiones, error_legible)``."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        items = json.loads(raw)
    except OSError as exc:
        return [], f"No se pudo leer el fichero: {exc}"
    except json.JSONDecodeError as exc:
        return [], f"El JSON no es válido: {exc}"
    if not isinstance(items, list):
        return [], "El contenido no es una lista de sesiones."
    return [item for item in items if isinstance(item, dict)], None


def save_plan(path: str | Path, items: Iterable[dict]) -> None:
    """Guarda el plan de forma atómica para no dejarlo a medias."""
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    payload = json.dumps(list(items), ensure_ascii=False, indent=2) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, target)


# --------------------------------------------------------------------------- #
# Bloques estructurados
# --------------------------------------------------------------------------- #


def _to_float(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return float(number)


def normalize_blocks(raw: Any) -> list[dict]:
    """Normaliza ``bloques`` para que el JSON sea predecible."""
    if not isinstance(raw, list):
        return []
    blocks = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        block = {
            "nombre": str(item.get("nombre") or "").strip(),
            "notas": str(item.get("notas") or "").strip(),
        }
        for field in (
            "repeticiones",
            "duracion_min",
            "potencia_min_pct",
            "potencia_max_pct",
            "fc_min",
            "fc_max",
            "cadencia",
        ):
            block[field] = _to_float(item.get(field))
        if any(
            value not in (None, "")
            for key, value in block.items()
            if key not in ("nombre", "notas")
        ) or block["nombre"] or block["notas"]:
            blocks.append(block)
    return blocks


def blocks_frame(blocks: list[dict] | None) -> pd.DataFrame:
    """Tabla editable de bloques (columnas en español)."""
    rows = []
    for block in normalize_blocks(blocks):
        rows.append(
            {
                label: block.get(field)
                for label, field in BLOCK_COLUMNS.items()
            }
        )
    return pd.DataFrame(rows, columns=list(BLOCK_COLUMNS))


def blocks_from_records(
    records: list[dict],
) -> tuple[list[dict], int]:
    """Convierte la tabla editada en bloques válidos y cuenta los inválidos."""
    blocks = []
    invalid = 0
    for record in records:
        block = {
            field: record.get(label)
            for label, field in BLOCK_COLUMNS.items()
        }
        empty = all(
            value in (None, "")
            or (isinstance(value, str) and not value.strip())
            or (isinstance(value, float) and pd.isna(value))
            for value in block.values()
        )
        if empty:
            continue

        cleaned = {
            "nombre": str(block.get("nombre") or "").strip(),
            "notas": str(block.get("notas") or "").strip(),
        }
        for field in (
            "repeticiones",
            "duracion_min",
            "potencia_min_pct",
            "potencia_max_pct",
            "fc_min",
            "fc_max",
            "cadencia",
        ):
            cleaned[field] = _to_float(block.get(field))

        repetitions = cleaned["repeticiones"]
        duration = cleaned["duracion_min"]
        power_low = cleaned["potencia_min_pct"]
        power_high = cleaned["potencia_max_pct"]
        hr_low = cleaned["fc_min"]
        hr_high = cleaned["fc_max"]

        row_invalid = (
            (repetitions is not None and (repetitions < 1 or repetitions > 99))
            or (duration is not None and (duration <= 0 or duration > 600))
            or (
                power_low is not None
                and power_high is not None
                and power_low > power_high
            )
            or (
                power_low is not None
                and not 0 <= power_low <= 300
            )
            or (
                power_high is not None
                and not 0 <= power_high <= 300
            )
            or (hr_low is not None and hr_high is not None and hr_low > hr_high)
            or (hr_low is not None and not 30 <= hr_low <= 250)
            or (hr_high is not None and not 30 <= hr_high <= 250)
            or (
                cleaned["cadencia"] is not None
                and not 30 <= cleaned["cadencia"] <= 250
            )
        )
        if row_invalid:
            invalid += 1
            continue
        if repetitions is not None:
            cleaned["repeticiones"] = int(round(repetitions))
        blocks.append(cleaned)
    return blocks, invalid


def _power_target_text(
    low: float | None, high: float | None, ftp: float | None
) -> str:
    if low is None and high is None:
        return ""
    if low is None:
        percent = f"≤{high:g} % FTP"
        watts = f"≤{round(high * ftp / 100)} W" if ftp else ""
    elif high is None or low == high:
        percent = f"{low:g} % FTP"
        watts = f"{round(low * ftp / 100)} W" if ftp else ""
    else:
        percent = f"{low:g}–{high:g} % FTP"
        watts = (
            f"{round(low * ftp / 100)}–{round(high * ftp / 100)} W"
            if ftp
            else ""
        )
    return percent + (f" ({watts})" if watts else "")


def _hr_target_text(low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return ""
    if low is None:
        return f"≤{high:g} ppm"
    if high is None or low == high:
        return f"{low:g} ppm"
    return f"{low:g}–{high:g} ppm"


def blocks_text(
    blocks: list[dict] | None,
    *,
    ftp: float | None = None,
    lthr: float | None = None,
) -> list[str]:
    """Líneas legibles de los bloques, con conversión a W/ppm si hay FTP/LTHR."""
    lines = []
    for index, block in enumerate(normalize_blocks(blocks), start=1):
        repetitions = block.get("repeticiones")
        duration = block.get("duracion_min")
        pieces = [f"Bloque {index}"]
        if block.get("nombre"):
            pieces.append(str(block["nombre"]))
        if repetitions:
            pieces.append(f"×{int(repetitions)}")
        if duration:
            pieces.append(f"{duration:g} min")
        power = _power_target_text(
            block.get("potencia_min_pct"),
            block.get("potencia_max_pct"),
            ftp,
        )
        if power:
            pieces.append(power)
        hr = _hr_target_text(block.get("fc_min"), block.get("fc_max"))
        if hr:
            pieces.append(hr if lthr is None else f"{hr} (LTHR {lthr:g})")
        if block.get("cadencia"):
            pieces.append(f"{block['cadencia']:g} rpm")
        if block.get("notas"):
            pieces.append(str(block["notas"]))
        lines.append(" · ".join(pieces))
    return lines


# --------------------------------------------------------------------------- #
# Plan y editor
# --------------------------------------------------------------------------- #


def editor_rows(
    items: list[dict], activity_id_to_label: dict[str, str]
) -> list[dict]:
    rows = []
    for item in items:
        planned_date = pd.to_datetime(item.get("fecha"), errors="coerce")
        rows.append(
            {
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
                "Actividad asociada": activity_id_to_label.get(
                    str(item.get("activity_link_id", "")), ""
                ),
            }
        )
    return rows


EDITOR_COLUMNS = [
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

FIELD_MAP = {
    "Semana": "semana",
    "Sesión": "sesion",
    "Modalidad": "modalidad",
    "Duración": "duracion",
    "Estructura": "estructura",
    "Objetivo": "objetivo",
    "Potencia objetivo": "potencia",
    "Pulso / esfuerzo": "pulso",
    "Observaciones": "observaciones",
}


def items_from_editor(
    records: list[dict], activity_labels: dict[str, str]
) -> tuple[list[dict], int]:
    """Convierte la tabla principal en sesiones; omite filas sin fecha."""
    items = []
    invalid = 0
    for record in records:
        planned_date = pd.to_datetime(record.get("Fecha"), errors="coerce")
        if pd.isna(planned_date):
            invalid += 1
            continue
        item = {
            target: str(record.get(column, "") or "")
            for column, target in FIELD_MAP.items()
        }
        item["fecha"] = planned_date.date().isoformat()
        selected_activity = record.get("Actividad asociada") or ""
        item["activity_link_id"] = activity_labels.get(selected_activity, "")
        items.append(item)
    return items, invalid


def plan_field_lines(plan_item: dict) -> list[str]:
    """Campos de una sesión listos para el resumen textual."""
    lines = []
    known = set(FIELD_MAP.values()) | {
        "fecha", "semana", "sesion", "activity_link_id"
    }
    known |= {"bloques"}
    for key, label in PLAN_FIELDS:
        value = plan_item.get(key)
        if value in (None, ""):
            continue
        if key == "fecha":
            parsed = pd.to_datetime(value, errors="coerce")
            value = parsed.strftime("%d/%m/%Y") if pd.notna(parsed) else value
        lines.append(f"Plan · {label}: {value}")
    for key, value in plan_item.items():
        if key not in known and value not in (None, ""):
            lines.append(f"Plan · {key}: {value}")
    return lines


def find_linked_plan(
    items: list[dict], activity_ids: set[str]
) -> dict | None:
    for item in items:
        link = str(item.get("activity_link_id", "")).strip()
        if link and link in activity_ids:
            return item
    return None


# --------------------------------------------------------------------------- #
# Comparación planificado vs real
# --------------------------------------------------------------------------- #


def _number_value(value: str) -> float:
    return float(value.replace(",", "."))


def _parse_duration_target(value: object) -> tuple[float, float] | None:
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:[-–]\s*(\d+(?:[.,]\d+)?))?\s*(min|m|h)\b",
        str(value or "").casefold(),
    )
    if not match:
        return None
    factor = 60.0 if match.group(3) == "h" else 1.0
    low = _number_value(match.group(1)) * factor
    high = _number_value(match.group(2)) * factor if match.group(2) else low
    return low, high


def _parse_planned_range(
    value: str, unit: str, *, maximum_word: str = "máximo"
) -> tuple[float, float, bool] | None:
    number = r"(\d+(?:[.,]\d+)?)"
    unit_pattern = re.escape(unit)
    range_match = re.search(
        rf"{number}\s*[-–]\s*{number}\s*{unit_pattern}\b",
        value,
        flags=re.IGNORECASE,
    )
    single_match = range_match or re.search(
        rf"{number}\s*{unit_pattern}\b", value, flags=re.IGNORECASE
    )
    if not single_match:
        return None
    if range_match:
        low = _number_value(range_match.group(1))
        high = _number_value(range_match.group(2))
    else:
        low = high = _number_value(single_match.group(1))
    nearby = value[
        max(0, single_match.start() - 28) : single_match.end() + 42
    ].casefold()
    is_maximum = maximum_word in nearby or "hasta" in nearby
    if is_maximum:
        return 0.0, high, True
    return low, high, False


def _fmt(value: float, decimals: int = 0) -> str:
    return an.format_number(value, decimals)


def _format_range(low: float, high: float, unit: str) -> str:
    if low == high:
        return f"{_fmt(low, 1 if low % 1 else 0)} {unit}"
    return (
        f"{_fmt(low, 1 if low % 1 else 0)}–"
        f"{_fmt(high, 1 if high % 1 else 0)} {unit}"
    )


def _compare_planned_value(
    actual: float | None,
    target: tuple[float, float, bool] | tuple[float, float] | None,
    unit: str,
) -> str:
    if actual is None or pd.isna(actual):
        return "Sin dato real"
    if target is None:
        return "Sin objetivo especificado"
    low, high = target[0], target[1]
    is_maximum = len(target) == 3 and bool(target[2])
    if is_maximum:
        if actual <= high:
            return "Dentro del máximo"
        return f"+{_fmt(actual - high, 1)} {unit} sobre el máximo"
    if actual < low:
        return f"−{_fmt(low - actual, 1)} {unit} por debajo"
    if actual > high:
        return f"+{_fmt(actual - high, 1)} {unit} por encima"
    if low == high:
        return "En objetivo"
    return "Dentro del rango"


def comparison_rows(
    plan_item: dict, activity: pd.Series | dict, streams: list[dict]
) -> list[dict[str, str]]:
    """Compara duración, distancia, desnivel y potencia con el plan."""
    plan_text = " ".join(
        str(plan_item.get(field, "") or "")
        for field in ("sesion", "estructura", "objetivo", "observaciones")
    )
    duration_target = _parse_duration_target(plan_item.get("duracion"))
    distance_target = _parse_planned_range(plan_text, "km")
    elevation_target = _parse_planned_range(plan_text, "m")

    actual_duration = pd.to_numeric(
        pd.Series([activity.get("duration_min")]), errors="coerce"
    ).iloc[0]
    actual_distance = pd.to_numeric(
        pd.Series([activity.get("distance_km")]), errors="coerce"
    ).iloc[0]
    actual_elevation = pd.to_numeric(
        pd.Series([activity.get("elevation_gain_m")]), errors="coerce"
    ).iloc[0]

    duration_display = (
        an.format_duration(actual_duration)
        if pd.notna(actual_duration)
        else "Sin dato real"
    )
    if duration_target:
        duration_plan = _format_range(*duration_target, "min")
        duration_comparison = _compare_planned_value(
            float(actual_duration) if pd.notna(actual_duration) else None,
            duration_target,
            "min",
        )
    else:
        duration_plan = str(plan_item.get("duracion") or "Sin objetivo")
        duration_comparison = "Sin comparación"

    if distance_target:
        distance_plan = (
            f"≤{_fmt(distance_target[1], 1)} km"
            if distance_target[2]
            else _format_range(
                distance_target[0], distance_target[1], "km"
            )
        )
    else:
        distance_plan = "Sin objetivo especificado"
    distance_comparison = _compare_planned_value(
        float(actual_distance) if pd.notna(actual_distance) else None,
        distance_target,
        "km",
    )

    if elevation_target:
        elevation_plan = (
            f"≤{_fmt(elevation_target[1])} m+"
            if elevation_target[2]
            else _format_range(
                elevation_target[0], elevation_target[1], "m+"
            )
        )
    else:
        elevation_plan = "Sin objetivo especificado"
    elevation_comparison = _compare_planned_value(
        float(actual_elevation) if pd.notna(actual_elevation) else None,
        elevation_target,
        "m",
    )

    power_text = str(plan_item.get("potencia") or "")
    power_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:[-–]\s*(\d+(?:[.,]\d+)?))?\s*W\b",
        power_text,
        flags=re.IGNORECASE,
    )
    power_is_rodillo_only = (
        "rodillo" in power_text.casefold()
        and "carretera" in power_text.casefold()
        and not bool(activity.get("indoor"))
    )
    if power_match and not power_is_rodillo_only:
        power_low = _number_value(power_match.group(1))
        power_high = (
            _number_value(power_match.group(2))
            if power_match.group(2)
            else power_low
        )
        power_plan = _format_range(power_low, power_high, "W")
        target_seconds, observed_seconds = st.power_range_time(
            streams, power_low, power_high
        )
        watts_values = pd.to_numeric(
            pd.Series(st.stream_values(streams, "watts")), errors="coerce"
        )
        if watts_values.notna().any():
            stream_average = float(watts_values.mean())
            power_actual = f"{_fmt(stream_average)} W de media global"
            if observed_seconds > 0:
                target_percent = target_seconds / observed_seconds * 100
                power_actual += (
                    f" · {_fmt(target_seconds / 60)} min en rango "
                    f"({_fmt(target_percent)}%)"
                )
                power_comparison = (
                    f"{_fmt(target_percent)}% del tiempo muestreado en rango"
                )
            else:
                power_comparison = (
                    "Sin muestras temporales válidas para medir el tiempo en rango"
                )
        else:
            power_actual = "Sin muestras de potencia"
            power_comparison = "Sin datos para comparar"
    else:
        power_plan = (
            "Sin objetivo de potencia para esta modalidad"
            if power_is_rodillo_only
            or "no disponible" in power_text.casefold()
            else "Sin objetivo numérico de potencia"
        )
        actual_avg_power = pd.to_numeric(
            pd.Series([activity.get("avg_power_w")]), errors="coerce"
        ).iloc[0]
        power_actual = (
            f"{_fmt(actual_avg_power)} W de media"
            if pd.notna(actual_avg_power)
            else "Sin datos de potencia"
        )
        power_comparison = (
            "No aplica"
            if power_is_rodillo_only
            or "no disponible" in power_text.casefold()
            else "Sin comparación"
        )

    return [
        {
            "Métrica": "Duración",
            "Planificado": duration_plan,
            "Real": duration_display,
            "Diferencia": duration_comparison,
        },
        {
            "Métrica": "Distancia",
            "Planificado": distance_plan,
            "Real": (
                f"{_fmt(actual_distance, 1)} km"
                if pd.notna(actual_distance)
                else "Sin dato real"
            ),
            "Diferencia": distance_comparison,
        },
        {
            "Métrica": "Desnivel",
            "Planificado": elevation_plan,
            "Real": (
                f"{_fmt(actual_elevation)} m+"
                if pd.notna(actual_elevation)
                else "Sin dato real"
            ),
            "Diferencia": elevation_comparison,
        },
        {
            "Métrica": "Potencia",
            "Planificado": power_plan,
            "Real": power_actual,
            "Diferencia": power_comparison,
        },
    ]
