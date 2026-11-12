"""Agregaciones y cálculos para el dashboard (sin dependencias de Streamlit)."""

from __future__ import annotations

import json
import re
from datetime import date

import pandas as pd

SPORT_LABELS = {
    "running": "Carrera",
    "trail_running": "Trail",
    "treadmill_running": "Cinta",
    "track_running": "Pista",
    "indoor_running": "Cinta",
    "virtual_run": "Carrera virtual",
    "cycling": "Ciclismo",
    "road_biking": "Carretera",
    "mountain_biking": "MTB",
    "gravel_cycling": "Gravel",
    "indoor_cycling": "Rodillo",
    "virtual_ride": "Rodillo",
    "bmx": "BMX",
    "cyclocross": "Ciclocrós",
    "track_cycling": "Pista",
    "e_bike_fitness": "E-Bike",
    "e_bike_mountain": "E-MTB",
    "swimming": "Natación",
    "lap_swimming": "Piscina",
    "open_water_swimming": "Aguas abiertas",
    "strength_training": "Fuerza",
    "fitness_equipment": "Gimnasio",
    "walking": "Caminata",
    "hiking": "Senderismo",
    "multi_sport": "Multideporte",
    "other": "Otro",
    # Tipos de intervals.icu
    "Ride": "Ciclismo",
    "VirtualRide": "Rodillo",
    "EBikeRide": "E-Bike",
    "EMountainBikeRide": "E-MTB",
    "GravelRide": "Gravel",
    "MountainBikeRide": "MTB",
    "Cyclocross": "Ciclocrós",
    "TrackRide": "Pista",
    "Velomobile": "Velomóvil",
    "Run": "Carrera",
    "VirtualRun": "Carrera virtual",
    "TrailRun": "Trail",
    "Swim": "Natación",
    "OpenWaterSwim": "Aguas abiertas",
    "WeightTraining": "Fuerza",
    "Walk": "Caminata",
    "Hike": "Senderismo",
    "Rowing": "Remo",
    "VirtualRow": "Remo virtual",
    "Workout": "Entrenamiento",
    "Yoga": "Yoga",
    "Other": "Otro",
}

RUNNING_TYPES = {
    "running",
    "trail_running",
    "treadmill_running",
    "track_running",
    "indoor_running",
    "virtual_run",
    "Run",
    "VirtualRun",
    "TrailRun",
}

CYCLING_TYPES = {
    # Garmin
    "cycling",
    "road_biking",
    "mountain_biking",
    "gravel_cycling",
    "indoor_cycling",
    "virtual_ride",
    "bmx",
    "cyclocross",
    "track_cycling",
    "e_bike_fitness",
    "e_bike_mountain",
    # intervals.icu
    "Ride",
    "VirtualRide",
    "EBikeRide",
    "EMountainBikeRide",
    "GravelRide",
    "MountainBikeRide",
    "Cyclocross",
    "TrackRide",
    "Velomobile",
}

INDOOR_TYPES = {
    "indoor_cycling",
    "virtual_ride",
    "VirtualRide",
}

# Tema Carbón nocturno: neutros oscuros y series luminosas de alto contraste.
APP_PALETTE = {
    "background": "#111827",
    "panel": "#1F2937",
    "border": "#38465A",
    "text": "#F1F5F9",
    "muted": "#B6C2D1",
    "primary": "#38BDF8",
    "ctl": "#34D399",
    "atl": "#FB7185",
    "tsb": "#A78BFA",
    "sleep": "#E879F9",
    "resting_hr": "#FBBF24",
    "load": "#94A3B8",
    "power_avg": "#38BDF8",
    "power_normalized": "#FB923C",
    "power_best": "#C084FC",
    "weekly_trend": "#E2E8F0",
    "battery_min": "#38BDF8",
    "battery_max": "#C084FC",
    "hrv": "#C084FC",
    "elevation": "#2DD4BF",
}

