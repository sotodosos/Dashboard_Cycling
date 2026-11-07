"""Persistencia local en SQLite.

Guardamos solo los campos que usa el dashboard en columnas propias y el JSON
original completo en ``raw_json``, de forma que se puedan añadir métricas
nuevas más adelante sin volver a descargar todo.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id         INTEGER PRIMARY KEY,
    start_time_local    TEXT NOT NULL,
    start_time_gmt      TEXT,
    activity_type       TEXT,
    activity_name       TEXT,
    location_name       TEXT,
    duration_s          REAL,
    moving_duration_s   REAL,
    elapsed_duration_s  REAL,
    distance_m          REAL,
    calories            REAL,
    avg_hr              REAL,
    max_hr              REAL,
    avg_speed_mps       REAL,
    max_speed_mps       REAL,
    elevation_gain_m    REAL,
    elevation_loss_m    REAL,
    aerobic_te          REAL,
    anaerobic_te        REAL,
    vo2max              REAL,
    training_load       REAL,
    avg_power_w         REAL,
    avg_cadence         REAL,
    hr_zone_1_s         REAL,
    hr_zone_2_s         REAL,
    hr_zone_3_s         REAL,
    hr_zone_4_s         REAL,
    hr_zone_5_s         REAL,
    raw_json            TEXT NOT NULL,
    synced_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activities_start
    ON activities (start_time_local);
CREATE INDEX IF NOT EXISTS idx_activities_type
    ON activities (activity_type);

CREATE TABLE IF NOT EXISTS daily_metrics (
    date                TEXT PRIMARY KEY,
    resting_hr          REAL,
    min_hr              REAL,
    max_hr              REAL,
    hrv_last_night      REAL,
    hrv_weekly_avg      REAL,
    hrv_status          TEXT,
    sleep_s             REAL,
    sleep_score         REAL,
    stress_avg          REAL,
    body_battery_min    REAL,
    body_battery_max    REAL,
    steps               REAL,
    total_calories      REAL,
    active_calories     REAL,
    vo2max              REAL,
    readiness_score     REAL,
    training_status     TEXT,
    raw_json            TEXT NOT NULL,
    synced_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intervals_wellness (
    date                TEXT PRIMARY KEY,
    ctl                 REAL,
    atl                 REAL,
    tsb                 REAL,
    ramp_rate           REAL,
    resting_hr          REAL,
    sleep_s             REAL,
    sleep_score         REAL,
    hrv                 REAL,
    weight              REAL,
    raw_json            TEXT NOT NULL,
    synced_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intervals_activities (
    activity_id         TEXT PRIMARY KEY,
    start_time_local    TEXT NOT NULL,
    activity_type       TEXT,
    activity_name       TEXT,
    trainer             INTEGER DEFAULT 0,
    duration_s          REAL,
    moving_duration_s   REAL,
    elapsed_duration_s  REAL,
    distance_m          REAL,
    calories            REAL,
    avg_hr              REAL,
    max_hr              REAL,
    avg_speed_mps       REAL,
    max_speed_mps       REAL,
    elevation_gain_m    REAL,
    elevation_loss_m    REAL,
    training_load       REAL,
    intensity           REAL,
    avg_power_w         REAL,
    weighted_avg_power_w REAL,
    avg_cadence         REAL,
    ftp                 REAL,
    hr_zone_times_json  TEXT,
    power_zone_times_json TEXT,
    raw_json            TEXT NOT NULL,
    synced_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_intervals_activities_start
    ON intervals_activities (start_time_local);
CREATE INDEX IF NOT EXISTS idx_intervals_activities_type
    ON intervals_activities (activity_type);

CREATE TABLE IF NOT EXISTS intervals_sport_settings (
    id                  TEXT PRIMARY KEY,
    types_json          TEXT,
    name                TEXT,
    ftp                 REAL,
    indoor_ftp          REAL,
    lthr                REAL,
    max_hr              REAL,
    hr_zones_json       TEXT,
    power_zones_json    TEXT,
    power_zone_names_json TEXT,
    raw_json            TEXT NOT NULL,
    synced_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_meta (
    key                 TEXT PRIMARY KEY,
    value               TEXT
);
"""

ACTIVITY_COLUMNS = [
    "activity_id",
    "start_time_local",
    "start_time_gmt",
    "activity_type",
    "activity_name",
    "location_name",
    "duration_s",
    "moving_duration_s",
    "elapsed_duration_s",
    "distance_m",
    "calories",
    "avg_hr",
    "max_hr",
    "avg_speed_mps",
    "max_speed_mps",
    "elevation_gain_m",
    "elevation_loss_m",
    "aerobic_te",
    "anaerobic_te",
    "vo2max",
    "training_load",
    "avg_power_w",
    "avg_cadence",
    "hr_zone_1_s",
    "hr_zone_2_s",
    "hr_zone_3_s",
    "hr_zone_4_s",
    "hr_zone_5_s",
    "raw_json",
    "synced_at",
]

