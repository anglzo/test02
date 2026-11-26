"""
auth.py — capa de ingreso de summarAI.

La pantalla sigue el diseño del login de Redactor (marca arriba a la izquierda, hero con
palabra resaltada en amarillo, demo animada y tarjeta de acceso a la derecha).

Modos (variable AUTH_MODE):
  local     (por defecto) usuarios de APP_USERS con contraseña cifrada (PBKDF2-SHA256).
  easyauth  en Azure App Service con Easy Auth + Microsoft Entra ID: Azure ya autenticó al
            usuario y su correo llega en la cabecera X-MS-CLIENT-PRINCIPAL-NAME. No se muestra
            formulario. Solo actívalo detrás de Easy Auth: fuera de él la cabecera se puede falsificar.
  off       sin login (solo para desarrollo).

APP_USERS:  usuario:hash;usuario2:hash   — genera cada línea con:
    python auth.py nombre.apellido
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

import streamlit as st

ACCENT = "#FFE600"
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "ey_logo.svg"
ITERATIONS = 310_000
MAX_ATTEMPTS = 5
LOCK_SECONDS = 60


# ------------------------------------------------------------------ contraseñas
def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _check(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(calc.hex(), digest)
    except ValueError:
        return False


def _users() -> dict[str, str]:
    users = {}
    for entry in os.environ.get("APP_USERS", "").replace(",", ";").split(";"):
        name, _, stored = entry.strip().partition(":")
        if name and stored:
            users[name.strip().lower()] = stored.strip()
    return users


def _verify(user: str, password: str) -> bool:
    stored = _users().get(user.strip().lower())
    if stored is None:
        _check(password, hash_password("x", 1_000))   # tiempo parecido aunque el usuario no exista
        return False
    return _check(password, stored)


# ------------------------------------------------------------------ estilos
CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

:root {{
  --bg: #0E0F12; --panel: #16181D; --panel-2: #1C1F25; --line: #2A2E36;
  --text: #F2F3F5; --muted: #9AA0AA; --accent: {ACCENT};
}}

header[data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer,
[data-testid="stDecoration"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebar"] {{ display: none !important; }}

html, body, .stApp, [class*="st-"] {{ font-family: 'Inter', system-ui, sans-serif; }}
/* que la regla anterior no pise la fuente de íconos (ojo de la contraseña) */
[data-testid="stTextInput"] button span, [data-testid="stIconMaterial"] {{
  font-family: 'Material Symbols Rounded' !important;
}}

.stApp {{
  background:
    radial-gradient(900px 500px at 15% 10%, rgba(255,230,0,.06), transparent 60%),
    linear-gradient(var(--bg), var(--bg));
  color: var(--text);
}}
.stApp::before {{
  content: ""; position: fixed; inset: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(ellipse at 30% 40%, #000 20%, transparent 75%);
}}

.block-container, [data-testid="stMainBlockContainer"] {{
  max-width: 1180px; padding: 2rem 2rem 2rem;
  min-height: 100vh; display: flex; flex-direction: column; justify-content: safe center;
}}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{ flex: 0 0 auto; }}
[data-testid="stHorizontalBlock"] {{ align-items: center; }}

/* ---------- Marca ---------- */
.brand {{ display: flex; align-items: center; gap: .65rem; margin-bottom: 3rem; }}
.brand img {{ height: 34px; width: auto; display: block; }}
.brand-name {{ font-weight: 700; font-size: 1.05rem; letter-spacing: -.01em; color: var(--text); }}
.brand-name b {{ color: var(--accent); font-weight: 700; }}
.brand-sep {{ width: 1px; height: 18px; background: var(--line); }}
.brand-tag {{ color: var(--muted); font-size: .85rem; }}

/* ---------- Hero ---------- */
.eyebrow {{
  font-family: 'JetBrains Mono', monospace; font-size: .75rem; letter-spacing: .14em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 1rem;
}}
.hero-title {{
  font-size: clamp(2.2rem, 4vw, 3.4rem); line-height: 1.05; font-weight: 800;
  letter-spacing: -.035em; color: var(--text); margin: 0 0 1.1rem;
}}
.hero-title .bar {{
  background: var(--accent); color: #111; border-radius: 4px; padding: 0 .14em;
  box-decoration-break: clone; -webkit-box-decoration-break: clone;
}}
.hero-sub {{ color: var(--muted); font-size: 1.02rem; line-height: 1.6; max-width: 30rem; margin-bottom: 2.2rem; }}

/* ---------- Demo animada: documento -> resumen -> audio ---------- */
.doc {{
  background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 1.25rem 1.4rem; max-width: 30rem;
  font-family: 'JetBrains Mono', monospace; font-size: .8rem; line-height: 1.9; color: #C9CDD4;
  box-shadow: 0 30px 60px -30px rgba(0,0,0,.7);
}}
.doc-head {{ display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px solid var(--line); padding-bottom: .7rem; margin-bottom: .8rem; }}
.doc-file {{ color: var(--text); font-weight: 500; }}
.doc-file small {{ color: var(--muted); font-weight: 400; }}
.doc-status {{ display: inline-flex; align-items: center; gap: .4rem; color: var(--muted); font-size: .72rem; }}
.doc-status i {{ width: 7px; height: 7px; border-radius: 50%; background: var(--accent);
  animation: pulse 1.6s ease-in-out infinite; }}

.stage {{ position: relative; height: 7.4rem; }}
.lines, .sum {{ position: absolute; inset: 0; }}
.lines span {{
  display: block; height: 6px; border-radius: 3px; background: #2C3038; margin: .62rem 0;
  transform-origin: left; animation: condense 7s cubic-bezier(.7,0,.2,1) infinite;
  animation-delay: var(--d, 0s);
}}
.sum div {{ opacity: 0; transform: translateY(4px); animation: reveal 7s infinite; animation-delay: var(--d, 0s); }}
.sum b {{ color: var(--accent); font-weight: 500; margin-right: .45rem; }}
.sum em {{ color: var(--text); font-style: normal; }}

.wave {{ display: flex; align-items: center; gap: .75rem; border-top: 1px solid var(--line);
  margin-top: .8rem; padding-top: .8rem; color: var(--muted); font-size: .72rem;
  opacity: 0; animation: reveal 7s infinite; animation-delay: 1.1s; }}
.play {{ width: 22px; height: 22px; border-radius: 50%; background: var(--accent); flex: none;
  display: grid; place-items: center; }}
.play::after {{ content: ""; border-left: 7px solid #111; border-top: 4.5px solid transparent;
  border-bottom: 4.5px solid transparent; margin-left: 2px; }}
.bars {{ display: flex; align-items: center; gap: 3px; height: 22px; flex: 1; }}
.bars span {{ width: 3px; height: 100%; border-radius: 2px; background: var(--accent); opacity: .85;
  transform: scaleY(.25); animation: eq 1.1s ease-in-out infinite; animation-delay: var(--d, 0s); }}

@keyframes condense {{
  0%,14% {{ transform: scaleX(1); opacity: 1; }}
  28%,84% {{ transform: scaleX(.12); opacity: 0; }}
  96%,100% {{ transform: scaleX(1); opacity: 1; }}
}}
@keyframes reveal {{
  0%,24% {{ opacity: 0; transform: translateY(4px); }}
  32%,84% {{ opacity: 1; transform: none; }}
  92%,100% {{ opacity: 0; transform: translateY(4px); }}
}}
@keyframes eq {{ 0%,100% {{ transform: scaleY(.25); }} 50% {{ transform: scaleY(1); }} }}
@keyframes pulse {{ 50% {{ opacity: .35; }} }}

.formats {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-top: 1.4rem; }}
.formats span {{
  font-size: .75rem; color: var(--muted); border: 1px solid var(--line);
  padding: .3rem .65rem; border-radius: 999px; background: rgba(255,255,255,.02);
}}

/* ---------- Tarjeta de login ---------- */
.st-key-login_card {{
  background: var(--panel); border: 1px solid var(--line); border-radius: 18px;
  padding: 2.2rem 2.2rem 1.6rem; box-shadow: 0 40px 80px -40px rgba(0,0,0,.8);
  max-width: 420px; margin-left: auto; position: relative; overflow: hidden;
}}
.st-key-login_card::before {{
  content: ""; position: absolute; top: 0; left: 2.2rem; width: 44px; height: 3px;
  background: var(--accent); border-radius: 0 0 3px 3px;
}}
.card-title {{ font-size: 1.5rem; font-weight: 700; letter-spacing: -.02em; color: var(--text); margin: 0 0 .35rem; }}
.card-sub {{ color: var(--muted); font-size: .9rem; margin-bottom: 1.6rem; }}

[data-testid="stForm"] {{ border: 0 !important; padding: 0 !important; background: transparent !important; }}

[data-testid="stTextInput"] label p {{ color: #C9CDD4 !important; font-size: .82rem !important; font-weight: 500 !important; }}
[data-testid="stTextInput"] div[data-baseweb="input"] {{
  background: var(--panel-2) !important; border: 1px solid var(--line) !important;
  border-radius: 10px !important; transition: border-color .15s, box-shadow .15s;
}}
[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {{
  border-color: var(--accent) !important; box-shadow: 0 0 0 3px rgba(255,230,0,.15) !important;
}}
[data-testid="stTextInput"] div[data-baseweb="input"] > div {{ background: transparent !important; }}
[data-testid="stTextInput"] input {{
  color: var(--text) !important; font-size: .95rem !important; padding: .75rem .9rem !important;
  caret-color: var(--accent);
}}
[data-testid="stTextInput"] input::placeholder {{ color: #5E646E !important; }}
[data-testid="stTextInput"] button {{ background: transparent !important; color: var(--muted) !important; }}
[data-testid="InputInstructions"] {{ display: none; }}

[data-testid="stFormSubmitButton"] button {{
  width: 100%; background: var(--accent) !important; color: #111 !important; border: 0 !important;
  border-radius: 10px !important; padding: .72rem 1rem !important; margin-top: .4rem;
  font-weight: 700 !important; transition: transform .1s, filter .15s;
}}
[data-testid="stFormSubmitButton"] button p {{ font-weight: 700 !important; font-size: .95rem !important; }}
[data-testid="stFormSubmitButton"] button:hover {{ filter: brightness(1.06); }}
[data-testid="stFormSubmitButton"] button:active {{ transform: translateY(1px); }}

[data-testid="stAlert"] {{ border-radius: 10px; }}

.card-foot {{
  display: flex; align-items: center; gap: .5rem; margin-top: 1.4rem; padding-top: 1.1rem;
  border-top: 1px solid var(--line); color: var(--muted); font-size: .76rem; line-height: 1.4;
}}
.card-foot svg {{ flex: none; }}

@media (max-width: 900px) {{
  .doc, .formats {{ display: none; }}
  .brand {{ margin-bottom: 1.5rem; }}
  .hero-sub {{ margin-bottom: .5rem; }}
  .st-key-login_card {{ margin: 0 auto; padding: 1.8rem 1.4rem 1.3rem; }}
  .block-container, [data-testid="stMainBlockContainer"] {{ padding: 1.5rem 1rem; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .lines span {{ animation: none; opacity: .25; }}
  .sum div, .wave {{ animation: none; opacity: 1; transform: none; }}
  .bars span {{ animation: none; transform: scaleY(.6); }}
}}
</style>
"""

