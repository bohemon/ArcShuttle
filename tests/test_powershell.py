from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from arcshuttle import __version__

ROOT = Path(__file__).parents[1]
PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is not installed")


def ps_quote(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_script(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "test.ps1"
    script.write_text(source, encoding="utf-8")
    return subprocess.run(
        [PWSH or "pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.parametrize(
    ("module_name", "expected_exports"),
    (
        (
            "ArcShuttle",
            {
                "Invoke-ArcShuttleCreate",
                "Invoke-ArcShuttleCreatePlan",
                "Invoke-ArcShuttleExtract",
                "Invoke-ArcShuttleExtractPlan",
                "Invoke-ArcShuttleRun",
            },
        ),
        (
            "Parxtract",
            {"Invoke-Parxtract", "Invoke-ParxtractPlan", "Invoke-ParxtractRun"},
        ),
    ),
)
def test_module_manifest_metadata_and_exports(
    tmp_path: Path,
    module_name: str,
    expected_exports: set[str],
) -> None:
    manifest = ROOT / "powershell" / f"{module_name}.psd1"
    script = f"""
$manifest = Test-ModuleManifest -Path {ps_quote(manifest)}
[pscustomobject]@{{
    name = $manifest.Name
    version = $manifest.Version.ToString()
    powershell_version = $manifest.PowerShellVersion.ToString()
    compatible_editions = @($manifest.CompatiblePSEditions)
    exports = @($manifest.ExportedFunctions.Keys)
}} | ConvertTo-Json -Compress -Depth 100
"""

    completed = run_script(tmp_path, script)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["name"] == module_name
    assert result["version"] == __version__
    assert result["powershell_version"] == "7.0"
    assert result["compatible_editions"] == ["Core"]
    assert set(result["exports"]) == expected_exports


FAKE_ARCSHUTTLE = r"""
function global:Invoke-FakeArcShuttle {
    $cliArgs = @($args)
    if ($cliArgs[0] -eq 'plan') {
        $inputIndex = [Array]::IndexOf($cliArgs, '--files0-from')
        $inputPath = $cliArgs[$inputIndex + 1]
        $bytes = [System.IO.File]::ReadAllBytes($inputPath)
        $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
        $text = [System.Text.UTF8Encoding]::new($false).GetString($bytes).TrimEnd([char]0)
        $paths = @($text.Split([char]0))
        foreach ($path in $paths) {
            [pscustomobject]@{
                record_type = 'job'
                operation = $cliArgs[1]
                source_path = $path
                arguments = $cliArgs
                temporary_path = $inputPath
                has_bom = $hasBom
            } | ConvertTo-Json -Compress -Depth 100
        }
        Write-Error 'fake plan diagnostic'
        $global:LASTEXITCODE = 7
        return
    }
    if ($cliArgs[0] -eq 'run') {
        $manifestIndex = [Array]::IndexOf($cliArgs, '--manifest')
        $manifestPath = $cliArgs[$manifestIndex + 1]
        $bytes = [System.IO.File]::ReadAllBytes($manifestPath)
        $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
        $records = @([System.IO.File]::ReadAllLines($manifestPath) | ForEach-Object { $_ | ConvertFrom-Json })
        [pscustomobject]@{
            record_type = 'result'
            operations = @($records | ForEach-Object { $_.operation })
            count = $records.Count
            arguments = $cliArgs
            temporary_path = $manifestPath
            has_bom = $hasBom
        } | ConvertTo-Json -Compress -Depth 100
        [pscustomobject]@{ record_type = 'summary'; total = $records.Count } |
            ConvertTo-Json -Compress -Depth 100
        Write-Error 'fake run diagnostic'
        $global:LASTEXITCODE = 9
        return
    }
    throw "unexpected arguments: $cliArgs"
}
"""


def test_create_plan_maps_pipeline_arguments_and_cleans_nul_file(tmp_path: Path) -> None:
    module = ROOT / "powershell" / "ArcShuttle.psm1"
    source_file = tmp_path / "file with space.txt"
    source_file.write_text("data", encoding="utf-8")
    source_dir = tmp_path / "directory"
    source_dir.mkdir()
    script = f"""
Import-Module {ps_quote(module)} -Force
{FAKE_ARCSHUTTLE}
$plans = @(
    @({ps_quote(source_dir)}, (Get-Item -LiteralPath {ps_quote(source_file)})) |
        Invoke-ArcShuttleCreatePlan -ArcShuttleCommand Invoke-FakeArcShuttle `
            -Format zip -Level 7 -CpuBudget 2 -Quiet
)
$savedExit = $LASTEXITCODE
[pscustomobject]@{{
    count = $plans.Count
    type_names = @($plans | ForEach-Object {{ $_.PSObject.TypeNames[0] }})
    operations = @($plans.operation)
    paths = @($plans.source_path)
    arguments = @($plans[0].arguments)
    has_bom = [bool]$plans[0].has_bom
    temporary_exists = Test-Path -LiteralPath $plans[0].temporary_path
    exit_code = $savedExit
}} | ConvertTo-Json -Compress -Depth 100
"""

    completed = run_script(tmp_path, script)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["count"] == 2
    assert result["type_names"] == [
        "System.Management.Automation.PSCustomObject",
        "System.Management.Automation.PSCustomObject",
    ]
    assert result["operations"] == ["create", "create"]
    assert result["paths"] == [str(source_dir), str(source_file)]
    assert result["arguments"][:4] == ["plan", "create", "--files0-from", result["arguments"][3]]
    format_index = result["arguments"].index("--format")
    level_index = result["arguments"].index("--level")
    assert result["arguments"][format_index + 1] == "zip"
    assert result["arguments"][level_index + 1] == "7"
    assert "--cpu-budget" in result["arguments"] and "--quiet" in result["arguments"]
    assert result["has_bom"] is False
    assert result["temporary_exists"] is False
    assert result["exit_code"] == 7
    assert "fake plan diagnostic" in completed.stderr


def test_run_converts_objects_to_bom_free_json_lines_and_cleans_manifest(
    tmp_path: Path,
) -> None:
    module = ROOT / "powershell" / "ArcShuttle.psm1"
    script = f"""
Import-Module {ps_quote(module)} -Force
{FAKE_ARCSHUTTLE}
$records = @(
    @(
        [pscustomobject]@{{ operation = 'extract'; value = 'one' }}
        [pscustomobject]@{{ operation = 'create'; value = 'two' }}
    ) | Invoke-ArcShuttleRun -ArcShuttleCommand Invoke-FakeArcShuttle `
        -FailFast -StorageProfile auto
)
$savedExit = $LASTEXITCODE
[pscustomobject]@{{
    record_types = @($records.record_type)
    operations = @($records[0].operations)
    count = $records[0].count
    arguments = @($records[0].arguments)
    has_bom = [bool]$records[0].has_bom
    temporary_exists = Test-Path -LiteralPath $records[0].temporary_path
    exit_code = $savedExit
}} | ConvertTo-Json -Compress -Depth 100
"""

    completed = run_script(tmp_path, script)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["record_types"] == ["result", "summary"]
    assert result["operations"] == ["extract", "create"]
    assert result["count"] == 2
    assert result["arguments"][:2] == ["run", "--manifest"]
    assert "--fail-fast" in result["arguments"]
    profile_index = result["arguments"].index("--storage-profile")
    assert result["arguments"][profile_index + 1] == "auto"
    assert result["has_bom"] is False
    assert result["temporary_exists"] is False
    assert result["exit_code"] == 9
    assert "fake run diagnostic" in completed.stderr


def test_clixml_snapshots_combine_into_object_run_pipeline(tmp_path: Path) -> None:
    module = ROOT / "powershell" / "ArcShuttle.psm1"
    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"archive")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    extract_snapshot = tmp_path / "extract.clixml"
    create_snapshot = tmp_path / "create.clixml"
    script = f"""
Import-Module {ps_quote(module)} -Force
{FAKE_ARCSHUTTLE}
$extractPlan = @(
    Get-Item -LiteralPath {ps_quote(archive)} |
        Invoke-ArcShuttleExtractPlan -ArcShuttleCommand Invoke-FakeArcShuttle
)
$createPlan = @(
    Get-Item -LiteralPath {ps_quote(source_dir)} |
        Invoke-ArcShuttleCreatePlan -ArcShuttleCommand Invoke-FakeArcShuttle `
            -Format 7z -Level 5
)
$extractPlan | Export-Clixml -LiteralPath {ps_quote(extract_snapshot)} -Depth 100
$createPlan | Export-Clixml -LiteralPath {ps_quote(create_snapshot)} -Depth 100
$restored = @(
    Import-Clixml -LiteralPath {ps_quote(extract_snapshot)}
    Import-Clixml -LiteralPath {ps_quote(create_snapshot)}
)
$records = @(
    $restored | Invoke-ArcShuttleRun -ArcShuttleCommand Invoke-FakeArcShuttle
)
$savedExit = $LASTEXITCODE
[pscustomobject]@{{
    restored_count = $restored.Count
    restored_operations = @($restored.operation)
    restored_type_names = @($restored | ForEach-Object {{ $_.PSObject.TypeNames[0] }})
    restored_argument_roots = @($restored | ForEach-Object {{ $_.arguments[0] }})
    record_types = @($records.record_type)
    run_operations = @($records[0].operations)
    run_count = $records[0].count
    run_has_bom = [bool]$records[0].has_bom
    run_temporary_exists = Test-Path -LiteralPath $records[0].temporary_path
    exit_code = $savedExit
}} | ConvertTo-Json -Compress -Depth 100
"""

    completed = run_script(tmp_path, script)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["restored_count"] == 2
    assert result["restored_operations"] == ["extract", "create"]
    assert result["restored_type_names"] == [
        "Deserialized.System.Management.Automation.PSCustomObject",
        "Deserialized.System.Management.Automation.PSCustomObject",
    ]
    assert result["restored_argument_roots"] == ["plan", "plan"]
    assert result["record_types"] == ["result", "summary"]
    assert result["run_operations"] == ["extract", "create"]
    assert result["run_count"] == 2
    assert result["run_has_bom"] is False
    assert result["run_temporary_exists"] is False
    assert result["exit_code"] == 9
    assert "fake run diagnostic" in completed.stderr


def test_extract_plan_maps_to_plan_extract(tmp_path: Path) -> None:
    module = ROOT / "powershell" / "ArcShuttle.psm1"
    source = tmp_path / "archive.zip"
    source.write_bytes(b"archive")
    script = f"""
Import-Module {ps_quote(module)} -Force
{FAKE_ARCSHUTTLE}
$plans = @({ps_quote(source)} |
    Invoke-ArcShuttleExtractPlan -ArcShuttleCommand Invoke-FakeArcShuttle -Existing rename)
$savedExit = $LASTEXITCODE
[pscustomobject]@{{
    operation = $plans[0].operation
    arguments = @($plans[0].arguments)
    temporary_exists = Test-Path -LiteralPath $plans[0].temporary_path
    exit_code = $savedExit
}} | ConvertTo-Json -Compress -Depth 100
"""

    completed = run_script(tmp_path, script)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["operation"] == "extract"
    assert result["arguments"][:3] == ["plan", "extract", "--files0-from"]
    existing_index = result["arguments"].index("--existing")
    assert result["arguments"][existing_index + 1] == "rename"
    assert result["temporary_exists"] is False
    assert result["exit_code"] == 7


def test_combined_create_runs_plan_then_run_for_independent_items(tmp_path: Path) -> None:
    module = ROOT / "powershell" / "ArcShuttle.psm1"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    script = f"""
Import-Module {ps_quote(module)} -Force
{FAKE_ARCSHUTTLE}
$records = @(
    @({ps_quote(first)}, {ps_quote(second)}) |
        Invoke-ArcShuttleCreate -ArcShuttleCommand Invoke-FakeArcShuttle -Format 7z -Level 5
)
$savedExit = $LASTEXITCODE
[pscustomobject]@{{
    record_types = @($records.record_type)
    count = $records[0].count
    operations = @($records[0].operations)
    run_arguments = @($records[0].arguments)
    run_temporary_exists = Test-Path -LiteralPath $records[0].temporary_path
    exit_code = $savedExit
}} | ConvertTo-Json -Compress -Depth 100
"""

    completed = run_script(tmp_path, script)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["record_types"] == ["result", "summary"]
    assert result["count"] == 2
    assert result["operations"] == ["create", "create"]
    assert "--format" not in result["run_arguments"]
    assert "--level" not in result["run_arguments"]
    assert result["run_temporary_exists"] is False
    assert result["exit_code"] == 9


def test_legacy_module_exports_and_plan_pipeline_remain_compatible(tmp_path: Path) -> None:
    module = ROOT / "powershell" / "Parxtract.psm1"
    source = tmp_path / "legacy.zip"
    source.write_bytes(b"archive")
    script = f"""
Import-Module {ps_quote(module)} -Force
function global:Invoke-FakeParxtract {{
    $cliArgs = @($args)
    $inputIndex = [Array]::IndexOf($cliArgs, '--files-from')
    $inputPath = $cliArgs[$inputIndex + 1]
    $hasBom = ([System.IO.File]::ReadAllBytes($inputPath) | Select-Object -First 3) -join ',' -eq '239,187,191'
    [pscustomobject]@{{
        record_type = 'job'
        path = [System.IO.File]::ReadAllLines($inputPath)[0]
        temporary_path = $inputPath
        has_bom = $hasBom
    }} | ConvertTo-Json -Compress
    $global:LASTEXITCODE = 4
}}
$plans = @((Get-Item -LiteralPath {ps_quote(source)}) |
    Invoke-ParxtractPlan -ParxtractCommand Invoke-FakeParxtract)
$savedExit = $LASTEXITCODE
[pscustomobject]@{{
    exported = @(Get-Command Invoke-ParxtractPlan, Invoke-ParxtractRun, Invoke-Parxtract |
        Select-Object -ExpandProperty Name)
    path = $plans[0].path
    has_bom = [bool]$plans[0].has_bom
    temporary_exists = Test-Path -LiteralPath $plans[0].temporary_path
    exit_code = $savedExit
}} | ConvertTo-Json -Compress -Depth 100
"""

    completed = run_script(tmp_path, script)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert set(result["exported"]) == {
        "Invoke-ParxtractPlan",
        "Invoke-ParxtractRun",
        "Invoke-Parxtract",
    }
    assert result["path"] == str(source)
    assert result["has_bom"] is False
    assert result["temporary_exists"] is False
    assert result["exit_code"] == 4


@pytest.mark.parametrize(
    ("module_name", "command_name", "command_parameter"),
    (
        ("ArcShuttle", "Invoke-ArcShuttleRun", "ArcShuttleCommand"),
        ("Parxtract", "Invoke-ParxtractRun", "ParxtractCommand"),
    ),
)
def test_stderr_streams_before_exit_in_order_and_preserves_contracts(
    tmp_path: Path,
    module_name: str,
    command_name: str,
    command_parameter: str,
) -> None:
    module = ROOT / "powershell" / f"{module_name}.psm1"
    release_marker = tmp_path / "release.marker"
    fixture = tmp_path / "native-fixture.ps1"
    fixture.write_text(
        f"""
$cliArgs = @($args)
$manifestIndex = [Array]::IndexOf($cliArgs, '--manifest')
$manifestPath = $cliArgs[$manifestIndex + 1]
[Console]::Error.WriteLine('stream-first')
[Console]::Error.Flush()
$deadline = [DateTime]::UtcNow.AddSeconds(15)
while (-not (Test-Path -LiteralPath {ps_quote(release_marker)})) {{
    if ([DateTime]::UtcNow -ge $deadline) {{ throw 'release marker timeout' }}
    Start-Sleep -Milliseconds 10
}}
[Console]::Error.WriteLine('stream-second')
[pscustomobject]@{{
    record_type = 'summary'
    temporary_path = $manifestPath
}} | ConvertTo-Json -Compress
[Console]::Error.WriteLine('stream-last')
[Console]::Error.Flush()
exit 23
""",
        encoding="utf-8",
    )
    if os.name == "nt":
        wrapper = tmp_path / "native-fixture.cmd"
        wrapper.write_text(
            f'@"{PWSH}" -NoLogo -NoProfile -NonInteractive -File "{fixture}" %*\n'
            "@exit /b %ERRORLEVEL%\n",
            encoding="utf-8",
        )
    else:
        wrapper = tmp_path / "native-fixture"
        wrapper.write_text(
            "#!/bin/sh\n"
            f"exec {shlex.quote(PWSH or 'pwsh')} -NoLogo -NoProfile -NonInteractive "
            f'-File {shlex.quote(str(fixture))} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    script = f"""
Import-Module {ps_quote(module)} -Force
$records = @(
    [pscustomobject]@{{ schema_version = 2; operation = 'extract' }} |
        {command_name} -{command_parameter} {ps_quote(wrapper)}
)
$savedExit = $LASTEXITCODE
[pscustomobject]@{{
    count = $records.Count
    type_name = $records[0].PSObject.TypeNames[0]
    record_type = $records[0].record_type
    temporary_exists = Test-Path -LiteralPath $records[0].temporary_path
    exit_code = $savedExit
}} | ConvertTo-Json -Compress
"""
    script_path = tmp_path / "streaming.ps1"
    script_path.write_text(script, encoding="utf-8")
    process = subprocess.Popen(
        [
            PWSH or "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    stderr_lines: list[str] = []
    first_line_seen = threading.Event()

    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(line)
            if "stream-first" in line:
                first_line_seen.set()

    reader = threading.Thread(target=read_stderr, daemon=True)
    reader.start()
    try:
        assert first_line_seen.wait(10), "first stderr line was not forwarded promptly"
        assert process.poll() is None, "process exited before its first stderr line was observed"
        release_marker.touch()
        assert process.stdout is not None
        stdout = process.stdout.read()
        return_code = process.wait(timeout=10)
        reader.join(timeout=2)
    finally:
        release_marker.touch(exist_ok=True)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert not reader.is_alive(), "stderr did not reach EOF"
    stderr = "".join(stderr_lines)
    assert return_code == 0, stderr
    result = json.loads(stdout)
    assert result == {
        "count": 1,
        "type_name": "System.Management.Automation.PSCustomObject",
        "record_type": "summary",
        "temporary_exists": False,
        "exit_code": 23,
    }
    assert "stream-" not in stdout
    assert stderr.index("stream-first") < stderr.index("stream-second")
    assert stderr.index("stream-second") < stderr.index("stream-last")


@pytest.mark.parametrize(
    ("module_name", "command_name", "command_parameter"),
    (
        ("ArcShuttle", "Invoke-ArcShuttleRun", "ArcShuttleCommand"),
        ("Parxtract", "Invoke-ParxtractRun", "ParxtractCommand"),
    ),
)
def test_quiet_is_forwarded_and_suppresses_fixture_progress(
    tmp_path: Path,
    module_name: str,
    command_name: str,
    command_parameter: str,
) -> None:
    module = ROOT / "powershell" / f"{module_name}.psm1"
    script = f"""
Import-Module {ps_quote(module)} -Force
function global:Invoke-QuietFixture {{
    $cliArgs = @($args)
    if ('--quiet' -notin $cliArgs) {{ Write-Error 'quiet-progress' }}
    [pscustomobject]@{{ record_type = 'summary'; quiet = '--quiet' -in $cliArgs }} |
        ConvertTo-Json -Compress
    $global:LASTEXITCODE = 0
}}
$record = [pscustomobject]@{{ schema_version = 2; operation = 'extract' }} |
    {command_name} -{command_parameter} Invoke-QuietFixture -Quiet
$record | ConvertTo-Json -Compress
"""

    completed = run_script(tmp_path, script)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["quiet"] is True
    assert "quiet-progress" not in completed.stderr


@pytest.mark.parametrize(
    ("module_name", "command_name", "command_parameter"),
    (
        ("ArcShuttle", "Invoke-ArcShuttleRun", "ArcShuttleCommand"),
        ("Parxtract", "Invoke-ParxtractRun", "ParxtractCommand"),
    ),
)
def test_explicit_stderr_merge_makes_success_stream_mixed(
    tmp_path: Path,
    module_name: str,
    command_name: str,
    command_parameter: str,
) -> None:
    module = ROOT / "powershell" / f"{module_name}.psm1"
    script = f"""
Import-Module {ps_quote(module)} -Force
function global:Invoke-MergedFixture {{
    Write-Error 'merged-diagnostic'
    [pscustomobject]@{{ record_type = 'summary' }} | ConvertTo-Json -Compress
    $global:LASTEXITCODE = 6
}}
$merged = @(
    [pscustomobject]@{{ schema_version = 2; operation = 'extract' }} |
        {command_name} -{command_parameter} Invoke-MergedFixture 2>&1
)
$savedExit = $LASTEXITCODE
[pscustomobject]@{{
    type_names = @($merged | ForEach-Object {{ $_.GetType().FullName }})
    diagnostic = [string]$merged[0]
    record_type = $merged[1].record_type
    exit_code = $savedExit
}} | ConvertTo-Json -Compress
"""

    completed = run_script(tmp_path, script)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["type_names"] == [
        "System.Management.Automation.ErrorRecord",
        "System.Management.Automation.PSCustomObject",
    ]
    assert "merged-diagnostic" in result["diagnostic"]
    assert result["record_type"] == "summary"
    assert result["exit_code"] == 6
