// Deployed first, alone, so images can be built and pushed with `az acr build`
// before main.bicep creates the Container Apps that reference them.
// Re-running main.bicep afterwards re-declares the same ACR (same name/suffix)
// idempotently -- this is not a separate resource.
param prefix string = 'dhara'
param location string = resourceGroup().location
param uniqueSuffix string

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: toLower('${prefix}acr${take(uniqueSuffix, 10)}')
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: true
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
