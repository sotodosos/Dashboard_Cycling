"""Genera datos sintéticos para probar el dashboard sin cuenta de Garmin.

Incluye dos orígenes: actividades de Garmin y datos de intervals.icu
(CTL/ATL/TSB, sueño, FC en reposo, potencia y zonas).

Uso:

    python scripts/seed_demo.py --force
    # PowerShell
    $env:GARMIN_DB_PATH="data/demo.db"; streamlit run app.py
    # Bash
    GARMIN_DB_PATH=data/demo.db streamlit run app.py
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from garmin_dashboard import config, db  # noqa: E402

CYCLING_SPORTS = {
    "indoor_cycling",
    "cycling",
    "gravel_cycling",
    "mountain_biking",
    "virtual_ride",
}

INTERVALS_TYPES = {
    "indoor_cycling": "Ride",
    "cycling": "Ride",
    "gravel_cycling": "GravelRide",
    "mountain_biking": "MountainBikeRide",
    "virtual_ride": "VirtualRide",
}

SPORTS = {
    "indoor_cycling": {
        "names": [
            "Rodillo · Z2",
            "Rodillo · tempo",
            "Rodillo · series",
            "Sesión de rodillo",
        ],
        "duration": (45, 100),
        "speed": (29.0, 35.0),
        "hr": (124, 154),
        "elevation": (0, 10),
        "te": (2.2, 4.3),
        "power": (155, 225),
        "trainer": True,
    },
    "cycling": {
        "names": ["Salida en bici", "Fondo en carretera", "Puertos", "Ruta costera"],
        "distance": (38.0, 115.0),
        "speed": (24.0, 33.0),
        "hr": (123, 152),
        "elevation": (150, 1300),
        "te": (2.2, 4.4),
        "power": (145, 220),
        "trainer": False,
    },
    "gravel_cycling": {
        "names": ["Gravel entre caminos", "Ruta gravel"],
        "distance": (35.0, 90.0),
        "speed": (21.0, 28.0),
        "hr": (128, 156),
        "elevation": (400, 1500),
        "te": (2.5, 4.6),
        "power": (140, 205),
        "trainer": False,
    },
    "mountain_biking": {
        "names": ["MTB por el monte", "Ruta MTB"],
        "distance": (18.0, 52.0),
        "speed": (15.0, 23.0),
        "hr": (132, 162),
        "elevation": (350, 1200),
        "te": (2.6, 4.8),
        "power": (150, 220),
        "trainer": False,
    },
    "virtual_ride": {
        "names": ["Ciclismo virtual · carrera", "Ciclismo virtual · fondo"],
        "duration": (40, 85),
        "speed": (31.0, 38.0),
        "hr": (128, 158),
        "elevation": (0, 300),
        "te": (2.3, 4.5),
        "power": (165, 235),
        "trainer": True,
    },
    "running": {
        "names": ["Carrera matutina", "Rodaje suave", "Tirada larga"],
        "distance": (5.0, 16.0),
        "pace": (4.4, 6.4),
        "hr": (140, 168),
        "elevation": (20, 180),
        "te": (2.4, 4.6),
        "power": None,
        "trainer": False,
    },
    "strength_training": {
        "names": ["Fuerza · tren superior", "Fuerza · piernas", "Core"],
        "duration": (35, 70),
        "hr": (95, 130),
        "te": (0.8, 2.4),
        "power": None,
        "trainer": False,
    },
    "walking": {
        "names": ["Paseo", "Caminata rápida"],
        "distance": (3.0, 9.0),
        "pace": (9.5, 12.5),
        "hr": (90, 120),
        "elevation": (5, 80),
        "te": (0.3, 1.5),
        "power": None,
        "trainer": False,
    },
}

WEEKDAY_PLAN = [
    "indoor_cycling",
    "strength_training",
    "cycling",
    "indoor_cycling",
    None,
    "gravel_cycling",
    "cycling",
]

HR_ZONE_WEIGHTS = [0.11, 0.36, 0.29, 0.17, 0.07]
HR7_ZONE_WEIGHTS = [0.05, 0.24, 0.26, 0.20, 0.14, 0.08, 0.03]
POWER_ZONE_WEIGHTS = [0.07, 0.33, 0.27, 0.20, 0.09, 0.03, 0.01]
THRESHOLD_POWER_WEIGHTS = [0.03, 0.18, 0.24, 0.26, 0.17, 0.08, 0.04]

HR_ZONES = [0, 118, 135, 150, 163, 175, 190]
POWER_ZONES = [0, 120, 165, 200, 235, 265, 320]
FTP = 265
INDOOR_FTP = 255
LTHR = 168
MAX_HR = 190


def _round(value: float, decimals: int = 1) -> float:
    return round(value, decimals)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _weighted_split(total: float, weights: list[float]) -> list[float]:
    return [total * weight for weight in weights]


def _jitter_weights(
    weights: list[float], rng: random.Random, spread: float = 0.22
) -> list[float]:
    """Mantiene la forma de la distribución con pequeñas variaciones."""
    varied = [weight * rng.uniform(1 - spread, 1 + spread) for weight in weights]
    total = sum(varied) or 1.0
    return [value / total for value in varied]


def _activity(
    activity_id: int,
    sport: str,
    start: datetime,
    rng: random.Random,
) -> dict:
    spec = SPORTS[sport]
    name = rng.choice(spec["names"])

    duration_override = spec.get("duration")
    if duration_override:
        duration_min = rng.uniform(*duration_override)
        if "speed" in spec:
            speed = rng.uniform(*spec["speed"])
            distance_m = duration_min / 60 * speed * 1000
        else:
            speed = 0.0
            distance_m = 0.0
    elif spec.get("pace"):
        distance_km = rng.uniform(*spec["distance"])
        pace = rng.uniform(*spec["pace"])
        duration_min = distance_km * pace
        speed = 60 / pace
        distance_m = distance_km * 1000
    else:
        distance_km = rng.uniform(*spec["distance"])
        speed = rng.uniform(*spec["speed"])
        duration_min = distance_km / speed * 60
        distance_m = distance_km * 1000

    duration_s = duration_min * 60
    avg_hr = rng.uniform(*spec["hr"])

    weights = _jitter_weights(HR_ZONE_WEIGHTS, rng)
    zones = _weighted_split(duration_s, weights)

    start_local = start.replace(
        hour=rng.randint(7, 19), minute=rng.choice([0, 5, 15, 30, 45])
    )
    calories = duration_min * rng.uniform(7.5, 12.0)
    power_spec = spec.get("power")
    avg_power = rng.uniform(*power_spec) if power_spec else None
    weighted_power = avg_power * rng.uniform(1.02, 1.08) if avg_power else None

    return {
        "activityId": activity_id,
        "activityName": name,
        "startTimeLocal": start_local.strftime("%Y-%m-%d %H:%M:%S"),
        "startTimeGMT": (start_local - timedelta(hours=2)).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "activityType": {"typeId": 1, "typeKey": sport},
        "locationName": rng.choice(
            ["Madrid", "Sierra de Guadarrama", "Casa", "Segovia"]
        ),
        "duration": _round(duration_s, 2),
        "movingDuration": _round(duration_s * 0.96, 2),
        "elapsedDuration": _round(duration_s * 1.03, 2),
        "distance": _round(distance_m, 1),
        "calories": _round(calories),
        "averageHR": _round(avg_hr),
        "maxHR": _round(avg_hr + rng.uniform(8, 25)),
        "averageSpeed": _round(speed, 3),
        "maxSpeed": _round(speed * rng.uniform(1.15, 1.45), 3),
        "elevationGain": _round(rng.uniform(*spec.get("elevation", (0, 50)))),
        "elevationLoss": _round(rng.uniform(*spec.get("elevation", (0, 50)))),
        "trainingEffect": _round(rng.uniform(*spec["te"]), 1),
        "anaerobicTrainingEffect": _round(rng.uniform(0.2, 2.8), 1),
        "vO2MaxValue": _round(rng.uniform(48, 54), 1),
        "activityTrainingLoad": _round(duration_min * rng.uniform(0.55, 1.65)),
        "avgPower": _round(avg_power) if avg_power else None,
        "weightedAvgPower": _round(weighted_power) if weighted_power else None,
        "hrTimeInZone_1": _round(zones[0]),
        "hrTimeInZone_2": _round(zones[1]),
        "hrTimeInZone_3": _round(zones[2]),
        "hrTimeInZone_4": _round(zones[3]),
        "hrTimeInZone_5": _round(zones[4]),
    }


def _intervals_activity(
    garmin_activity: dict,
    rng: random.Random,
) -> dict | None:
    """Convierte una actividad de ciclismo de Garmin al formato de intervals."""
    sport = garmin_activity["activityType"]["typeKey"]
    if sport not in CYCLING_SPORTS:
        return None

    interval_type = INTERVALS_TYPES[sport]
    trainer = bool(SPORTS[sport].get("trainer"))
    duration_s = float(garmin_activity["duration"])
    avg_power = garmin_activity.get("avgPower") or rng.uniform(150, 220)
    weighted_power = (
        garmin_activity.get("weightedAvgPower") or avg_power * rng.uniform(1.02, 1.09)
    )

    weights = _jitter_weights(
        THRESHOLD_POWER_WEIGHTS if rng.random() < 0.35 else POWER_ZONE_WEIGHTS, rng
    )
    power_secs = _weighted_split(duration_s, weights)

    hr_weights = _jitter_weights(HR7_ZONE_WEIGHTS, rng)
    hr_secs = _weighted_split(duration_s, hr_weights)

    load = float(garmin_activity["activityTrainingLoad"])
    intensity = _clamp(
        (weighted_power / (INDOOR_FTP if trainer else FTP)) * 100, 45, 125
    )

    return {
        "id": f"i{garmin_activity['activityId']}",
        "start_date_local": garmin_activity["startTimeLocal"].replace(" ", "T"),
        "type": interval_type,
        "name": garmin_activity["activityName"],
        "trainer": trainer,
        "moving_time": _round(duration_s, 0),
        "elapsed_time": _round(duration_s * 1.03, 0),
        "distance": garmin_activity["distance"],
        "icu_distance": garmin_activity["distance"],
        "calories": garmin_activity["calories"],
        "average_heartrate": garmin_activity["averageHR"],
        "max_heartrate": garmin_activity["maxHR"],
        "average_speed": garmin_activity["averageSpeed"],
        "max_speed": garmin_activity["maxSpeed"],
        "total_elevation_gain": garmin_activity["elevationGain"],
        "total_elevation_loss": garmin_activity["elevationLoss"],
        "icu_training_load": load,
        "icu_intensity": _round(intensity, 1),
        "icu_average_watts": _round(avg_power),
        "icu_weighted_avg_watts": _round(weighted_power),
        "icu_ftp": INDOOR_FTP if trainer else FTP,
        "average_cadence": _round(rng.uniform(78, 95)),
        "icu_hr_zone_times": [_round(value, 0) for value in hr_secs],
        "icu_zone_times": [
            {"id": f"Z{index + 1}", "secs": _round(value, 0)}
            for index, value in enumerate(power_secs)
        ],
    }


def _daily(
    date_str: str,
    rng: random.Random,
    *,
    sleep_s: float | None = None,
    resting_hr: int | None = None,
) -> dict:
    sleep_s = sleep_s if sleep_s is not None else rng.uniform(6.0, 8.6) * 3600
    resting_hr = resting_hr or rng.randint(47, 56)
    stats = {
        "restingHeartRate": resting_hr,
        "minHeartRate": max(resting_hr - rng.randint(4, 9), 35),
        "maxHeartRate": rng.randint(150, 185),
        "averageStressLevel": rng.randint(18, 45),
        "bodyBatteryLowestValue": rng.randint(12, 40),
        "bodyBatteryHighestValue": rng.randint(70, 100),
        "totalSteps": rng.randint(6000, 19000),
        "totalKilocalories": rng.randint(2200, 3000),
        "activeKilocalories": rng.randint(350, 1000),
        "vO2MaxValue": _round(rng.uniform(48, 54), 1),
    }
    sleep = {
        "dailySleepDTO": {
            "sleepTimeSeconds": _round(sleep_s),
            "sleepScores": {"overall": {"value": rng.randint(55, 95)}},
        }
    }
    hrv = {
        "hrvSummary": {
            "lastNightAvg": rng.randint(42, 82),
            "weeklyAvg": rng.randint(45, 75),
            "status": rng.choice(["balanced", "balanced", "unbalanced", "low"]),
        }
    }
    readiness = [
        {
            "score": rng.randint(45, 92),
            "trainingReadinessScore": rng.randint(45, 92),
        }
    ]
    return db.daily_row(
        date_str, stats=stats, sleep=sleep, hrv=hrv, readiness=readiness
    )


def _settings() -> dict:
    return {
        "id": 1,
        "types": list(INTERVALS_TYPES.values())
        + ["EBikeRide", "EMountainBikeRide", "TrackRide", "Cyclocross"],
        "name": "Ciclismo",
        "ftp": FTP,
        "indoor_ftp": INDOOR_FTP,
        "lthr": LTHR,
        "max_hr": MAX_HR,
        "hr_zones": HR_ZONES,
        "power_zones": POWER_ZONES,
        "power_zone_names": [
            "Recovery",
            "Endurance",
            "Tempo",
            "Sweet Spot",
            "Threshold",
            "VO2 Max",
            "Anaerobic",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/demo.db", help="Ruta de la BD demo")
    parser.add_argument(
        "--days",
        type=int,
        default=430,
        help="Días de historial (por defecto 430, más de un año)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="Sobrescribe la BD")
    args = parser.parse_args()

    db_path = Path(args.db)
    if db_path.exists() and not args.force:
        print(f"{db_path} ya existe. Usa --force para sobrescribirla.")
        return 1
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{db_path}{suffix}")
        if candidate.exists():
            candidate.unlink()

    rng = random.Random(args.seed)
    conn = db.connect(db_path)

    today = date.today()
    days = [today - timedelta(days=offset) for offset in range(args.days, -1, -1)]

    activities: list[dict] = []
    intervals_activities: list[dict] = []
    load_by_date: dict[str, float] = {}
    activity_id = 100000

    # 1) Actividades de Garmin y su equivalente en intervals.icu.
    for current in days:
        sport = WEEKDAY_PLAN[current.weekday()]
        if rng.random() < 0.12:
            sport = rng.choice(list(SPORTS))
        if rng.random() < 0.10:
            sport = None
        if sport is None:
            continue

        activity_id += 1
        start = datetime.combine(current, time(8, 0))
        activity = _activity(activity_id, sport, start, rng)
        activities.append(activity)
        load_by_date[current.isoformat()] = load_by_date.get(
            current.isoformat(), 0.0
        ) + float(activity["activityTrainingLoad"])

        interval_activity = _intervals_activity(activity, rng)
        if interval_activity is not None:
            intervals_activities.append(interval_activity)

        if rng.random() < 0.12:
            activity_id += 1
            extra = _activity(activity_id, "walking", start, rng)
            activities.append(extra)
            load_by_date[current.isoformat()] = load_by_date.get(
                current.isoformat(), 0.0
            ) + float(extra["activityTrainingLoad"])

    # 2) Wellness de intervals.icu: CTL, ATL y TSB con EWMA estándar.
    daily_rows: list[dict] = []
    wellness_rows: list[dict] = []
    ctl = 0.0
    atl = 0.0
    ctl_history: list[float] = []

    for current in days:
        key = current.isoformat()
        load = load_by_date.get(key, 0.0)
        ctl += (load - ctl) / 42.0
        atl += (load - atl) / 7.0
        ctl_history.append(ctl)
        ramp_rate = ctl - (ctl_history[-8] if len(ctl_history) >= 8 else 0.0)
        tsb = ctl - atl

        sleep_h = _clamp(
            7.35 - load / 450.0 + rng.gauss(0, 0.55), 5.3, 9.3
        )
        sleep_s = sleep_h * 3600
        resting_hr = int(
            round(
                _clamp(
                    49.5
                    + (atl - ctl) * 0.035
                    + load / 900.0
                    + rng.gauss(0, 1.1),
                    42,
                    62,
                )
            )
        )
        hrv = _round(
            _clamp(66 - (atl - ctl) * 0.35 + rng.gauss(0, 5), 28, 105), 0
        )
        sleep_score = _clamp(
            48 + (sleep_h - 6) * 13 + rng.gauss(0, 6), 40, 98
        )
        weight = _round(73.4 - ctl * 0.012 + rng.gauss(0, 0.35), 1)

        wellness_rows.append(
            {
                "id": key,
                "ctl": _round(ctl, 1),
                "atl": _round(atl, 1),
                "tsb": _round(tsb, 1),
                "rampRate": _round(ramp_rate, 1),
                "restingHR": resting_hr,
                "sleepSecs": int(sleep_s),
                "sleepScore": _round(sleep_score, 0),
                "hrv": hrv,
                "weight": weight,
            }
        )
        daily_rows.append(
            _daily(key, rng, sleep_s=sleep_s, resting_hr=resting_hr)
        )

    saved = db.upsert_activities(conn, activities)
    saved_daily = db.upsert_daily(conn, daily_rows)
    saved_wellness = db.upsert_intervals_wellness(conn, wellness_rows)
    saved_intervals = db.upsert_intervals_activities(conn, intervals_activities)
    saved_settings = db.upsert_intervals_settings(conn, [_settings()])

    last = wellness_rows[-1]
    print(f"BD demo: {db_path.resolve()}")
    print(f"Actividades Garmin:    {saved}")
    print(f"Actividades intervals: {saved_intervals}")
    print(f"Días de salud Garmin:  {saved_daily}")
    print(f"Días wellness:         {saved_wellness}")
    print(f"Ajustes de deporte:    {saved_settings}")
    print(
        f"Último estado: CTL {last['ctl']} · ATL {last['atl']} "
        f"· TSB {last['tsb']}"
    )
    print()
    print("Para verla:")
    print('  PowerShell: $env:GARMIN_DB_PATH="data/demo.db"; streamlit run app.py')
    print("  Bash:       GARMIN_DB_PATH=data/demo.db streamlit run app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
