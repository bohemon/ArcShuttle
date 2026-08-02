from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

import pytest

from arcshuttle import __version__, config
from arcshuttle.cli import build_parser

ROOT = Path(__file__).parents[1]
MANUALS = (
    ROOT / "docs" / "COMMAND_MANUAL.en.md",
    ROOT / "docs" / "COMMAND_MANUAL.ja.md",
)
INSTALLATION_GUIDES = (
    ROOT / "docs" / "INSTALLATION.en.md",
    ROOT / "docs" / "INSTALLATION.ja.md",
)
POWERSHELL_MANIFESTS = (
    ROOT / "powershell" / "ArcShuttle.psd1",
    ROOT / "powershell" / "Parxtract.psd1",
)


@pytest.mark.parametrize("manual", MANUALS, ids=("en", "ja"))
def test_command_manual_covers_every_cli_command_and_option(manual: Path) -> None:
    text = manual.read_text(encoding="utf-8")
    options: set[str] = set()
    commands: set[str] = set()

    def collect(parser: argparse.ArgumentParser) -> None:
        for action in parser._actions:
            options.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                for command, child in action.choices.items():
                    commands.add(command)
                    collect(child)

    collect(build_parser(program_name="arcshuttle"))
    collect(build_parser(program_name="parxtract", legacy=True))

    missing = [command for command in sorted(commands) if f"`{command}`" not in text]
    for option in sorted(options):
        option_pattern = re.compile(rf"`{re.escape(option)}(?=`|\s|,)")
        if not option_pattern.search(text):
            missing.append(option)

    assert missing == []


@pytest.mark.parametrize("manual", MANUALS, ids=("en", "ja"))
def test_command_manual_covers_every_environment_variable(manual: Path) -> None:
    text = manual.read_text(encoding="utf-8")

    for variable in (*config._ENV_NAMES.values(), *config._LEGACY_ENV_NAMES.values()):
        assert f"`{variable}`" in text


def test_readme_links_to_packaged_manuals() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for manual in MANUALS:
        relative_path = manual.relative_to(ROOT).as_posix()
        assert relative_path in readme
        assert manual.is_file()

    for guide in INSTALLATION_GUIDES:
        relative_path = guide.relative_to(ROOT).as_posix()
        assert relative_path in readme
        assert guide.is_file()


def test_current_version_is_aligned_across_documentation_and_modules() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    wheel_name = f"arcshuttle-{__version__}-py3-none-any.whl"

    assert f"releases/download/v{__version__}/{wheel_name}" in readme
    for manual in MANUALS:
        text = manual.read_text(encoding="utf-8")
        assert f"applies_to_cli_version: {__version__}" in text
    for guide in INSTALLATION_GUIDES:
        text = guide.read_text(encoding="utf-8")
        assert f"releases/download/v{__version__}/{wheel_name}" in text
        assert f"git@v{__version__}" in text
        assert f"$removeVersion = '{__version__}'" in text
        assert "ArcShuttle/$removeVersion" in text
        assert "Parxtract/$removeVersion" in text
    for manifest in POWERSHELL_MANIFESTS:
        text = manifest.read_text(encoding="utf-8")
        assert f"ModuleVersion = '{__version__}'" in text
        assert f"blob/v{__version__}/LICENSE" in text
        assert f"releases/tag/v{__version__}" in text


@pytest.mark.parametrize("guide", INSTALLATION_GUIDES, ids=("en", "ja"))
def test_installation_guides_cover_clone_free_and_verified_installation(guide: Path) -> None:
    text = guide.read_text(encoding="utf-8")
    required_terms = (
        "pipx install",
        "python -m pip install",
        "--upgrade",
        "python -m pip uninstall arcshuttle",
        f"arcshuttle-{__version__}-py3-none-any.whl",
        f"git+https://github.com/bohemon/ArcShuttle.git@v{__version__}",
        "ArcShuttle-PowerShell-$version.zip",
        '$checksumFile = "$archive.sha256"',
        "Get-FileHash",
        "Expand-Archive",
        "Test-ModuleManifest",
        "Import-Module ArcShuttle",
        "Import-Module Parxtract",
        "-RequiredVersion $version",
        "Invoke-Expression",
    )
    assert [term for term in required_terms if term not in text] == []


