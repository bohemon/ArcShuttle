@{
    RootModule = 'Parxtract.psm1'
    ModuleVersion = '0.2.0'
    GUID = '17bbb106-56d9-473c-b20f-1d044d0f8031'
    Author = 'ArcShuttle contributors'
    CompanyName = 'ArcShuttle contributors'
    Copyright = 'Copyright (c) 2026 bohemon'
    Description = 'Compatibility PowerShell 7 object-pipeline commands for parxtract.'
    PowerShellVersion = '7.0'
    CompatiblePSEditions = @('Core')
    FunctionsToExport = @(
        'Invoke-ParxtractPlan'
        'Invoke-ParxtractRun'
        'Invoke-Parxtract'
    )
    CmdletsToExport = @()
    VariablesToExport = @()
    AliasesToExport = @()
    PrivateData = @{
        PSData = @{
            Tags = @('ArcShuttle', 'Parxtract', 'Archive', 'Compatibility')
            LicenseUri = 'https://github.com/bohemon/ArcShuttle/blob/v0.2.0/LICENSE'
            ProjectUri = 'https://github.com/bohemon/ArcShuttle'
            ReleaseNotes = 'https://github.com/bohemon/ArcShuttle/releases/tag/v0.2.0'
        }
    }
}
