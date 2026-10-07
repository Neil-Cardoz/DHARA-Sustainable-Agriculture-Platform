@description('Short project prefix used to name every resource, e.g. "dhara".')
param prefix string = 'dhara'

@description('Primary region for most resources (India-focused deployment).')
param location string = resourceGroup().location

@description('Region for the Azure AI Services account hosting the OpenAI model deployment (must support GlobalStandard gpt-4o-mini).')
param openAiLocation string = 'koreacentral'

@description('Region for the operator-console Static Web App (limited region list).')
param staticWebAppLocation string = 'eastasia'

@secure()
@description('Administrator password for the PostgreSQL Flexible Server.')
param postgresAdminPassword string

param postgresAdminLogin string = 'dhara_admin'

@secure()
@description('Shared secret used for service-to-service auth between the API and the ingestion/decision-engine/advisory-bot workers.')
param apiSharedSecret string

@description('Deploy the Azure OpenAI resource + model deployment. Set false if your subscription lacks OpenAI access.')
param deployOpenAi bool = true

@description('Container image tag to deploy for api/advisory-bot (pushed to ACR before this run, or updated after).')
param imageTag string = 'latest'

@description('Stable suffix used to name globally-unique resources (ACR, storage, Key Vault). Generate once and reuse across deployments so names never drift.')
param uniqueSuffix string = uniqueString(resourceGroup().id)
var names = {
  logAnalytics: '${prefix}-log-${uniqueSuffix}'
  appInsights: '${prefix}-appi-${uniqueSuffix}'
  keyVault: '${prefix}-kv-${take(uniqueSuffix, 8)}'
  identity: '${prefix}-identity'
  storage: toLower('${prefix}st${take(uniqueSuffix, 10)}')
  postgres: '${prefix}-pg-${uniqueSuffix}'
  iotHub: '${prefix}-iothub-${uniqueSuffix}'
  acr: toLower('${prefix}acr${take(uniqueSuffix, 10)}')
  containerEnv: '${prefix}-cae-${uniqueSuffix}'
  apiApp: '${prefix}-api'
  advisoryApp: '${prefix}-advisory-bot'
  ingestionApp: '${prefix}-ingestion-${uniqueSuffix}'
  decisionFunc: '${prefix}-decision-engine-${uniqueSuffix}'
  communication: '${prefix}-acs-${uniqueSuffix}'
  speech: '${prefix}-speech-${uniqueSuffix}'
  openAi: '${prefix}-openai-${uniqueSuffix}'
  staticWebApp: '${prefix}-console'
}

// ---------------------------------------------------------------------------
// Observability
// ---------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.logAnalytics
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: names.appInsights
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------------------------------------------------------------------------
// Identity + secrets
// ---------------------------------------------------------------------------
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: names.identity
  location: location
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: names.keyVault
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
  }
}

resource kvSecretsOfficerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, identity.id, 'kv-secrets-officer')
  scope: keyVault
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'b86a8fe4-44ce-4948-aee5-eccb2c155cd7' // Key Vault Secrets Officer
    )
  }
}

// ---------------------------------------------------------------------------
// Storage (blobs + Function App backing storage)
// ---------------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: names.storage
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource photosContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'advisory-photos'
  properties: { publicAccess: 'None' }
}

resource firmwareContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'firmware'
  properties: { publicAccess: 'None' }
}

// ---------------------------------------------------------------------------
// PostgreSQL Flexible Server (core relational store)
// ---------------------------------------------------------------------------
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: names.postgres
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'dhara'
}

resource postgresAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ---------------------------------------------------------------------------
// IoT Hub (Tier 0-2 -> Tier 3 ingress)
// ---------------------------------------------------------------------------
resource iotHub 'Microsoft.Devices/IotHubs@2023-06-30' = {
  name: names.iotHub
  location: location
  sku: {
    name: 'S1'
    capacity: 1
  }
  properties: {
    eventHubEndpoints: {
      events: {
        retentionTimeInDays: 1
        partitionCount: 4
      }
    }
    // BUG THAT COST HOURS TO FIND: declaring a custom `eventHubEndpoints` block
    // above, without also declaring `routing`, leaves the hub with its
    // fallback route DISABLED. Device messages are then accepted (ingress
    // metrics look completely healthy) but routed nowhere -- no Function
    // trigger, no direct Event Hub SDK consumer, not even `az iot hub
    // monitor-events` sees anything. Every symptom looks like a consumer-side
    // problem; the actual fault is here. Explicit and load-bearing:
    routing: {
      fallbackRoute: {
        name: '$fallback'
        source: 'DeviceMessages'
        condition: 'true'
        endpointNames: ['events']
        isEnabled: true
      }
    }
  }
}

// Dedicated consumer group for the ingestion consumer, so it never contends
// with anything else reading `$Default` (a Functions Event Hub trigger
// left running against `$Default`, or an ad-hoc `az iot hub monitor-events`
// session, both hold an epoch-based lock that a plain SDK reader on the same
// consumer group cannot share).
resource ingestionConsumerGroup 'Microsoft.Devices/IotHubs/eventHubEndpoints/ConsumerGroups@2023-06-30' = {
  name: '${iotHub.name}/events/ingestion-consumer'
  properties: {
    name: 'ingestion-consumer'
  }
}

