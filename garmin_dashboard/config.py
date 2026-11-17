"""Configuración central del proyecto.

Las credenciales se leen de variables de entorno (o de un fichero ``.env``
en la raíz del proyecto). Nunca se guardan en el repositorio.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .secure_storage import SecureStorageError, load_json

BASE_DIR = Path(__file__).resolve().parent.parent

# Carga .env una sola vez; no sobreescribe variables ya definidas en el sistema.
load_dotenv(BASE_DIR / ".env", override=False)


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


DATA_DIR = _path_from_env("GARMIN_DATA_DIR", BASE_DIR / "data")
DB_PATH = _path_from_env("GARMIN_DB_PATH", DATA_DIR / "garmin.db")
TOKENSTORE = _path_from_env("GARMIN_TOKENSTORE", DATA_DIR / "tokens.json")
ENCRYPTED_TOKENSTORE = DATA_DIR / "tokens.dpapi"
SECURE_CREDENTIALS = DATA_DIR / "credentials.dpapi"
try:
    _credentials = load_json(SECURE_CREDENTIALS) or {}
    SECURE_STORAGE_ERROR = None
except SecureStorageError as exc:
    _credentials = {}
    SECURE_STORAGE_ERROR = str(exc)

# Secretos solo desde el archivo protegido por DPAPI; nunca desde .env.
EMAIL = _credentials.get("garmin_email")
PASSWORD = _credentials.get("garmin_password")

# Zona horaria usada solo para mostrar/etiquetar datos, no para las consultas.
TIMEZONE = os.getenv("GARMIN_TIMEZONE", "Europe/Madrid")

# intervals.icu
INTERVALS_API_KEY = _credentials.get("intervals_api_key")
INTERVALS_ATHLETE_ID = os.getenv("INTERVALS_ATHLETE_ID", "0")


def _flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().casefold() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    try:
        return int(str(value).strip()) if value else default
    except (TypeError, ValueError):
        return default


# Sincronización automática al arrancar.
AUTO_SYNC_ENABLED = _flag("GARMIN_AUTO_SYNC", True)
AUTO_SYNC_TTL_MINUTES = max(_int_env("GARMIN_AUTO_SYNC_TTL_MINUTES", 60), 0)
AUTO_SYNC_DAYS = max(_int_env("GARMIN_AUTO_SYNC_DAYS", 7), 1)


def is_demo() -> bool:
    """Modo demostración: nunca se usan credenciales reales."""
    return _flag("GARMIN_DEMO", False) or DB_PATH.stem.casefold() == "demo"
