from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

import pytest

from arcshuttle import config
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


@pytest.mark.parametrize("guide", INSTALLATION_GUIDES, ids=("en", "ja"))
def test_installation_guides_cover_clone_free_and_verified_installation(guide: Path) -> None:
    text = guide.read_text(encoding="utf-8")
    required_terms = (
        "pipx install",
        "python -m pip install",
        "--upgrade",
        "python -m pip uninstall arcshuttle",
        "arcshuttle-0.2.0-py3-none-any.whl",
        "git+https://github.com/bohemon/ArcShuttle.git@v0.2.0",
        "ArcShuttle-PowerShell-$version.zip",
        '$checksumFile = "$archive.sha256"',
        "Get-FileHash",
        "Expand-Archive",
        "Test-ModuleManifest",
        "Import-Module ArcShuttle",
        "Import-Module Parxtract",
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
        "multi-source manifest",
        "Invoke-ArcShuttleCreatePlan",
        "Invoke-ParxtractPlan",
        "stdout",
        "stderr",
        "CPU token",
    )
    missing = [term for term in required_terms if term not in text]
    assert missing == []


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
