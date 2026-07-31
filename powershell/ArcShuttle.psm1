Set-StrictMode -Version Latest

function Get-ArcShuttleCommonArguments {
    [CmdletBinding()]
    param([System.Collections.IDictionary] $BoundParameters)

    $arguments = [System.Collections.Generic.List[string]]::new()
    $mapping = [ordered]@{
        SevenZip               = '--7z'
        OutputDir              = '--output-dir'
        Existing               = '--existing'
        CpuBudget              = '--cpu-budget'
        MaxProcesses           = '--max-processes'
        StorageProfile         = '--storage-profile'
        IoSlots                = '--io-slots'
        HeavyThreads           = '--heavy-threads'
        SmallThreshold         = '--small-threshold'
        InspectThreshold       = '--inspect-threshold'
        InspectTimeout         = '--inspect-timeout'
        ReservationDelay       = '--reservation-delay'
        SequentialIfTotalBelow = '--sequential-if-total-below'
        LogDir                 = '--log-dir'
        Config                 = '--config'
        OnInputError           = '--on-input-error'
        Format                 = '--format'
        Level                  = '--level'
    }
    foreach ($entry in $mapping.GetEnumerator()) {
        if ($BoundParameters.ContainsKey($entry.Key) -and $null -ne $BoundParameters[$entry.Key]) {
            $arguments.Add($entry.Value)
            $arguments.Add([string]$BoundParameters[$entry.Key])
        }
    }
    $switches = [ordered]@{
        Quiet        = '--quiet'
        FailFast     = '--fail-fast'
        AllowChanged = '--allow-changed'
    }
    foreach ($entry in $switches.GetEnumerator()) {
        if ($BoundParameters.ContainsKey($entry.Key) -and $BoundParameters[$entry.Key].IsPresent) {
            $arguments.Add($entry.Value)
        }
    }
    return $arguments.ToArray()
}

function Invoke-ArcShuttleNativeJsonLines {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Command,
        [Parameter(Mandatory)] [string[]] $Arguments
    )

    $stderrPath = [System.IO.Path]::GetTempFileName()
    $nativeExitCode = $null
    try {
        $lines = @(& $Command @Arguments 2> $stderrPath)
        $nativeExitCode = $LASTEXITCODE
        if (Test-Path -LiteralPath $stderrPath) {
            foreach ($line in [System.IO.File]::ReadLines($stderrPath)) {
                [Console]::Error.WriteLine($line)
            }
        }
        foreach ($line in $lines) {
            if (-not [string]::IsNullOrWhiteSpace([string]$line)) {
                $line | ConvertFrom-Json -Depth 100
            }
        }
    }
    finally {
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
        if ($null -ne $nativeExitCode) {
            $global:LASTEXITCODE = $nativeExitCode
        }
    }
}

function ConvertTo-ArcShuttlePath {
    [CmdletBinding()]
    param([Parameter(Mandatory)] [object] $InputObject)

    if ($InputObject -is [System.IO.FileSystemInfo]) {
        return $InputObject.FullName
    }
    if ($InputObject -is [string]) {
        return $InputObject
    }
    throw "ArcShuttle plan commands accept strings or FileSystemInfo objects, not $($InputObject.GetType().FullName)"
}

