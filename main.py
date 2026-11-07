"""Punto de entrada de línea de comandos.

Uso habitual:

    python main.py login                 # primera vez / renovar sesión (MFA)
    python main.py sync                  # actividades nuevas
    python main.py sync --full           # todo el historial
    python main.py sync-health --days 30 # sueño, HRV, recuperación...
    python main.py status                # qué hay descargado
"""

from __future__ import annotations

import argparse
import sys

from garmin_dashboard import auth, config, db, intervals, sync


def _progress(done: int, total: int, message: str) -> None:
    total = max(total, 1)
    print(f"\r{message:<45} [{done}/{total}]", end="", flush=True)


def _finish_progress() -> None:
    print()


def cmd_login(_: argparse.Namespace) -> int:
    print("Conectando con Garmin Connect...")
    if not config.EMAIL or not config.PASSWORD:
        print(
            "Aviso: no hay credenciales en el entorno. Se intentará usar la "
            f"sesión guardada en {config.TOKENSTORE}.",
            file=sys.stderr,
        )
    api = auth.login(interactive=True)
    name = api.get_full_name()
    print(f"Login correcto: {name}")
    print(f"Tokens guardados en: {config.TOKENSTORE}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    conn = db.connect()
    api = auth.login(interactive=True)

    print("Sincronizando actividades...")
    result = sync.sync_activities(
        api,
        conn,
        since=args.since,
        until=args.until,
        full=args.full,
        progress=_progress,
    )
    _finish_progress()
    print(
        f"Actividades: {result['saved']} guardadas "
        f"({result['fetched']} descargadas) "
        f"del {result['since']} al {result['until']}."
    )

    if args.health:
        print(f"Sincronizando salud de los últimos {args.days} días...")
        health = sync.sync_daily(
            api,
            conn,
            days=args.days,
            include_training_status=args.include_training_status,
            progress=_progress,
        )
        _finish_progress()
        print(f"Días de salud guardados: {health['saved']}.")
        if health["empty"]:
            print(f"Días sin datos: {len(health['empty'])}.")

    return 0


def cmd_sync_health(args: argparse.Namespace) -> int:
    conn = db.connect()
    api = auth.login(interactive=True)
    print(f"Sincronizando salud de los últimos {args.days} días...")
    result = sync.sync_daily(
        api,
        conn,
        days=args.days,
        until=args.until,
        include_training_status=args.include_training_status,
        progress=_progress,
    )
    _finish_progress()
    print(
        f"Días guardados: {result['saved']} "
        f"({result['since']} → {result['until']})."
    )
    if result["empty"]:
        print(f"Días sin datos: {len(result['empty'])}.")
    return 0


def cmd_sync_intervals(args: argparse.Namespace) -> int:
    conn = db.connect()
    client = intervals.create_client()
    print(
        f"Sincronizando intervals.icu ({args.days} días: "
        f"{args.until or 'hoy'})..."
    )
    result = sync.sync_intervals(
        client,
        conn,
        days=args.days,
        until=args.until,
        progress=_progress,
    )
    _finish_progress()
    print(
        f"Wellness: {result['wellness']} días · "
        f"actividades: {result['activities']} · "
        f"ajustes de deporte: {result['settings']} "
        f"({result['since']} → {result['until']})."
    )
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    if not config.DB_PATH.exists():
        print(f"No hay base de datos todavía en {config.DB_PATH}.")
        print("Ejecuta `python main.py sync --full` para descargar tus datos.")
        return 0

    conn = db.connect()
    info = db.counts(conn)
    print(f"Base de datos: {config.DB_PATH}")
    print(f"Actividades Garmin:    {info['activities']}")
    print(f"Días de salud Garmin:  {info['daily']}")
    print(f"Actividades intervals: {info['intervals_activities']}")
    print(f"Días wellness intervals: {info['intervals_wellness']}")
    print(f"Última actividad: {info['last_activity'] or '–'}")
    print(f"Última sincronización Garmin: {info['last_sync'] or '–'}")
    print(f"Última sincronización intervals: {info['last_intervals_sync'] or '–'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="garmin-connect",
        description="Sincroniza tus datos de Garmin Connect en SQLite.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Inicia sesión y guarda los tokens").set_defaults(
        func=cmd_login
    )

    sync_parser = sub.add_parser(
        "sync", help="Descarga actividades (y opcionalmente salud)"
    )
    sync_parser.add_argument(
        "--full", action="store_true", help="Descarga todo el historial"
    )
    sync_parser.add_argument("--since", help="Fecha inicial YYYY-MM-DD")
    sync_parser.add_argument("--until", help="Fecha final YYYY-MM-DD")
    sync_parser.add_argument(
        "--health", action="store_true", help="Sincroniza también métricas diarias"
    )
    sync_parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Días de salud a descargar con --health (por defecto 30)",
    )
    sync_parser.add_argument(
        "--include-training-status",
        action="store_true",
        help="Incluye training status por día (una petición extra por día)",
    )
    sync_parser.set_defaults(func=cmd_sync)

    health_parser = sub.add_parser(
        "sync-health", help="Descarga sueño, HRV, recuperación, etc."
    )
    health_parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Número de días hacia atrás (por defecto 30)",
    )
    health_parser.add_argument("--until", help="Fecha final YYYY-MM-DD")
    health_parser.add_argument(
        "--include-training-status",
        action="store_true",
        help="Incluye training status por día (una petición extra por día)",
    )
    health_parser.set_defaults(func=cmd_sync_health)

    intervals_parser = sub.add_parser(
        "sync-intervals",
        help="Descarga CTL/ATL/TSB, wellness y actividades de intervals.icu",
    )
    intervals_parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Número de días hacia atrás (por defecto 365)",
    )
    intervals_parser.add_argument("--until", help="Fecha final YYYY-MM-DD")
    intervals_parser.set_defaults(func=cmd_sync_intervals)

    sub.add_parser("status", help="Muestra el estado de la base de datos").set_defaults(
        func=cmd_status
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (auth.AuthError, sync.SyncError, intervals.IntervalsError) as exc:
        _finish_progress()
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        _finish_progress()
        print("\nCancelado.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
