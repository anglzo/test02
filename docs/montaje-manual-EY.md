# summarAI · Montaje manual en Azure de EY

Guía para recrear summarAI **a mano desde el portal** en la suscripción de EY y para preparar el
PC de EY para desarrollo local. Probado en local con Azurite + servicios de IA reales
(2026-11-25).

---

## 1. Arquitectura

```
Usuario (navegador)
   │  HTTPS
   ▼
App Service Linux · Streamlit (frontend/)          ← login Entra ID (Easy Auth)
   │  HTTPS + x-functions-key
   ▼
Function App · Flex Consumption · Python 3.12 (backend/)
   ├──▶ Azure OpenAI ............ resumen, guion del podcast, lectura de imágenes
   ├──▶ Azure AI Speech ......... voces neuronales → MP3
   ├──▶ Document Intelligence ... OCR de PDFs escaneados
   └──▶ Storage Account (Blob) .. texto extraído + MP3 (se borran a los 7 días)
Application Insights + Log Analytics ← logs de ambos
```

| Componente | Local (PC) | Azure EY |
|---|---|---|
| Frontend | `streamlit run app.py` :8501 | App Service Linux B1 |
| API | `func start` :7071 | Function App Flex Consumption |
| Almacenamiento | Azurite :10000 | Storage Account StorageV2 |
| IA | Azure OpenAI, Speech, Doc. Intelligence (siempre en la nube) | Igual |

> Los servicios de IA no tienen equivalente local: incluso para desarrollar en el PC de EY
> necesitas que existan en Azure (pasos 3.4 a 3.6) y poner sus claves en `local.settings.json`.

---

## 2. Antes de empezar (pedir a TI / Cloud de EY)

- [ ] Suscripción y **grupo de recursos** (p. ej. `rg-summarai-dev`), con rol **Contributor**
      (y **User Access Administrator** o alguien que asigne roles, si usarán identidad administrada).
- [ ] **Acceso a Azure OpenAI** aprobado en la suscripción y cuota del modelo (≥ 50K TPM).
- [ ] **Cuota de App Service** para 1 instancia B1 Linux en la región elegida (en la cuenta
      personal falló con `SubscriptionIsOverQuotaForSku`; en EY suele estar habilitada).
- [ ] Región aprobada por EY con disponibilidad de OpenAI + Speech + Document Intelligence
      (East US 2 funciona para los tres).
- [ ] Políticas de EY: nomenclatura, etiquetas obligatorias, SKUs permitidos, si exigen
      Private Endpoints / sin acceso público.
- [ ] Aprobación de riesgo/datos: qué documentos se pueden subir, retención (7 días por defecto)
      y residencia de datos (ver tipo de deployment en 3.4).

---

## 3. Recursos (en este orden)

Usa la misma región y el mismo grupo de recursos para todo. Los nombres son sugeridos.

### 3.1 Log Analytics workspace — `log-summarai`
- Plan: Pay-as-you-go (PerGB2018) · Retención: 30 días.

### 3.2 Application Insights — `appi-summarai`
- Modo: **basado en workspace** → `log-summarai`.
- Guarda la **Connection String**.

### 3.3 Storage account — `stsummarai<sufijo>` (3-24 minúsculas/números)
- Rendimiento Standard · Redundancia **LRS** · Tipo StorageV2.
- Avanzado: TLS mínimo **1.2**, **desactivar** acceso anónimo a blobs, solo HTTPS.
- Contenedores (privados):
  - `summarai` → datos de la app (`docs/*.json`, `podcasts/*.mp3`). La app lo crea si no existe.
  - `deploymentpackage` → paquetes de despliegue de la Function App (Flex lo usa).
- **Administración del ciclo de vida** → regla `borrar-temporales`:
  blobs en bloque, filtro de prefijo `summarai/`, *eliminar si se modificó hace más de* **7 días**.
- Guarda la **cadena de conexión** (Claves de acceso).

### 3.4 Azure OpenAI — `oai-summarai`
- Tipo: Azure OpenAI · Plan **S0**.
- En **Azure AI Foundry → Deployments → Deploy model**:
  - Modelo: **`gpt-4.1-mini`**, versión **`2025-04-14`** (necesita visión para infografías;
    `gpt-4o-mini` o `gpt-5-mini` también sirven).
  - **Nombre del deployment: `gpt-4.1-mini`** (debe coincidir con `AZURE_OPENAI_DEPLOYMENT`).
  - Tipo: **Data Zone Standard** si los datos no deben salir de EE. UU./UE; *Global Standard*
    si EY lo permite.
  - Capacidad: **50K TPM** (sobra para pruebas; subir si hay muchos usuarios).
- Guarda **Endpoint** (`https://oai-summarai.openai.azure.com/`) y **Key 1**.

