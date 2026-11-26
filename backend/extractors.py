"""
extractors.py
=============
Convierte cualquier archivo soportado en texto plano para el resumen.

- Texto / Markdown / datos:  decodificación directa
- Código fuente / notebooks:  decodificación (o celdas del .ipynb)
- PDF:                        pypdf; si está escaneado -> OCR con Document Intelligence
- PowerPoint (.pptx):         texto de cada diapositiva + notas del orador
- Word (.docx):               párrafos y tablas
- Imágenes / infografías:     modelo con visión de Azure OpenAI (OCR + descripción)
"""

from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from config import MAX_TOTAL_CHARS, settings

TEXT_EXT = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml",
            ".html", ".htm", ".log", ".ini", ".toml"}
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".go", ".rb", ".php", ".c", ".cpp",
            ".h", ".hpp", ".rs", ".kt", ".swift", ".sql", ".sh", ".ps1", ".scala", ".r", ".m", ".tf",
            ".bicep", ".vue", ".dart", ".lua", ".pl", ".dax", ".bas", ".vb"}
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif"}
OTHER_EXT = {".pdf", ".pptx", ".docx", ".ipynb"}

SUPPORTED_EXT = TEXT_EXT | CODE_EXT | set(IMAGE_MIME) | OTHER_EXT


class ExtractionError(ValueError):
    """Error que se le puede mostrar tal cual al usuario."""


@dataclass
class Extracted:
    text: str
    kind: str                      # texto | codigo | pdf | presentacion | documento | imagen
    units: int | None = None       # páginas o diapositivas
    notes: list[str] = field(default_factory=list)


def extract(filename: str, data: bytes) -> Extracted:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise ExtractionError(f"Formato '{ext or 'sin extensión'}' no soportado.")
    if not data:
        raise ExtractionError("El archivo está vacío.")

    if ext == ".pdf":
        result = _pdf(data)
    elif ext == ".pptx":
        result = _pptx(data)
    elif ext == ".docx":
        result = _docx(data)
    elif ext == ".ipynb":
        result = _ipynb(data)
    elif ext in IMAGE_MIME:
        result = _image(data, IMAGE_MIME[ext])
    else:
        kind = "codigo" if ext in CODE_EXT else "texto"
        text = _decode(data)
        if kind == "codigo":
            text = f"Archivo de código: {filename}\n\n{text}"
        result = Extracted(text=text, kind=kind)

    result.text = result.text.strip()
    if len(result.text) < 20:
        raise ExtractionError("No se encontró texto suficiente en el archivo para resumir.")
    if len(result.text) > MAX_TOTAL_CHARS:
        result.text = result.text[:MAX_TOTAL_CHARS]
        result.notes.append("El documento es muy largo; se resumió solo la primera parte.")
    return result


# ------------------------------------------------------------------
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(enc)
            if "\x00" not in text:
                return text
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _pdf(data: bytes) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise ExtractionError("El PDF está protegido con contraseña.") from exc
        pages = [(p.extract_text() or "") for p in reader.pages]
    except PdfReadError as exc:
        raise ExtractionError("No se pudo leer el PDF (¿está dañado?).") from exc

    n = len(pages)
    text = "\n\n".join(f"[Página {i + 1}]\n{t.strip()}" for i, t in enumerate(pages) if t.strip())
    real_chars = sum(len(t.strip()) for t in pages)

    # Poco texto por página => casi seguro es un PDF escaneado.
    if real_chars < max(80, 40 * n):
        if not settings.ocr_enabled:
            raise ExtractionError(
                "El PDF parece escaneado (sin texto) y el OCR no está configurado "
                "(AZURE_DOCINTEL_ENDPOINT / AZURE_DOCINTEL_KEY)."
            )
        return Extracted(text=ocr(data, "application/pdf"), kind="pdf", units=n,
                         notes=["PDF escaneado: el texto se obtuvo con OCR."])
    return Extracted(text=text, kind="pdf", units=n)


def _pptx(data: bytes) -> Extracted:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("No se pudo leer la presentación .pptx.") from exc

    def shape_text(shape) -> list[str]:
        out: list[str] = []
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            for s in shape.shapes:
                out.extend(shape_text(s))
            return out
        if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
            out.append(shape.text_frame.text.strip())
        if getattr(shape, "has_table", False):
            for row in shape.table.rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    out.append(" | ".join(cells))
        if getattr(shape, "has_chart", False):
            chart = shape.chart
            if chart.has_title and chart.chart_title.has_text_frame:
                out.append(f"(Gráfica) {chart.chart_title.text_frame.text.strip()}")
        return out

    blocks = []
    for i, slide in enumerate(prs.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            parts.extend(shape_text(shape))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"Notas del orador: {notes}")
        if parts:
            blocks.append(f"[Diapositiva {i}]\n" + "\n".join(parts))
    return Extracted(text="\n\n".join(blocks), kind="presentacion", units=len(prs.slides))


def _docx(data: bytes) -> Extracted:
    from docx import Document

    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("No se pudo leer el documento .docx.") from exc

    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return Extracted(text="\n".join(parts), kind="documento")


def _ipynb(data: bytes) -> Extracted:
    try:
        nb = json.loads(_decode(data))
    except json.JSONDecodeError as exc:
        raise ExtractionError("El notebook .ipynb no es JSON válido.") from exc
    parts = []
    for cell in nb.get("cells", []):
        src = "".join(cell.get("source", []))
        if src.strip():
            label = "Markdown" if cell.get("cell_type") == "markdown" else "Código"
            parts.append(f"[{label}]\n{src}")
    return Extracted(text="\n\n".join(parts), kind="codigo")


def _image(data: bytes, mime: str) -> Extracted:
    import llm

    text = llm.describe_image(data, mime)
    if len(text.strip()) < 20 and settings.ocr_enabled:
        text = ocr(data, "application/octet-stream")
    return Extracted(text=text, kind="imagen", notes=["Imagen interpretada con el modelo de visión."])


# ------------------------------------------------------------------
def ocr(data: bytes, content_type: str) -> str:
    """OCR con Azure AI Document Intelligence (modelo prebuilt-read)."""
    endpoint = settings.docintel_endpoint.rstrip("/")
    url = f"{endpoint}/documentintelligence/documentModels/prebuilt-read:analyze?api-version=2024-11-30"
    headers = {"Ocp-Apim-Subscription-Key": settings.docintel_key, "Content-Type": content_type}
    resp = requests.post(url, headers=headers, data=data, timeout=60)
    if resp.status_code != 202:
        raise RuntimeError(f"Document Intelligence respondió {resp.status_code}: {resp.text[:300]}")

    op_url = resp.headers["Operation-Location"]
    for _ in range(60):
        time.sleep(2)
        poll = requests.get(op_url, headers={"Ocp-Apim-Subscription-Key": settings.docintel_key}, timeout=30)
        body = poll.json()
        status = body.get("status")
        if status == "succeeded":
            return body.get("analyzeResult", {}).get("content", "")
        if status == "failed":
            raise RuntimeError(f"OCR falló: {body.get('error')}")
    raise RuntimeError("El OCR tardó demasiado.")
