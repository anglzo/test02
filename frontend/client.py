"""
client.py — cómo habla el frontend con el backend.

BACKEND_MODE (en frontend/.env):
  http       llama a la API de Azure Functions en BACKEND_URL (con FUNCTION_KEY si aplica).
  inprocess  importa el código de backend/ y lo ejecuta en el mismo proceso de Streamlit.
             No necesita Azure Functions Core Tools ni un Function App: solo Python y las
             claves de los servicios de IA (en backend/.env o backend/local.settings.json).
Si no se define, usa http cuando hay BACKEND_URL y inprocess cuando no.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import requests

TIMEOUT = 240
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"


class ApiError(Exception):
    pass


def mode() -> str:
    m = os.environ.get("BACKEND_MODE", "").strip().lower()
    if m in ("http", "inprocess"):
        return m
    return "http" if os.environ.get("BACKEND_URL", "").strip() else "inprocess"


def _url() -> str:
    return os.environ.get("BACKEND_URL", "http://localhost:7071/api").strip().rstrip("/")


def _headers() -> dict:
    key = os.environ.get("FUNCTION_KEY", "").strip()
    return {"x-functions-key": key} if key else {}


def _service():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    import service  # noqa: PLC0415  (backend/service.py)
    return service


def _http_error(resp: requests.Response) -> ApiError:
    try:
        return ApiError(resp.json().get("error") or f"Error {resp.status_code}")
    except ValueError:
        return ApiError(f"Error {resp.status_code}: {resp.text[:200]}")


def summarize(file_name: str, data: bytes, mime: str, language: str) -> dict:
    if mode() == "inprocess":
        service = _service()
        try:
            return service.summarize_file(file_name, data, language)
        except service.ServiceError as exc:
            raise ApiError(str(exc)) from exc
    try:
        resp = requests.post(
            f"{_url()}/summarize", headers=_headers(),
            files={"file": (file_name, data, mime or "application/octet-stream")},
            data={"language": language}, timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ApiError(f"No se pudo contactar al servicio: {exc}") from exc
    if not resp.ok:
        raise _http_error(resp)
    return resp.json()


def make_audio(doc_id: str, length: str, language: str, style: str) -> dict:
    """Devuelve el resultado con 'audio_bytes' ya descargado/decodificado."""
    if mode() == "inprocess":
        service = _service()
        try:
            pod = service.make_audio(doc_id, length, language, style)
        except service.ServiceError as exc:
            raise ApiError(str(exc)) from exc
    else:
        try:
            resp = requests.post(
                f"{_url()}/podcast", headers=_headers(),
                json={"doc_id": doc_id, "length": length, "language": language, "style": style},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ApiError(f"No se pudo contactar al servicio: {exc}") from exc
        if not resp.ok:
            raise _http_error(resp)
        pod = resp.json()

    if pod.get("audio_b64"):                       # almacenamiento local
        pod["audio_bytes"] = base64.b64decode(pod.pop("audio_b64"))
    else:                                          # blob: URL SAS temporal
        try:
            audio = requests.get(pod["audio_url"], timeout=TIMEOUT)
            audio.raise_for_status()
        except requests.RequestException as exc:
            raise ApiError(f"No se pudo descargar el audio: {exc}") from exc
        pod["audio_bytes"] = audio.content
    return pod