### 3.5 Azure AI Speech — `spch-summarai`
- Tipo: Speech service · Plan **S0** (F0 sirve para pruebas, pero limita minutos de voz).
- Guarda **Key 1** y la **región** (p. ej. `eastus2`).
- Voces que usa la app (todas disponibles en las regiones principales):
  `es-MX-DaliaNeural`, `es-MX-JorgeNeural`, `en-US-AvaNeural`, `en-US-AndrewNeural`.

### 3.6 Document Intelligence — `di-summarai`
- Tipo: Document Intelligence (Form Recognizer) · Plan **S0** (F0 para pruebas: 500 páginas/mes).
- Solo se usa para PDFs escaneados (modelo `prebuilt-read`, API `2024-11-30`). Es opcional:
  si no existe, el resto funciona y esos PDFs dan un error claro.
- Guarda **Endpoint** y **Key 1**.

### 3.7 Function App (API) — `func-summarai`
- Plan de hospedaje: **Flex Consumption**.
- Pila: **Python 3.12** · Memoria de instancia: **2048 MB** · Máx. instancias: 40.
- Storage: `stsummarai…` · Application Insights: `appi-summarai`.
- **Configuración → Variables de entorno** (ver tabla de la sección 4).
- Configuración general: HTTPS only, TLS 1.2, FTPS deshabilitado.
- Despliegue del código (`backend/`), cualquiera de estas opciones:
  - VS Code + extensión *Azure Functions* → *Deploy to Function App*.
  - CLI: `zip -r api.zip . -x ".venv/*" "__pycache__/*" "local.settings*.json"` y luego
    `az functionapp deployment source config-zip -g <rg> -n func-summarai --src api.zip --build-remote true`
- Comprueba: `https://func-summarai.azurewebsites.net/api/health` → todo en `true`.
- Copia la **clave de función** `default` (Funciones → Claves de la aplicación).

### 3.8 App Service (frontend) — `app-summarai`
- Publicar: Código · Pila **Python 3.12** · SO **Linux** · Plan **B1** (`plan-web-summarai`).
- **Configuración**:
  - Comando de inicio: `sh startup.sh`
  - **Web sockets: Activado** (Streamlit lo necesita) · **Always On: Activado**
  - HTTPS only, TLS 1.2, FTPS deshabilitado.
- **Variables de entorno**: ver sección 4.
- Despliegue del código (`frontend/`, sin `.env` ni `.venv`):
  VS Code (*Azure App Service → Deploy to Web App*) o
  `az webapp deploy -g <rg> -n app-summarai --src-path frontend.zip --type zip`.
- **Autenticación** → Agregar proveedor **Microsoft** (tenant de EY), *requerir autenticación*.

---

## 4. Variables de entorno

### Function App (`func-summarai`)