// ---------------------------------------------------------------------------
// Container Registry + Container Apps environment
// ---------------------------------------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: names.acr
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: true
  }
}

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: names.containerEnv
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Azure Communication Services (WhatsApp + voice)
// ---------------------------------------------------------------------------
resource communication 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: names.communication
  location: 'global'
  properties: {
    dataLocation: 'India'
  }
}

// ---------------------------------------------------------------------------
// Azure AI Speech (voice IVR text-to-speech / speech-to-text)
// ---------------------------------------------------------------------------
resource speech 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: names.speech
  location: location
  kind: 'SpeechServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: names.speech
    publicNetworkAccess: 'Enabled'
  }
}

// ---------------------------------------------------------------------------
// Azure OpenAI (advisory NLU)
// ---------------------------------------------------------------------------
// Uses the unified "AIServices" (Azure AI Foundry) resource kind rather than the
// legacy standalone "OpenAI" kind: this subscription's OpenAI-kind account quota
// (1 per region) was already consumed by another project, while AIServices-kind
// accounts (which host the same OpenAI model deployments) have ample quota.
resource openAi 'Microsoft.CognitiveServices/accounts@2023-05-01' = if (deployOpenAi) {
  name: names.openAi
  location: openAiLocation
  kind: 'AIServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: names.openAi
    publicNetworkAccess: 'Enabled'
  }
}

resource openAiDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = if (deployOpenAi) {
  parent: openAi
  name: 'dhara-advisory-gpt'
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1-mini'
      version: '2025-04-14'
    }
  }
}

