"""
app.py — frontend de summarAI (Streamlit).

Habla con el backend vía client.py (API HTTP de Azure Functions o en el mismo proceso) y muestra:
1. cargar archivo -> 2. resumen en pantalla (descargable) -> 3. audio opcional (podcast o audio resumen).

La línea visual (tema oscuro, IBM Plex Sans, acento #FFE600, logo EY en el
sidebar, secciones numeradas) sigue la de scanner (Homologación de materiales).
"""

from __future__ import annotations

import html
import re
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import auth
import client

# Solo local: en Azure el .env no se despliega.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

MAX_FILE_MB = 25

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSETS_DIR / "ey_logo.svg"

FORMAT_GROUPS = {
    "Documentos": ["pdf", "docx", "txt", "md", "markdown", "rst"],
    "Presentaciones": ["pptx"],
    "Imágenes e infografías": ["png", "jpg", "jpeg", "webp", "gif"],
    "Datos": ["csv", "tsv", "json", "xml", "yaml", "yml", "html", "htm", "log", "ini", "toml"],
    "Código": ["py", "ipynb", "js", "ts", "tsx", "jsx", "java", "cs", "go", "rb", "php", "c", "cpp", "h",
               "hpp", "rs", "kt", "swift", "sql", "sh", "ps1", "scala", "r", "m", "tf", "bicep", "vue",
               "dart", "lua", "pl", "dax", "bas", "vb"],
}
ACCEPTED = [ext for group in FORMAT_GROUPS.values() for ext in group]

KIND_LABEL = {
    "texto": ("Texto", ":material/description:"),
    "codigo": ("Código", ":material/code:"),
    "pdf": ("PDF", ":material/picture_as_pdf:"),
    "presentacion": ("Presentación", ":material/slideshow:"),
    "documento": ("Word", ":material/article:"),
    "imagen": ("Imagen", ":material/image:"),
}
LANG_LABEL = {"es": "Español", "en": "English"}
HOSTS = {"es": ("Sofía", "Diego"), "en": ("Ava", "Andrew")}
NARRATOR = {"es": "Dalia", "en": "Ava"}
STYLE_LABEL = {"podcast": "Podcast", "resumen": "Audio resumen"}
STYLE_ICON = {"podcast": ":material/podcasts:", "resumen": ":material/record_voice_over:"}
LENGTH_LABEL = {"corto": "Corto · ~2 min", "medio": "Medio · ~5 min"}

st.set_page_config(page_title="summarAI · EY", page_icon=str(LOGO_PATH), layout="wide")
USER = auth.require_login()   # muestra el login y se detiene si no hay sesión
st.logo(str(LOGO_PATH), size="large")

# ------------------------------------------------------------------ estilos
st.html("""
<style>
/* Botones primarios: amarillo EY con texto oscuro (Streamlit pone texto claro por defecto). */
button[kind="primary"], button[kind="primary"] p,
[data-testid="stDownloadButton"] button[kind="primary"] p { color: #0E0E12 !important; font-weight: 600; }
button[kind="primary"]:hover { filter: brightness(0.92); }

/* Encabezado */
.sa-eyebrow { font: 500 11px/1 'IBM Plex Mono', ui-monospace, monospace; letter-spacing: .16em;
              text-transform: uppercase; color: #9A9AA5; margin-bottom: .6rem; }
.sa-title { font-size: 2.6rem; font-weight: 700; letter-spacing: -.02em; line-height: 1.05; margin: 0; }
.sa-title span { color: #FFE600; }
.sa-lead { color: #B4B4BE; font-size: 1.02rem; margin: .6rem 0 0; max-width: 52rem; }

/* Pasos numerados */
.sa-step { display: flex; align-items: center; gap: .7rem; margin: 1.6rem 0 .8rem;
           padding-bottom: .55rem; border-bottom: 1px solid #33333C; }
.sa-step b { display: grid; place-items: center; width: 1.7rem; height: 1.7rem; border-radius: 50%;
             background: #FFE600; color: #0E0E12; font-size: .85rem; font-weight: 700; flex: none; }
.sa-step span { font-size: 1.15rem; font-weight: 600; }
.sa-step.off b { background: #2A2A33; color: #77777F; }
.sa-step.off span { color: #77777F; }

/* Chips de formatos */
.sa-chips { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .3rem; }
.sa-chip { border: 1px solid #33333C; border-radius: 999px; padding: .15rem .65rem;
           font-size: .78rem; color: #B4B4BE; }

/* Tarjeta del resumen: acento amarillo a la izquierda */
.st-key-summary_card { border-left: 4px solid #FFE600 !important; }
.st-key-summary_card h2 { font-size: 1.45rem; margin-top: .2rem; }

/* Panel de podcast */
.st-key-podcast_card { background: linear-gradient(180deg, #1A1A22 0%, #15151B 100%); }
.sa-pod-title { font-weight: 600; font-size: 1.05rem; margin: .2rem 0 .4rem; }
.sa-turn { display: grid; grid-template-columns: 2rem 1fr; gap: .6rem; margin: .65rem 0; }
.sa-avatar { width: 2rem; height: 2rem; border-radius: 50%; display: grid; place-items: center;
             font-weight: 700; font-size: .8rem; }
.sa-avatar.a { background: #FFE600; color: #0E0E12; }
.sa-avatar.b { background: #2E2E38; color: #F2F2F2; border: 1px solid #4A4A55; }
.sa-who { font-size: .78rem; color: #9A9AA5; margin-bottom: .1rem; }
.sa-text { font-size: .93rem; line-height: 1.5; }

/* Sidebar */
.sa-how { counter-reset: s; list-style: none; padding: 0; margin: .2rem 0 0; }
.sa-how li { counter-increment: s; position: relative; padding-left: 1.8rem; margin: .55rem 0;
             font-size: .88rem; color: #C8C8D0; }
.sa-how li::before { content: counter(s); position: absolute; left: 0; top: .05rem; width: 1.2rem;
                     height: 1.2rem; border-radius: 50%; border: 1px solid #FFE600; color: #FFE600;
                     font-size: .7rem; display: grid; place-items: center; }
.sa-foot { font-size: .78rem; color: #8A8A94; line-height: 1.45; }
</style>
""")


