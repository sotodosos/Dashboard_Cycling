"""Autenticación contra Garmin Connect.

La librería ``garminconnect`` guarda los tokens de sesión en un fichero JSON.
Reutilizamos ese fichero para no tener que introducir credenciales (ni el
código MFA) cada vez que arranca el dashboard.

La primera vez hay que ejecutar ``python main.py login`` en una terminal
interactiva para poder introducir el código MFA si la cuenta lo requiere.
"""

from __future__ import annotations

from typing import Callable

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from . import config


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
        email: Email de Garmin. Por defecto ``GARMIN_EMAIL``.
        password: Contraseña de Garmin. Por defecto ``GARMIN_PASSWORD``.
        tokenstore: Ruta del fichero de tokens. Por defecto ``data/tokens.json``.
        interactive: Si es ``True`` permite pedir el código MFA por consola.
            En Streamlit debe ser ``False``: si hace falta MFA hay que lanzar
            antes ``python main.py login``.
        mfa_prompt: Callable alternativa para obtener el código MFA.
    """
    email = email or config.EMAIL
    password = password or config.PASSWORD
    tokenstore_path = str(tokenstore or config.TOKENSTORE)

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
        api.login(tokenstore_path)
    except GarminConnectTooManyRequestsError as exc:
        raise AuthError(
            "Garmin está limitando los intentos de login (HTTP 429). "
            "Espera unos minutos y vuelve a intentarlo."
        ) from exc
    except GarminConnectAuthenticationError as exc:
        message = str(exc)
        if not config.EMAIL and not email:
            message += (
                "\n\nNo hay credenciales configuradas. Copia .env.example a .env "
                "y rellena GARMIN_EMAIL y GARMIN_PASSWORD."
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
