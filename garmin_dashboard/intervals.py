"""Cliente mínimo para la API de intervals.icu.

La autenticación es HTTP Basic con usuario ``API_KEY`` y la clave como
contraseña. El atleta ``0`` hace referencia al dueño de la clave.

Documentación: https://intervals.icu/api-docs.html
"""

from __future__ import annotations

import base64
import gzip
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import config

BASE_URL = "https://intervals.icu/api/v1"


class IntervalsError(RuntimeError):
    """Error de configuración o de la API de intervals.icu."""


def is_configured() -> bool:
    return bool(config.INTERVALS_API_KEY)


def create_client() -> "IntervalsClient":
    return IntervalsClient()


class IntervalsClient:
    def __init__(
        self,
        api_key: str | None = None,
        athlete_id: str | None = None,
        *,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or config.INTERVALS_API_KEY
        self.athlete_id = str(athlete_id or config.INTERVALS_ATHLETE_ID or "0")
        self.timeout = timeout
        if not self.api_key:
            raise IntervalsError(
                "Falta INTERVALS_API_KEY. Añádela a tu `.env` (la tienes en "
                "intervals.icu → Settings → Developer Settings)."
            )

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{BASE_URL}{path}"
        if params:
            clean = {key: value for key, value in params.items() if value is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"

        credentials = base64.b64encode(
            f"API_KEY:{self.api_key}".encode("utf-8")
        ).decode("ascii")
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Basic {credentials}",
                "Accept": "application/json",
                "User-Agent": "garmin-dashboard/1.0",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if exc.code == 401:
                raise IntervalsError(
                    "intervals.icu ha rechazado la API key (401). Revisa "
                    "INTERVALS_API_KEY."
                ) from exc
            if exc.code == 403:
                raise IntervalsError(
                    "La API key no tiene permiso para este recurso (403). "
                    "Comprueba los permisos en intervals.icu → Settings."
                ) from exc
            if exc.code == 429:
                raise IntervalsError(
                    "intervals.icu ha limitado las peticiones (429). Espera "
                    "unos minutos y vuelve a intentarlo."
                ) from exc
            message = f"Error {exc.code} de intervals.icu"
            if detail:
                message += f": {detail[:300]}"
            raise IntervalsError(message) from exc
        except urllib.error.URLError as exc:
            raise IntervalsError(
                f"No se pudo conectar con intervals.icu: {exc.reason}"
            ) from exc

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise IntervalsError(
                "intervals.icu devolvió una respuesta que no es JSON."
            ) from exc

    # ------------------------------------------------------------------ #
    # Endpoints
    # ------------------------------------------------------------------ #

    def get_wellness(self, oldest: str, newest: str) -> list[dict[str, Any]]:
        """CTL, ATL, TSB, sueño, FC en reposo, HRV y peso por día."""
        data = self._get(
            f"/athlete/{self.athlete_id}/wellness",
            {"oldest": oldest, "newest": newest},
        )
        return data if isinstance(data, list) else []

    def get_sport_settings(self) -> list[dict[str, Any]]:
        """Ajustes por deporte: FTP, LTHR, zonas de FC y de potencia."""
        data = self._get(f"/athlete/{self.athlete_id}/sport-settings")
        return data if isinstance(data, list) else []

    def get_activities(
        self, oldest: str | None = None, newest: str | None = None
    ) -> list[dict[str, Any]]:
        """Actividades con carga, potencia y tiempo en zonas."""
        data = self._get(
            f"/athlete/{self.athlete_id}/activities",
            {"oldest": oldest, "newest": newest},
        )
        return data if isinstance(data, list) else []

    def get_activity_streams(
        self,
        activity_id: str,
        types: str = "time,watts,distance,altitude,heartrate,cadence,velocity_smooth",
    ) -> list[dict[str, Any]]:
        """Descarga las series temporales de una actividad concreta."""
        data = self._get(
            f"/activity/{urllib.parse.quote(str(activity_id), safe='')}/streams",
            {"types": types},
        )
        return data if isinstance(data, list) else []

    def get_activity_fit_file(self, activity_id: str) -> bytes:
        """Descarga el FIT generado por intervals.icu para una actividad."""
        path = f"{BASE_URL}/activity/{urllib.parse.quote(str(activity_id), safe='')}/fit-file"
        credentials = base64.b64encode(
            f"API_KEY:{self.api_key}".encode("utf-8")
        ).decode("ascii")
        request = urllib.request.Request(
            path,
            headers={
                "Authorization": f"Basic {credentials}",
                "Accept": "application/octet-stream",
                "User-Agent": "garmin-dashboard/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                message = f"Error {exc.code} al descargar el FIT de intervals.icu"
                if detail:
                    message += f": {detail}"
            else:
                message = f"No se pudo conectar con intervals.icu: {exc.reason}"
            raise IntervalsError(message) from exc
        if payload.startswith(bytes((0x1F, 0x8B))):
            try:
                payload = gzip.decompress(payload)
            except OSError as exc:
                raise IntervalsError("El FIT descargado llegó comprimido pero no se pudo descomprimir.") from exc
        return payload
