"""
config.py
=========
Única fuente de configuración del backend.

Regla: SOLO las credenciales / endpoints de Azure salen del entorno
(.env en local, App Settings en Azure). Todo lo demás está aquí.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Configuración local (en Azure ninguno de los dos archivos se despliega):
#   1) backend/.env               -> formato CLAVE=valor
#   2) backend/local.settings.json -> el que usa `func start`; se lee también para que el modo
#      inprocess del frontend comparta las mismas claves sin duplicarlas.
# Nunca pisan variables que ya existan en el entorno.
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)
try:
    for _k, _v in json.loads((BASE_DIR / "local.settings.json").read_text())["Values"].items():
        if isinstance(_v, str) and _v and _k not in os.environ:
            os.environ[_k] = _v
except (FileNotFoundError, KeyError, ValueError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # Azure OpenAI (resumen, guion del podcast, lectura de imágenes)
    openai_endpoint: str = field(default_factory=lambda: _env("AZURE_OPENAI_ENDPOINT"))
    openai_api_key: str = field(default_factory=lambda: _env("AZURE_OPENAI_API_KEY"))
    openai_api_version: str = field(default_factory=lambda: _env("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"))
    openai_deployment: str = field(default_factory=lambda: _env("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini"))

    # Azure AI Speech (voz del podcast)
    speech_key: str = field(default_factory=lambda: _env("AZURE_SPEECH_KEY"))
    speech_region: str = field(default_factory=lambda: _env("AZURE_SPEECH_REGION"))
    # Opcional: endpoint propio (dominio personalizado / private endpoint), p. ej.
    # https://spch-x.cognitiveservices.azure.com/ . Si está, se usa en vez de la región.
    speech_endpoint: str = field(default_factory=lambda: _env("AZURE_SPEECH_ENDPOINT"))

    # Azure AI Document Intelligence (OCR de PDFs escaneados; opcional)
    docintel_endpoint: str = field(default_factory=lambda: _env("AZURE_DOCINTEL_ENDPOINT"))
    docintel_key: str = field(default_factory=lambda: _env("AZURE_DOCINTEL_KEY"))

    # Blob Storage (texto extraído y audios). Si no hay uno propio, usa el de Functions.
    storage_connection_string: str = field(
        default_factory=lambda: _env("STORAGE_CONNECTION_STRING") or _env("AzureWebJobsStorage")
    )

    # local | blob | auto (auto = blob si hay cadena de conexión, si no local)
    storage_mode: str = field(default_factory=lambda: _env("STORAGE_MODE", "auto").lower())
    local_storage_dir: str = field(
        default_factory=lambda: _env("LOCAL_STORAGE_DIR") or str(BASE_DIR.parent / ".data")
    )

    @property
    def speech_enabled(self) -> bool:
        return bool(self.speech_key and (self.speech_endpoint or self.speech_region))

    def speech_url(self, path: str) -> str:
        """path: 'cognitiveservices/v1' (síntesis) o 'cognitiveservices/voices/list'."""
        if self.speech_endpoint:
            return f"{self.speech_endpoint.rstrip('/')}/tts/{path}"
        return f"https://{self.speech_region}.tts.speech.microsoft.com/{path}"

    @property
    def storage_connection_string_explicit(self) -> bool:
        return bool(_env("STORAGE_CONNECTION_STRING"))

    @property
    def ocr_enabled(self) -> bool:
        return bool(self.docintel_endpoint and self.docintel_key)


settings = Settings()

# ------------------------------------------------------------------
# Límites y parámetros fijos
# ------------------------------------------------------------------
MAX_FILE_MB = 25
MAX_TOTAL_CHARS = 400_000          # más allá de esto se trunca el documento
SINGLE_PASS_CHARS = 60_000         # hasta aquí se resume en una sola llamada
CHUNK_CHARS = 40_000               # tamaño de cada bloque en map-reduce
PODCAST_SOURCE_CHARS = 30_000      # contexto máximo que se manda al guionista

BLOB_CONTAINER = "summarai"
AUDIO_SAS_HOURS = 2
LOCAL_RETENTION_DAYS = 7          # almacenamiento local: se borra lo más viejo

SUPPORTED_LANGUAGES = {"es", "en"}

# Estilos de audio: conversación a dos voces o resumen narrado por una sola voz
AUDIO_STYLES = {
    "podcast": {"label": "Podcast", "suffix": "podcast"},
    "resumen": {"label": "Audio resumen", "suffix": "audio_resumen"},
}

# Duración aproximada del audio -> palabras objetivo del guion
PODCAST_LENGTHS = {
    "corto": {"words": 350, "label": "~2 min"},
    "medio": {"words": 750, "label": "~5 min"},
}

# Voces neuronales de Azure Speech por idioma: (anfitriona A, anfitrión B).
# Catálogo para escucharlas: https://speech.microsoft.com/portal/voicegallery
PODCAST_VOICES = {
    "es": {"A": ("Sofía", "es-MX-DaliaNeural"), "B": ("Diego", "es-MX-JorgeNeural"), "xml_lang": "es-MX"},
    "en": {"A": ("Ava", "en-US-AvaNeural"), "B": ("Andrew", "en-US-AndrewNeural"), "xml_lang": "en-US"},
}
# Voz única del audio resumen. Para probar otras: https://speech.microsoft.com/portal/voicegallery
NARRATOR_VOICES = {
    "es": {"A": ("Dalia", "es-MX-DaliaNeural"), "xml_lang": "es-MX"},
    "en": {"A": ("Ava", "en-US-AvaNeural"), "xml_lang": "en-US"},
}
SPEECH_OUTPUT_FORMAT = "audio-24khz-96kbitrate-mono-mp3"
SPEECH_MAX_CHARS_PER_REQUEST = 3_500
SPEECH_MAX_TURNS_PER_REQUEST = 30
SPEECH_PARALLEL_REQUESTS = 4
