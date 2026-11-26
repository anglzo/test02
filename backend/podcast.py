"""
podcast.py
==========
1. Azure OpenAI escribe el guion (JSON):
   - style="podcast": conversación entre dos anfitriones.
   - style="resumen": audio resumen narrado por una sola voz.
2. Azure AI Speech lo convierte en MP3 con voces neuronales.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

import requests

import llm
from config import (
    NARRATOR_VOICES,
    PODCAST_LENGTHS,
    PODCAST_SOURCE_CHARS,
    PODCAST_VOICES,
    SPEECH_MAX_CHARS_PER_REQUEST,
    SPEECH_MAX_TURNS_PER_REQUEST,
    SPEECH_OUTPUT_FORMAT,
    SPEECH_PARALLEL_REQUESTS,
    settings,
)
from prompts import narration_system, podcast_system


def _voices(language: str, style: str) -> dict:
    return NARRATOR_VOICES[language] if style == "resumen" else PODCAST_VOICES[language]


def build_script(text: str, summary: str, language: str, length: str, style: str = "podcast") -> dict:
    words = PODCAST_LENGTHS[length]["words"]
    if style == "resumen":
        system = narration_system(language, words)
    else:
        voices = PODCAST_VOICES[language]
        system = podcast_system(language, words, voices["A"][0], voices["B"][0])
    user = f"Resumen del documento:\n{summary}\n\n---\nContenido del documento:\n{text[:PODCAST_SOURCE_CHARS]}"

    raw = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=4_000,
        json_mode=True,
    )
    try:
        script = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("El modelo no devolvió un guion válido.") from exc

    if style == "resumen":
        turns = [{"speaker": "A", "text": str(p).strip()}
                 for p in script.get("paragraphs", []) if str(p).strip()]
    else:
        turns = [
            {"speaker": "B" if str(t.get("speaker", "A")).upper().startswith("B") else "A",
             "text": str(t.get("text", "")).strip()}
            for t in script.get("turns", [])
            if str(t.get("text", "")).strip()
        ]
    if not turns:
        raise RuntimeError("El guion llegó vacío.")
    return {"title": str(script.get("title", "summarAI")).strip(), "turns": turns}


# ------------------------------------------------------------------
def _batches(turns: list[dict]) -> list[list[dict]]:
    """Agrupa turnos para no pasar los límites por petición de Azure Speech."""
    batches: list[list[dict]] = [[]]
    size = 0
    for turn in turns:
        cur = batches[-1]
        if cur and (size + len(turn["text"]) > SPEECH_MAX_CHARS_PER_REQUEST
                    or len(cur) >= SPEECH_MAX_TURNS_PER_REQUEST):
            batches.append([])
            size = 0
        batches[-1].append(turn)
        size += len(turn["text"])
    return batches


def build_ssml(turns: list[dict], language: str, style: str = "podcast") -> str:
    v = _voices(language, style)
    pause = "550ms" if style == "resumen" else "350ms"
    parts = [f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{v["xml_lang"]}">']
    for t in turns:
        voice = v[t["speaker"]][1]
        parts.append(f'<voice name="{voice}">{escape(t["text"])}<break time="{pause}"/></voice>')
    parts.append("</speak>")
    return "".join(parts)


def _tts(ssml: str) -> bytes:
    if not settings.speech_enabled:
        raise RuntimeError("Falta configurar AZURE_SPEECH_KEY y AZURE_SPEECH_REGION (o AZURE_SPEECH_ENDPOINT).")
    url = settings.speech_url("cognitiveservices/v1")
    headers = {
        "Ocp-Apim-Subscription-Key": settings.speech_key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": SPEECH_OUTPUT_FORMAT,
        "User-Agent": "summarAI",
    }
    for attempt in range(4):
        resp = requests.post(url, headers=headers, data=ssml.encode("utf-8"), timeout=120)
        if resp.status_code == 200:
            return resp.content
        if resp.status_code in (429, 500, 503) and attempt < 3:
            wait = 2 ** attempt * 2
            logging.warning("Azure Speech %s, reintento en %ss", resp.status_code, wait)
            time.sleep(wait)
            continue
        raise RuntimeError(f"Azure Speech respondió {resp.status_code}: {resp.text[:300]}")
    raise RuntimeError("Azure Speech no respondió.")


def synthesize(turns: list[dict], language: str, style: str = "podcast") -> bytes:
    """Devuelve un MP3. Los fragmentos MP3 del mismo formato se pueden concatenar tal cual."""
    ssmls = [build_ssml(b, language, style) for b in _batches(turns)]
    with ThreadPoolExecutor(max_workers=SPEECH_PARALLEL_REQUESTS) as pool:
        audio_parts = list(pool.map(_tts, ssmls))   # map conserva el orden
    return b"".join(audio_parts)
