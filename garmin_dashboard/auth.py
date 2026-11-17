"""Autenticación contra Garmin Connect.

La librería ``garminconnect`` necesita un fichero JSON para sus tokens. El
dashboard lo crea temporalmente y protege la sesión persistente con Windows
DPAPI, ligado al usuario que ejecuta la aplicación.

La primera vez hay que ejecutar ``python main.py login`` en una terminal
interactiva para poder introducir el código MFA si la cuenta lo requiere.
"""

from __future__ import annotations

import json
import tempfile
from typing import Callable
from pathlib import Path

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from . import config
from .secure_storage import SecureStorageError, delete, load_json, save_json


class AuthError(RuntimeError):
    """Error de autenticación con un mensaje apto para mostrar al usuario."""


def _read_mfa_code() -> str:
    return input("Código MFA de Garmin: ").strip()


def login(
    email: str | None = None,
    password: str | None = None,
    *,
    tokenstore: str | None = None,
    interactive: bool = True,
    mfa_prompt: Callable[[], str] | None = None,
) -> Garmin:
    """Crea un cliente autenticado de Garmin Connect.

    Intenta primero reutilizar los tokens guardados; si no existen o han
    caducado, hace login con las credenciales del entorno.

    Args:
        email: Email de Garmin. Por defecto, el almacén cifrado local.
        password: Contraseña de Garmin. Por defecto, el almacén cifrado local.
        tokenstore: Ruta opcional del archivo JSON antiguo que se migrará.
        interactive: Si es ``True`` permite pedir el código MFA por consola.
            En Streamlit debe ser ``False``: si hace falta MFA hay que lanzar
            antes ``python main.py login``.
        mfa_prompt: Callable alternativa para obtener el código MFA.
    """
    email = email or config.EMAIL
    password = password or config.PASSWORD
    encrypted_tokenstore = config.ENCRYPTED_TOKENSTORE
    legacy_tokenstore = Path(tokenstore or config.TOKENSTORE)

    if config.SECURE_STORAGE_ERROR:
        raise AuthError(config.SECURE_STORAGE_ERROR)
    if not encrypted_tokenstore.exists() and legacy_tokenstore.exists():
        try:
            legacy_tokens = json.loads(legacy_tokenstore.read_text(encoding="utf-8"))
            save_json(encrypted_tokenstore, legacy_tokens)
            delete(legacy_tokenstore)
        except (OSError, json.JSONDecodeError, SecureStorageError) as exc:
            raise AuthError(
                "No se pudo cifrar la sesión Garmin existente. "
                "Se conserva el archivo original para evitar perderla."
            ) from exc

    if mfa_prompt is None and interactive:
        mfa_prompt = _read_mfa_code

    api = Garmin(
        email=email,
        password=password,
        prompt_mfa=mfa_prompt,
        # En modo no interactivo nunca debe quedarse esperando una entrada.
        return_on_mfa=False,
    )

    try:
        with tempfile.TemporaryDirectory(prefix="dashboard-cycling-") as temp_dir:
            tokenstore_path = Path(temp_dir) / "tokens.json"
            saved_tokens = load_json(encrypted_tokenstore)
            if saved_tokens is not None:
                tokenstore_path.write_text(
                    json.dumps(saved_tokens, ensure_ascii=False), encoding="utf-8"
                )
            api.login(str(tokenstore_path))
            if tokenstore_path.exists():
                save_json(
                    encrypted_tokenstore,
                    json.loads(tokenstore_path.read_text(encoding="utf-8")),
                )
    except GarminConnectTooManyRequestsError as exc:
        raise AuthError(
            "Garmin está limitando los intentos de login (HTTP 429). "
            "Espera unos minutos y vuelve a intentarlo."
        ) from exc
    except GarminConnectAuthenticationError as exc:
        message = str(exc)
        if not config.EMAIL and not email:
            message += (
                "\n\nNo hay credenciales cifradas. Ejecuta "
                "`python main.py credentials-set` o migra las actuales con "
                "`python main.py credentials-migrate`."
            )
        if "MFA" in message and not interactive:
            message += (
                "\n\nLa sesión ha caducado y Garmin pide MFA. Ejecuta "
                "`python main.py login` en una terminal para renovarla."
            )
        raise AuthError(message) from exc
    except GarminConnectConnectionError as exc:
        raise AuthError(
            "No se pudo conectar con Garmin Connect. Comprueba tu conexión "
            f"o inténtalo más tarde.\n\nDetalle: {exc}"
        ) from exc
    except SecureStorageError as exc:
        raise AuthError(str(exc)) from exc

    return api


def try_login(**kwargs) -> tuple[Garmin | None, str | None]:
    """Devuelve ``(api, error)`` sin lanzar excepciones.

    Útil para el dashboard: si falla el login se puede seguir mostrando lo
    que ya hay descargado en SQLite.
    """
    try:
        return login(**kwargs), None
    except AuthError as exc:
        return None, str(exc)