DAILY_COLUMNS = [
    "date",
    "resting_hr",
    "min_hr",
    "max_hr",
    "hrv_last_night",
    "hrv_weekly_avg",
    "hrv_status",
    "sleep_s",
    "sleep_score",
    "stress_avg",
    "body_battery_min",
    "body_battery_max",
    "steps",
    "total_calories",
    "active_calories",
    "vo2max",
    "readiness_score",
    "training_status",
    "raw_json",
    "synced_at",
]

INTERVALS_WELLNESS_COLUMNS = [
    "date",
    "ctl",
    "atl",
    "tsb",
    "ramp_rate",
    "resting_hr",
    "sleep_s",
    "sleep_score",
    "hrv",
    "weight",
    "raw_json",
    "synced_at",
]

INTERVALS_ACTIVITY_COLUMNS = [
    "activity_id",
    "start_time_local",
    "activity_type",
    "activity_name",
    "trainer",
    "duration_s",
    "moving_duration_s",
    "elapsed_duration_s",
    "distance_m",
    "calories",
    "avg_hr",
    "max_hr",
    "avg_speed_mps",
    "max_speed_mps",
    "elevation_gain_m",
    "elevation_loss_m",
    "training_load",
    "intensity",
    "avg_power_w",
    "weighted_avg_power_w",
    "avg_cadence",
    "ftp",
    "hr_zone_times_json",
    "power_zone_times_json",
    "raw_json",
    "synced_at",
]

INTERVALS_SETTINGS_COLUMNS = [
    "id",
    "types_json",
    "name",
    "ftp",
    "indoor_ftp",
    "lthr",
    "max_hr",
    "hr_zones_json",
    "power_zones_json",
    "power_zone_names_json",
    "raw_json",
    "synced_at",
]


