Set-StrictMode -Version Latest

function Get-ParxtractCommonArguments {
    [CmdletBinding()]
    param([hashtable] $BoundParameters)

    $arguments = [System.Collections.Generic.List[string]]::new()
    $mapping = [ordered]@{
        SevenZip              = '--7z'
        OutputDir             = '--output-dir'
        Existing              = '--existing'
        CpuBudget             = '--cpu-budget'
        MaxProcesses          = '--max-processes'
        StorageProfile        = '--storage-profile'
        IoSlots               = '--io-slots'
        HeavyThreads          = '--heavy-threads'
        SmallThreshold        = '--small-threshold'
        InspectThreshold      = '--inspect-threshold'
        InspectTimeout        = '--inspect-timeout'
        ReservationDelay      = '--reservation-delay'
        SequentialIfTotalBelow = '--sequential-if-total-below'
        LogDir                = '--log-dir'
        Config                = '--config'
        OnInputError          = '--on-input-error'
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

function Invoke-ParxtractNativeJsonLines {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Command,
        [Parameter(Mandatory)] [string[]] $Arguments
    )

    $nativeExitCode = $null
    try {
        $lines = @(& $Command @Arguments)
        $nativeExitCode = $LASTEXITCODE
        foreach ($line in $lines) {
            if (-not [string]::IsNullOrWhiteSpace([string]$line)) {
                $line | ConvertFrom-Json -Depth 100
            }
        }
    }
    finally {
        if ($null -ne $nativeExitCode) {
            $global:LASTEXITCODE = $nativeExitCode
        }
    }
}

function Invoke-ParxtractPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)] [object] $InputObject,
        [string] $ParxtractCommand = 'parxtract',
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
        if ($InputObject -is [System.IO.FileSystemInfo]) {
            $paths.Add($InputObject.FullName)
        }
        elseif ($InputObject -is [string]) {
            $paths.Add($InputObject)
        }
        else {
            throw "Invoke-ParxtractPlan accepts strings or FileSystemInfo objects, not $($InputObject.GetType().FullName)"
        }
    }
    end {
        $inputPath = [System.IO.Path]::GetTempFileName()
        try {
            [System.IO.File]::WriteAllLines(
                $inputPath,
                $paths,
                [System.Text.UTF8Encoding]::new($false)
            )
            $arguments = [System.Collections.Generic.List[string]]::new()
            $arguments.Add('plan')
            $arguments.Add('--files-from')
            $arguments.Add($inputPath)
            foreach ($commonArgument in @(Get-ParxtractCommonArguments $PSBoundParameters)) {
                $arguments.Add([string]$commonArgument)
            }
            Invoke-ParxtractNativeJsonLines -Command $ParxtractCommand -Arguments $arguments.ToArray()
        }
        finally {
            Remove-Item -LiteralPath $inputPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-ParxtractRun {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)] [object] $InputObject,
        [string] $ParxtractCommand = 'parxtract',
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
            foreach ($commonArgument in @(Get-ParxtractCommonArguments $PSBoundParameters)) {
                $arguments.Add([string]$commonArgument)
            }
            Invoke-ParxtractNativeJsonLines -Command $ParxtractCommand -Arguments $arguments.ToArray()
        }
        finally {
            Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-Parxtract {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)] [object] $InputObject,
        [string] $ParxtractCommand = 'parxtract',
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
            if ($key -notin @('InputObject')) {
                $forward[$key] = $PSBoundParameters[$key]
            }
        }
        $plans = @($items | Invoke-ParxtractPlan @forward)
        if ($plans.Count -gt 0) {
            $plans | Invoke-ParxtractRun @forward
        }
    }
}

Export-ModuleMember -Function Invoke-ParxtractPlan, Invoke-ParxtractRun, Invoke-Parxtract
