"""
function_app.py
===============
API HTTP de summarAI (Azure Functions, modelo de programación Python v2).
Solo traduce HTTP <-> service.py; la lógica vive allá.

  GET  /api/health      -> estado y qué servicios están configurados (anónimo)
  POST /api/summarize   -> multipart 'file' (+ 'language' es|en) -> resumen en Markdown
  POST /api/podcast     -> JSON {doc_id, length: corto|medio, language, style: podcast|resumen}
                         -> MP3 (audio_url con blob, audio_b64 con almacenamiento local) + guion
"""

from __future__ import annotations

import json
from pathlib import Path

import azure.functions as func

import service
import storage
from config import MAX_FILE_MB, settings
from extractors import SUPPORTED_EXT

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def _json(body: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body, ensure_ascii=False), status_code=status,
                             mimetype="application/json", charset="utf-8")


def _error(message: str, status: int) -> func.HttpResponse:
    return _json({"error": message}, status)


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json({
        "status": "ok",
        "openai": bool(settings.openai_endpoint and settings.openai_api_key),
        "speech": settings.speech_enabled,
        "ocr": settings.ocr_enabled,
        "storage": storage.mode(),
        "formats": sorted(SUPPORTED_EXT),
        "max_file_mb": MAX_FILE_MB,
    })


@app.route(route="summarize", methods=["POST"])
def summarize(req: func.HttpRequest) -> func.HttpResponse:
    upload = req.files.get("file")
    if upload is not None:
        filename, data = upload.filename or "archivo", upload.read()
        language = req.form.get("language")
    else:  # alternativa: cuerpo crudo + cabecera X-Filename
        filename, data = req.headers.get("X-Filename", ""), req.get_body()
        language = req.params.get("language")
    try:
        return _json(service.summarize_file(Path(filename).name, data, language))
    except service.ServiceError as exc:
        return _error(str(exc), exc.status)


@app.route(route="podcast", methods=["POST"])
def podcast(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _error("El cuerpo debe ser JSON.", 400)
    try:
        return _json(service.make_audio(
            body.get("doc_id"), body.get("length", "corto"), body.get("language"),
            body.get("style", "podcast"),
        ))
    except service.ServiceError as exc:
        return _error(str(exc), exc.status)