# --------------------------------------------------------------------------- #
# Conexión y esquema
# --------------------------------------------------------------------------- #


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Abre (y crea si hace falta) la base de datos y su esquema."""
    db_path = str(path or config.DB_PATH)
    if db_path != ":memory:":
        Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Normalización de las respuestas de Garmin
# --------------------------------------------------------------------------- #


def _first(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _activity_type(activity: Mapping[str, Any]) -> str | None:
    raw_type = activity.get("activityType")
    if isinstance(raw_type, Mapping):
        return raw_type.get("typeKey") or raw_type.get("typeId")
    return raw_type or activity.get("activityTypeKey")


def activity_row(activity: Mapping[str, Any]) -> dict[str, Any]:
    """Convierte una actividad cruda de Garmin en una fila de SQLite."""
    activity_id = activity.get("activityId") or activity.get("activityID")
    if activity_id is None:
        raise ValueError("La actividad no tiene activityId")

    cadence = _first(
        activity,
        "averageRunningCadenceInStepsPerMinute",
        "avgRunningCadenceInStepsPerMinute",
        "averageBikeCadenceInStepsPerMinute",
        "averageBikeCadence",
    )

    row = {
        "activity_id": int(activity_id),
        "start_time_local": activity.get("startTimeLocal"),
        "start_time_gmt": activity.get("startTimeGMT"),
        "activity_type": _activity_type(activity),
        "activity_name": activity.get("activityName"),
        "location_name": activity.get("locationName"),
        "duration_s": _as_float(activity.get("duration")),
        "moving_duration_s": _as_float(activity.get("movingDuration")),
        "elapsed_duration_s": _as_float(activity.get("elapsedDuration")),
        "distance_m": _as_float(activity.get("distance")),
        "calories": _as_float(activity.get("calories")),
        "avg_hr": _as_float(_first(activity, "averageHR", "avgHR")),
        "max_hr": _as_float(_first(activity, "maxHR")),
        "avg_speed_mps": _as_float(activity.get("averageSpeed")),
        "max_speed_mps": _as_float(activity.get("maxSpeed")),
        "elevation_gain_m": _as_float(activity.get("elevationGain")),
        "elevation_loss_m": _as_float(activity.get("elevationLoss")),
        "aerobic_te": _as_float(
            _first(activity, "trainingEffect", "aerobicTrainingEffect")
        ),
        "anaerobic_te": _as_float(activity.get("anaerobicTrainingEffect")),
        "vo2max": _as_float(_first(activity, "vO2MaxValue", "vo2MaxValue")),
        "training_load": _as_float(
            _first(activity, "activityTrainingLoad", "trainingLoad")
        ),
        "avg_power_w": _as_float(_first(activity, "avgPower", "averagePower")),
        "avg_cadence": _as_float(cadence),
        "hr_zone_1_s": _as_float(activity.get("hrTimeInZone_1")),
        "hr_zone_2_s": _as_float(activity.get("hrTimeInZone_2")),
        "hr_zone_3_s": _as_float(activity.get("hrTimeInZone_3")),
        "hr_zone_4_s": _as_float(activity.get("hrTimeInZone_4")),
        "hr_zone_5_s": _as_float(activity.get("hrTimeInZone_5")),
        "raw_json": json.dumps(activity, ensure_ascii=False),
        "synced_at": _now(),
    }

    if not row["start_time_local"]:
        raise ValueError(f"Actividad {activity_id} sin startTimeLocal")

    return row


def daily_row(
    date: str,
    stats: Mapping[str, Any] | None = None,
    sleep: Mapping[str, Any] | None = None,
    hrv: Mapping[str, Any] | None = None,
    readiness: Iterable[Mapping[str, Any]] | None = None,
    training_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Combina los distintos payloads diarios en una sola fila."""
    stats = stats or {}
    sleep = sleep or {}
    hrv = hrv or {}

    readiness_list = list(readiness or [])
    readiness_item = readiness_list[-1] if readiness_list else {}

    sleep_dto = sleep.get("dailySleepDTO") or {}
    sleep_scores = sleep_dto.get("sleepScores") or {}
    overall_score = sleep_scores.get("overall") or {}
    sleep_score = _first(
        overall_score if isinstance(overall_score, Mapping) else {},
        "value",
        "score",
    )
    if sleep_score is None:
        sleep_score = _first(
            sleep_dto,
            "sleepScore",
            "sleepScoreValue",
        )

    hrv_summary = hrv.get("hrvSummary") or hrv

    status_raw = (
        (training_status or {}).get("mostRecentTrainingStatus") or {}
    )
    status_value = status_raw.get("trainingStatus") if isinstance(status_raw, Mapping) else None
    if isinstance(status_value, Mapping):
        status_value = _first(status_value, "trainingStatusKey", "trainingStatusValue")
    if status_value is None:
        status_value = _first(
            (training_status or {}).get("mostRecentTrainingStatus") or {},
            "trainingStatusKey",
        )

    return {
        "date": date,
        "resting_hr": _as_float(
            _first(stats, "restingHeartRate", "lastSevenDaysAvgRestingHeartRate")
        ),
        "min_hr": _as_float(stats.get("minHeartRate")),
        "max_hr": _as_float(stats.get("maxHeartRate")),
        "hrv_last_night": _as_float(
            _first(hrv_summary, "lastNightAvg", "lastNight")
        ),
        "hrv_weekly_avg": _as_float(hrv_summary.get("weeklyAvg")),
        "hrv_status": hrv_summary.get("status"),
        "sleep_s": _as_float(
            _first(sleep_dto, "sleepTimeSeconds", "sleepTimeInSeconds")
        ),
        "sleep_score": _as_float(sleep_score),
        "stress_avg": _as_float(
            _first(stats, "averageStressLevel", "avgStressLevel")
        ),
        "body_battery_min": _as_float(stats.get("bodyBatteryLowestValue")),
        "body_battery_max": _as_float(stats.get("bodyBatteryHighestValue")),
        "steps": _as_float(stats.get("totalSteps")),
        "total_calories": _as_float(stats.get("totalKilocalories")),
        "active_calories": _as_float(stats.get("activeKilocalories")),
        "vo2max": _as_float(
            _first(stats, "vO2MaxValue", "vo2MaxValue", "vo2Max")
        ),
        "readiness_score": _as_float(
            _first(readiness_item, "score", "trainingReadinessScore")
        ),
        "training_status": status_value if isinstance(status_value, str) else None,
        "raw_json": json.dumps(
            {
                "stats": stats,
                "sleep": sleep,
                "hrv": hrv,
                "readiness": readiness_list,
                "training_status": training_status,
            },
            ensure_ascii=False,
        ),
        "synced_at": _now(),
    }


# --------------------------------------------------------------------------- #
# Normalización de las respuestas de intervals.icu
# --------------------------------------------------------------------------- #


