@description('''
Flex Consumption (FC1) Python Function App, used for decision-engine only.

Not used for ingestion: the Event Hub trigger binding proved unreliable on
this subscription/region across every combination tried (legacy Y1
Consumption x2 recreations, Flex Consumption with default and dedicated
consumer groups, with and without an always-ready instance) -- see
docs/SETUP.md for the diagnostic trail. The actual root cause turned out to
be unrelated to the hosting plan (the IoT Hub fallback route was disabled --
fixed on the `iotHub` resource in main.bicep), but by the time that was
found, ingestion had already been rebuilt as a plain Container App
(services/ingestion/consumer.py) directly against the azure-eventhub SDK,
which needs no Functions-specific scaling machinery and is what
infra/main.bicep now deploys for it. Flex Consumption is kept here for
decision-engine because its timer triggers work reliably on it.
''')
param name string
param location string
param storageAccountName string
param appInsightsConnectionString string
param appSettings array = []
param userAssignedIdentityId string
param alwaysReadyFunctionName string
param pythonVersion string = '3.12'
param maximumInstanceCount int = 100
param instanceMemoryMB int = 2048

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: toLower('app-package-${name}')
  properties: { publicAccess: 'None' }
}

resource hostingPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${name}-plan'
  location: location
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  kind: 'functionapp'
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: name
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  }
  properties: {
    serverFarmId: hostingPlan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storageAccount.properties.primaryEndpoints.blob}${deploymentContainer.name}'
          authentication: {
            type: 'StorageAccountConnectionString'
            storageAccountConnectionStringName: 'DEPLOYMENT_STORAGE_CONNECTION_STRING'
          }
        }
      }
      runtime: {
        name: 'python'
        version: pythonVersion
      }
      scaleAndConcurrency: {
        instanceMemoryMB: instanceMemoryMB
        maximumInstanceCount: maximumInstanceCount
        alwaysReady: [
          {
            name: 'function:${alwaysReadyFunctionName}'
            instanceCount: 1
          }
        ]
      }
    }
    siteConfig: {
      appSettings: concat(
        [
          {
            name: 'AzureWebJobsStorage'
            value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
          }
          {
            name: 'DEPLOYMENT_STORAGE_CONNECTION_STRING'
            value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
          }
          {
            name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
            value: appInsightsConnectionString
          }
        ],
        appSettings
      )
    }
  }
}

output name string = functionApp.name
output defaultHostName string = functionApp.properties.defaultHostName
