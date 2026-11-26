// =====================================================================
// summarAI — infraestructura completa en Azure
//   - Storage (blobs temporales con borrado automático)
//   - Azure OpenAI + deployment del modelo de chat (con visión)
//   - Azure AI Speech (voces del podcast)
//   - Azure AI Document Intelligence (OCR de PDFs escaneados)
//   - Function App en Flex Consumption (API, Python)
//   - App Service Linux (frontend Streamlit)
//   - Log Analytics + Application Insights
// =====================================================================
targetScope = 'resourceGroup'

@description('Prefijo corto para nombrar recursos (solo minúsculas y números).')
@maxLength(10)
param prefix string = 'summarai'

@description('Región principal.')
param location string = resourceGroup().location

@description('Región de Azure OpenAI (puede diferir si el modelo no está disponible en la principal).')
param openAiLocation string = location

@description('Modelo de chat (debe soportar visión para infografías).')
param chatModelName string = 'gpt-4.1-mini'

@description('Versión del modelo.')
param chatModelVersion string = '2025-04-14'

@description('Capacidad del deployment en miles de tokens por minuto.')
param chatModelCapacity int = 50

@description('SKU del plan del frontend (F1 gratis, B1 recomendado).')
param webSku string = 'B1'

@description('Región del frontend (por si no hay cuota de App Service en la principal).')
param webLocation string = location

@description('Desplegar el frontend en App Service (requiere cuota de App Service en la suscripción).')
param deployWeb bool = true

@description('Días que se conservan textos y audios antes de borrarse.')
param retentionDays int = 7

@description('Etiquetas comunes.')
param tags object = {
  app: 'summarAI'
  owner: 'EY'
}

var suffix = take(uniqueString(resourceGroup().id), 6)
var base = '${prefix}-${suffix}'
var storageName = take(toLower('st${prefix}${suffix}'), 24)
var deployContainerName = 'deploymentpackage'

// ---------------------------------------------------------------- Storage
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource dataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'summarai'
}

resource deployContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: deployContainerName
}

resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'borrar-temporales'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: [ 'blockBlob' ]
              prefixMatch: [ 'summarai/' ]
            }
            actions: {
              baseBlob: {
                delete: { daysAfterModificationGreaterThan: retentionDays }
              }
            }
          }
        }
      ]
    }
  }
}

var storageConnection = 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'

// ---------------------------------------------------------------- Monitoreo
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${base}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${base}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// ---------------------------------------------------------------- IA
resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'oai-${base}'
  location: openAiLocation
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'oai-${base}'
    publicNetworkAccess: 'Enabled'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: chatModelName
  sku: {
    name: 'GlobalStandard'
    capacity: chatModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
}

resource speech 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'spch-${base}'
  location: location
  tags: tags
  kind: 'SpeechServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'spch-${base}'
    publicNetworkAccess: 'Enabled'
  }
}

resource docIntel 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'di-${base}'
  location: location
  tags: tags
  kind: 'FormRecognizer'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'di-${base}'
    publicNetworkAccess: 'Enabled'
  }
}

// ---------------------------------------------------------------- API (Functions Flex Consumption)
resource funcPlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-func-${base}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: { reserved: true }
}

resource funcApp 'Microsoft.Web/sites@2024-04-01' = {
  name: 'func-${base}'
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: funcPlan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: storageConnection }
        { name: 'STORAGE_MODE', value: 'blob' }
        { name: 'DEPLOYMENT_STORAGE_CONNECTION_STRING', value: storageConnection }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'AZURE_OPENAI_ENDPOINT', value: openAi.properties.endpoint }
        { name: 'AZURE_OPENAI_API_KEY', value: openAi.listKeys().key1 }
        { name: 'AZURE_OPENAI_DEPLOYMENT', value: chatDeployment.name }
        { name: 'AZURE_SPEECH_KEY', value: speech.listKeys().key1 }
        { name: 'AZURE_SPEECH_REGION', value: speech.location }
        { name: 'AZURE_DOCINTEL_ENDPOINT', value: docIntel.properties.endpoint }
        { name: 'AZURE_DOCINTEL_KEY', value: docIntel.listKeys().key1 }
      ]
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deployContainerName}'
          authentication: {
            type: 'StorageAccountConnectionString'
            storageAccountConnectionStringName: 'DEPLOYMENT_STORAGE_CONNECTION_STRING'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
      runtime: {
        name: 'python'
        version: '3.12'
      }
    }
  }
  dependsOn: [ deployContainer ]
}

// ---------------------------------------------------------------- Frontend (Streamlit)
resource webPlan 'Microsoft.Web/serverfarms@2024-04-01' = if (deployWeb) {
  name: 'plan-web-${base}'
  location: webLocation
  tags: tags
  kind: 'linux'
  sku: { name: webSku }
  properties: { reserved: true }
}

resource webApp 'Microsoft.Web/sites@2024-04-01' = if (deployWeb) {
  name: 'app-${base}'
  location: webLocation
  tags: tags
  kind: 'app,linux'
  properties: {
    serverFarmId: webPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'sh startup.sh'
      webSocketsEnabled: true
      alwaysOn: webSku != 'F1'   // F1 no permite Always On
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'BACKEND_URL', value: 'https://${funcApp.properties.defaultHostName}/api' }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        // FUNCTION_KEY lo pone deploy.sh después de publicar la API
      ]
    }
  }
}

output functionAppName string = funcApp.name
output webAppName string = deployWeb ? webApp.name : ''
output webUrl string = deployWeb ? 'https://${webApp!.properties.defaultHostName}' : ''
output apiUrl string = 'https://${funcApp.properties.defaultHostName}/api'
output storageAccountName string = storage.name
