"""
probar_voces.py
===============
Escucha voces de Azure AI Speech con tu propio recurso y tu propio texto, para elegir
las que usa summarAI. Usa la clave de backend/.env o backend/local.settings.json.

  # listar voces disponibles de un idioma
  python tools/probar_voces.py --list es-MX

  # generar un MP3 por voz con una frase de prueba (quedan en tools/voces/)
  python tools/probar_voces.py es-MX-DaliaNeural es-MX-JorgeNeural es-ES-ElviraNeural

  # con tu propio texto
  python tools/probar_voces.py es-MX-NuriaNeural --text "Hola, este es el resumen del trimestre."

Para elegir la voz final, cambia PODCAST_VOICES / NARRATOR_VOICES en backend/config.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "voces"
SAMPLE = {
    "es": "Hola, soy la voz de summarAI. En este documento se presentan los resultados del tercer "
          "trimestre: los ingresos crecieron doce por ciento y quedan dos pendientes para enero.",
    "en": "Hi, this is the voice of summarAI. This document presents third-quarter results: "
          "revenue grew twelve percent, and two items remain open for January.",
}


def _creds():
    """Usa la misma configuración que el backend (backend/.env o backend/local.settings.json)."""
    sys.path.insert(0, str(ROOT / "backend"))
    from config import settings  # noqa: PLC0415
    if not settings.speech_enabled:
        sys.exit("Falta AZURE_SPEECH_KEY y AZURE_SPEECH_REGION/ENDPOINT en backend/.env o local.settings.json")
    return settings


def list_voices(locale: str) -> None:
    cfg = _creds()
    resp = requests.get(cfg.speech_url("cognitiveservices/voices/list"),
                        headers={"Ocp-Apim-Subscription-Key": cfg.speech_key}, timeout=30)
    resp.raise_for_status()
    voices = [v for v in resp.json() if v["Locale"].lower().startswith(locale.lower())]
    for v in sorted(voices, key=lambda v: v["ShortName"]):
        styles = ", ".join(v.get("StyleList", [])[:4])
        print(f'{v["ShortName"]:<38} {v["Gender"]:<7} {v.get("VoiceType", ""):<8} {styles}')
    print(f"\n{len(voices)} voces para {locale}")


def speak(voice: str, text: str) -> Path:
    cfg = _creds()
    lang = "-".join(voice.split("-")[:2])
    ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
            f'<voice name="{voice}">{escape(text)}</voice></speak>')
    resp = requests.post(
        cfg.speech_url("cognitiveservices/v1"),
        headers={"Ocp-Apim-Subscription-Key": cfg.speech_key, "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3", "User-Agent": "summarAI"},
        data=ssml.encode("utf-8"), timeout=60,
    )
    if resp.status_code != 200:
        sys.exit(f"{voice}: Azure Speech respondió {resp.status_code} {resp.text[:200]}")
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{voice.replace(':', '_')}.mp3"
    path.write_bytes(resp.content)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("voices", nargs="*", help="nombres cortos, p. ej. es-MX-DaliaNeural")
    ap.add_argument("--list", metavar="LOCALE", help="lista voces de un idioma (es, es-MX, en-US…)")
    ap.add_argument("--text", help="texto a leer (por defecto, una frase de ejemplo)")
    args = ap.parse_args()

    if args.list:
        list_voices(args.list)
    elif args.voices:
        for voice in args.voices:
            text = args.text or SAMPLE["en" if voice.startswith("en") else "es"]
            print("✓", speak(voice, text))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
