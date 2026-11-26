#!/usr/bin/env bash
# Despliegue completo de summarAI en la suscripción activa de `az`.
#
#   ./infra/deploy.sh                       # usa los valores por defecto
#   RG=rg-summarai-dev LOCATION=eastus2 ./infra/deploy.sh
#
# Requisitos: az (con `az login` hecho) y zip.
set -euo pipefail

RG="${RG:-rg-summarai-dev}"
LOCATION="${LOCATION:-eastus2}"
OPENAI_LOCATION="${OPENAI_LOCATION:-$LOCATION}"
WEB_LOCATION="${WEB_LOCATION:-$LOCATION}"
WEB_SKU="${WEB_SKU:-B1}"
DEPLOY_WEB="${DEPLOY_WEB:-true}"            # false = solo backend (sin cuota de App Service)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Suscripción: $(az account show --query name -o tsv)"
echo "==> Grupo de recursos $RG en $LOCATION"
az group create -n "$RG" -l "$LOCATION" --tags app=summarAI -o none

echo "==> Infraestructura (Bicep)"
OUT=$(az deployment group create -g "$RG" -n summarai \
  -f "$ROOT/infra/main.bicep" \
  -p location="$LOCATION" openAiLocation="$OPENAI_LOCATION" webLocation="$WEB_LOCATION" webSku="$WEB_SKU" deployWeb="$DEPLOY_WEB" \
  --query properties.outputs -o json)

FUNC_APP=$(echo "$OUT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["functionAppName"]["value"])')
WEB_APP=$(echo "$OUT"  | python3 -c 'import sys,json;print(json.load(sys.stdin)["webAppName"]["value"])')
WEB_URL=$(echo "$OUT"  | python3 -c 'import sys,json;print(json.load(sys.stdin)["webUrl"]["value"])')
API_URL=$(echo "$OUT"  | python3 -c 'import sys,json;print(json.load(sys.stdin)["apiUrl"]["value"])')

echo "==> Publicando API en $FUNC_APP"
API_ZIP="$(mktemp -d)/api.zip"
( cd "$ROOT/backend" && zip -qr "$API_ZIP" . -x ".venv/*" "venv/*" "*__pycache__/*" ".env" "local.settings*.json" ".funcignore" )
az functionapp deployment source config-zip -g "$RG" -n "$FUNC_APP" --src "$API_ZIP" --build-remote true -o none
rm -f "$API_ZIP"

if [ "$DEPLOY_WEB" != "true" ]; then
  echo; echo "Listo (solo backend)."; echo "  API: $API_URL/health"; exit 0
fi

echo "==> Conectando el frontend con la clave de la API"
KEY=$(az functionapp keys list -g "$RG" -n "$FUNC_APP" --query functionKeys.default -o tsv)
az webapp config appsettings set -g "$RG" -n "$WEB_APP" --settings FUNCTION_KEY="$KEY" -o none

echo "==> Publicando frontend en $WEB_APP"
TMP_ZIP="$(mktemp -d)/frontend.zip"
( cd "$ROOT/frontend" && zip -qr "$TMP_ZIP" . -x ".env" "__pycache__/*" ".venv/*" "venv/*" )
az webapp deploy -g "$RG" -n "$WEB_APP" --src-path "$TMP_ZIP" --type zip -o none
rm -f "$TMP_ZIP"

echo
echo "Listo."
echo "  Frontend: $WEB_URL"
echo "  API:      $API_URL/health"
