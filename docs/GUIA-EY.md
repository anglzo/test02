# summarAI — Guía de montaje en EY solo con endpoints y claves

Esta guía es para el escenario de EY: **no tienes consola ni portal de Azure**; el equipo de
plataforma te *entrega* recursos ya creados (un endpoint y una clave por servicio) y tú solo los
usas. Con eso, summarAI corre completo en tu equipo con **Python**, sin Azure Functions, sin
Azurite y, si quieres, sin Blob Storage.

Contenido:

1. [Qué es summarAI y qué se construyó](#1-qué-es-summarai-y-qué-se-construyó)
2. [Arquitectura en EY](#2-arquitectura-en-ey)
3. [Recursos: detalle de cada uno y qué pedir](#3-recursos-detalle-de-cada-uno-y-qué-pedir)
4. [El switch de almacenamiento (local ↔ Blob)](#4-el-switch-de-almacenamiento-local--blob)
5. [Variables de configuración (referencia completa)](#5-variables-de-configuración-referencia-completa)
6. [Paso a paso en el PC de EY](#6-paso-a-paso-en-el-pc-de-ey)
7. [Validación](#7-validación)
8. [Problemas comunes](#8-problemas-comunes)
9. [Datos, seguridad y costos](#9-datos-seguridad-y-costos)
10. [Si después te dan hosting (Function App / App Service)](#10-si-después-te-dan-hosting)

---

## 1. Qué es summarAI y qué se construyó

**Qué hace:** subes un archivo y obtienes

1. **Un resumen breve en pantalla** (≤ 220 palabras, Markdown con título, "En resumen", puntos
   clave y "Para tener en cuenta"), descargable en `.md` o `.txt`.
2. **Opcional, un audio MP3** en dos estilos:
   - **Podcast:** dos anfitriones conversan sobre el documento (Sofía y Diego en español;
     Ava y Andrew en inglés).
   - **Audio resumen:** una sola voz narra un briefing ejecutivo (Dalia / Ava).
   Ambos en duración corta (~2 min) o media (~5 min), con el guion visible.

**Formatos de entrada** (máx. 25 MB):

| Tipo | Cómo se lee | Servicio que usa |
|---|---|---|
| PDF con texto | `pypdf` (local) | — |
| PDF escaneado (sin texto) | OCR `prebuilt-read` | Document Intelligence |
| PowerPoint `.pptx` | texto, tablas, títulos de gráficas y notas del orador (`python-pptx`) | — |
| Word `.docx` | párrafos y tablas (`python-docx`) | — |
| Texto, Markdown, CSV, JSON, YAML, HTML, logs | directo | — |
| Imágenes / infografías (`png`, `jpg`, `webp`, `gif`) | el modelo con visión transcribe y describe | Azure OpenAI |
| Código (`py`, `js`, `ts`, `java`, `cs`, `sql`, `ipynb`, …) | directo; el resumen explica qué hace, componentes y riesgos | — |

Después de extraer el texto, **todo resumen y todo guion de audio lo genera Azure OpenAI**, y
**toda voz la genera Azure AI Speech**.

**Cómo se procesa un documento:**

1. *Extracción* (`backend/extractors.py`): archivo → texto. Si el PDF no trae texto, OCR.
2. *Resumen* (`backend/summarizer.py`): hasta 60 000 caracteres va en una sola llamada; más
   largo, se parte en bloques de 40 000, se resume cada bloque en paralelo (map) y luego se
   resume el conjunto (reduce). Tope: 400 000 caracteres.
3. *Guardado* (`backend/storage.py`): se guardan el texto y el resumen con un `doc_id`, para que
   el audio se genere después sin volver a subir el archivo.
4. *Audio* (`backend/podcast.py`): el modelo escribe un guion JSON (turnos o párrafos, sin
   Markdown, números pronunciables, sin inventar datos ni atribuir el documento a EY). Ese guion
   se convierte a SSML, se parte en bloques (≤ 3 500 caracteres y ≤ 30 turnos por petición), se
   sintetizan hasta 4 bloques en paralelo y se concatenan los MP3.

**Lo que se construyó, por capas:**

| Capa | Archivo(s) | Qué hace |
|---|---|---|
| Interfaz | `frontend/app.py` | Streamlit con la línea visual de EY (tema oscuro, IBM Plex Sans, `#FFE600`, logo EY, pasos numerados 1-2-3, tarjeta de resumen, panel de audio, guion como conversación) |
| Ingreso | `frontend/auth.py` | Pantalla de login con el diseño de Redactor (hero "Lo extenso, en breve.", demo animada documento → resumen → audio). Contraseñas con PBKDF2-SHA256, bloqueo de 60 s tras 5 intentos fallidos. Modos `local` / `easyauth` / `off` |
| Conexión | `frontend/client.py` | `BACKEND_MODE=inprocess` (ejecuta el backend dentro de Streamlit) o `http` (llama a la API de Functions) |
| Lógica | `backend/service.py` | `summarize_file()` y `make_audio()`; la comparten la API y el modo inprocess |
| API | `backend/function_app.py` | Azure Functions Python v2: `GET /health`, `POST /summarize`, `POST /podcast` (solo si usas hosting) |
| IA | `backend/llm.py`, `backend/prompts.py` | Cliente de Azure OpenAI con reintentos; todos los prompts en un solo archivo |
| Voz | `backend/podcast.py`, `backend/config.py` | Guion + SSML + Azure Speech; voces configurables |
| Almacenamiento | `backend/storage.py` | **Switch local ↔ Blob** (sección 4) |
| Herramientas | `tools/verificar.py`, `tools/probar_voces.py` | Probar endpoints y claves uno por uno; escuchar y comparar voces |
| Infra (opcional) | `infra/main.bicep`, `infra/deploy.sh` | Despliegue automático en una suscripción propia; **no se usa en EY** |

---

## 2. Arquitectura en EY

Escenario recomendado: todo corre en tu PC y solo sale a los servicios de IA.

```
 PC de EY (Python 3.11/3.12)
 ┌───────────────────────────────────────────────────────┐
 │  Streamlit  (frontend/app.py, login en auth.py)        │
 │     │  BACKEND_MODE=inprocess                          │
 │     ▼                                                  │
 │  backend/service.py  ── extracción local (pypdf, pptx, │
 │     │                    docx) ── .data/ (STORAGE_MODE │
 │     │                    =local)                       │
 └─────┼──────────────────────────────────────────────────┘
       │ HTTPS (api-key / Ocp-Apim-Subscription-Key)
       ├──────────────▶ Azure OpenAI ............ obligatorio
       ├──────────────▶ Azure AI Speech ......... obligatorio para el audio
       ├──────────────▶ Document Intelligence ... opcional (PDF escaneados)
       └──────────────▶ Blob Storage ............ opcional (STORAGE_MODE=blob)
```

**Lo que NO necesitas en este escenario:** Function App, App Service, Azure Functions Core
Tools, Azurite, Key Vault, Application Insights, ni el CLI `az`.

---

## 3. Recursos: detalle de cada uno y qué pedir

Para cada recurso: para qué lo usa summarAI, **qué datos exactos pedir al equipo de plataforma**,
cómo debe estar configurado y cómo comprobarlo.

### 3.1 Azure OpenAI — **obligatorio**

**Para qué:** generar el resumen, escribir el guion del audio y leer imágenes/infografías
(visión).

**Cuándo se llama:**
- 1 llamada por resumen (o N+1 si el documento es largo: N bloques + 1 de unión).
- 1 llamada extra por cada imagen subida.
- 1 llamada por cada audio generado.

**Qué pedir:**

| Dato | Ejemplo | Variable |
|---|---|---|
| Endpoint | `https://oai-xxx.openai.azure.com/` | `AZURE_OPENAI_ENDPOINT` |
| Clave (key1 o key2) | `3f9c…` (32 caracteres) | `AZURE_OPENAI_API_KEY` |
| **Nombre del deployment** (no el del modelo) | `gpt-4.1-mini` | `AZURE_OPENAI_DEPLOYMENT` |
| Versión de API soportada | `2024-12-01-preview` | `AZURE_OPENAI_API_VERSION` |

**Configuración que debe tener el deployment:**
- **Modelo con visión y modo JSON.** Probado con `gpt-4.1-mini` (versión `2025-04-14`).
  También sirven `gpt-4.1`, `gpt-4o` y `gpt-4o-mini`.
- **Cuota:** al menos **50 000 TPM** (tokens por minuto) para uso individual; 100 000+ si lo
  usarán varias personas. Con menos funciona, pero los documentos largos pueden dar
  `429` (el código reintenta solo).
- Tipo de deployment: `GlobalStandard`, `DataZoneStandard` o `Standard`. Lo decide EY según
  dónde deben procesarse los datos; summarAI funciona con cualquiera.
- Filtros de contenido: los predeterminados son suficientes.
- Red: tu PC debe poder alcanzar el endpoint. Si el recurso tiene *private endpoint*, debes
  estar en la VPN/red de EY.

**Parámetros que usa el código:** `chat.completions` con `max_completion_tokens`;
`response_format: json_object` (para el guion); imágenes como `data:` URL en base64 con
`detail: high`.

> Si EY te entrega un **gateway de API Management** en lugar del endpoint directo de OpenAI,
> pide también el encabezado que exige (normalmente `Ocp-Apim-Subscription-Key`). El código
> actual envía `api-key`; agregar otro encabezado es un cambio menor en `backend/llm.py`.

**Prueba manual (opcional):**

```bash
curl -s "$AZURE_OPENAI_ENDPOINT/openai/deployments/$AZURE_OPENAI_DEPLOYMENT/chat/completions?api-version=2024-12-01-preview" \
  -H "api-key: $AZURE_OPENAI_API_KEY" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Di hola"}],"max_completion_tokens":20}'
```

### 3.2 Azure AI Speech — **obligatorio para el audio**

**Para qué:** convertir el guion en voz (texto a voz neuronal, MP3 de 24 kHz y 96 kbps mono).

**Cuándo se llama:** solo al pulsar *Generar podcast / audio resumen*: de 1 a 4 peticiones en
paralelo por audio.

**Qué pedir:**

| Dato | Ejemplo | Variable |
|---|---|---|
| Clave | `8a1d…` | `AZURE_SPEECH_KEY` |
| **Región** del recurso | `eastus2` | `AZURE_SPEECH_REGION` |
| **o** endpoint propio (si el recurso usa dominio personalizado o private endpoint) | `https://spch-xxx.cognitiveservices.azure.com/` | `AZURE_SPEECH_ENDPOINT` |

Con región, el código llama a `https://<región>.tts.speech.microsoft.com/cognitiveservices/v1`.
Con endpoint, llama a `<endpoint>/tts/cognitiveservices/v1`. Si te dan los dos, gana el
endpoint. **Si el recurso tiene private endpoint, usa el endpoint**: la URL por región no pasa
por la red privada.

**Configuración que debe tener:**
- **SKU S0** (estándar). F0 (gratis) sirve para pruebas cortas, pero limita la concurrencia y
  los caracteres por mes.
- Región con **voces neuronales**: todas las regiones principales las tienen.
- Voces que usa summarAI (el verificador confirma que existan):
  `es-MX-DaliaNeural`, `es-MX-JorgeNeural`, `en-US-AvaNeural`, `en-US-AndrewNeural`.
  Para cambiarlas, edita `PODCAST_VOICES` y `NARRATOR_VOICES` en `backend/config.py`.
  Para escucharlas antes, usa https://speech.microsoft.com/portal/voicegallery o
  `python tools/probar_voces.py --list es-MX`.

**Prueba manual (opcional):**

```bash
curl -s "https://$AZURE_SPEECH_REGION.tts.speech.microsoft.com/cognitiveservices/voices/list" \
  -H "Ocp-Apim-Subscription-Key: $AZURE_SPEECH_KEY" | head -c 300
```

### 3.3 Azure AI Document Intelligence — **opcional**

**Para qué:** OCR de PDFs escaneados (imágenes de páginas sin capa de texto). Modelo
`prebuilt-read`, API `2024-11-30` (v4.0 GA).

**Cuándo se llama:** solo cuando un PDF no trae texto. Si no lo configuras, la app muestra
"El PDF no contiene texto…" para esos archivos y **todo lo demás funciona igual**.

**Qué pedir:**

| Dato | Ejemplo | Variable |
|---|---|---|
| Endpoint | `https://di-xxx.cognitiveservices.azure.com/` | `AZURE_DOCINTEL_ENDPOINT` |
| Clave | `c71e…` | `AZURE_DOCINTEL_KEY` |

**Configuración que debe tener:**
- SKU **S0**. F0 solo lee las 2 primeras páginas.
- Debe soportar la API **2024-11-30**. Los recursos de *Form Recognizer* muy antiguos solo
  soportan `2023-07-31`; en ese caso, pide uno nuevo o avisa para ajustar la versión en
  `backend/extractors.py`.

### 3.4 Azure Blob Storage — **opcional** (ver sección 4)

**Para qué:** guardar el texto extraído y los MP3 en la nube en vez de en tu disco. Solo hace
falta si la app corre en un servidor o la usarán varias personas desde distintos equipos.

**Qué pedir (si lo vas a usar):**

| Dato | Ejemplo | Variable |
|---|---|---|
| **Cadena de conexión con clave de cuenta** | `DefaultEndpointsProtocol=https;AccountName=stxxx;AccountKey=…;EndpointSuffix=core.windows.net` | `STORAGE_CONNECTION_STRING` |
| Contenedor | `summarai` (la app lo crea si tiene permiso; si no, pide que lo creen) | fijo en `backend/config.py` (`BLOB_CONTAINER`) |

**Configuración que debe tener:**
- **StorageV2**, redundancia LRS.
- Acceso público a blobs: deshabilitado. La app entrega los audios con **URLs SAS de solo
  lectura que caducan a las 2 h**; por eso necesita la *cadena con AccountKey*. Una SAS o una
  identidad administrada no bastan sin cambios de código.
- **Regla de ciclo de vida** recomendada: borrar blobs del contenedor `summarai` a los 7 días.
- Si te dan Blob y algo falla (red, permisos, firewall), cambia a `STORAGE_MODE=local` y sigue
  probando; no tienes que tocar código.

### Resumen: qué pedir en un correo

> Para la herramienta summarAI necesito, por favor:
> 1. **Azure OpenAI:** endpoint, clave y nombre de un deployment de `gpt-4.1-mini` (o `gpt-4o-mini`)
>    con ≥ 50k TPM, y la api-version soportada (usamos `2024-12-01-preview`).
> 2. **Azure AI Speech (S0):** clave y región (o endpoint si tiene private endpoint).
> 3. *(Opcional)* **Document Intelligence (S0):** endpoint y clave, con soporte de API `2024-11-30`.
> 4. *(Opcional)* **Storage account:** cadena de conexión con AccountKey y un contenedor `summarai`
>    con regla de borrado a 7 días.
>
> Necesito alcanzar esos endpoints desde mi equipo (VPN/red de EY).

---

## 4. El switch de almacenamiento (local ↔ Blob)

summarAI necesita guardar dos cosas entre el paso 2 (resumen) y el paso 3 (audio):

- `docs/<doc_id>.json`: el nombre, el tipo, el idioma, el resumen y el texto extraído.
- `audio/<doc_id>.mp3` (en Blob: `podcasts/<doc_id>.mp3`): el audio generado.

Se elige con **`STORAGE_MODE`**, sin tocar código:

| `STORAGE_MODE` | Dónde guarda | Cómo te llega el MP3 | Requiere |
|---|---|---|---|
| **`local`** (recomendado para pruebas) | Carpeta `.data/` del proyecto (o `LOCAL_STORAGE_DIR`) | En la misma respuesta (base64) | Nada |
| `blob` | Contenedor `summarai` de la cuenta de Storage | URL SAS de 2 h | `STORAGE_CONNECTION_STRING` |
| `auto` | `blob` si hay `STORAGE_CONNECTION_STRING`; si no, `local` | — | — |

Detalles:
- En `local`, al guardar un documento nuevo se borra lo que tenga más de **7 días**
  (`LOCAL_RETENTION_DAYS` en `backend/config.py`), igual que la regla de ciclo de vida de Blob.
- `auto` **ignora** `AzureWebJobsStorage` (la cadena interna de Azure Functions). Así, aunque
  corras la API con `func start`, una prueba local nunca se queda esperando a Azurite.
- Si `blob` falla al guardar, el resumen igual se muestra y solo se desactiva el audio, con un
  aviso. `tools/verificar.py` te dice exactamente qué falló.
- Para cambiar de modo, edita la variable y reinicia la app. Los documentos guardados en un modo
  no se ven desde el otro (sube el archivo de nuevo).

---

## 5. Variables de configuración (referencia completa)

La configuración del backend va en **`backend/.env`** (plantilla: `backend/.env.example`) **o**
en `backend/local.settings.json` (el formato de Azure Functions). Se leen los dos; usa uno.

| Variable | Obligatoria | Valor por defecto | Descripción |
|---|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | **sí** | — | Endpoint del recurso de Azure OpenAI |
| `AZURE_OPENAI_API_KEY` | **sí** | — | Clave |
| `AZURE_OPENAI_DEPLOYMENT` | **sí** | `gpt-4.1-mini` | Nombre del deployment |
| `AZURE_OPENAI_API_VERSION` | no | `2024-12-01-preview` | Versión de la API |
| `AZURE_SPEECH_KEY` | para audio | — | Clave de Speech |
| `AZURE_SPEECH_REGION` | para audio* | — | Región (p. ej. `eastus2`) |
| `AZURE_SPEECH_ENDPOINT` | para audio* | — | Endpoint propio; si existe, reemplaza la región |
| `AZURE_DOCINTEL_ENDPOINT` | no | — | OCR de PDFs escaneados |
| `AZURE_DOCINTEL_KEY` | no | — | Clave de Document Intelligence |
| `STORAGE_MODE` | no | `auto` | `local`, `blob` o `auto` |
| `LOCAL_STORAGE_DIR` | no | `<proyecto>/.data` | Carpeta del modo local |
| `STORAGE_CONNECTION_STRING` | si `blob` | — | Cadena de conexión con AccountKey |

\* Una de las dos.

Frontend: **`frontend/.env`** (plantilla: `frontend/.env.example`).

| Variable | Valor en EY | Descripción |
|---|---|---|
| `BACKEND_MODE` | `inprocess` | `inprocess` = todo en Streamlit. `http` = llamar a una API de Functions |
| `BACKEND_URL` | (vacío) | Solo con `http`: `https://<func>.azurewebsites.net/api` o `http://localhost:7071/api` |
| `FUNCTION_KEY` | (vacío) | Solo con `http` contra Azure: clave de la Function App |
| `AUTH_MODE` | `local` | `local` (usuarios de `APP_USERS`), `easyauth` (App Service + Entra ID) u `off` |
| `APP_USERS` | `tool02_user:<hash>` | `usuario:hash` separados por `;`. Genera cada línea con `python frontend/auth.py <usuario>` |

> Las variables del sistema operativo **ganan** sobre los archivos. Así puedes probar un cambio
> sin editarlos, por ejemplo: `STORAGE_MODE=blob streamlit run app.py`.

---

## 6. Paso a paso en el PC de EY

### 6.1 Requisitos

- **Python 3.11 o 3.12** (de la tienda de software de EY o python.org). Se probó con 3.12.
- **Git**, o descargar el repositorio como ZIP.
- Salida HTTPS a los endpoints de la sección 3, y a PyPI para instalar paquetes (o un
  mirror/proxy de PyPI de EY).

### 6.2 Instalar

```powershell
git clone https://github.com/anglzo/test02.git summarAI
cd summarAI
python -m venv .venv
.venv\Scripts\activate              # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt     # instala backend + frontend
```

Si estás detrás del proxy corporativo:

```powershell
pip install --proxy http://<proxy>:<puerto> -r requirements.txt
```

### 6.3 Configurar

```powershell
copy backend\.env.example backend\.env      # macOS/Linux: cp
copy frontend\.env.example frontend\.env
```

- En `backend/.env`: pega los endpoints y claves de la sección 3 y deja `STORAGE_MODE=local`.
- En `frontend/.env`: deja `BACKEND_MODE=inprocess` y `AUTH_MODE=local`. En `APP_USERS` pega
  la línea de tu usuario. Puedes copiar la de `tool02_user` de tu `.env` actual o generar una:

```powershell
python frontend\auth.py tool02_user
```

### 6.4 Verificar y arrancar

```powershell
python tools\verificar.py           # debe salir todo en ✓ (DocIntel puede quedar en –)
cd frontend
streamlit run app.py
```

Abre http://localhost:8501, entra con tu usuario y sube un archivo de `muestras/`.

---

## 7. Validación

| # | Prueba | Archivo | Esperado |
|---|---|---|---|
| 1 | Login incorrecto | — | "Usuario o contraseña incorrectos." |
| 2 | Login correcto | — | Pantalla principal con tu usuario abajo a la izquierda |
| 3 | PDF con texto | `muestras/estrategia.pdf` | Resumen; distintivos "PDF · 2 páginas" |
| 4 | PowerPoint | `muestras/resultados.pptx` | Resumen con cifras de las diapositivas |
| 5 | Imagen | `muestras/infografia.png` | Resumen de la infografía (usa visión) |
| 6 | Código | `muestras/ejemplo.py` | Explica qué hace el código |
| 7 | PDF escaneado | `muestras/escaneado.pdf` | Con DocIntel: OCR. Sin DocIntel: aviso claro |
| 8 | Podcast corto | cualquiera | MP3 de ~1-2 min con dos voces y guion |
| 9 | Audio resumen | cualquiera | MP3 con una voz; archivo `*_audio_resumen.mp3` |
| 10 | Idioma English | cualquiera | Resumen y audio en inglés |
| 11 | Almacenamiento | — | Con `local`: aparecen archivos en `.data/docs` y `.data/audio` |

---

## 8. Problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `verificar.py`: OpenAI **401** | Clave incorrecta o de otro recurso | Pide de nuevo la key1 del recurso de OpenAI |
| OpenAI **404** | Usaste el nombre del *modelo* y no el del *deployment*, o la api-version no existe | Confirma el nombre exacto del deployment; prueba `2024-10-21` |
| OpenAI **403** / "Public access is disabled" | El recurso tiene private endpoint y no estás en la red de EY | Conéctate a la VPN o pide acceso de red |
| OpenAI **429** | Cuota (TPM) baja | Funciona con reintentos; pide más TPM si es frecuente |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Inspección SSL del proxy corporativo | Exporta el certificado raíz de EY a `.pem` y define `REQUESTS_CA_BUNDLE` y `SSL_CERT_FILE` con su ruta (o `pip install pip-system-certs`) |
| `ConnectionError` / timeout | Proxy | Define `HTTPS_PROXY=http://<proxy>:<puerto>` antes de arrancar |
| Speech **401** | Clave o región no corresponden | La región debe ser la del recurso; si te dieron endpoint, usa `AZURE_SPEECH_ENDPOINT` |
| Speech funciona por región pero no en la red de EY | Private endpoint | Usa `AZURE_SPEECH_ENDPOINT` |
| "faltan: es-MX-…Neural" en `verificar.py` | Región sin esa voz | Elige otra voz en `config.py` (`probar_voces.py --list es-MX`) |
| DocIntel **404** | Recurso antiguo sin API 2024-11-30 | Pide un recurso nuevo o ajusta la versión en `extractors.py` |
| Blob: `AuthenticationFailed` / `AuthorizationFailure` | Cadena sin AccountKey o firewall de Storage | `STORAGE_MODE=local` y sigue; pide la cadena con clave |
| El audio no aparece: "El audio no está disponible…" | Falló el guardado (Blob) | `STORAGE_MODE=local` |
| "No hay usuarios configurados (APP_USERS)" | `frontend/.env` sin usuarios | Genera uno con `python frontend/auth.py <usuario>` |
| Demasiados intentos | 5 contraseñas erróneas | Espera 60 s |

---

## 9. Datos, seguridad y costos

**Qué sale de tu equipo:**
- El texto extraído del documento va a **Azure OpenAI**. Las imágenes van completas (base64).
- El guion de audio va a **Azure AI Speech**.
- Los PDFs escaneados van completos a **Document Intelligence**.
- Con `STORAGE_MODE=blob`, el texto y los MP3 se guardan en la cuenta de Storage.
- Ningún otro servicio externo recibe datos. Streamlit tiene la telemetría desactivada
  (`gatherUsageStats = false`).

**Qué queda en tu equipo:** con `STORAGE_MODE=local`, los archivos de `.data/` se borran solos a
los 7 días. Puedes borrar la carpeta en cualquier momento.

**Credenciales:**
- `backend/.env`, `backend/local.settings.json` y `frontend/.env` están en `.gitignore` y
  **nunca se suben al repositorio**.
- Las contraseñas de `APP_USERS` se guardan con hash (PBKDF2-SHA256, 310 000 iteraciones), no
  en texto legible.
- El login `local` es una barrera básica para una prueba piloto. Para producción, usa
  `AUTH_MODE=easyauth` detrás de un App Service con Entra ID (sección 10).

**Costos por uso (aprox., precios de lista en EE. UU.):**

| Servicio | Unidad | Costo típico por documento |
|---|---|---|
| Azure OpenAI `gpt-4.1-mini` | ~0.40 USD / 1M tokens de entrada, ~1.60 USD / 1M de salida | Resumen de 10 páginas: < 0.01 USD |
| Azure AI Speech (neural) | ~15 USD / 1M caracteres | Audio de 2 min (~2 000 caracteres): ~0.03 USD; de 5 min: ~0.08 USD |
| Document Intelligence Read | ~1.50 USD / 1 000 páginas | 0.0015 USD por página escaneada |
| Blob Storage | centavos al mes | Despreciable con borrado a 7 días |

No hay costo fijo mientras no se use: ninguno de los cuatro servicios cobra por estar encendido
en S0.

---

## 10. Si después te dan hosting

Si más adelante EY te da un **Function App** y/o un **App Service** (sin consola, solo para
publicar):

- **Function App (API):** Python 3.12, plan Flex Consumption o Premium. Publica la carpeta
  `backend/` y pon como *App Settings* las mismas variables de la sección 5, con
  `STORAGE_MODE=blob` y `STORAGE_CONNECTION_STRING`. Endpoints: `/api/health` (anónimo),
  `/api/summarize` y `/api/podcast` (requieren `x-functions-key`). Timeout: 10 min (`host.json`).
- **App Service (interfaz):** Python 3.12. Publica `frontend/` y `backend/` juntos con
  `BACKEND_MODE=inprocess` (no hace falta Function App). Si prefieres separarlos, publica solo
  `frontend/` con `BACKEND_MODE=http`, `BACKEND_URL` y `FUNCTION_KEY`.
  - Comando de inicio: `python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0`
    (o `frontend/startup.sh`).
  - Con Easy Auth + Entra ID activo, usa `AUTH_MODE=easyauth` y no necesitas `APP_USERS`.
- La creación de esos recursos desde el portal está en
  [montaje-manual-EY.md](montaje-manual-EY.md); la versión automática, en `infra/main.bicep`.