// ---------------------------------------------------------------------------
// Container Apps: api + advisory-bot
// ---------------------------------------------------------------------------
module apiApp 'modules/containerApp.bicep' = {
  name: 'apiApp'
  params: {
    name: names.apiApp
    location: location
    containerAppsEnvironmentId: containerEnv.id
    containerRegistryServer: acr.properties.loginServer
    containerRegistryUsername: acr.listCredentials().username
    containerRegistryPassword: acr.listCredentials().passwords[0].value
    imageName: '${acr.properties.loginServer}/dhara-api:${imageTag}'
    targetPort: 8000
    minReplicas: 1
    maxReplicas: 3
    userAssignedIdentityId: identity.id
    envVars: [
      { name: 'DATABASE_URL', value: 'postgresql+psycopg://${postgresAdminLogin}:${postgresAdminPassword}@${postgres.properties.fullyQualifiedDomainName}:5432/dhara?sslmode=require' }
      { name: 'API_SHARED_SECRET', secretRef: 'api-shared-secret' }
      { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
      { name: 'ENVIRONMENT', value: 'production' }
    ]
    secretEnvVars: [
      { name: 'api-shared-secret', value: apiSharedSecret }
    ]
  }
}

module advisoryApp 'modules/containerApp.bicep' = {
  name: 'advisoryApp'
  params: {
    name: names.advisoryApp
    location: location
    containerAppsEnvironmentId: containerEnv.id
    containerRegistryServer: acr.properties.loginServer
    containerRegistryUsername: acr.listCredentials().username
    containerRegistryPassword: acr.listCredentials().passwords[0].value
    imageName: '${acr.properties.loginServer}/dhara-advisory-bot:${imageTag}'
    targetPort: 8100
    minReplicas: 0
    maxReplicas: 3
    userAssignedIdentityId: identity.id
    envVars: [
      { name: 'API_BASE_URL', value: 'https://${apiApp.outputs.fqdn}' }
      { name: 'API_SHARED_SECRET', secretRef: 'api-shared-secret' }
      { name: 'ACS_CONNECTION_STRING', secretRef: 'acs-connection-string' }
      { name: 'AZURE_OPENAI_ENDPOINT', value: deployOpenAi ? openAi.properties.endpoint : '' }
      { name: 'AZURE_OPENAI_API_KEY', secretRef: 'openai-key' }
      { name: 'IOT_HUB_CONNECTION_STRING', secretRef: 'iothub-connection-string' }
      { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
    ]
    secretEnvVars: [
      { name: 'api-shared-secret', value: apiSharedSecret }
      { name: 'acs-connection-string', value: communication.listKeys().primaryConnectionString }
      { name: 'openai-key', value: deployOpenAi ? openAi.listKeys().key1 : 'not-deployed' }
      { name: 'iothub-connection-string', value: iotHubOwnerConnectionString }
    ]
  }
}

var iotHubOwnerKey = filter(iotHub.listKeys().value, k => k.keyName == 'iothubowner')[0].primaryKey
var iotHubOwnerConnectionString = 'HostName=${iotHub.properties.hostName};SharedAccessKeyName=iothubowner;SharedAccessKey=${iotHubOwnerKey}'

var iotHubEventHubCompatibleEndpoint = 'Endpoint=${iotHub.properties.eventHubEndpoints.events.endpoint};SharedAccessKeyName=iothubowner;SharedAccessKey=${iotHubOwnerKey};EntityPath=${iotHub.properties.eventHubEndpoints.events.path}'

// ---------------------------------------------------------------------------
// Ingestion: a plain Container App reading IoT Hub's built-in Event Hub
// endpoint directly via the azure-eventhub SDK (services/ingestion/consumer.py).
//
// NOT an Azure Function with an Event Hub trigger -- that was the original
// design, and it never fired a single execution in this deployment across
// four different hosting configurations (see docs/SETUP.md). The real fault
// was the IoT Hub fallback route being disabled (fixed above); by the time
// that was found, this Container App replacement was already built, tested,
// and simpler to operate (no Functions-specific scale-controller behaviour
// to reason about), so it stayed.
// ---------------------------------------------------------------------------
module ingestionApp 'modules/containerApp.bicep' = {
  name: 'ingestionApp'
  params: {
    name: names.ingestionApp
    location: location
    containerAppsEnvironmentId: containerEnv.id
    containerRegistryServer: acr.properties.loginServer
    containerRegistryUsername: acr.listCredentials().username
    containerRegistryPassword: acr.listCredentials().passwords[0].value
    imageName: '${acr.properties.loginServer}/dhara-ingestion:${imageTag}'
    enableIngress: false
    minReplicas: 1
    maxReplicas: 1
    userAssignedIdentityId: identity.id
    envVars: [
      { name: 'API_BASE_URL', value: 'https://${apiApp.outputs.fqdn}' }
      { name: 'API_SHARED_SECRET', secretRef: 'api-shared-secret' }
      { name: 'IOT_HUB_EVENTHUB_COMPATIBLE_ENDPOINT', secretRef: 'iothub-eventhub-endpoint' }
      { name: 'IOT_HUB_EVENTHUB_CONSUMER_GROUP', value: 'ingestion-consumer' }
    ]
    secretEnvVars: [
      { name: 'api-shared-secret', value: apiSharedSecret }
      { name: 'iothub-eventhub-endpoint', value: iotHubEventHubCompatibleEndpoint }
    ]
  }
}

// ---------------------------------------------------------------------------
// Decision engine: Flex Consumption Function App. Unlike the Event Hub
// trigger above, decision-engine's timer triggers work reliably here -- kept
// on Functions rather than folded into a Container App.
// ---------------------------------------------------------------------------
module decisionFunc 'modules/functionAppFlex.bicep' = {
  name: 'decisionFunc'
  params: {
    name: names.decisionFunc
    location: location
    storageAccountName: storage.name
    appInsightsConnectionString: appInsights.properties.ConnectionString
    userAssignedIdentityId: identity.id
    alwaysReadyFunctionName: 'IrrigationControlLoop'
    appSettings: [
      { name: 'API_BASE_URL', value: 'https://${apiApp.outputs.fqdn}' }
      { name: 'API_SHARED_SECRET', value: apiSharedSecret }
      { name: 'ADVISORY_BOT_URL', value: 'https://${advisoryApp.outputs.fqdn}' }
      { name: 'IOT_HUB_CONNECTION_STRING', value: iotHubOwnerConnectionString }
      { name: 'CONTROL_LOOP_INTERVAL_MINUTES', value: '15' }
    ]
  }
}

// ---------------------------------------------------------------------------
// Operator console (Static Web App)
// ---------------------------------------------------------------------------
resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: names.staticWebApp
  location: staticWebAppLocation
  sku: { name: 'Free', tier: 'Free' }
  properties: {
    allowConfigFileUpdates: true
  }
}

// ---------------------------------------------------------------------------
// Outputs (also written to .env by scripts/export-env.sh after deployment)
// ---------------------------------------------------------------------------
output resourceGroupName string = resourceGroup().name
output apiUrl string = 'https://${apiApp.outputs.fqdn}'
output advisoryBotUrl string = 'https://${advisoryApp.outputs.fqdn}'
output staticWebAppDefaultHostname string = staticWebApp.properties.defaultHostname
output staticWebAppName string = staticWebApp.name
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output storageAccountName string = storage.name
output postgresFqdn string = postgres.properties.fullyQualifiedDomainName
output postgresDatabaseName string = postgresDb.name
output iotHubName string = iotHub.name
output iotHubHostName string = iotHub.properties.hostName
output communicationServiceName string = communication.name
output speechAccountName string = speech.name
output speechRegion string = location
output openAiEndpoint string = deployOpenAi ? openAi.properties.endpoint : ''
output openAiAccountName string = deployOpenAi ? openAi.name : ''
output keyVaultName string = keyVault.name
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output managedIdentityClientId string = identity.properties.clientId
output ingestionAppName string = ingestionApp.outputs.name
output decisionFunctionAppName string = decisionFunc.outputs.name
output ingestionConsumerGroupName string = 'ingestion-consumer'
