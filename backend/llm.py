"""Cliente de Azure OpenAI y llamadas al modelo."""

from __future__ import annotations

import base64
import logging
import time

from openai import APIConnectionError, APITimeoutError, AzureOpenAI, RateLimitError

from config import settings
from prompts import IMAGE_EXTRACTION_SYSTEM

_client: AzureOpenAI | None = None


def client() -> AzureOpenAI:
    global _client
    if _client is None:
        if not settings.openai_endpoint or not settings.openai_api_key:
            raise RuntimeError("Falta configurar AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY.")
        _client = AzureOpenAI(
            azure_endpoint=settings.openai_endpoint,
            api_key=settings.openai_api_key,
            api_version=settings.openai_api_version,
            timeout=120,
            max_retries=2,
        )
    return _client


def chat(messages: list[dict], max_tokens: int = 1_200, json_mode: bool = False) -> str:
    kwargs: dict = {
        "model": settings.openai_deployment,
        "messages": messages,
        "max_completion_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(4):
        try:
            resp = client().chat.completions.create(**kwargs)
            return (resp.choices[0].message.content or "").strip()
        except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
            if attempt == 3:
                raise
            wait = 2 ** attempt * 3
            logging.warning("Azure OpenAI reintento %s en %ss: %s", attempt + 1, wait, exc)
            time.sleep(wait)
    return ""


def describe_image(data: bytes, mime: str) -> str:
    """Transcribe y describe una imagen (infografía, diagrama, captura)."""
    b64 = base64.b64encode(data).decode("ascii")
    return chat(
        [
            {"role": "system", "content": IMAGE_EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Lee esta imagen."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}},
                ],
            },
        ],
        max_tokens=2_500,
    )