| Nombre | Valor |
|---|---|
| `AzureWebJobsStorage` | Cadena de conexión del storage (la pone el asistente) |
| `DEPLOYMENT_STORAGE_CONNECTION_STRING` | Misma cadena (solo si el asistente de Flex la pide) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Connection string de `appi-summarai` |
| `AZURE_OPENAI_ENDPOINT` | `https://oai-summarai.openai.azure.com/` |
| `AZURE_OPENAI_API_KEY` | Key 1 de OpenAI |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-4.1-mini` (nombre del deployment) |
| `AZURE_OPENAI_API_VERSION` | *(opcional)* por defecto `2024-12-01-preview` |
| `AZURE_SPEECH_KEY` | Key 1 de Speech |
| `AZURE_SPEECH_REGION` | `eastus2` (región de Speech) |
| `AZURE_DOCINTEL_ENDPOINT` | Endpoint de Document Intelligence |
| `AZURE_DOCINTEL_KEY` | Key 1 de Document Intelligence |
| `STORAGE_MODE` | `blob` (en la nube; `local` solo para pruebas en un equipo) |
| `STORAGE_CONNECTION_STRING` | *(opcional)* si los datos van a otro storage distinto |

> En Flex Consumption **no** se ponen `FUNCTIONS_WORKER_RUNTIME` ni `FUNCTIONS_EXTENSION_VERSION`.

### App Service (`app-summarai`)

| Nombre | Valor |
|---|---|
| `BACKEND_URL` | `https://func-summarai.azurewebsites.net/api` |
| `FUNCTION_KEY` | Clave de función `default` de la Function App |
| `BACKEND_MODE` | `http` (o `inprocess` si publicas `frontend/` y `backend/` juntos, sin Function App) |
| `AUTH_MODE` | `easyauth` (con Easy Auth + Entra ID activo) · `local` mientras no esté |
| `APP_USERS` | Solo con `AUTH_MODE=local`: `usuario:hash;…` (genera cada uno con `python frontend/auth.py nombre.apellido`) |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` (instala `requirements.txt` al desplegar) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Connection string de `appi-summarai` |

**Recomendado en EY:** guarda las claves en **Key Vault** y usa referencias
`@Microsoft.KeyVault(SecretUri=…)` en lugar del valor en claro.

---

## 5. Endurecimiento para EY (después de que funcione)

1. **Login:** la app trae su propia pantalla de ingreso (`frontend/auth.py`, mismo diseño que
   Redactor). En EY activa Easy Auth con Microsoft Entra ID en el App Service (sección 3.8) y pon
   `AUTH_MODE=easyauth`: Azure autentica con la cuenta corporativa, la app toma el correo de la
   cabecera `X-MS-CLIENT-PRINCIPAL-NAME` y no pide contraseña. No uses `easyauth` sin Easy Auth
   activo, porque esa cabecera se puede falsificar.
2. **Sin claves (identidad administrada):** activa identidad del sistema en la Function App y
   asigna roles: *Cognitive Services OpenAI User* (OpenAI), *Cognitive Services Speech User*
   (Speech), *Cognitive Services User* (Doc. Intelligence), *Storage Blob Data Contributor*
   (Storage). ⚠️ Requiere un cambio de código (hoy la app usa claves); pídelo cuando llegues aquí.
3. **Red:** Private Endpoints para OpenAI, Speech, Doc. Intelligence y Storage; integración con
   VNet en Function App y App Service; *acceso de red público: deshabilitado* en los servicios;
   restricción de acceso en la Function App para aceptar solo al App Service.
4. **Datos:** retención (regla de ciclo de vida), deployment Data Zone, y desactivar
   *abuse monitoring logging* si EY tiene la excepción aprobada.
5. **Monitoreo:** alertas en Application Insights por errores 5xx y por uso de tokens.

---

## 6. PC de EY: entorno local

> **Más simple:** si solo tienes endpoints y claves, sigue [GUIA-EY.md](GUIA-EY.md) §6. Con
> `BACKEND_MODE=inprocess` y `STORAGE_MODE=local` basta con Python: no necesitas Core Tools
> ni Azurite. Lo de abajo aplica solo si quieres correr la API de Functions en local.

### Software
| Herramienta | Versión | Para qué |
|---|---|---|
| Python | 3.12 | backend y frontend |
| Node.js | 20 LTS | Core Tools y Azurite |
| Azure Functions Core Tools | 4.x (`npm i -g azure-functions-core-tools@4`) | `func start` |
| Azurite | `npm i -g azurite` | emulador de Blob Storage |
| VS Code + extensiones *Azure Functions*, *Azure App Service*, *Python* | — | desarrollo y despliegue manual |
| Azure CLI | opcional | despliegues por línea de comandos |

> **Redes corporativas:** si `pip`/`npm` fallan por certificados (inspección SSL de EY),
> configura el certificado raíz de EY: `pip config set global.cert <ruta.pem>`,
> `npm config set cafile <ruta.pem>` y para Python en ejecución `REQUESTS_CA_BUNDLE=<ruta.pem>`.

### Arranque (3 terminales, desde la carpeta del proyecto)

```bash
# 1) Azurite
azurite --silent --skipApiVersionCheck --location .azurite

# 2) API
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp local.settings.example.json local.settings.json   # Windows: copy …; rellenar claves (sección 4)
func start

# 3) Frontend
cd frontend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # BACKEND_URL=http://localhost:7071/api, FUNCTION_KEY vacío
streamlit run app.py          # http://localhost:8501
```

En `startup.sh` no hace falta tocar nada para Windows local; solo lo usa App Service (Linux).

---

## 7. Validación

1. `GET /api/health` → `openai`, `speech`, `ocr`, `storage` en `true`.
2. Sube los archivos de `muestras/` (PDF, PPTX, DOCX, MD, PNG, PY): cada uno devuelve un
   resumen en 3–10 s.
3. *Generar podcast* corto → ~2 min de audio en 10–20 s; se reproduce y se descarga el MP3.
4. En Storage: aparecen `summarai/docs/<id>.json` y `summarai/podcasts/<id>.mp3`.
5. Llamar a la API sin `x-functions-key` → **401**.

## 8. Costo aproximado (pruebas, EE. UU.)

| Recurso | Costo |
|---|---|
| App Service B1 | ~13 USD/mes fijo |
| Function App Flex | ~0 en reposo; por ejecución |
| Azure OpenAI gpt-4.1-mini | centavos por documento |
| Speech neural | ~16 USD por millón de caracteres (~1 podcast corto ≈ 2,500 caracteres) |
| Document Intelligence read | ~1.5 USD por 1,000 páginas (solo PDFs escaneados) |
| Storage + App Insights | centavos |
