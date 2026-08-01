@{
    RootModule = 'ArcShuttle.psm1'
    ModuleVersion = '0.2.0'
    GUID = 'd7d92b85-fc6b-4053-84df-33b2fb2db6ec'
    Author = 'ArcShuttle contributors'
    CompanyName = 'ArcShuttle contributors'
    Copyright = 'Copyright (c) 2026 bohemon'
    Description = 'PowerShell 7 object-pipeline commands for ArcShuttle.'
    PowerShellVersion = '7.0'
    CompatiblePSEditions = @('Core')
    FunctionsToExport = @(
        'Invoke-ArcShuttleExtractPlan'
        'Invoke-ArcShuttleCreatePlan'
        'Invoke-ArcShuttleRun'
        'Invoke-ArcShuttleExtract'
        'Invoke-ArcShuttleCreate'
    )
    CmdletsToExport = @()
    VariablesToExport = @()
    AliasesToExport = @()
    PrivateData = @{
        PSData = @{
            Tags = @('ArcShuttle', 'Archive', '7-Zip', 'Compression', 'Extraction')
            LicenseUri = 'https://github.com/bohemon/ArcShuttle/blob/v0.2.0/LICENSE'
            ProjectUri = 'https://github.com/bohemon/ArcShuttle'
            ReleaseNotes = 'https://github.com/bohemon/ArcShuttle/releases/tag/v0.2.0'
        }
    }
}
