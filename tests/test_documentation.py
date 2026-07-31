from __future__ import annotations

import argparse
from pathlib import Path

from parxtract import config
from parxtract.cli import build_parser

ROOT = Path(__file__).parents[1]
MANUAL = ROOT / "docs" / "COMMAND_MANUAL.ja.md"


def test_command_manual_covers_every_cli_command_and_option() -> None:
    text = MANUAL.read_text(encoding="utf-8")
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


def test_command_manual_covers_every_environment_variable() -> None:
    text = MANUAL.read_text(encoding="utf-8")

    for variable in config._ENV_NAMES.values():
        assert f"`{variable}`" in text


def test_readme_links_to_packaged_manual() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/COMMAND_MANUAL.ja.md" in readme
    assert MANUAL.is_file()