SPORT_COLORS = {
    "Ciclismo": "#38BDF8",
    "Carretera": "#60A5FA",
    "MTB": "#A78BFA",
    "Gravel": "#2DD4BF",
    "Rodillo": "#C084FC",
    "Ciclismo virtual": "#E879F9",
    "Ciclocrós": "#22D3EE",
    "Pista": "#34D399",
    "E-Bike": "#A3E635",
    "E-MTB": "#5EEAD4",
    "Velomóvil": "#94A3B8",
    "Carrera": "#CBD5E1",
    "Trail": "#A1A1AA",
    "Cinta": "#D1D5DB",
    "Carrera virtual": "#C4B5FD",
    "Natación": "#38BDF8",
    "Piscina": "#22D3EE",
    "Aguas abiertas": "#22D3EE",
    "Fuerza": "#C4B5FD",
    "Gimnasio": "#A78BFA",
    "Caminata": "#CBD5E1",
    "Senderismo": "#A1A1AA",
    "Multideporte": "#94A3B8",
    "Entrenamiento": "#C4B5FD",
    "Yoga": "#D8B4FE",
    "Remo": "#38BDF8",
    "Remo virtual": "#7DD3FC",
    "Otro": "#94A3B8",
}

HR_ZONE_COLORS = [
    "#38BDF8",
    "#60A5FA",
    "#A78BFA",
    "#FB7185",
    "#FBBF24",
    "#C084FC",
    "#22D3EE",
]

POWER_ZONE_COLORS = [
    "#94A3B8",
    "#38BDF8",
    "#34D399",
    "#A3E635",
    "#FBBF24",
    "#FB923C",
    "#FB7185",
]

HR_ZONE_NAMES = [
    "Recuperación",
    "Aeróbico",
    "Tempo",
    "Umbral",
    "VO2max",
    "Anaeróbico",
    "Neuromuscular",
]

POWER_ZONE_NAMES = [
    "Recuperación activa",
    "Resistencia",
    "Tempo",
    "Umbral",
    "VO₂ máx",
    "Anaeróbico",
    "Neuromuscular",
]

ZONE_LABELS = {
    "hr_zone_1_s": "Z1 · Suave",
    "hr_zone_2_s": "Z2 · Aeróbico",
    "hr_zone_3_s": "Z3 · Tempo",
    "hr_zone_4_s": "Z4 · Umbral",
    "hr_zone_5_s": "Z5 · Máximo",
}

# Modelos de referencia del dashboard. Los límites son los bordes superiores
# de cada zona: Z1 queda por debajo del primero y la última no tiene techo.
LTHR_ZONE_NAMES = [
    "Recuperación",
    "Aeróbica",
    "Tempo",
    "Umbral",
    "Sobre umbral",
]
FRIEL_LTHR_BOUNDS = (0.85, 0.90, 0.95, 1.00)
COGGAN_FTP_BOUNDS = (0.55, 0.75, 0.90, 1.05, 1.20, 1.50)

HEALTH_COLUMNS = [
    "date",
    "ctl",
    "atl",
    "tsb",
    "ramp_rate",
    "resting_hr",
    "sleep_s",
    "sleep_h",
    "sleep_score",
    "hrv",
    "weight",
]


def zone_label(index: int, kind: str = "hr") -> str:
    """Etiqueta legible para una zona (1-based)."""
    names = HR_ZONE_NAMES if kind == "hr" else POWER_ZONE_NAMES
    name = names[index - 1] if 0 < index <= len(names) else "Zona"
    return f"Z{index} · {name}"


# --------------------------------------------------------------------------- #
# Preparación de datos
# --------------------------------------------------------------------------- #


