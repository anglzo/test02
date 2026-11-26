"""Resumen breve. Una sola llamada si el texto cabe; map-reduce si es largo."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import llm
from config import CHUNK_CHARS, SINGLE_PASS_CHARS
from extractors import Extracted
from prompts import chunk_system, summary_system

KIND_LABEL = {
    "texto": "documento de texto",
    "codigo": "código fuente",
    "pdf": "PDF",
    "presentacion": "presentación",
    "documento": "documento Word",
    "imagen": "imagen / infografía",
}


def _chunks(text: str, size: int) -> list[str]:
    """Corta en bloques de ~size caracteres intentando respetar saltos de párrafo."""
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind("\n\n", start + size // 2, end)
            if cut != -1:
                end = cut
        out.append(text[start:end])
        start = end
    return out


def summarize(ex: Extracted, filename: str, language: str) -> str:
    body = ex.text
    if len(body) > SINGLE_PASS_CHARS:
        pieces = _chunks(body, CHUNK_CHARS)

        def one(piece: str) -> str:
            return llm.chat(
                [{"role": "system", "content": chunk_system(language)}, {"role": "user", "content": piece}],
                max_tokens=700,
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            partials = list(pool.map(one, pieces))
        body = "\n\n".join(f"[Parte {i + 1}]\n{p}" for i, p in enumerate(partials))

    header = f"Archivo: {filename} ({KIND_LABEL.get(ex.kind, ex.kind)})"
    if ex.units:
        header += f", {ex.units} {'diapositivas' if ex.kind == 'presentacion' else 'páginas'}"
    return llm.chat(
        [
            {"role": "system", "content": summary_system(language)},
            {"role": "user", "content": f"{header}\n\n---\n{body}"},
        ],
        max_tokens=900,
    )
