from __future__ import annotations

from pathlib import Path

import pytest

from parxtract.config import resolve_config
from parxtract.util import parse_size


@pytest.mark.parametrize(
    ("value", "expected"),
    [("64M", 64 * 1024 * 1024), ("1GiB", 1024**3), (7, 7)],
)
def test_size_parser(value: str | int, expected: int) -> None:
    assert parse_size(value) == expected


def test_cli_environment_toml_precedence(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[parxtract]\nmax_processes = 2\nsmall_threshold = '10M'\nsevenzip = 'from-file'\n",
        encoding="utf-8",
    )

    config = resolve_config(
        {"max_processes": 4, "sevenzip": None},
        config_path=config_path,
        environ={"PARXTRACT_7Z": "from-env", "PARXTRACT_SMALL_THRESHOLD": "20M"},
    )

    assert config.max_processes == 4
    assert config.sevenzip == "from-env"
    assert config.small_threshold == 20 * 1024 * 1024


def test_storage_profile_default_slots() -> None:
    config = resolve_config({"storage_profile": "nvme", "max_processes": 8}, environ={})
    assert config.io_slots == 4

    override = resolve_config({"storage_profile": "hdd", "io_slots": 3}, environ={})
    assert override.io_slots == 3


def test_cpu_budget_updates_dependent_defaults() -> None:
    config = resolve_config({"cpu_budget": 1}, environ={})
    assert config.max_processes == 1
    assert config.heavy_threads == 1
    assert config.io_slots == 1