LOCK_ICON = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" '
    'width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>'
)


def _hero() -> str:
    logo = base64.b64encode(LOGO_PATH.read_bytes()).decode()
    widths = [96, 88, 92, 70, 94, 62]
    lines = "".join(f'<span style="width:{w}%;--d:{i * .06:.2f}s"></span>' for i, w in enumerate(widths))
    heights = [.4, .7, 1, .6, .85, .5, .95, .65, .8, .45, .9, .55, .75, 1, .6, .4, .7, .85, .5, .65]
    bars = "".join(f'<span style="--d:{h * -1.1:.2f}s"></span>' for h in heights)
    return f"""
<div class="brand">
  <img src="data:image/svg+xml;base64,{logo}" alt="EY">
  <div class="brand-name">summar<b>AI</b></div>
  <div class="brand-sep"></div>
  <div class="brand-tag">Resúmenes y audio con IA</div>
</div>

<div class="eyebrow">Acceso interno</div>
<h1 class="hero-title">Lo extenso,<br><span class="bar">en breve</span>.</h1>
<p class="hero-sub">Sube un documento, presentación, imagen o código y obtén un resumen claro en
segundos — o escúchalo como podcast o audio resumen mientras haces otra cosa.</p>

<div class="doc">
  <div class="doc-head">
    <span class="doc-file">informe_trimestral.pdf <small>· 42 págs.</small></span>
    <span class="doc-status"><i></i>Resumiendo</span>
  </div>
  <div class="stage">
    <div class="lines">{lines}</div>
    <div class="sum">
      <div style="--d:.15s"><b>›</b><em>Ingresos +12 %</em> frente al trimestre anterior</div>
      <div style="--d:.4s"><b>›</b>Migración a la nube: <em>80 % en 2027</em></div>
      <div style="--d:.65s"><b>›</b>Riesgo: <em>dependencia de proveedores</em></div>
      <div style="--d:.9s"><b>›</b>Pendiente: <em>plan de talento en IA</em></div>
    </div>
  </div>
  <div class="wave"><span class="play"></span><span class="bars">{bars}</span><span>Audio resumen · 1:14</span></div>
</div>

<div class="formats"><span>PDF</span><span>Word</span><span>PowerPoint</span><span>Imágenes</span><span>Código</span></div>
"""


