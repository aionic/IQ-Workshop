// -----------------------------------------------------------------------
// main.bicep — IQ Foundry Agent Lab Infrastructure
// Dual-mode networking: public (workshop default) | private (enterprise)
// -----------------------------------------------------------------------

targetScope = 'resourceGroup'

// -----------------------------------------------------------------------
// Parameters
// -----------------------------------------------------------------------

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Environment name (dev, staging, prod)')
param environmentName string = 'dev'

@description('Network mode: public (default for workshop) or private (enterprise)')
@allowed(['public', 'private'])
param networkMode string = 'public'

@description('Entra ID admin object ID for Azure SQL AAD-only auth')
param entraAdminObjectId string // TODO: set to your Entra user/group object ID

@description('Entra ID admin display name for Azure SQL')
param entraAdminDisplayName string // TODO: set to your Entra user/group display name

@description('VNet address prefix (only used when networkMode == private)')
param vnetAddressPrefix string = '10.0.0.0/16'

@description('Container Apps subnet prefix')
param snetContainerAppsPrefix string = '10.0.1.0/24'

@description('Private endpoints subnet prefix')
param snetPrivateEndpointsPrefix string = '10.0.2.0/24'

@description('Container image for tool service (use placeholder until first build)')
param toolServiceImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Model name to deploy in Azure AI Services')
param aiModelName string = 'gpt-4.1-mini'

@description('Model version')
param aiModelVersion string = '2025-04-14'

@description('Model deployment capacity in 1K TPM units (e.g. 30 = 30K TPM)')
param aiModelCapacity int = 30

// -----------------------------------------------------------------------
// Variables
// -----------------------------------------------------------------------

var suffix = 'iq-lab-${environmentName}'
var isPrivate = networkMode == 'private'

var sqlServerName = 'sql-${suffix}'
var sqlDatabaseName = 'sqldb-iq'
var lawName = 'law-${suffix}'
var appInsightsName = 'appi-${suffix}'
var acrName = replace('acr${suffix}', '-', '') // ACR names must be alphanumeric
var caEnvName = 'cae-${suffix}'
var caName = 'ca-tools-${suffix}'
var miToolsName = 'id-iq-tools-${suffix}'
var miAgentName = 'id-iq-agent-${suffix}'
var vnetName = 'vnet-${suffix}'
var amplsName = 'ampls-${suffix}'
var aiServicesName = 'ai-${suffix}'

// -----------------------------------------------------------------------
// Managed Identities
// -----------------------------------------------------------------------

resource miTools 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: miToolsName
  location: location
}

resource miAgent 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: miAgentName
  location: location
}

// -----------------------------------------------------------------------
// Networking (conditional on networkMode == 'private')
// -----------------------------------------------------------------------

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = if (isPrivate) {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [vnetAddressPrefix]
    }
    subnets: [
      {
        name: 'snet-container-apps'
        properties: {
          addressPrefix: snetContainerAppsPrefix
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: snetPrivateEndpointsPrefix
        }
      }
    ]
  }
}

// --- Private DNS Zones (private mode only) ---

resource dnsZoneSql 'Microsoft.Network/privateDnsZones@2020-06-01' = if (isPrivate) {
  // Disable this warning for SQL private DNS zone name; this exact zone name is required by Azure Private Link.
  #disable-next-line no-hardcoded-env-urls
  name: 'privatelink.database.windows.net'
  location: 'global'
}

