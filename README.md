# summarAI

Herramienta de EY que recibe un archivo y devuelve **un resumen breve en pantalla** (descargable en
`.md` / `.txt`) y, opcionalmente, **un audio en MP3**: podcast a dos voces o audio resumen narrado.
La IA corre en servicios de Azure (OpenAI, AI Speech, Document Intelligence).

> **¿Solo tienes endpoints y claves (sin consola de Azure)?** Sigue
> **[docs/GUIA-EY.md](docs/GUIA-EY.md)**: detalle de cada recurso, qué pedir y cómo arrancarlo
> en el equipo solo con Python.

| Entrada | Cómo se lee |
|---|---|
| PDF | `pypdf`; si está escaneado → OCR con **Azure AI Document Intelligence** |
| PowerPoint `.pptx` | Texto de cada diapositiva, tablas, títulos de gráficas y notas del orador |
| Word `.docx` | Párrafos y tablas |
| Texto, Markdown, CSV, JSON, YAML, HTML… | Directo |
| Infografías / imágenes (`png`, `jpg`, `webp`, `gif`) | Modelo con visión de **Azure OpenAI** (transcribe + describe) |
| Código (`py`, `js`, `ts`, `java`, `cs`, `sql`, `ipynb`…) | Directo; el resumen explica qué hace, componentes y riesgos |

## Arquitectura

```
Usuario ──▶ App Service (Streamlit)  ──x-functions-key──▶  Function App (Flex Consumption, Python)
                                                              │
                     ┌────────────────────┬──────────────────┼───────────────────┐
                     ▼                    ▼                  ▼                   ▼
              Azure OpenAI         Azure AI Speech    Document Intelligence   Blob Storage
          (resumen, guion,        (2 voces neuronales,   (OCR de PDFs       (texto extraído y MP3,
           lectura de imágenes)    MP3)                   escaneados)         borrado a los 7 días)
```

**Flujo del audio:** al resumir se guarda el texto extraído con un `doc_id` (en disco o en Blob,
según `STORAGE_MODE`). Al pulsar *Generar*, el modelo escribe un guion JSON (conversación o
narración), Azure Speech lo sintetiza por bloques en paralelo con SSML y se concatena el MP3. Con
Blob se entrega una URL SAS de 2 h; con almacenamiento local el MP3 viaja en la respuesta.

**Tres interruptores** (todo se arma con variables, sin tocar código):

| Variable | Valores | Para qué |
|---|---|---|
| `BACKEND_MODE` (frontend) | `inprocess` · `http` | `inprocess`: Streamlit ejecuta el backend en el mismo proceso (solo Python). `http`: llama a la API de Azure Functions |
| `STORAGE_MODE` (backend) | `local` · `blob` · `auto` | `local`: carpeta `.data/` en disco. `blob`: Azure Blob Storage. `auto`: blob solo si hay `STORAGE_CONNECTION_STRING` |
| `AUTH_MODE` (frontend) | `local` · `easyauth` · `off` | Login propio, Entra ID vía App Service, o sin login |

## Estructura

```
backend/            lógica + API (Azure Functions, modelo Python v2)
  service.py        lógica de negocio (la usan la API y el modo inprocess)
  function_app.py   endpoints HTTP: /health, /summarize, /podcast
  extractors.py     archivo → texto (PDF, PPTX, DOCX, imágenes, código…)
  summarizer.py     resumen breve (map-reduce si el documento es largo)
  podcast.py        guion (podcast o narración) + síntesis con Azure Speech
  storage.py        almacenamiento local o Blob (texto y audios)
  llm.py            cliente de Azure OpenAI
  prompts.py        todos los prompts
  config.py         configuración (solo credenciales vienen del entorno)
frontend/           Streamlit (login → subir → resumen → audio)
  app.py            interfaz
  auth.py           pantalla de ingreso y usuarios
  client.py         cómo hablar con el backend (inprocess / http)
tools/
  probar_voces.py   escucha y compara voces de Azure Speech
docs/
  GUIA-EY.md        montaje solo con endpoints y claves (equipo EY)
  montaje-manual-EY.md  crear los recursos desde el portal (si tienes acceso)
infra/
  main.bicep        toda la infraestructura
  deploy.sh         despliegue de punta a punta
muestras/           archivos de prueba
```

## Correr en local

### Opción A — lo mínimo (solo Python, sin Functions ni Azurite)

```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt                        # backend + frontend
cp backend/.env.example backend/.env                   # llena endpoints y claves
cp frontend/.env.example frontend/.env                 # BACKEND_MODE=inprocess
cd frontend && streamlit run app.py
```

### Opción B — con la API de Azure Functions (igual que en la nube)

```bash
# backend (terminal 1) — requiere Azure Functions Core Tools v4
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp local.settings.example.json local.settings.json     # llena endpoints y claves
func start

# frontend (terminal 2): en frontend/.env pon BACKEND_MODE=http
cd frontend && streamlit run app.py
```