function Invoke-ArcShuttlePathPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Operation,
        [Parameter(Mandatory)] [string[]] $Paths,
        [Parameter(Mandatory)] [string] $Command,
        [Parameter(Mandatory)] [System.Collections.IDictionary] $BoundParameters
    )

    $inputPath = [System.IO.Path]::GetTempFileName()
    try {
        $payload = ($Paths -join "`0") + "`0"
        [System.IO.File]::WriteAllBytes(
            $inputPath,
            [System.Text.UTF8Encoding]::new($false).GetBytes($payload)
        )
        $arguments = [System.Collections.Generic.List[string]]::new()
        $arguments.Add('plan')
        $arguments.Add($Operation)
        $arguments.Add('--files0-from')
        $arguments.Add($inputPath)
        foreach ($commonArgument in @(Get-ArcShuttleCommonArguments $BoundParameters)) {
            $arguments.Add([string]$commonArgument)
        }
        Invoke-ArcShuttleNativeJsonLines -Command $Command -Arguments $arguments.ToArray()
    }
    finally {
        Remove-Item -LiteralPath $inputPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-ArcShuttleExtractPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)] [object] $InputObject,
        [string] $ArcShuttleCommand = 'arcshuttle',
        [Alias('7z')] [string] $SevenZip,
        [string] $OutputDir,
        [ValidateSet('fail', 'skip', 'rename')] [string] $Existing,
        [string] $CpuBudget,
        [int] $MaxProcesses,
        [ValidateSet('auto', 'hdd', 'ssd', 'nvme')] [string] $StorageProfile,
        [int] $IoSlots,
        [int] $HeavyThreads,
        [string] $SmallThreshold,
        [string] $InspectThreshold,
        [double] $InspectTimeout,
        [double] $ReservationDelay,
        [string] $SequentialIfTotalBelow,
        [string] $LogDir,
        [string] $Config,
        [ValidateSet('fail', 'skip')] [string] $OnInputError,
        [switch] $Quiet,
        [switch] $FailFast,
        [switch] $AllowChanged
    )
    begin {
        $paths = [System.Collections.Generic.List[string]]::new()
    }
    process {
        $paths.Add((ConvertTo-ArcShuttlePath $InputObject))
    }
    end {
        Invoke-ArcShuttlePathPlan -Operation extract -Paths $paths.ToArray() `
            -Command $ArcShuttleCommand -BoundParameters $PSBoundParameters
    }
}

function Invoke-ArcShuttleCreatePlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)] [object] $InputObject,
        [string] $ArcShuttleCommand = 'arcshuttle',
        [Alias('7z')] [string] $SevenZip,
        [string] $OutputDir,
        [ValidateSet('fail', 'skip', 'rename')] [string] $Existing,
        [string] $CpuBudget,
        [int] $MaxProcesses,
        [ValidateSet('auto', 'hdd', 'ssd', 'nvme')] [string] $StorageProfile,
        [int] $IoSlots,
        [int] $HeavyThreads,
        [string] $SmallThreshold,
        [string] $InspectThreshold,
        [double] $InspectTimeout,
        [double] $ReservationDelay,
        [string] $SequentialIfTotalBelow,
        [string] $LogDir,
        [string] $Config,
        [ValidateSet('fail', 'skip')] [string] $OnInputError,
        [ValidateSet('7z', 'zip')] [string] $Format,
        [ValidateRange(0, 9)] [int] $Level,
        [switch] $Quiet,
        [switch] $FailFast,
        [switch] $AllowChanged
    )
    begin {
        $paths = [System.Collections.Generic.List[string]]::new()
    }
    process {
        $paths.Add((ConvertTo-ArcShuttlePath $InputObject))
    }
    end {
        Invoke-ArcShuttlePathPlan -Operation create -Paths $paths.ToArray() `
            -Command $ArcShuttleCommand -BoundParameters $PSBoundParameters
    }
}

