"""
verificar.py
============
Prueba, uno por uno, los endpoints y claves configurados (backend/.env o
backend/local.settings.json) y dice qué falta o qué falla. No sube documentos reales.

  python tools/verificar.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from config import settings  # noqa: E402

OK, FAIL, SKIP = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m–\033[0m"
failures = 0


def report(ok: bool | None, name: str, detail: str) -> None:
    global failures
    mark = SKIP if ok is None else (OK if ok else FAIL)
    if ok is False:
        failures += 1
    print(f" {mark} {name:<24} {detail}")


def check_openai() -> None:
    if not (settings.openai_endpoint and settings.openai_api_key):
        report(False, "Azure OpenAI", "faltan AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY (obligatorio)")
        return
    url = (f"{settings.openai_endpoint.rstrip('/')}/openai/deployments/{settings.openai_deployment}"
           f"/chat/completions?api-version={settings.openai_api_version}")
    try:
        r = requests.post(url, headers={"api-key": settings.openai_api_key}, timeout=60, json={
            "messages": [{"role": "user", "content": 'Responde solo con este json: {"ok": true}'}],
            "max_completion_tokens": 20, "response_format": {"type": "json_object"},
        })
    except requests.RequestException as exc:
        report(False, "Azure OpenAI", f"sin conexión: {exc.__class__.__name__} (¿proxy / certificado?)")
        return
    hints = {401: "clave incorrecta", 403: "sin permiso o red bloqueada (firewall/private endpoint)",
             404: f"no existe el deployment '{settings.openai_deployment}' o la api-version",
             429: "cuota (TPM) agotada; funciona pero reintenta"}
    if r.ok:
        report(True, "Azure OpenAI", f"deployment '{settings.openai_deployment}' responde (modelo {r.json().get('model')})")
    else:
        report(r.status_code == 429, "Azure OpenAI", f"HTTP {r.status_code}: {hints.get(r.status_code, r.text[:150])}")


def check_speech() -> None:
    if not settings.speech_enabled:
        report(False, "Azure AI Speech", "faltan AZURE_SPEECH_KEY y AZURE_SPEECH_REGION o AZURE_SPEECH_ENDPOINT (audio)")
        return
    from config import NARRATOR_VOICES, PODCAST_VOICES  # noqa: PLC0415
    try:
        r = requests.get(settings.speech_url("cognitiveservices/voices/list"),
                         headers={"Ocp-Apim-Subscription-Key": settings.speech_key}, timeout=30)
    except requests.RequestException as exc:
        report(False, "Azure AI Speech", f"sin conexión: {exc.__class__.__name__}")
        return
    if not r.ok:
        report(False, "Azure AI Speech", f"HTTP {r.status_code}: {'clave o región incorrecta' if r.status_code == 401 else r.text[:150]}")
        return
    available = {v["ShortName"] for v in r.json()}
    needed = {v[s][1] for cfg in (PODCAST_VOICES, NARRATOR_VOICES) for v in cfg.values() for s in ("A", "B") if s in v}
    missing = needed - available
    report(not missing, "Azure AI Speech",
           f"{len(available)} voces disponibles" + (f"; faltan: {', '.join(sorted(missing))}" if missing else "; voces de summarAI OK"))


def check_docintel() -> None:
    if not settings.ocr_enabled:
        report(None, "Document Intelligence", "no configurado (opcional: solo OCR de PDFs escaneados)")
        return
    url = f"{settings.docintel_endpoint.rstrip('/')}/documentintelligence/documentModels/prebuilt-read?api-version=2024-11-30"
    try:
        r = requests.get(url, headers={"Ocp-Apim-Subscription-Key": settings.docintel_key}, timeout=30)
    except requests.RequestException as exc:
        report(False, "Document Intelligence", f"sin conexión: {exc.__class__.__name__}")
        return
    report(r.ok, "Document Intelligence",
           "modelo prebuilt-read disponible (API 2024-11-30)" if r.ok else f"HTTP {r.status_code}: {r.text[:150]}")


def check_storage() -> None:
    import storage  # noqa: PLC0415
    m = storage.mode()
    if m == "local":
        path = Path(settings.local_storage_dir)
        try:
            path.mkdir(parents=True, exist_ok=True)
            (path / ".probe").write_text("ok")
            (path / ".probe").unlink()
            report(True, "Almacenamiento", f"local en {path}")
        except OSError as exc:
            report(False, "Almacenamiento", f"no se puede escribir en {path}: {exc}")
        return
    try:
        container = storage._container()
        next(iter(container.list_blobs(results_per_page=1)), None)
        report(True, "Almacenamiento", f"blob, contenedor '{container.container_name}' en {container.account_name}")
    except Exception as exc:  # noqa: BLE001
        report(False, "Almacenamiento", f"blob falló: {str(exc)[:160]} -> usa STORAGE_MODE=local para seguir probando")


if __name__ == "__main__":
    print("\nsummarAI · verificación de servicios\n")
    check_openai()
    check_speech()
    check_docintel()
    check_storage()
    print("\nTodo listo." if not failures else f"\n{failures} problema(s). Revisa docs/GUIA-EY.md §8 (Problemas comunes).")
    sys.exit(1 if failures else 0)
