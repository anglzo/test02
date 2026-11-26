"""
service.py
==========
Lógica de negocio de summarAI, independiente del transporte.

La usan:
  - function_app.py (API HTTP en Azure Functions), y
  - el frontend en modo "inprocess" (BACKEND_MODE=inprocess), que la importa directo sin
    levantar el host de Functions: así en un equipo sin Core Tools basta con Python.
"""

from __future__ import annotations

import base64
import logging
import re
import uuid
from pathlib import Path

import podcast as podcast_mod
import storage
from config import AUDIO_STYLES, MAX_FILE_MB, PODCAST_LENGTHS, SUPPORTED_LANGUAGES
from extractors import ExtractionError, extract
from summarizer import summarize as summarize_doc

DOC_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class ServiceError(Exception):
    """Error con mensaje apto para el usuario y código HTTP sugerido."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def lang(value: str | None) -> str:
    value = (value or "es").lower()[:2]
    return value if value in SUPPORTED_LANGUAGES else "es"


def summarize_file(filename: str, data: bytes, language: str | None) -> dict:
    filename = Path(filename or "").name
    if not filename or not data:
        raise ServiceError("Envía un archivo con nombre y contenido.", 400)
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise ServiceError(f"El archivo supera el límite de {MAX_FILE_MB} MB.", 413)
    language = lang(language)

    try:
        extracted = extract(filename, data)
        summary = summarize_doc(extracted, filename, language)
    except ExtractionError as exc:
        raise ServiceError(str(exc), 400) from exc
    except Exception as exc:  # noqa: BLE001
        logging.exception("Error resumiendo %s", filename)
        raise ServiceError("No se pudo generar el resumen. Intenta de nuevo en un momento.", 500) from exc

    doc_id = uuid.uuid4().hex
    try:
        storage.save_document(doc_id, {
            "filename": filename, "kind": extracted.kind, "language": language,
            "summary": summary, "text": extracted.text,
        })
        audio_ready = True
    except Exception:  # noqa: BLE001 - sin almacenamiento igual devolvemos el resumen
        logging.exception("No se pudo guardar el documento %s", doc_id)
        audio_ready = False

    return {
        "doc_id": doc_id if audio_ready else None,
        "filename": filename,
        "kind": extracted.kind,
        "units": extracted.units,
        "chars": len(extracted.text),
        "language": language,
        "summary": summary,
        "notes": extracted.notes,
        "storage": storage.mode(),
    }


def make_audio(doc_id: str, length: str = "corto", language: str | None = None,
               style: str = "podcast") -> dict:
    """Genera el audio. Devuelve audio_url (blob) o audio_b64 (local)."""
    doc_id = str(doc_id or "")
    if not DOC_ID_RE.match(doc_id):
        raise ServiceError("doc_id inválido.", 400)
    if length not in PODCAST_LENGTHS:
        raise ServiceError(f"length debe ser uno de: {', '.join(PODCAST_LENGTHS)}.", 400)
    if style not in AUDIO_STYLES:
        raise ServiceError(f"style debe ser uno de: {', '.join(AUDIO_STYLES)}.", 400)

    doc = storage.load_document(doc_id)
    if doc is None:
        raise ServiceError("El documento ya no existe; vuelve a subir el archivo.", 404)
    language = lang(language or doc.get("language"))

    try:
        script = podcast_mod.build_script(doc["text"], doc["summary"], language, length, style)
        audio = podcast_mod.synthesize(script["turns"], language, style)
        audio_name = f"{Path(doc['filename']).stem}_{AUDIO_STYLES[style]['suffix']}.mp3"
        url = storage.save_audio(doc_id, audio, audio_name)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Error generando audio (%s) %s", style, doc_id)
        raise ServiceError("No se pudo generar el audio. Intenta de nuevo en un momento.", 500) from exc

    result = {
        "doc_id": doc_id,
        "title": script["title"],
        "turns": script["turns"],
        "audio_url": url,
        "audio_filename": audio_name,
        "length": length,
        "style": style,
        "language": language,
    }
    if url is None:   # almacenamiento local: el MP3 viaja en la respuesta
        result["audio_b64"] = base64.b64encode(audio).decode()
    return result