@pytest.mark.parametrize("manual", MANUALS, ids=("en", "ja"))
def test_command_manual_table_rows_have_consistent_column_counts(manual: Path) -> None:
    expected_pipes: int | None = None

    for line_number, line in enumerate(manual.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("|"):
            expected_pipes = None
            continue

        pipe_count = len(re.findall(r"(?<!\\)\|", line))
        if expected_pipes is None:
            expected_pipes = pipe_count
        assert pipe_count == expected_pipes, (
            f"{manual.name}:{line_number}: table row has {pipe_count - 1} columns; "
            f"expected {expected_pipes - 1}. Escape literal pipes as \\|."
        )


@pytest.mark.parametrize("manual", MANUALS, ids=("en", "ja"))
def test_command_manual_covers_safety_compatibility_and_automation_contracts(
    manual: Path,
) -> None:
    text = manual.read_text(encoding="utf-8")
    required_terms = (
        "schema v2",
        "schema v1",
        "destination.path",
        "verification_exit_code",
        "create.stdout.log",
        ".arcshuttle-owned",
        ".parxtract",
        "multi-source",
        "Invoke-ArcShuttleCreatePlan",
        "Invoke-ParxtractPlan",
        "stdout",
        "stderr",
        "CPU token",
    )
    folded_text = text.casefold()
    missing = [term for term in required_terms if term.casefold() not in folded_text]
    assert missing == []


@pytest.mark.parametrize("manual", MANUALS, ids=("en", "ja"))
def test_command_manual_defines_powershell_output_and_persistence_contracts(
    manual: Path,
) -> None:
    text = manual.read_text(encoding="utf-8")
    required_terms = (
        "PSCustomObject",
        "display formatting",
        "Invoke-ArcShuttleExtractPlan >",
        "arcshuttle plan extract --",
        "ConvertFrom-Json",
        "Export-Clixml",
        "Import-Clixml",
        "CLIXML",
        "`job_id`",
        "output collision",
        "`plan_index`",
        "`integrity`",
        "Invoke-ParxtractRun",
    )
    assert [term for term in required_terms if term not in text] == []
    duplicate_term = "duplicate" if manual.name.endswith(".en.md") else "重複"
    assert duplicate_term in text.casefold()


@pytest.mark.parametrize("manual", MANUALS, ids=("en", "ja"))
def test_command_manual_does_not_claim_storage_detection_is_unsupported(manual: Path) -> None:
    text = manual.read_text(encoding="utf-8")

    assert "disk auto-detection" not in text
    assert "disk自動判定" not in text


@pytest.mark.parametrize("manual", MANUALS, ids=("en", "ja"))
def test_command_manual_defines_powershell_stream_contract(manual: Path) -> None:
    text = manual.read_text(encoding="utf-8")
    required_terms = (
        "PSCustomObject",
        "stderr",
        "-Quiet",
        "2>&1",
        "ErrorRecord",
        "object pipeline",
    )
    assert [term for term in required_terms if term not in text] == []
    real_time_term = "in real time" if manual.name.endswith(".en.md") else "リアルタイム"
    assert real_time_term in text


@pytest.mark.parametrize("manual", MANUALS, ids=("en", "ja"))
def test_command_manual_defines_automatic_io_resolution_contract(manual: Path) -> None:
    text = manual.read_text(encoding="utf-8")
    required_terms = (
        'storage_profile = "auto"',
        "HDD = 1",
        "SSD = 2",
        "NVMe = 4",
        "unknown = 2",
        "source",
        "destination",
        "max_processes",
        "stderr",
        "--quiet",
        "--io-slots",
        "`plan`",
    )

    assert [term for term in required_terms if term not in text] == []


def test_readme_has_required_arcshuttle_opening_and_migration_notes() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "ArcShuttle is a resource-aware command-line tool for creating, extracting, "
        "and verifying multiple archives through the 7-Zip CLI."
    ) in readme
    for term in ("`parxtract`", "schema-v1", "`.parxtract`", "memory", "multi-source"):
        assert term in readme


def test_bilingual_manuals_and_powershell_modules_are_packaged() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    included = project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert included == {
        "powershell/ArcShuttle.psd1": "arcshuttle/powershell/ArcShuttle.psd1",
        "powershell/ArcShuttle.psm1": "arcshuttle/powershell/ArcShuttle.psm1",
        "powershell/Parxtract.psd1": "arcshuttle/powershell/Parxtract.psd1",
        "powershell/Parxtract.psm1": "arcshuttle/powershell/Parxtract.psm1",
        "docs/COMMAND_MANUAL.en.md": "arcshuttle/docs/COMMAND_MANUAL.en.md",
        "docs/COMMAND_MANUAL.ja.md": "arcshuttle/docs/COMMAND_MANUAL.ja.md",
        "docs/INSTALLATION.en.md": "arcshuttle/docs/INSTALLATION.en.md",
        "docs/INSTALLATION.ja.md": "arcshuttle/docs/INSTALLATION.ja.md",
    }