def prepare_activities(df: pd.DataFrame) -> pd.DataFrame:
    """Añade columnas derivadas (fecha, semana, deporte, ritmo, ...)."""
    empty_columns = [
        "activity_id",
        "start",
        "date",
        "week",
        "sport",
        "duration_min",
        "distance_km",
        "speed_kmh",
        "pace_min_km",
        "is_cycling",
        "indoor",
        "source",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=empty_columns)

    out = df.copy()
    out["start"] = pd.to_datetime(out["start_time_local"], errors="coerce")
    out = out.dropna(subset=["start"])
    out["date"] = out["start"].dt.date
    out["week"] = out["start"].dt.to_period("W-MON").dt.start_time
    out["sport"] = (
        out["activity_type"]
        .map(SPORT_LABELS)
        .fillna(out["activity_type"])
        .fillna("Otro")
    )

    if "trainer" in out.columns:
        trainer = pd.to_numeric(out["trainer"], errors="coerce").fillna(0) > 0
    else:
        trainer = pd.Series(False, index=out.index)
        out["trainer"] = 0

    out["is_cycling"] = out["activity_type"].isin(CYCLING_TYPES)
    out["indoor"] = (
        out["activity_type"].isin(INDOOR_TYPES) | (trainer & out["is_cycling"])
    )
    # En el dashboard todo el ciclismo indoor se agrupa como "Rodillo".
    out.loc[out["is_cycling"] & out["indoor"], "sport"] = "Rodillo"
    # Los tipos de intervals.icu se muestran con la etiqueta en español.
    out.loc[out["is_cycling"], "sport"] = out.loc[
        out["is_cycling"], "sport"
    ].replace({"Ciclismo virtual": "Rodillo"})

    if "source" not in out.columns:
        out["source"] = "Garmin"
    else:
        out["source"] = out["source"].fillna("Garmin")

    for column in (
        "duration_s",
        "distance_m",
        "calories",
        "avg_hr",
        "max_hr",
        "training_load",
        "avg_power_w",
        "weighted_avg_power_w",
        "intensity",
        "ftp",
        "avg_cadence",
        "elevation_gain_m",
    ):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
        else:
            out[column] = float("nan")

    out["duration_min"] = out["duration_s"] / 60
    out["distance_km"] = out["distance_m"] / 1000
    out["speed_kmh"] = out["distance_km"] / (out["duration_s"] / 3600)
    out["pace_min_km"] = out["duration_min"] / out["distance_km"]
    out.loc[out["distance_km"] <= 0.2, "pace_min_km"] = float("nan")
    out.loc[out["duration_s"] <= 0, "speed_kmh"] = float("nan")

    out["elevation_gain_m"] = out["elevation_gain_m"].fillna(0)

    return out