function Invoke-ArcShuttleRun {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)] [object] $InputObject,
        [string] $ArcShuttleCommand = 'arcshuttle',
        [Alias('7z')] [string] $SevenZip,
        [string] $OutputDir,
        [ValidateSet('fail', 'skip', 'rename')] [string] $Existing,
        [string] $CpuBudget,
        [int] $MaxProcesses,
        [ValidateSet('auto', 'hdd', 'ssd', 'nvme')] [string] $StorageProfile,
        [int] $IoSlots,
        [int] $HeavyThreads,
        [string] $SmallThreshold,
        [string] $InspectThreshold,
        [double] $InspectTimeout,
        [double] $ReservationDelay,
        [string] $SequentialIfTotalBelow,
        [string] $LogDir,
        [string] $Config,
        [ValidateSet('fail', 'skip')] [string] $OnInputError,
        [switch] $Quiet,
        [switch] $FailFast,
        [switch] $AllowChanged
    )
    begin {
        $jsonLines = [System.Collections.Generic.List[string]]::new()
    }
    process {
        $jsonLines.Add(($InputObject | ConvertTo-Json -Compress -Depth 100))
    }
    end {
        $manifestPath = [System.IO.Path]::GetTempFileName()
        try {
            [System.IO.File]::WriteAllLines(
                $manifestPath,
                $jsonLines,
                [System.Text.UTF8Encoding]::new($false)
            )
            $arguments = [System.Collections.Generic.List[string]]::new()
            $arguments.Add('run')
            $arguments.Add('--manifest')
            $arguments.Add($manifestPath)
            foreach ($commonArgument in @(Get-ArcShuttleCommonArguments $PSBoundParameters)) {
                $arguments.Add([string]$commonArgument)
            }
            Invoke-ArcShuttleNativeJsonLines -Command $ArcShuttleCommand `
                -Arguments $arguments.ToArray()
        }
        finally {
            Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-ArcShuttleExtract {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)] [object] $InputObject,
        [string] $ArcShuttleCommand = 'arcshuttle',
        [Alias('7z')] [string] $SevenZip,
        [string] $OutputDir,
        [ValidateSet('fail', 'skip', 'rename')] [string] $Existing,
        [string] $CpuBudget,
        [int] $MaxProcesses,
        [ValidateSet('auto', 'hdd', 'ssd', 'nvme')] [string] $StorageProfile,
        [int] $IoSlots,
        [int] $HeavyThreads,
        [string] $SmallThreshold,
        [string] $InspectThreshold,
        [double] $InspectTimeout,
        [double] $ReservationDelay,
        [string] $SequentialIfTotalBelow,
        [string] $LogDir,
        [string] $Config,
        [ValidateSet('fail', 'skip')] [string] $OnInputError,
        [switch] $Quiet,
        [switch] $FailFast,
        [switch] $AllowChanged
    )
    begin {
        $items = [System.Collections.Generic.List[object]]::new()
    }
    process {
        $items.Add($InputObject)
    }
    end {
        $forward = @{}
        foreach ($key in $PSBoundParameters.Keys) {
            if ($key -ne 'InputObject') {
                $forward[$key] = $PSBoundParameters[$key]
            }
        }
        $plans = @($items | Invoke-ArcShuttleExtractPlan @forward)
        if ($plans.Count -gt 0) {
            $plans | Invoke-ArcShuttleRun @forward
        }
    }
}

function Invoke-ArcShuttleCreate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)] [object] $InputObject,
        [string] $ArcShuttleCommand = 'arcshuttle',
        [Alias('7z')] [string] $SevenZip,
        [string] $OutputDir,
        [ValidateSet('fail', 'skip', 'rename')] [string] $Existing,
        [string] $CpuBudget,
        [int] $MaxProcesses,
        [ValidateSet('auto', 'hdd', 'ssd', 'nvme')] [string] $StorageProfile,
        [int] $IoSlots,
        [int] $HeavyThreads,
        [string] $SmallThreshold,
        [string] $InspectThreshold,
        [double] $InspectTimeout,
        [double] $ReservationDelay,
        [string] $SequentialIfTotalBelow,
        [string] $LogDir,
        [string] $Config,
        [ValidateSet('fail', 'skip')] [string] $OnInputError,
        [ValidateSet('7z', 'zip')] [string] $Format,
        [ValidateRange(0, 9)] [int] $Level,
        [switch] $Quiet,
        [switch] $FailFast,
        [switch] $AllowChanged
    )
    begin {
        $items = [System.Collections.Generic.List[object]]::new()
    }
    process {
        $items.Add($InputObject)
    }
    end {
        $planForward = @{}
        foreach ($key in $PSBoundParameters.Keys) {
            if ($key -ne 'InputObject') {
                $planForward[$key] = $PSBoundParameters[$key]
            }
        }
        $runForward = $planForward.Clone()
        $runForward.Remove('Format')
        $runForward.Remove('Level')
        $plans = @($items | Invoke-ArcShuttleCreatePlan @planForward)
        if ($plans.Count -gt 0) {
            $plans | Invoke-ArcShuttleRun @runForward
        }
    }
}

Export-ModuleMember -Function `
    Invoke-ArcShuttleExtractPlan, `
    Invoke-ArcShuttleCreatePlan, `
    Invoke-ArcShuttleRun, `
    Invoke-ArcShuttleExtract, `
    Invoke-ArcShuttleCreate