# ------------------------------------------------------------------ pantalla
def _login_screen() -> None:
    st.html(CSS)
    left, right = st.columns([1.15, 1], gap="large", vertical_alignment="center")

    with left:
        st.html(_hero())

    with right:
        with st.container(key="login_card"):
            st.html(
                '<div class="card-title">Iniciar sesión</div>'
                '<div class="card-sub">Usa tus credenciales para continuar.</div>'
            )
            with st.form("login", border=False):
                user = st.text_input("Usuario", placeholder="nombre.apellido", autocomplete="username")
                password = st.text_input("Contraseña", type="password", placeholder="••••••••",
                                         autocomplete="current-password")
                submitted = st.form_submit_button("Ingresar", width="stretch")

            locked_until = st.session_state.get("_auth_locked_until", 0)
            if submitted:
                if time.time() < locked_until:
                    st.error(f"Demasiados intentos. Espera {int(locked_until - time.time()) + 1} s.")
                elif not _users():
                    st.error("No hay usuarios configurados (APP_USERS).")
                elif not user or not password:
                    st.warning("Ingresa tu usuario y contraseña.")
                elif _verify(user, password):
                    st.session_state.pop("_auth_fails", None)
                    st.session_state.auth_user = user.strip().lower()
                    st.rerun()
                else:
                    fails = st.session_state.get("_auth_fails", 0) + 1
                    st.session_state._auth_fails = fails
                    if fails >= MAX_ATTEMPTS:
                        st.session_state._auth_fails = 0
                        st.session_state._auth_locked_until = time.time() + LOCK_SECONDS
                        st.error(f"Demasiados intentos. Espera {LOCK_SECONDS} s.")
                    else:
                        st.error("Usuario o contraseña incorrectos.")

            st.html(
                f'<div class="card-foot">{LOCK_ICON}'
                "Uso exclusivo para personal autorizado. Los accesos quedan registrados.</div>"
            )