Con `STORAGE_MODE=local` ninguna de las dos opciones necesita Azurite. Para probar Blob en local:
`azurite --silent --skipApiVersionCheck --location .azurite &` y `STORAGE_MODE=blob`.

## Ingreso (login)

La app abre con una pantalla de ingreso con el mismo diseño que el login de Redactor
(`frontend/auth.py`). Se controla con `AUTH_MODE` en `frontend/.env`:

| `AUTH_MODE` | Comportamiento |
|---|---|
| `local` (defecto) | Usuario y contraseña de `APP_USERS` (cifradas con PBKDF2-SHA256; bloqueo de 60 s tras 5 intentos) |
| `easyauth` | En App Service con Easy Auth + Entra ID: entra directo con la cuenta corporativa |
| `off` | Sin login (solo desarrollo) |

Para agregar un usuario, corre el comando y pega la línea que imprime en `APP_USERS` (separa varios con `;`):

```bash
cd frontend && .venv/bin/python auth.py nombre.apellido
```

El usuario de prueba local está anotado en `frontend/.env`, que no se versiona.

## Estilos de audio y voces

El paso 3 ofrece dos estilos (`style` en `POST /api/podcast`):

| Estilo | Qué genera | Voces (en `backend/config.py`) |
|---|---|---|
| `podcast` | Conversación entre dos anfitriones | `PODCAST_VOICES` (Sofía = es-MX-DaliaNeural, Diego = es-MX-JorgeNeural) |
| `resumen` | Briefing narrado por una sola voz | `NARRATOR_VOICES` (es-MX-DaliaNeural / en-US-AvaNeural) |

**Para escuchar y comparar voces:**
- Voice Gallery de Speech Studio: https://speech.microsoft.com/portal/voicegallery (filtra por idioma; escribe tu propio texto).
- Lista oficial de voces e idiomas: https://learn.microsoft.com/azure/ai-services/speech-service/language-support?tabs=tts
- Con tu propio recurso de Speech:

```bash
python tools/probar_voces.py --list es-MX
python tools/probar_voces.py es-MX-DaliaNeural es-MX-NuriaNeural es-ES-ElviraNeural
```

Los MP3 de prueba quedan en `tools/voces/`. Para cambiar la voz, edita el nombre corto en `config.py` y reinicia la app.

## Desplegar en Azure (cuenta personal)

```bash
brew install azure-cli          # si no lo tienes
az login
az account set --subscription "<tu suscripción>"
./infra/deploy.sh               # RG=… LOCATION=… OPENAI_LOCATION=… para cambiar valores
```

Al terminar imprime la URL del frontend. Variables útiles: `DEPLOY_WEB=false` (solo backend),
`WEB_SKU=F1|B1`, `WEB_LOCATION=<región>`.

> **Cuota de App Service:** las suscripciones Pay-As-You-Go nuevas pueden traer cuota 0 en
> App Service (incluso F1) y el despliegue falla con `SubscriptionIsOverQuotaForSku`. Pide
> 1 instancia de B1 en *Portal → Quotas → App Service* o despliega con `DEPLOY_WEB=false`.

Verifica con `GET <api>/health` que `openai`, `speech` y `ocr` estén en `true` y `storage` en `blob`.

**Notas:**
- Si el modelo `gpt-4.1-mini` / versión `2025-04-14` no está disponible en tu región o
  suscripción, cambia `chatModelName`, `chatModelVersion` u `OPENAI_LOCATION`
  (`az cognitiveservices model list -l <región>`). Debe ser un modelo con visión.
- Costos aproximados en reposo: App Service B1 (~13 USD/mes); Functions Flex, OpenAI, Speech y
  Document Intelligence se cobran por uso.
- Para bajar todo: `az group delete -n rg-summarai-dev`.

## Pasar a la red de EY (checklist)

Lo que conviene cambiar al mover la herramienta a la suscripción de EY:

1. **Autenticación de usuarios:** activar *Easy Auth* (Microsoft Entra ID) en el App Service y
   restringir a usuarios del tenant de EY.
2. **Sin claves:** usar la identidad administrada de la Function App con roles
   `Cognitive Services OpenAI User`, `Cognitive Services Speech User`,
   `Cognitive Services User` y `Storage Blob Data Contributor`, y quitar las claves de los
   App Settings (o, como mínimo, moverlas a **Key Vault** con referencias).
3. **Red:** Private Endpoints para OpenAI, Speech, Document Intelligence y Storage;
   integración de VNet en Function App y App Service; `publicNetworkAccess: Disabled`.
   La API solo debería aceptar tráfico del frontend (restricciones de acceso).
4. **Datos:** confirmar con el equipo de riesgo la retención (parámetro `retentionDays`) y la
   región de procesamiento (deployment `DataZoneStandard` o `Standard` en vez de
   `GlobalStandard` si los datos no deben salir de la geografía).
5. **Políticas de Azure de EY:** nombres, etiquetas obligatorias y SKUs permitidos.
6. **CI/CD:** pipeline en Azure DevOps / GitHub Actions con `main.bicep` + publicación.
