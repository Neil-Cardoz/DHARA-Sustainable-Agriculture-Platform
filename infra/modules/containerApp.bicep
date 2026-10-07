@description('Generic Azure Container App module, reused for the api and advisory-bot services.')
param name string
param location string
param containerAppsEnvironmentId string
param containerRegistryServer string
param containerRegistryUsername string
@secure()
param containerRegistryPassword string
param imageName string
param targetPort int = 8080
param cpu string = '0.5'
param memory string = '1Gi'
param minReplicas int = 0
param maxReplicas int = 3
param envVars array = []
param secretEnvVars array = []
param externalIngress bool = true
@description('Set false for a pure background worker with no HTTP endpoint at all (e.g. the ingestion consumer) -- omits the ingress block entirely.')
param enableIngress bool = true
param userAssignedIdentityId string

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      ingress: enableIngress ? {
        external: externalIngress
        targetPort: targetPort
        transport: 'auto'
      } : null
      registries: [
        {
          server: containerRegistryServer
          username: containerRegistryUsername
          passwordSecretRef: 'registry-password'
        }
      ]
      secrets: concat(
        [
          {
            name: 'registry-password'
            value: containerRegistryPassword
          }
        ],
        secretEnvVars
      )
    }
    template: {
      containers: [
        {
          name: name
          image: imageName
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: envVars
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output fqdn string = enableIngress ? containerApp.properties.configuration.ingress.fqdn : ''
output name string = containerApp.name
