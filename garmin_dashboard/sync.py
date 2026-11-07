"""Descarga de datos de Garmin Connect y volcado a SQLite."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Protocol

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from . import db
from .intervals import IntervalsClient, IntervalsError

ProgressFn = Callable[[int, int, str], None]


class SyncError(RuntimeError):
    """Error durante la sincronización con un mensaje legible."""


class GarminApi(Protocol):
    def get_activities_by_date(self, *args: Any, **kwargs: Any) -> list[dict]: ...

    def get_stats(self, cdate: str) -> dict: ...

    def get_sleep_data(self, cdate: str) -> dict: ...

    def get_hrv_data(self, cdate: str) -> dict | None: ...

    def get_training_readiness(self, cdate: str) -> list[dict]: ...

    def get_training_status(self, cdate: str) -> dict: ...


def _today() -> date:
    return date.today()


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SyncError(
            f"Fecha inválida: {value!r}. El formato debe ser YYYY-MM-DD."
        ) from exc


def _notify(progress: ProgressFn | None, done: int, total: int, message: str) -> None:
    if progress is not None:
        progress(done, total, message)


def _date_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Trocea un rango en años naturales.

    Evita pedir décadas de actividades en una sola petición (la librería
    pagina internamente y tiene un límite de páginas).
    """
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(date(cursor.year, 12, 31), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def sync_activities(
    api: GarminApi,
    conn,
    *,
    since: str | None = None,
    until: str | None = None,
    full: bool = False,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Descarga actividades y las guarda en SQLite.

    Por defecto hace una sincronización incremental desde la última actividad
    guardada (con 7 días de margen para captar ediciones). Usa ``full=True``
    para descargar todo el historial.
    """
    end = _parse_date(until) if until else _today()

    if since:
        start = _parse_date(since)
    elif full:
        start = date(2000, 1, 1)
    else:
        last = db.latest_activity_date(conn)
        start = (
            _parse_date(last) - timedelta(days=7)
            if last
            else date(2000, 1, 1)
        )

    if start > end:
        return {
            "fetched": 0,
            "saved": 0,
            "since": start.isoformat(),
            "until": end.isoformat(),
            "chunks": 0,
        }

    chunks = _date_chunks(start, end)
    fetched = 0
    saved = 0

    for index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        _notify(
            progress,
            index - 1,
            len(chunks),
            f"Descargando {chunk_start.year}...",
        )
        try:
            activities = api.get_activities_by_date(
                chunk_start.isoformat(),
                chunk_end.isoformat(),
                sortorder="asc",
            )
        except GarminConnectTooManyRequestsError as exc:
            raise SyncError(
                "Garmin ha limitado las peticiones (HTTP 429). Espera unos "
                "minutos y vuelve a sincronizar."
            ) from exc
        except GarminConnectAuthenticationError as exc:
            raise SyncError(
                "La sesión de Garmin ha caducado. Ejecuta `python main.py login`."
            ) from exc

        fetched += len(activities)
        saved += db.upsert_activities(conn, activities)

    _notify(progress, len(chunks), len(chunks), "Actividades guardadas")

    return {
        "fetched": fetched,
        "saved": saved,
        "skipped": fetched - saved,
        "since": start.isoformat(),
        "until": end.isoformat(),
        "chunks": len(chunks),
    }


def _safe_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Ejecuta una llamada tolerando días sin datos o endpoints no soportados."""
    try:
        return fn(*args, **kwargs)
    except GarminConnectAuthenticationError:
        raise
    except Exception:
        return None


def sync_daily(
    api: GarminApi,
    conn,
    *,
    days: int = 30,
    until: str | None = None,
    include_training_status: bool = False,
    pause: float = 0.2,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Descarga métricas de salud/estado diario (sueño, HRV, recuperación...).

    Hace varias peticiones por día, así que por defecto solo cubre los últimos
    30 días. Los días sin datos se ignoran en lugar de abortar la sincronización.
    """
    end = _parse_date(until) if until else _today()
    start = end - timedelta(days=max(days - 1, 0))
    total_days = (end - start).days + 1

    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, offset in enumerate(range(total_days), start=1):
        current = start + timedelta(days=offset)
        current_str = current.isoformat()
        _notify(progress, index - 1, total_days, f"Día {current_str}")

        stats = _safe_call(api.get_stats, current_str)
        sleep = _safe_call(api.get_sleep_data, current_str)
        hrv = _safe_call(api.get_hrv_data, current_str)
        readiness = _safe_call(api.get_training_readiness, current_str)
        training_status = (
            _safe_call(api.get_training_status, current_str)
            if include_training_status
            else None
        )

        if not any((stats, sleep, hrv, readiness, training_status)):
            errors.append(current_str)
            continue

        rows.append(
            db.daily_row(
                current_str,
                stats=stats,
                sleep=sleep,
                hrv=hrv,
                readiness=readiness,
                training_status=training_status,
            )
        )

        if pause:
            time.sleep(pause)

    _notify(progress, total_days, total_days, "Salud guardada")

    saved = db.upsert_daily(conn, rows)
    return {
        "saved": saved,
        "empty": errors,
        "since": start.isoformat(),
        "until": end.isoformat(),
    }


def sync_intervals(
    client: IntervalsClient,
    conn,
    *,
    days: int = 365,
    until: str | None = None,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Descarga aptitud (CTL/ATL/TSB), wellness y actividades de intervals.icu.

    ``days`` permite traer un histórico largo de una sola vez: wellness y
    actividades se piden por rango de fechas, no día a día.
    """
    end = _parse_date(until) if until else _today()
    start = end - timedelta(days=max(days - 1, 0))
    oldest = start.isoformat()
    newest = end.isoformat()

    try:
        _notify(progress, 0, 3, "Descargando wellness (CTL/ATL/TSB)...")
        wellness = client.get_wellness(oldest, newest)

        _notify(progress, 1, 3, "Descargando ajustes y zonas...")
        settings = client.get_sport_settings()

        _notify(progress, 2, 3, "Descargando actividades...")
        activities = client.get_activities(oldest, newest)
    except IntervalsError as exc:
        raise SyncError(str(exc)) from exc

    saved_wellness = db.upsert_intervals_wellness(conn, wellness)
    saved_settings = db.upsert_intervals_settings(conn, settings)
    saved_activities = db.upsert_intervals_activities(conn, activities)

    _notify(progress, 3, 3, "Datos de intervals.icu guardados")

    return {
        "since": oldest,
        "until": newest,
        "wellness": saved_wellness,
        "activities": saved_activities,
        "settings": saved_settings,
    }
