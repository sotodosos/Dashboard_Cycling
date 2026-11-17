"""Cifrado local de credenciales y tokens con Windows DPAPI.

Los datos protegidos solo se pueden descifrar desde el perfil de Windows que
los cifró. No se guardan claves de cifrado junto a los archivos protegidos.
"""

from __future__ import annotations

import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Any


class SecureStorageError(RuntimeError):
    """Error al proteger o recuperar datos locales."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise SecureStorageError("El almacén cifrado requiere Windows DPAPI.")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source_buffer = ctypes.create_string_buffer(data, len(data))
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    target = _DataBlob()

    if protect:
        operation = crypt32.CryptProtectData
        operation.argtypes = [
            ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
    else:
        operation = crypt32.CryptUnprotectData
        operation.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
    operation.restype = wintypes.BOOL

    if protect:
        ok = operation(ctypes.byref(source), "Dashboard Cycling", None, None, None, 0, ctypes.byref(target))
    else:
        description = wintypes.LPWSTR()
        ok = operation(ctypes.byref(source), ctypes.byref(description), None, None, None, 0, ctypes.byref(target))
        if description:
            kernel32.LocalFree(description)

    if not ok:
        raise SecureStorageError(f"Windows no pudo {'cifrar' if protect else 'descifrar'} los datos (error {ctypes.get_last_error()}).")

    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(target.pbData)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def save_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        _atomic_write(path, _dpapi(payload, protect=True))
    except (OSError, TypeError, ValueError) as exc:
        raise SecureStorageError(f"No se pudo guardar el almacén cifrado {path.name}.") from exc


def load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(_dpapi(path.read_bytes(), protect=False).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecureStorageError(f"No se pudo leer el almacén cifrado {path.name}.") from exc


def delete(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise SecureStorageError(f"No se pudo retirar el archivo antiguo {path.name}.") from exc