resource dnsZoneSqlLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (isPrivate) {
  parent: dnsZoneSql
  name: '${vnetName}-sql-link'
  location: 'global'
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

resource dnsZoneAcr 'Microsoft.Network/privateDnsZones@2020-06-01' = if (isPrivate) {
  name: 'privatelink.azurecr.io'
  location: 'global'
}

resource dnsZoneAcrLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (isPrivate) {
  parent: dnsZoneAcr
  name: '${vnetName}-acr-link'
  location: 'global'
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

resource dnsZoneMonitor 'Microsoft.Network/privateDnsZones@2020-06-01' = if (isPrivate) {
  name: 'privatelink.monitor.azure.com'
  location: 'global'
}

resource dnsZoneMonitorLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (isPrivate) {
  parent: dnsZoneMonitor
  name: '${vnetName}-monitor-link'
  location: 'global'
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

// -----------------------------------------------------------------------
// Azure SQL (AAD-only auth, no SQL admin password)
// -----------------------------------------------------------------------

resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: sqlServerName
  location: location
  properties: {
    // AAD-only authentication — no SQL admin password
    administrators: {
      administratorType: 'ActiveDirectory'
      login: entraAdminDisplayName
      sid: entraAdminObjectId
      tenantId: subscription().tenantId
      azureADOnlyAuthentication: true
      principalType: 'User' // Change to 'Group' if using a group account
    }
    publicNetworkAccess: isPrivate ? 'Disabled' : 'Enabled'
    minimalTlsVersion: '1.2'
  }
}

resource sqlDatabase 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: sqlDatabaseName
  location: location
  sku: {
    name: 'Basic'
    tier: 'Basic'
    capacity: 5
  }
  properties: {
    collation: 'SQL_Latin1_General_CP1_CI_AS'
    maxSizeBytes: 2147483648 // 2 GB
  }
}

// Allow Azure services (public mode only)
resource sqlFirewallAllowAzure 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = if (!isPrivate) {
  parent: sqlServer
  name: 'AllowAllAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// Private endpoint for SQL (private mode only)
resource peSql 'Microsoft.Network/privateEndpoints@2023-11-01' = if (isPrivate) {
  name: 'pe-sql-${suffix}'
  location: location
  properties: {
    subnet: {
      id: vnet!.properties.subnets[1].id // snet-private-endpoints
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-sql-connection'
        properties: {
          privateLinkServiceId: sqlServer.id
          groupIds: ['sqlServer']
        }
      }
    ]
  }
}

resource peSqlDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = if (isPrivate) {
  parent: peSql
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-database-windows-net'
        properties: {
          privateDnsZoneId: dnsZoneSql.id
        }
      }
    ]
  }
}

// -----------------------------------------------------------------------
// Container Registry
// -----------------------------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  sku: {
    name: isPrivate ? 'Premium' : 'Basic' // Premium required for private endpoints
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: isPrivate ? 'Disabled' : 'Enabled'
    networkRuleBypassOptions: 'AzureServices'
  }
}

// ACR pull role for tool service MI (allows Container Apps to pull images)
// Role: AcrPull — 7f951dda-4ed3-4680-a7ca-43fe172d538d
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, miTools.id, '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
    principalId: miTools.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Private endpoint for ACR (private mode only)
resource peAcr 'Microsoft.Network/privateEndpoints@2023-11-01' = if (isPrivate) {
  name: 'pe-acr-${suffix}'
  location: location
  properties: {
    subnet: {
      id: vnet!.properties.subnets[1].id
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-acr-connection'
        properties: {
          privateLinkServiceId: acr.id
          groupIds: ['registry']
        }
      }
    ]
  }
}

resource peAcrDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = if (isPrivate) {
  parent: peAcr
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-azurecr-io'
        properties: {
          privateDnsZoneId: dnsZoneAcr.id
        }
      }
    ]
  }
}

// -----------------------------------------------------------------------
// Observability
// -----------------------------------------------------------------------

resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: lawName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    publicNetworkAccessForIngestion: isPrivate ? 'Disabled' : 'Enabled'
    publicNetworkAccessForQuery: isPrivate ? 'Disabled' : 'Enabled'
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    publicNetworkAccessForIngestion: isPrivate ? 'Disabled' : 'Enabled'
    publicNetworkAccessForQuery: isPrivate ? 'Disabled' : 'Enabled'
  }
}

