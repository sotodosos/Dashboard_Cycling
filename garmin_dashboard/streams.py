"""Series temporales y curvas de potencia (sin dependencias de Streamlit)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

# Duraciones habituales de la curva de potencia. El resumen de Garmin usa
# ``maxAvgPower_<segundos>``; los streams de intervals.icu se agregan aparte.
POWER_DURATIONS = (1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200)


def stream_values(streams: list[dict] | None, stream_type: str) -> list:
    """Datos de un stream concreto (``time``, ``watts``, ``heartrate``...)."""
    if not streams:
        return []
    if isinstance(streams, dict):
        streams = streams.get("streams", [])
    if not isinstance(streams, (list, tuple)):
        return []
    stream = next(
        (
            item for item in streams
            if isinstance(item, dict) and item.get("type") == stream_type
        ),
        None,
    )
    return (stream.get("data") or []) if stream else []


def profile_frame(
    x_values: list | np.ndarray | pd.Series,
    y_values: list | np.ndarray | pd.Series,
    x_name: str,
    y_name: str,
) -> pd.DataFrame:
    """Empareja dos series y descarta pares no numéricos."""
    length = min(len(x_values), len(y_values))
    if not length:
        return pd.DataFrame(columns=[x_name, y_name])
    frame = pd.DataFrame(
        {x_name: list(x_values)[:length], y_name: list(y_values)[:length]}
    )
    for column in (x_name, y_name):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna()


def _uniform_watts(watts: list | np.ndarray | pd.Series, times=None) -> np.ndarray:
    """Potencia en una rejilla de 1 segundo para agregar por duración."""
    values = pd.to_numeric(pd.Series(watts), errors="coerce").to_numpy(dtype=float)
    if not len(values):
        return np.array([], dtype=float)

    if times is not None and len(times) >= 2:
        seconds = pd.to_numeric(
            pd.Series(times), errors="coerce"
        ).to_numpy(dtype=float)
        count = min(len(seconds), len(values))
        seconds = seconds[:count]
        values = values[:count]
        valid = np.isfinite(seconds) & np.isfinite(values)
        seconds = seconds[valid]
        values = values[valid]
        if len(seconds) >= 2 and seconds[-1] > seconds[0]:
            seconds = seconds - seconds[0]
            grid = np.arange(0.0, seconds[-1] + 1.0, 1.0)
            values = np.interp(grid, seconds, values)
            return values

    return values[np.isfinite(values)]


def power_duration_curve(
    watts: list | np.ndarray | pd.Series,
    durations: tuple[int, ...] = POWER_DURATIONS,
    *,
    times=None,
) -> pd.DataFrame:
    """Mejor potencia media para cada duración de una serie de potencia.

    ``times`` permite remuestrear a 1 Hz cuando los streams no vienen ya en
    esa frecuencia. Devuelve columnas ``duration_s`` y ``watts``.
    """
    values = _uniform_watts(watts, times)
    rows = []
    if len(values):
        cumulative = np.concatenate(([0.0], np.cumsum(values)))
        for seconds in durations:
            if len(values) < seconds:
                continue
            means = (cumulative[seconds:] - cumulative[:-seconds]) / seconds
            best = float(np.nanmax(means)) if means.size else float("nan")
            if np.isfinite(best) and best > 0:
                rows.append({"duration_s": int(seconds), "watts": best})
    return pd.DataFrame(rows, columns=["duration_s", "watts"])


def power_range_time(
    streams: list[dict], low: float, high: float
) -> tuple[float, float]:
    """Segundos en un rango de potencia y segundos totales muestreados."""
    times = pd.to_numeric(
        pd.Series(stream_values(streams, "time")), errors="coerce"
    ).to_numpy(dtype=float)
    watts = pd.to_numeric(
        pd.Series(stream_values(streams, "watts")), errors="coerce"
    ).to_numpy(dtype=float)
    count = min(len(times), len(watts))
    if count < 2:
        return 0.0, 0.0
    deltas = np.diff(times[:count])
    point_watts = watts[:count - 1]
    valid = (
        np.isfinite(deltas)
        & np.isfinite(point_watts)
        & (deltas > 0)
        & (deltas <= 5)
    )
    observed_seconds = float(deltas[valid].sum())
    target_seconds = float(
        deltas[valid & (point_watts >= low) & (point_watts <= high)].sum()
    )
    return target_seconds, observed_seconds


def power_curve_from_summary(activities: pd.DataFrame | None) -> pd.DataFrame:
    """Curva de potencia a partir de los ``maxAvgPower_*`` de Garmin.

    Es la vía rápida y no requiere descargar streams. Devuelve la mejor
    potencia de cada duración y la actividad que la consiguió.
    """
    if activities is None or activities.empty:
        return pd.DataFrame(columns=["duration_s", "watts", "activity"])

    rows = []
    for _, activity in activities.iterrows():
        try:
            raw = json.loads(activity.get("raw_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        for seconds in POWER_DURATIONS:
            value = pd.to_numeric(
                pd.Series([raw.get(f"maxAvgPower_{seconds}")]), errors="coerce"
            ).iloc[0]
            if pd.notna(value) and value > 0:
                rows.append(
                    {
                        "duration_s": int(seconds),
                        "watts": float(value),
                        "activity": activity.get("activity_name")
                        or activity.get("sport")
                        or "Sin nombre",
                    }
                )

    frame = pd.DataFrame(rows, columns=["duration_s", "watts", "activity"])
    if frame.empty:
        return frame
    best = frame.loc[frame.groupby("duration_s")["watts"].idxmax()]
    return best.sort_values("duration_s", ignore_index=True)