def require_login() -> str:
    """Devuelve el usuario autenticado; si no hay sesión, muestra el login y detiene la página."""
    mode = os.environ.get("AUTH_MODE", "local").strip().lower()
    if mode == "off":
        return "local"
    if mode == "easyauth":
        user = st.context.headers.get("X-Ms-Client-Principal-Name")
        if user:
            return user
        st.error("No llegó la identidad de Easy Auth. Revisa la autenticación del App Service.")
        st.stop()

    if st.session_state.get("auth_user"):
        return st.session_state.auth_user
    _login_screen()
    st.stop()


def logout_button() -> None:
    """Usuario + cerrar sesión (para el sidebar). En Easy Auth usa el endpoint de Azure."""
    mode = os.environ.get("AUTH_MODE", "local").strip().lower()
    if mode == "off":
        return
    user = st.session_state.get("auth_user") or st.context.headers.get("X-Ms-Client-Principal-Name", "")
    st.caption(f":material/account_circle: {user}")
    if mode == "easyauth":
        st.link_button("Cerrar sesión", "/.auth/logout", icon=":material/logout:", use_container_width=True)
    elif st.button("Cerrar sesión", icon=":material/logout:", use_container_width=True):
        st.session_state.clear()
        st.rerun()


if __name__ == "__main__":   # python auth.py nombre.apellido  -> línea para APP_USERS
    import getpass
    import sys

    name = (sys.argv[1] if len(sys.argv) > 1 else input("Usuario: ")).strip().lower()
    pw = getpass.getpass("Contraseña: ")
    if len(pw) < 10:
        sys.exit("Usa al menos 10 caracteres.")
    if pw != getpass.getpass("Repite la contraseña: "):
        sys.exit("No coinciden.")
    print(f"{name}:{hash_password(pw)}")
