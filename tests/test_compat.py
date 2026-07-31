from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from arcshuttle.cli import build_parser


@pytest.mark.parametrize(
    ("module", "expected"),
    [("arcshuttle", "arcshuttle 0.2.0"), ("parxtract", "parxtract 0.2.0")],
)
def test_python_module_entry_points(module: str, expected: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", module, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == expected
    assert completed.stderr == ""


def test_legacy_parser_keeps_extraction_commands() -> None:
    parser = build_parser(program_name="parxtract", legacy=True)
    help_text = parser.format_help()

    assert parser.prog == "parxtract"
    assert "{plan,run,extract}" in help_text


def test_primary_parser_requires_a_plan_operation() -> None:
    args = build_parser().parse_args(["plan", "extract", "archive.zip"])

    assert args.command == "plan"
    assert args.plan_operation == "extract"


def test_legacy_package_contains_no_implementation_modules() -> None:
    assert importlib.util.find_spec("parxtract.cli") is None
