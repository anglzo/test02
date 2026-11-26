"""
storage.py
==========
Guarda el texto extraído (para generar el audio después sin volver a subir el archivo) y los MP3.

Dos modos, elegidos con STORAGE_MODE:
  local  -> carpeta en disco (LOCAL_STORAGE_DIR, por defecto <proyecto>/.data). No necesita Azure.
            Borra lo que tenga más de LOCAL_RETENTION_DAYS días.
            El MP3 se devuelve en la respuesta (audio_b64) en lugar de una URL.
  blob   -> Azure Blob Storage (STORAGE_CONNECTION_STRING). El MP3 se entrega con una URL SAS
            de solo lectura que caduca en AUDIO_SAS_HOURS. Una regla de ciclo de vida borra todo
            a los N días.
  auto   -> (por defecto) blob si hay cadena de conexión; si no, local.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import AUDIO_SAS_HOURS, BLOB_CONTAINER, LOCAL_RETENTION_DAYS, settings

_SAFE_ID = re.compile(r"^[0-9a-f]{32}$")


def mode() -> str:
    m = settings.storage_mode
    if m in ("local", "blob"):
        return m
    # auto: solo pasa a blob con una cadena propia; AzureWebJobsStorage (la del host de
    # Functions) no cuenta, para que la prueba local nunca dependa de Azurite.
    return "blob" if settings.storage_connection_string_explicit else "local"


# ------------------------------------------------------------------ local
def _local_dir(sub: str) -> Path:
    path = Path(settings.local_storage_dir) / sub
    path.mkdir(parents=True, exist_ok=True)
    return path


def _purge_local() -> None:
    """Equivalente local de la regla de ciclo de vida de Blob: borra archivos viejos."""
    cutoff = time.time() - LOCAL_RETENTION_DAYS * 86_400
    for sub in ("docs", "audio"):
        for f in _local_dir(sub).iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass


def _check_id(doc_id: str) -> str:
    if not _SAFE_ID.match(doc_id):
        raise ValueError("doc_id inválido")
    return doc_id


# ------------------------------------------------------------------ blob
_service = None


def _container():
    global _service
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import BlobServiceClient

    if _service is None:
        if not settings.storage_connection_string:
            raise RuntimeError("STORAGE_MODE=blob pero falta STORAGE_CONNECTION_STRING.")
        _service = BlobServiceClient.from_connection_string(settings.storage_connection_string)
        try:
            _service.create_container(BLOB_CONTAINER)
        except ResourceExistsError:
            pass
    return _service.get_container_client(BLOB_CONTAINER)


# ------------------------------------------------------------------ API pública
def save_document(doc_id: str, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if mode() == "local":
        _purge_local()
        (_local_dir("docs") / f"{_check_id(doc_id)}.json").write_bytes(raw)
        return
    from azure.storage.blob import ContentSettings

    _container().upload_blob(f"docs/{doc_id}.json", raw, overwrite=True,
                             content_settings=ContentSettings(content_type="application/json"))


def load_document(doc_id: str) -> dict | None:
    if mode() == "local":
        path = _local_dir("docs") / f"{_check_id(doc_id)}.json"
        return json.loads(path.read_bytes()) if path.exists() else None
    from azure.core.exceptions import ResourceNotFoundError

    try:
        raw = _container().download_blob(f"docs/{doc_id}.json").readall()
    except ResourceNotFoundError:
        return None
    return json.loads(raw)


def save_audio(doc_id: str, audio: bytes, filename: str) -> str | None:
    """Guarda el MP3. En blob devuelve una URL SAS; en local devuelve None (el audio va en la respuesta)."""
    if mode() == "local":
        (_local_dir("audio") / f"{_check_id(doc_id)}.mp3").write_bytes(audio)
        return None

    from azure.storage.blob import BlobSasPermissions, ContentSettings, generate_blob_sas

    container = _container()
    blob_name = f"podcasts/{doc_id}.mp3"
    container.upload_blob(
        blob_name, audio, overwrite=True,
        content_settings=ContentSettings(content_type="audio/mpeg",
                                         content_disposition=f'inline; filename="{filename}"'),
    )
    sas = generate_blob_sas(
        account_name=container.account_name,
        container_name=BLOB_CONTAINER,
        blob_name=blob_name,
        account_key=_service.credential.account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=AUDIO_SAS_HOURS),
    )
    return f"{container.get_blob_client(blob_name).url}?{sas}"