# ------------------------------------------------------------------ helpers
def _plain(md: str) -> str:
    return re.sub(r"^#+\s*", "", md, flags=re.M).replace("**", "")


def _human_size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def step(num: int, title: str, active: bool = True) -> None:
    st.html(f'<div class="sa-step{"" if active else " off"}"><b>{num}</b><span>{title}</span></div>')


def summarize(file_name: str, data: bytes, mime: str, language: str) -> None:
    start = time.perf_counter()
    with st.status("Procesando el documento…", expanded=False) as status:
        status.write("Extrayendo contenido y generando el resumen")
        try:
            result = client.summarize(file_name, data, mime, language)
        except client.ApiError as exc:
            status.update(label="No se pudo resumir el archivo", state="error")
            st.error(str(exc))
            st.stop()
        status.update(label="Resumen listo", state="complete")
    result["elapsed"] = time.perf_counter() - start
    st.session_state.result = result
    st.session_state.pop("podcast", None)


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    language = st.segmented_control(
        "Idioma del resultado", list(LANG_LABEL), default="es",
        format_func=LANG_LABEL.get, key="language",
    ) or "es"

    st.markdown("**Cómo funciona**")
    st.html("""
    <ol class="sa-how">
      <li>Sube un documento, presentación, imagen o código.</li>
      <li>La IA lo lee y genera un resumen breve.</li>
      <li>Descárgalo o escúchalo: podcast a dos voces o audio resumen narrado.</li>
    </ol>
    """)
    st.divider()
    if "result" in st.session_state and st.button("Nuevo archivo", icon=":material/restart_alt:",
                                                  use_container_width=True):
        keep = {k: st.session_state[k] for k in ("auth_user",) if k in st.session_state}
        st.session_state.clear()
        st.session_state.update(keep)
        st.session_state.uploader_nonce = time.time()
        st.rerun()
    st.html(f"""
    <p class="sa-foot">Máx. {MAX_FILE_MB} MB por archivo. Los archivos se procesan en Azure
    (OpenAI, AI Speech, Document Intelligence) y se eliminan automáticamente tras unos días.
    Revisa el resultado antes de compartirlo: es generado por IA.</p>
    """)
    st.divider()
    auth.logout_button()

# ------------------------------------------------------------------ encabezado
st.html("""
<div class="sa-eyebrow">EY · Herramientas de IA</div>
<h1 class="sa-title">summar<span>AI</span></h1>
<p class="sa-lead">Sube un documento y obtén un resumen breve en segundos — o escúchalo como
audio mientras haces otra cosa.</p>
""")

# ------------------------------------------------------------------ 1. cargar
step(1, "Cargar archivo")
uploaded = st.file_uploader(
    "Archivo", type=ACCEPTED, label_visibility="collapsed",
    key=f"uploader_{st.session_state.get('uploader_nonce', 0)}",
)
if uploaded is None:
    chips = "".join(f'<span class="sa-chip">{g}</span>' for g in FORMAT_GROUPS)
    st.html(f'<div class="sa-chips">{chips}</div>')

if uploaded is not None:
    file_key = (uploaded.name, uploaded.size)
    if st.session_state.get("file_key") != file_key:
        st.session_state.file_key = file_key
        st.session_state.pop("result", None)
        st.session_state.pop("podcast", None)
    if uploaded.size > MAX_FILE_MB * 1024 * 1024:
        st.error(f"El archivo supera {MAX_FILE_MB} MB.")
        st.stop()
    if "result" not in st.session_state:
        summarize(uploaded.name, uploaded.getvalue(), uploaded.type, language)

result = st.session_state.get("result")
if uploaded is None or result is None:
    step(2, "Resumen", active=False)
    step(3, "Audio", active=False)
    st.stop()

