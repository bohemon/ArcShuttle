from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from parxtract import config
from parxtract.cli import build_parser

ROOT = Path(__file__).parents[1]
MANUALS = (
    ROOT / "docs" / "COMMAND_MANUAL.en.md",
    ROOT / "docs" / "COMMAND_MANUAL.ja.md",
)


@pytest.mark.parametrize("manual", MANUALS, ids=("en", "ja"))
def test_command_manual_covers_every_cli_command_and_option(manual: Path) -> None:
    text = manual.read_text(encoding="utf-8")
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    missing: list[str] = []

    for option in (option for action in parser._actions for option in action.option_strings):
        if f"`{option}`" not in text:
            missing.append(option)
    for command, command_parser in subparsers.choices.items():
        if f"`{command}`" not in text:
            missing.append(command)
        for option in (
            option for action in command_parser._actions for option in action.option_strings
        ):
            if f"`{option}`" not in text:
                missing.append(option)

    assert missing == []


@pytest.mark.parametrize("manual", MANUALS, ids=("en", "ja"))
def test_command_manual_covers_every_environment_variable(manual: Path) -> None:
    text = manual.read_text(encoding="utf-8")

    for variable in config._ENV_NAMES.values():
        assert f"`{variable}`" in text


def test_readme_links_to_packaged_manuals() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for manual in MANUALS:
        relative_path = manual.relative_to(ROOT).as_posix()
        assert relative_path in readme
        assert manual.is_file()