def _zone_list(value: object) -> list[float]:
    """Normaliza a lista de segundos un campo JSON de zonas."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, (list, tuple)):
        return []
    seconds: list[float] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("secs")
        try:
            seconds.append(float(item))
        except (TypeError, ValueError):
            seconds.append(0.0)
    return seconds


def _expand_zone_columns(out: pd.DataFrame) -> pd.DataFrame:
    """Convierte las listas JSON de intervals.icu en columnas por zona."""
    specs = {
        "hr": ("hr_zone_times_json", "hr_zone_{}_s"),
        "power": ("power_zone_times_json", "power_zone_{}_s"),
    }
    for kind, (source, pattern) in specs.items():
        if source not in out.columns:
            continue
        series = out[source].apply(_zone_list)
        max_len = max((len(value) for value in series), default=0)
        if not max_len:
            continue
        for index in range(max_len):
            column = pattern.format(index + 1)
            values = series.apply(
                lambda items, i=index: items[i] if i < len(items) else 0.0
            )
            if column in out.columns:
                out[column] = pd.to_numeric(
                    out[column], errors="coerce"
                ).fillna(values)
                out[column] = out[column].where(out[column] != 0, values)
            else:
                out[column] = values
    return out


def prepare_intervals_activities(df: pd.DataFrame) -> pd.DataFrame:
    """Prepara las actividades de intervals.icu y expande sus zonas."""
    if df is None or df.empty:
        return prepare_activities(pd.DataFrame())
    out = _expand_zone_columns(df.copy())
    out["source"] = "intervals.icu"
    return prepare_activities(out)


def _compatible_activity_type(first: pd.Series, second: pd.Series) -> bool:
    """Indica si dos filas pueden ser la misma sesión para deduplicar."""
    if bool(first.get("is_cycling")) and bool(second.get("is_cycling")):
        # La misma salida debe coincidir también en exterior/rodillo.
        return bool(first.get("indoor")) == bool(second.get("indoor"))
    if bool(first.get("is_cycling")) != bool(second.get("is_cycling")):
        return False
    first_type = first.get("activity_type")
    second_type = second.get("activity_type")
    if first_type == second_type:
        return True
    if first_type in RUNNING_TYPES and second_type in RUNNING_TYPES:
        return True
    first_sport = first.get("sport")
    return bool(first_sport) and first_sport == second.get("sport")


def _compatible_activity_fields(first: tuple, second: tuple) -> bool:
    """Versión ligera de compatibilidad para filas ya extraídas a tuplas.

    Tupla: ``(start, is_cycling, indoor, activity_type, sport, source)``.
    """
    _, first_cycling, first_indoor, first_type, first_sport, _ = first
    _, second_cycling, second_indoor, second_type, second_sport, _ = second
    if bool(first_cycling) and bool(second_cycling):
        return bool(first_indoor) == bool(second_indoor)
    if bool(first_cycling) != bool(second_cycling):
        return False
    if first_type == second_type:
        return True
    if first_type in RUNNING_TYPES and second_type in RUNNING_TYPES:
        return True
    return bool(first_sport) and first_sport == second_sport


def combine_activities(
    garmin: pd.DataFrame | None,
    intervals: pd.DataFrame | None,
) -> pd.DataFrame:
    """Une ambas fuentes y evita actividades duplicadas.

    Se consideran la misma sesión dos actividades de tipo compatible que
    empiecen con una diferencia de hasta 90 segundos. Cuando la misma sesión
    aparece en Garmin y en intervals.icu se conserva la de intervals.icu porque
    incluye potencia y zonas de potencia.
    """
    frames = []
    for frame, source in ((garmin, "Garmin"), (intervals, "intervals.icu")):
        if frame is None or frame.empty:
            continue
        current = frame.copy()
        current["source"] = source
        frames.append(current)

    if not frames:
        return prepare_activities(pd.DataFrame())

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values("start", ignore_index=True)
    # Las filas están ordenadas por inicio; una actividad más antigua que 90 s
    # ya no puede ser duplicada por las siguientes. Mantener solo esa ventana
    # evita el recorrido cuadrático y las búsquedas repetidas vía ``.loc``.
    fields = list(
        out[
            ["start", "is_cycling", "indoor", "activity_type", "sport", "source"]
        ].itertuples(index=False, name=None)
    )
    kept: list[int] = []
    active: list[int] = []
    for index, row in enumerate(fields):
        start = row[0]
        active = [
            previous_index
            for previous_index in active
            if (start - fields[previous_index][0]).total_seconds() <= 90
        ]
        duplicate_index = next(
            (
                previous_index
                for previous_index in active
                if _compatible_activity_fields(fields[previous_index], row)
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(index)
            active.append(index)
        elif (
            row[5] == "intervals.icu"
            and fields[duplicate_index][5] != "intervals.icu"
        ):
            kept[kept.index(duplicate_index)] = index
            active[active.index(duplicate_index)] = index

    return out.iloc[kept].sort_values("start", ignore_index=True)



def prepare_wellness(df: pd.DataFrame) -> pd.DataFrame:
    """Prepara la tabla de wellness de intervals.icu."""
    empty = pd.DataFrame(
        columns=[
            "date",
            "ctl",
            "atl",
            "tsb",
            "ramp_rate",
            "resting_hr",
            "sleep_s",
            "sleep_h",
            "sleep_score",
            "hrv",
            "weight",
        ]
    )
    if df is None or df.empty:
        return empty

    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"]).sort_values("date")
    for column in (
        "ctl",
        "atl",
        "tsb",
        "ramp_rate",
        "resting_hr",
        "sleep_s",
        "sleep_score",
        "hrv",
        "weight",
    ):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
        else:
            out[column] = float("nan")
    out["sleep_h"] = out["sleep_s"] / 3600
    missing_tsb = out["tsb"].isna() & out["ctl"].notna() & out["atl"].notna()
    out.loc[missing_tsb, "tsb"] = (
        out.loc[missing_tsb, "ctl"] - out.loc[missing_tsb, "atl"]
    )
    return out


def prepare_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Añade columnas derivadas a las métricas diarias."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "sleep_h", "sleep_score"])

    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["sleep_h"] = pd.to_numeric(out["sleep_s"], errors="coerce") / 3600
    for column in (
        "resting_hr",
        "hrv_last_night",
        "hrv_weekly_avg",
        "sleep_score",
        "stress_avg",
        "body_battery_min",
        "body_battery_max",
        "readiness_score",
        "steps",
    ):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out.sort_values("date")


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series(float("nan"), index=frame.index, dtype=float)


def merge_health(
    wellness: pd.DataFrame | None, daily: pd.DataFrame | None
) -> pd.DataFrame:
    """Fusiona la salud de intervals.icu con la de Garmin, columna a columna.

    intervals.icu tiene prioridad porque aporta CTL/ATL/TSB y peso. Garmin
    cubre los huecos de sueño, score de sueño, FC en reposo y HRV. Así un día
    en el que intervals.icu no trae una métrica no oculta el dato de Garmin.
    """
    if wellness is None or wellness.empty:
        out = pd.DataFrame(columns=HEALTH_COLUMNS)
    else:
        out = wellness.copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.dropna(subset=["date"])

    for column in HEALTH_COLUMNS:
        if column not in out.columns:
            out[column] = float("nan")

    if daily is not None and not daily.empty:
        garmin = pd.DataFrame(
            {"date": pd.to_datetime(daily["date"], errors="coerce")}
        )
        garmin["resting_hr_g"] = _numeric_column(daily, "resting_hr")
        garmin["sleep_s_g"] = _numeric_column(daily, "sleep_s")
        garmin["sleep_score_g"] = _numeric_column(daily, "sleep_score")
        hrv_last = _numeric_column(daily, "hrv_last_night")
        hrv_week = _numeric_column(daily, "hrv_weekly_avg")
        garmin["hrv_g"] = hrv_last.where(hrv_last.notna(), hrv_week)
        garmin = garmin.dropna(subset=["date"]).drop_duplicates(
            "date", keep="last"
        )
        out = out.merge(garmin, on="date", how="outer")
        for column in ("resting_hr", "sleep_s", "sleep_score", "hrv"):
            fallback = pd.to_numeric(out.get(f"{column}_g"), errors="coerce")
            out[column] = pd.to_numeric(out[column], errors="coerce")
            out[column] = out[column].where(out[column].notna(), fallback)
            out = out.drop(columns=[f"{column}_g"])

    out["sleep_s"] = pd.to_numeric(out["sleep_s"], errors="coerce")
    out["sleep_h"] = pd.to_numeric(out["sleep_h"], errors="coerce")
    out["sleep_h"] = out["sleep_h"].where(
        out["sleep_h"].notna(), out["sleep_s"] / 3600
    )
    missing_tsb = out["tsb"].isna() & out["ctl"].notna() & out["atl"].notna()
    out.loc[missing_tsb, "tsb"] = (
        out.loc[missing_tsb, "ctl"] - out.loc[missing_tsb, "atl"]
    )
    return (
        out.sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )


def weight_trend(wellness: pd.DataFrame | None) -> dict[str, object]:
    """Último peso observado y variación respecto a 7 y 30 días antes.

    Ignora los valores rellenados con ``ffill`` para que la variación refleje
    pesajes reales y no días sin báscula. La referencia es el último pesaje.
    """
    result: dict[str, object] = {
        "latest": None,
        "date": None,
        "delta7": None,
        "delta30": None,
        "mean": None,
        "count": 0,
    }
    if wellness is None or wellness.empty:
        return result

    column = (
        "weight_observed" if "weight_observed" in wellness.columns else "weight"
    )
    if column not in wellness.columns:
        return result

    observations = wellness.dropna(subset=[column]).copy()
    if observations.empty:
        return result
    observations["date"] = pd.to_datetime(
        observations["date"], errors="coerce"
    )
    observations = observations.dropna(subset=["date"]).sort_values("date")
    if observations.empty:
        return result

    latest = observations.iloc[-1]
    latest_value = float(latest[column])
    reference = latest["date"]
    result.update(
        latest=latest_value,
        date=latest["date"],
        mean=float(observations[column].mean()),
        count=int(len(observations)),
    )
    for days in (7, 30):
        cutoff = reference - pd.Timedelta(days=days)
        previous = observations[observations["date"] <= cutoff]
        if not previous.empty:
            result[f"delta{days}"] = latest_value - float(
                previous.iloc[-1][column]
            )
    return result


# --------------------------------------------------------------------------- #
# Filtros
# --------------------------------------------------------------------------- #


def filter_activities(
    df: pd.DataFrame,
    start: date | None = None,
    end: date | None = None,
    sports: list[str] | None = None,
) -> pd.DataFrame:
    out = df
    if start is not None:
        out = out[out["date"] >= start]
    if end is not None:
        out = out[out["date"] <= end]
    if sports:
        out = out[out["sport"].isin(sports)]
    return out.copy()


def filter_daily(
    df: pd.DataFrame,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    out = df
    if start is not None:
        out = out[out["date"] >= pd.Timestamp(start)]
    if end is not None:
        out = out[out["date"] <= pd.Timestamp(end)]
    return out


# --------------------------------------------------------------------------- #
# KPIs y agregaciones
# --------------------------------------------------------------------------- #


def kpis(df: pd.DataFrame) -> dict[str, float]:
    """Resumen del periodo filtrado."""
    if df.empty:
        return {
            "sessions": 0,
            "distance_km": 0.0,
            "duration_h": 0.0,
            "elevation_m": 0.0,
            "calories": 0.0,
            "active_days": 0,
            "avg_hr": 0.0,
            "avg_power": 0.0,
            "load": 0.0,
        }

    return {
        "sessions": int(len(df)),
        "distance_km": float(df["distance_km"].sum(skipna=True)),
        "duration_h": float(df["duration_min"].sum(skipna=True)) / 60,
        "elevation_m": float(df["elevation_gain_m"].sum(skipna=True)),
        "calories": float(df["calories"].sum(skipna=True)),
        "active_days": int(df["date"].nunique()),
        "avg_hr": float(df["avg_hr"].mean(skipna=True)),
        "avg_power": float(df["avg_power_w"].mean(skipna=True)),
        "load": float(df["training_load"].sum(skipna=True)),
    }


def weekly_volume(df: pd.DataFrame, metric: str = "distance_km") -> pd.DataFrame:
    """Volumen semanal desglosado por deporte."""
    if df.empty:
        return pd.DataFrame(columns=["week", "sport", metric])
    return (
        df.groupby(["week", "sport"], as_index=False)[metric]
        .sum()
        .sort_values("week")
    )


def weekly_totals(df: pd.DataFrame, metric: str = "distance_km") -> pd.DataFrame:
    """Serie semanal total con media móvil de 4 semanas."""
    if df.empty:
        return pd.DataFrame(columns=["week", metric, "trend"])
    out = (
        df.groupby("week", as_index=False)[metric]
        .sum()
        .sort_values("week")
        .reset_index(drop=True)
    )
    out["trend"] = out[metric].rolling(4, min_periods=1).mean()
    return out


def sport_breakdown(df: pd.DataFrame, metric: str = "distance_km") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["sport", metric, "sessions"])
    out = (
        df.groupby("sport", as_index=False)
        .agg({metric: "sum", "activity_id": "count"})
        .rename(columns={"activity_id": "sessions"})
        .sort_values(metric, ascending=False)
    )
    return out


def weekly_running_pace(df: pd.DataFrame) -> pd.DataFrame:
    """Ritmo medio semanal de carrera (min/km), ponderado por distancia."""
    running = df[df["activity_type"].isin(RUNNING_TYPES)]
    running = running[running["distance_km"] > 0.3]
    if running.empty:
        return pd.DataFrame(columns=["week", "pace_min_km", "distance_km"])
    out = (
        running.groupby("week", as_index=False)
        .agg({"distance_km": "sum", "duration_min": "sum"})
        .sort_values("week")
    )
    out["pace_min_km"] = out["duration_min"] / out["distance_km"]
    return out


def weekly_avg_hr(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["week", "avg_hr"])
    return (
        df.dropna(subset=["avg_hr"])
        .groupby("week", as_index=False)["avg_hr"]
        .mean()
        .sort_values("week")
    )


def hr_zone_minutes(df: pd.DataFrame) -> pd.DataFrame:
    """Minutos totales en cada zona de frecuencia cardiaca."""
    return zone_minutes(df, "hr")


def _zone_columns(df: pd.DataFrame, kind: str) -> list[tuple[int, str]]:
    pattern = re.compile(rf"^{kind}_zone_(\d+)_s$")
    columns = []
    for column in df.columns:
        match = pattern.match(column)
        if match:
            columns.append((int(match.group(1)), column))
    return sorted(columns)


def zone_minutes(df: pd.DataFrame, kind: str = "hr") -> pd.DataFrame:
    """Minutos totales por zona para ``hr`` o ``power``."""
    kind = "power" if kind == "power" else "hr"
    columns = _zone_columns(df, kind)
    # Este dashboard presenta los modelos solicitados: 5 zonas FC y 7 zonas
    # de potencia Coggan. Algunas fuentes traen bins adicionales.
    columns = columns[: (7 if kind == "power" else 5)]
    if df.empty or not columns:
        return pd.DataFrame(columns=["zone", "label", "minutes"])

    total = 0.0
    rows = []
    for index, column in columns:
        values = pd.to_numeric(df[column], errors="coerce").fillna(0)
        minutes = float(values.sum()) / 60
        total += minutes
        rows.append(
            {
                "zone": f"Z{index}",
                "label": zone_label(index, kind),
                "minutes": minutes,
            }
        )

    out = pd.DataFrame(rows)
    if total > 0:
        out["share"] = out["minutes"] / total
    else:
        out["share"] = 0.0
    return out


def activity_zone_minutes(row: pd.Series | dict, kind: str = "hr") -> pd.DataFrame:
    """Minutos por zona de una actividad concreta."""
    data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
    frame = pd.DataFrame([data])
    columns = _zone_columns(frame, "power" if kind == "power" else "hr")
    columns = columns[: (7 if kind == "power" else 5)]
    rows = []
    for index, column in columns:
        value = pd.to_numeric(frame[column], errors="coerce").fillna(0).iloc[0]
        rows.append(
            {
                "zone": f"Z{index}",
                "label": zone_label(index, kind),
                "minutes": float(value) / 60,
            }
        )
    return pd.DataFrame(rows, columns=["zone", "label", "minutes"])


def _positive_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number) or number <= 0:
        return None
    return number


def _zone_rows(limits: list[int], kind: str) -> list[dict[str, object]]:
    """Construye las zonas a partir de sus límites superiores."""
    unit = "ppm" if kind == "hr" else "W"
    names = LTHR_ZONE_NAMES if kind == "hr" else POWER_ZONE_NAMES
    rows = []
    for index in range(len(limits) + 1):
        low = limits[index - 1] if index > 0 else None
        high = limits[index] if index < len(limits) else None
        if low is None:
            range_label = f"<{high} {unit}"
        elif high is None:
            range_label = f"≥{low} {unit}"
        else:
            range_label = f"{low}–{high - 1} {unit}"
        name = names[index] if index < len(names) else "Zona"
        rows.append(
            {
                "zone": f"Z{index + 1}",
                "name": name,
                "label": f"Z{index + 1} · {name}",
                "min": low,
                "max": high,
                "range": range_label,
            }
        )
    return rows


def lthr_zones(lthr: object) -> list[dict[str, object]]:
    """Cinco zonas Friel calculadas con LTHR (85/90/95/100 %)."""
    value = _positive_number(lthr)
    if value is None:
        return []
    limits = [round(value * ratio) for ratio in FRIEL_LTHR_BOUNDS]
    return _zone_rows(limits, "hr")


def power_zone_ratios(settings_row: pd.Series | dict | None) -> tuple[float, ...]:
    """Bordes de potencia de intervals.icu como fracción de FTP.

    ``power_zones`` llega en porcentaje de FTP y suele terminar en un centinela
    (por ejemplo ``999``). Si no se puede interpretar, se usa Coggan.
    """
    if settings_row is None:
        return COGGAN_FTP_BOUNDS
    data = (
        settings_row.to_dict()
        if isinstance(settings_row, pd.Series)
        else dict(settings_row)
    )
    raw = data.get("power_zones_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return COGGAN_FTP_BOUNDS
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return COGGAN_FTP_BOUNDS

    try:
        values = [float(item) for item in raw]
    except (TypeError, ValueError):
        return COGGAN_FTP_BOUNDS
    if len(values) >= 7:
        values = values[:6]
    if (
        len(values) != 6
        or values != sorted(values)
        or not all(20 <= value <= 250 for value in values)
    ):
        return COGGAN_FTP_BOUNDS
    return tuple(value / 100 for value in values)


def coggan_zones(
    ftp: object, ratios: tuple[float, ...] = COGGAN_FTP_BOUNDS
) -> list[dict[str, object]]:
    """Siete zonas Coggan calculadas con FTP."""
    value = _positive_number(ftp)
    if value is None:
        return []
    limits = [round(value * ratio) for ratio in ratios]
    return _zone_rows(limits, "power")


def zone_model(
    settings_row: pd.Series | dict | None,
    kind: str = "power",
    *,
    indoor: bool = False,
) -> list[dict[str, object]]:
    """Zonas de referencia del dashboard a partir de los ajustes del deporte.

    Se usa un FTP único para las zonas: ``indoor_ftp`` si existe y, en caso
    contrario, ``ftp``. Así el modelo queda alineado con el FTP de rodillo que
    usa el deportista, también al mostrar las actividades exteriores.
    """
    if settings_row is None:
        return []
    data = (
        settings_row.to_dict()
        if isinstance(settings_row, pd.Series)
        else dict(settings_row)
    )
    if kind == "power":
        ftp = _positive_number(data.get("indoor_ftp"))
        if ftp is None:
            ftp = _positive_number(data.get("ftp"))
        return coggan_zones(ftp, power_zone_ratios(data))
    return lthr_zones(data.get("lthr"))


def zone_ranges(
    settings_row: pd.Series | dict | None,
    kind: str = "power",
    *,
    indoor: bool = False,
) -> list[tuple[float, float | None]]:
    """Rangos (inicio, fin) del modelo mostrado en el dashboard."""
    return [
        (zone["min"], zone["max"])
        for zone in zone_model(settings_row, kind, indoor=indoor)
    ]


def zone_range_labels(
    settings_row: pd.Series | dict | None,
    kind: str = "power",
    *,
    indoor: bool = False,
) -> list[str]:
    return [
        zone["range"]
        for zone in zone_model(settings_row, kind, indoor=indoor)
    ]



def weekly_power(df: pd.DataFrame) -> pd.DataFrame:
    """Potencia media y normalizada por semana."""
    if df.empty:
        return pd.DataFrame(columns=["week", "avg_power_w", "weighted_avg_power_w"])
    out = df.dropna(subset=["avg_power_w"]).copy()
    if out.empty:
        return pd.DataFrame(columns=["week", "avg_power_w", "weighted_avg_power_w"])
    return (
        out.groupby("week", as_index=False)
        .agg(
            avg_power_w=("avg_power_w", "mean"),
            weighted_avg_power_w=("weighted_avg_power_w", "mean"),
        )
        .sort_values("week")
    )


def monthly_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Número de sesiones por mes y deporte."""
    if df.empty:
        return pd.DataFrame(columns=["month", "sport", "sessions"])
    out = df.copy()
    out["month"] = out["start"].dt.to_period("M").dt.start_time
    return (
        out.groupby(["month", "sport"], as_index=False)
        .size()
        .rename(columns={"size": "sessions"})
        .sort_values("month")
    )


# --------------------------------------------------------------------------- #
# Formateo
# --------------------------------------------------------------------------- #


def format_duration(minutes: float | None) -> str:
    if minutes is None or pd.isna(minutes):
        return "–"
    total = int(round(float(minutes)))
    hours, mins = divmod(total, 60)
    return f"{hours} h {mins:02d} min" if hours else f"{mins} min"


def format_pace(pace_min_km: float | None) -> str:
    if pace_min_km is None or pd.isna(pace_min_km):
        return "–"
    minutes = int(pace_min_km)
    seconds = int(round((float(pace_min_km) - minutes) * 60))
    if seconds == 60:
        minutes, seconds = minutes + 1, 0
    return f"{minutes}:{seconds:02d} /km"


def format_number(value: float | None, decimals: int = 0) -> str:
    if value is None or pd.isna(value):
        return "–"
    formatted = f"{float(value):,.{decimals}f}"
    # Formato español: 1.234,5 en lugar de 1,234.5
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