# ------------------------------------------------------------------ 2. resumen + 3. podcast
kind_label, kind_icon = KIND_LABEL.get(result["kind"], (result["kind"], ":material/description:"))
stem = Path(result["filename"]).stem

left, right = st.columns([3, 2], gap="large")

with left:
    step(2, "Resumen")

    with st.container(horizontal=True, gap="small"):
        st.badge(kind_label, icon=kind_icon, color="gray")
        if result.get("units"):
            unit = "diapositivas" if result["kind"] == "presentacion" else "páginas"
            st.badge(f"{result['units']} {unit}", icon=":material/layers:", color="gray")
        st.badge(_human_size(uploaded.size), icon=":material/folder_open:", color="gray")
        st.badge(f"{result['chars']:,} caracteres leídos", icon=":material/text_fields:", color="gray")
        st.badge(f"{result['elapsed']:.1f} s", icon=":material/bolt:", color="yellow")

    for note in result.get("notes", []):
        st.info(note, icon=":material/info:")

    if result["language"] != language:
        st.caption(f"Este resumen está en {LANG_LABEL[result['language']]}.")
        if st.button(f"Resumir de nuevo en {LANG_LABEL[language]}", icon=":material/translate:"):
            summarize(uploaded.name, uploaded.getvalue(), uploaded.type, language)
            st.rerun()

    with st.container(border=True, key="summary_card"):
        st.markdown(result["summary"])

    with st.container(horizontal=True, gap="small"):
        st.download_button("Descargar .md", result["summary"], f"{stem}_resumen.md", "text/markdown",
                           icon=":material/download:")
        st.download_button("Descargar .txt", _plain(result["summary"]), f"{stem}_resumen.txt",
                           "text/plain", icon=":material/download:")

with right:
    step(3, "Audio")
    with st.container(border=True, key="podcast_card"):
        if not result.get("doc_id"):
            st.warning("El audio no está disponible para este archivo (falló el almacenamiento).")
            st.stop()

        style = st.segmented_control(
            "Estilo", list(STYLE_LABEL), default="podcast", format_func=STYLE_LABEL.get,
            key="audio_style",
        ) or "podcast"
        hosts = HOSTS[language]
        if style == "podcast":
            st.markdown(
                f"**{hosts[0]}** y **{hosts[1]}** conversan sobre el documento en "
                f"{LANG_LABEL[language].lower()}. Ideal para temas que se entienden mejor platicados."
            )
        else:
            st.markdown(
                f"**{NARRATOR[language]}** narra un briefing ejecutivo en {LANG_LABEL[language].lower()}: "
                "puntos clave, cifras y pendientes, sin conversación. Ideal para reportes, minutas y código."
            )
        length = st.segmented_control(
            "Duración", list(LENGTH_LABEL), default="corto", format_func=LENGTH_LABEL.get,
        ) or "corto"

        if st.button(f"Generar {STYLE_LABEL[style].lower()}", type="primary", icon=STYLE_ICON[style],
                     use_container_width=True):
            with st.status("Creando el audio…", expanded=True) as status:
                status.write("Escribiendo el guion y grabando "
                             + ("la voz" if style == "resumen" else "las voces"))
                try:
                    pod = client.make_audio(result["doc_id"], length, language, style)
                except client.ApiError as exc:
                    status.update(label="No se pudo generar el audio", state="error")
                    st.error(str(exc))
                    st.stop()
                status.update(label="Audio listo", state="complete", expanded=False)
            st.session_state.podcast = pod

        pod = st.session_state.get("podcast")
        if pod:
            st.html(f'<div class="sa-pod-title">{html.escape(pod["title"])}</div>')
            st.audio(pod["audio_bytes"], format="audio/mpeg")
            st.download_button("Descargar MP3", pod["audio_bytes"], pod["audio_filename"], "audio/mpeg",
                               type="primary", icon=":material/download:", use_container_width=True)

            pod_lang = pod.get("language", "es")
            narrated = pod.get("style") == "resumen"
            names = (NARRATOR[pod_lang], NARRATOR[pod_lang]) if narrated else HOSTS[pod_lang]
            st.caption(f"{STYLE_LABEL.get(pod.get('style', 'podcast'))} · {LENGTH_LABEL[pod['length']]}")
            turns_html = []
            for i, t in enumerate(pod["turns"]):
                is_a = t["speaker"] == "A"
                name = names[0] if is_a else names[1]
                if narrated and i:   # en narración solo se muestra el nombre una vez
                    turns_html.append(f'<div class="sa-turn"><div></div>'
                                      f'<div class="sa-text">{html.escape(t["text"])}</div></div>')
                    continue
                turns_html.append(
                    f'<div class="sa-turn"><div class="sa-avatar {"a" if is_a else "b"}">{name[0]}</div>'
                    f'<div><div class="sa-who">{name}</div>'
                    f'<div class="sa-text">{html.escape(t["text"])}</div></div></div>'
                )
            with st.expander("Ver guion", icon=":material/subject:"):
                st.html("".join(turns_html))