// Azure Monitor Private Link Scope (private mode only)
resource ampls 'Microsoft.Insights/privateLinkScopes@2021-07-01-preview' = if (isPrivate) {
  name: amplsName
  location: 'global'
  properties: {
    accessModeSettings: {
      ingestionAccessMode: 'PrivateOnly'
      queryAccessMode: 'PrivateOnly'
    }
  }
}

resource amplsScopedLaw 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = if (isPrivate) {
  parent: ampls
  name: '${lawName}-scope'
  properties: {
    linkedResourceId: law.id
  }
}

resource amplsScopedAppInsights 'Microsoft.Insights/privateLinkScopes/scopedResources@2021-07-01-preview' = if (isPrivate) {
  parent: ampls
  name: '${appInsightsName}-scope'
  properties: {
    linkedResourceId: appInsights.id
  }
}

resource peAmpls 'Microsoft.Network/privateEndpoints@2023-11-01' = if (isPrivate) {
  name: 'pe-ampls-${suffix}'
  location: location
  properties: {
    subnet: {
      id: vnet!.properties.subnets[1].id
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-ampls-connection'
        properties: {
          privateLinkServiceId: ampls.id
          groupIds: ['azuremonitor']
        }
      }
    ]
  }
}

resource peAmplsDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = if (isPrivate) {
  parent: peAmpls
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-monitor-azure-com'
        properties: {
          privateDnsZoneId: dnsZoneMonitor.id
        }
      }
    ]
  }
}

// -----------------------------------------------------------------------
// Azure AI Services + Model Deployment
// -----------------------------------------------------------------------

resource aiServices 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: aiServicesName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: aiServicesName
    publicNetworkAccess: isPrivate ? 'Disabled' : 'Enabled'
    disableLocalAuth: true
    allowProjectManagement: true
  }
}

// Foundry project under AI Services (prompt agent + OpenAPI tools)
var foundryProjectName = 'iq-lab-project'

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: aiServices
  name: foundryProjectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

resource aiModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: aiServices
  name: aiModelName
  sku: {
    name: 'GlobalStandard'
    capacity: aiModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: aiModelName
      version: aiModelVersion
    }
  }
}

// Cognitive Services OpenAI User role for tool service MI
// Role: 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd
resource aiRoleTools 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServices.id, miTools.id, '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    )
    principalId: miTools.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Cognitive Services OpenAI User role for agent MI
resource aiRoleAgent 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServices.id, miAgent.id, '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    )
    principalId: miAgent.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// -----------------------------------------------------------------------
// Container Apps
// -----------------------------------------------------------------------

resource caEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: caEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: isPrivate
      ? {
          infrastructureSubnetId: vnet!.properties.subnets[0].id // snet-container-apps
          internal: true
        }
      : null
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: caName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${miTools.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: caEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: miTools.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'iq-tools'
          image: toolServiceImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AZURE_SQL_SERVER_FQDN', value: sqlServer.properties.fullyQualifiedDomainName }
            { name: 'AZURE_SQL_DATABASE_NAME', value: sqlDatabaseName }
            { name: 'DB_AUTH_MODE', value: 'token' }
            { name: 'AZURE_CLIENT_ID', value: miTools.properties.clientId }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsights.properties.ConnectionString
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

// -----------------------------------------------------------------------
// Outputs
// -----------------------------------------------------------------------

output toolServiceUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output sqlServerFqdn string = sqlServer.properties.fullyQualifiedDomainName
output acrLoginServer string = acr.properties.loginServer
output miToolsPrincipalId string = miTools.properties.principalId
output miToolsClientId string = miTools.properties.clientId
output miAgentPrincipalId string = miAgent.properties.principalId
output miAgentClientId string = miAgent.properties.clientId
output miToolsName string = miTools.name
output miAgentName string = miAgent.name
output aiServicesEndpoint string = aiServices.properties.endpoint
output aiServicesName string = aiServices.name
output aiModelDeploymentName string = aiModelDeployment.name
output foundryProjectEndpoint string = 'https://${aiServicesName}.services.ai.azure.com/api/projects/${foundryProjectName}'
output foundryProjectName string = foundryProject.name