def _date_key(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else None


def intervals_wellness_row(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Convierte un día de ``wellness`` de intervals.icu en una fila."""
    date_value = _date_key(entry.get("id") or entry.get("date"))
    if not date_value:
        raise ValueError("Registro de wellness sin fecha")

    ctl = _as_float(entry.get("ctl"))
    atl = _as_float(entry.get("atl"))
    tsb = _as_float(entry.get("tsb"))
    if tsb is None and ctl is not None and atl is not None:
        tsb = ctl - atl

    return {
        "date": date_value,
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "ramp_rate": _as_float(entry.get("rampRate")),
        "resting_hr": _as_float(entry.get("restingHR")),
        "sleep_s": _as_float(entry.get("sleepSecs")),
        "sleep_score": _as_float(entry.get("sleepScore")),
        "hrv": _as_float(entry.get("hrv")),
        "weight": _as_float(entry.get("weight")),
        "raw_json": json.dumps(entry, ensure_ascii=False),
        "synced_at": _now(),
    }


def intervals_activity_row(activity: Mapping[str, Any]) -> dict[str, Any]:
    """Convierte una actividad de intervals.icu en una fila de SQLite."""
    activity_id = activity.get("id")
    if activity_id is None:
        raise ValueError("La actividad de intervals.icu no tiene id")

    start_local = activity.get("start_date_local") or activity.get("start_date")
    if not start_local:
        raise ValueError(f"Actividad {activity_id} sin start_date_local")

    moving = _as_float(activity.get("moving_time"))
    elapsed = _as_float(activity.get("elapsed_time"))
    hr_zone_times = activity.get("icu_hr_zone_times")
    power_zone_times = activity.get("icu_zone_times")

    return {
        "activity_id": str(activity_id),
        "start_time_local": str(start_local).replace("T", " ")[:19],
        "activity_type": activity.get("type") or activity.get("sub_type"),
        "activity_name": activity.get("name"),
        "trainer": 1 if activity.get("trainer") else 0,
        "duration_s": moving if moving is not None else elapsed,
        "moving_duration_s": moving,
        "elapsed_duration_s": elapsed,
        "distance_m": _as_float(
            _first(activity, "icu_distance", "distance")
        ),
        "calories": _as_float(activity.get("calories")),
        "avg_hr": _as_float(activity.get("average_heartrate")),
        "max_hr": _as_float(activity.get("max_heartrate")),
        "avg_speed_mps": _as_float(activity.get("average_speed")),
        "max_speed_mps": _as_float(activity.get("max_speed")),
        "elevation_gain_m": _as_float(activity.get("total_elevation_gain")),
        "elevation_loss_m": _as_float(activity.get("total_elevation_loss")),
        "training_load": _as_float(activity.get("icu_training_load")),
        "intensity": _as_float(activity.get("icu_intensity")),
        "avg_power_w": _as_float(activity.get("icu_average_watts")),
        "weighted_avg_power_w": _as_float(
            activity.get("icu_weighted_avg_watts")
        ),
        "avg_cadence": _as_float(activity.get("average_cadence")),
        "ftp": _as_float(activity.get("icu_ftp")),
        "hr_zone_times_json": json.dumps(
            hr_zone_times or [], ensure_ascii=False
        ),
        "power_zone_times_json": json.dumps(
            power_zone_times or [], ensure_ascii=False
        ),
        "raw_json": json.dumps(activity, ensure_ascii=False),
        "synced_at": _now(),
    }


def intervals_settings_row(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Convierte un bloque de ``sport-settings`` en una fila."""
    types = settings.get("types") or []
    settings_id = settings.get("id")
    if settings_id is None:
        settings_id = ",".join(str(item) for item in types) or "default"

    return {
        "id": str(settings_id),
        "types_json": json.dumps(types, ensure_ascii=False),
        "name": settings.get("name"),
        "ftp": _as_float(settings.get("ftp")),
        "indoor_ftp": _as_float(settings.get("indoor_ftp")),
        "lthr": _as_float(settings.get("lthr")),
        "max_hr": _as_float(settings.get("max_hr")),
        "hr_zones_json": json.dumps(settings.get("hr_zones") or []),
        "power_zones_json": json.dumps(settings.get("power_zones") or []),
        "power_zone_names_json": json.dumps(
            settings.get("power_zone_names") or []
        ),
        "raw_json": json.dumps(settings, ensure_ascii=False),
        "synced_at": _now(),
    }


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #


def _upsert(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
    rows: Iterable[Mapping[str, Any]],
    key: str,
) -> int:
    rows = list(rows)
    if not rows:
        return 0

    placeholders = ", ".join("?" for _ in columns)
    # No sobrescribir con NULL: si una sincronización parcial no trae una
    # métrica, se conserva el último valor válido ya guardado.
    updates = ", ".join(
        f"{col} = COALESCE(excluded.{col}, {table}.{col})"
        for col in columns
        if col != key
    )
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT({key}) DO UPDATE SET {updates}"
    )
    values = [tuple(row.get(col) for col in columns) for row in rows]
    with conn:
        conn.executemany(sql, values)
    return len(values)


def upsert_activities(
    conn: sqlite3.Connection, activities: Iterable[Mapping[str, Any]]
) -> int:
    rows = []
    for activity in activities:
        try:
            rows.append(activity_row(activity))
        except ValueError:
            continue
    return _upsert(conn, "activities", ACTIVITY_COLUMNS, rows, "activity_id")


def upsert_daily(conn: sqlite3.Connection, rows: Iterable[Mapping[str, Any]]) -> int:
    return _upsert(conn, "daily_metrics", DAILY_COLUMNS, rows, "date")


def upsert_intervals_wellness(
    conn: sqlite3.Connection, entries: Iterable[Mapping[str, Any]]
) -> int:
    rows = []
    for entry in entries:
        try:
            rows.append(intervals_wellness_row(entry))
        except ValueError:
            continue
    return _upsert(
        conn, "intervals_wellness", INTERVALS_WELLNESS_COLUMNS, rows, "date"
    )


def upsert_intervals_activities(
    conn: sqlite3.Connection, activities: Iterable[Mapping[str, Any]]
) -> int:
    rows = []
    for activity in activities:
        try:
            rows.append(intervals_activity_row(activity))
        except ValueError:
            continue
    return _upsert(
        conn,
        "intervals_activities",
        INTERVALS_ACTIVITY_COLUMNS,
        rows,
        "activity_id",
    )


def upsert_intervals_settings(
    conn: sqlite3.Connection, settings: Iterable[Mapping[str, Any]]
) -> int:
    rows = []
    for item in settings:
        try:
            rows.append(intervals_settings_row(item))
        except ValueError:
            continue
    return _upsert(
        conn, "intervals_sport_settings", INTERVALS_SETTINGS_COLUMNS, rows, "id"
    )


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #


def load_activities(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM activities ORDER BY start_time_local", conn
    )


def load_daily(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM daily_metrics ORDER BY date", conn)


def load_intervals_wellness(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM intervals_wellness ORDER BY date", conn
    )


def load_intervals_activities(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM intervals_activities ORDER BY start_time_local", conn
    )


def load_intervals_settings(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM intervals_sport_settings ORDER BY id", conn
    )


def counts(conn: sqlite3.Connection) -> dict[str, Any]:
    activities = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    daily = conn.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0]
    intervals_activities = conn.execute(
        "SELECT COUNT(*) FROM intervals_activities"
    ).fetchone()[0]
    intervals_wellness = conn.execute(
        "SELECT COUNT(*) FROM intervals_wellness"
    ).fetchone()[0]
    last_activity = conn.execute(
        "SELECT MAX(start_time_local) FROM activities"
    ).fetchone()[0]
    last_sync = conn.execute("SELECT MAX(synced_at) FROM activities").fetchone()[0]
    last_intervals_sync = conn.execute(
        "SELECT MAX(synced_at) FROM intervals_activities"
    ).fetchone()[0]
    return {
        "activities": activities,
        "daily": daily,
        "intervals_activities": intervals_activities,
        "intervals_wellness": intervals_wellness,
        "last_activity": last_activity,
        "last_sync": last_sync,
        "last_intervals_sync": last_intervals_sync,
    }


def latest_activity_date(conn: sqlite3.Connection) -> str | None:
    value = conn.execute("SELECT MAX(start_time_local) FROM activities").fetchone()[0]
    return value[:10] if value else None


# --------------------------------------------------------------------------- #
# Metadatos de la app (última sincronización automática, etc.)
# --------------------------------------------------------------------------- #


def get_meta(
    conn: sqlite3.Connection, key: str, default: str | None = None
) -> str | None:
    row = conn.execute(
        "SELECT value FROM app_meta WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def data_revision(conn: sqlite3.Connection) -> str:
    """Huella barata para invalidar la caché de lectura del dashboard."""
    parts = []
    for table in (
        "activities",
        "daily_metrics",
        "intervals_wellness",
        "intervals_activities",
        "intervals_sport_settings",
    ):
        row = conn.execute(
            f"SELECT COUNT(*) AS total, MAX(synced_at) AS updated FROM {table}"
        ).fetchone()
        parts.append(f"{table}:{row['total']}:{row['updated'] or ''}")
    return "|".join(parts)
