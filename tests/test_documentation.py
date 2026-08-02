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


def _markdown_prose(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?ms)\A---\n.*?^---\n", "", text)
    text = re.sub(r"(?ms)^```.*?^```\s*", "", text)
    text = re.sub(r"`[^`\n]*`", "", text)
    return re.sub(r"\]\([^\n)]*\)", "]", text)


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
        "destination.path",
        "verification_exit_code",
        "create.stdout.log",
        ".arcshuttle-owned",
        ".parxtract",
        "Invoke-ArcShuttleCreatePlan",
        "Invoke-ParxtractPlan",
        "stdout",
        "stderr",
    )
    required_terms += (
        ("schema v2", "schema v1", "multi-source", "CPU token")
        if manual.name.endswith(".en.md")
        else ("スキーマv2", "スキーマv1", "複数の*source*", "*CPU token*")
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
        "Invoke-ArcShuttleExtractPlan >",
        "arcshuttle plan extract --",
        "ConvertFrom-Json",
        "Export-Clixml",
        "Import-Clixml",
        "CLIXML",
        "`job_id`",
        "`plan_index`",
        "`integrity`",
        "Invoke-ParxtractRun",
    )
    required_terms += (
        ("display formatting", "output collision")
        if manual.name.endswith(".en.md")
        else ("表示形式", "*destination*の衝突")
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
    )
    required_terms += (
        ("object pipeline",) if manual.name.endswith(".en.md") else ("オブジェクトパイプライン",)
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
        "max_processes",
        "--quiet",
        "--io-slots",
        "`plan`",
    )
    required_terms += (
        ("unknown = 2", "source", "destination", "stderr")
        if manual.name.endswith(".en.md")
        else ("不明 = 2", "*source*", "*destination*", "標準エラー出力")
    )

    assert [term for term in required_terms if term not in text] == []


@pytest.mark.parametrize(
    "document",
    (ROOT / "docs" / "COMMAND_MANUAL.ja.md", ROOT / "docs" / "INSTALLATION.ja.md"),
    ids=("command", "installation"),
)
def test_japanese_manual_prose_does_not_use_unformatted_english_terms(
    document: Path,
) -> None:
    prose = _markdown_prose(document)
    bare_general_terms = (
        "archive",
        "boolean",
        "checkout",
        "command",
        "contract",
        "create",
        "default",
        "directory",
        "download",
        "end-user",
        "environment",
        "error",
        "extract",
        "field",
        "file",
        "filter",
        "global",
        "help",
        "input",
        "install",
        "key",
        "log",
        "metadata",
        "module",
        "namespace",
        "object",
        "option",
        "output",
        "parser",
        "path",
        "process",
        "queue",
        "record",
        "release",
        "root",
        "run",
        "schema",
        "session",
        "stderr",
        "stdout",
        "stream",
        "tagged",
        "text",
        "thread",
        "version",
        "virtual",
        "warning",
    )
    found = [
        term
        for term in bare_general_terms
        if re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(term)}(?![A-Za-z0-9_-])",
            prose,
            flags=re.IGNORECASE,
        )
    ]

    assert found == []


def test_japanese_command_manual_marks_arcshuttle_concepts_as_italics() -> None:
    manual = ROOT / "docs" / "COMMAND_MANUAL.ja.md"
    text = manual.read_text(encoding="utf-8")
    concepts = (
        "operation",
        "plan",
        "source",
        "destination",
        "inventory",
        "job",
        "manifest",
        "profile",
        "schedule",
        "scheduler",
        "staging",
        "result",
        "summary",
        "allowlist",
        "CPU token",
        "I/O token",
        "I/O slot",
    )

    assert [concept for concept in concepts if f"*{concept}*" not in text] == []

    prose = _markdown_prose(manual)
    prose_without_italics = re.sub(r"(?<!\*)\*[^*\n]+\*(?!\*)", "", prose)
    unmarked = [
        concept
        for concept in concepts
        if re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(concept)}(?![A-Za-z0-9_-])",
            prose_without_italics,
            flags=re.IGNORECASE,
        )
    ]
    assert unmarked == []


def test_japanese_command_manual_uses_literal_operation_names_for_sections() -> None:
    text = (ROOT / "docs" / "COMMAND_MANUAL.ja.md").read_text(encoding="utf-8")
    required_terms = (
        "### 10.1 `extract`",
        "### 10.2 `create`",
        "`extract`のログ",
        "`create`のログ",
        "`extract`で引き続き利用",
        "`create`の設定",
    )

    assert [term for term in required_terms if term not in text] == []


def test_readme_covers_stable_project_entrypoint_contracts() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "ArcShuttle is a resource-aware command-line tool for creating, extracting, "
        "and verifying multiple archives through the 7-Zip CLI."
    ) in readme
    for term in (
        "Windows",
        "Linux",
        "Python 3.11",
        "`arcshuttle` is the primary CLI",
        "`parxtract`",
        "schema-v1",
        "UTF-8 JSON Lines",
        "never modifies or deletes a source",
    ):
        assert term in readme


def test_readme_quick_start_is_shell_neutral() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    quick_start = readme.split("## Quick start", maxsplit=1)[1].split(
        "## Safety and output", maxsplit=1
    )[0]

    assert "arcshuttle create" in quick_start
    assert "arcshuttle extract" in quick_start
    for posix_only_term in ("cat ", "find ", "/data/"):
        assert posix_only_term not in quick_start


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
