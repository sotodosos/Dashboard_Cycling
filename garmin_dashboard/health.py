"""Bandas de referencia para las métricas de salud.

No son diagnósticos ni objetivos médicos: sirven para comparar el dato de hoy
con una referencia general (sueño) o con la propia distribución reciente del
deportista (FC en reposo y HRV).
"""

from __future__ import annotations

import pandas as pd

SLEEP_TARGET_H = (7.0, 9.0)
RHR_MARGIN_PPM = 5.0
MIN_OBSERVATIONS = 7


def band_status(value: float | None, low: float | None, high: float | None) -> str | None:
    """``Dentro``, ``Por encima`` o ``Por debajo`` de una banda."""
    if value is None or pd.isna(value) or low is None or high is None:
        return None
    if value < low:
        return "Por debajo"
    if value > high:
        return "Por encima"
    return "Dentro"


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype=float)
    values = pd.to_numeric(frame[column], errors="coerce")
    if "date" in frame.columns:
        order = pd.to_datetime(frame["date"], errors="coerce")
        values = values.set_axis(order).dropna().sort_index()
    else:
        values = values.dropna()
    return values


def _latest(values: pd.Series) -> tuple[float | None, object]:
    if values.empty:
        return None, None
    return float(values.iloc[-1]), values.index[-1]


def reference_bands(wellness: pd.DataFrame | None) -> dict[str, dict]:
    """Bandas y estado actual de sueño, FC en reposo, HRV y peso."""
    result: dict[str, dict] = {
        "sleep": {
            "low": SLEEP_TARGET_H[0],
            "high": SLEEP_TARGET_H[1],
            "label": "7–9 h",
            "source": "referencia general de sueño",
            "latest": None,
            "date": None,
            "status": None,
            "note": "Fuera de la banda no implica un problema: valora cómo te encuentras.",
        },
        "resting_hr": {
            "low": None,
            "high": None,
            "baseline": None,
            "label": "Sin datos suficientes",
            "source": "mediana personal ± 5 ppm",
            "latest": None,
            "date": None,
            "status": None,
            "note": "Una FC en reposo claramente alta varios días puede reflejar fatiga o enfermedad.",
        },
        "hrv": {
            "low": None,
            "high": None,
            "baseline": None,
            "label": "Sin datos suficientes",
            "source": "mediana personal ± 1 desviación estándar",
            "latest": None,
            "date": None,
            "status": None,
            "note": "La HRV es muy individual; compara contigo, no con valores de otras personas.",
        },
        "weight": {
            "latest": None,
            "mean": None,
            "count": 0,
            "label": "Sin banda universal",
            "source": "el rango saludable depende de talla y composición",
            "status": None,
            "note": "Se muestran el último pesaje y su variación, no un objetivo de peso.",
        },
    }
    if wellness is None or wellness.empty:
        return result

    sleep = _series(wellness, "sleep_h")
    latest_sleep, sleep_date = _latest(sleep)
    result["sleep"].update(
        latest=latest_sleep,
        date=sleep_date,
        status=band_status(latest_sleep, *SLEEP_TARGET_H),
    )

    for key, column, margin in (
        ("resting_hr", "resting_hr", RHR_MARGIN_PPM),
        ("hrv", "hrv", None),
    ):
        values = _series(wellness, column)
        if len(values) < MIN_OBSERVATIONS:
            continue
        baseline = float(values.median())
        if margin is not None:
            spread = margin
        else:
            spread = float(values.std(ddof=0))
            spread = max(spread, 3.0)
        low = baseline - spread
        high = baseline + spread
        latest, date = _latest(values)
        result[key].update(
            low=low,
            high=high,
            baseline=baseline,
            latest=latest,
            date=date,
            label=(
                f"{baseline:.0f} ± {spread:.0f} "
                + ("ppm" if key == "resting_hr" else "ms")
            ),
            status=band_status(latest, low, high),
        )

    weight_column = (
        "weight_observed"
        if "weight_observed" in wellness.columns
        else "weight"
    )
    weight = _series(wellness, weight_column)
    if not weight.empty:
        result["weight"].update(
            latest=float(weight.iloc[-1]),
            mean=float(weight.mean()),
            count=int(len(weight)),
        )
    return result
