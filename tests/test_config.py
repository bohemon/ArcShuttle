from __future__ import annotations

from pathlib import Path

import pytest

from arcshuttle.config import resolve_config
from arcshuttle.util import UsageError, parse_size


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


def test_new_names_override_legacy_configuration(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "small_threshold = '1M'\n"
        "[parxtract]\nsmall_threshold = '2M'\nsevenzip = 'legacy-file'\n"
        "[arcshuttle]\nsmall_threshold = '3M'\nsevenzip = 'new-file'\n",
        encoding="utf-8",
    )

    config = resolve_config(
        {"small_threshold": "6M"},
        config_path=config_path,
        environ={
            "PARXTRACT_SMALL_THRESHOLD": "4M",
            "ARCSHUTTLE_SMALL_THRESHOLD": "5M",
            "PARXTRACT_7Z": "legacy-env",
            "ARCSHUTTLE_7Z": "new-env",
        },
    )

    assert config.small_threshold == 6 * 1024 * 1024
    assert config.sevenzip == "new-env"


def test_legacy_root_toml_and_environment_remain_supported(tmp_path: Path) -> None:
    config_path = tmp_path / "legacy.toml"
    config_path.write_text("small_threshold = '7M'\n", encoding="utf-8")

    config = resolve_config(
        {},
        config_path=config_path,
        environ={"PARXTRACT_7Z": "legacy-env"},
    )

    assert config.small_threshold == 7 * 1024 * 1024
    assert config.sevenzip == "legacy-env"


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


def test_create_configuration_uses_only_new_names(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[arcshuttle]\ncreate_format = 'zip'\ncompression_level = 8\n",
        encoding="utf-8",
    )

    config = resolve_config(
        {"compression_level": 2},
        config_path=config_path,
        environ={
            "PARXTRACT_CREATE_FORMAT": "ignored",
            "ARCSHUTTLE_CREATE_FORMAT": "7z",
        },
    )

    assert config.create_format == "7z"
    assert config.compression_level == 2


@pytest.mark.parametrize("level", [-1, 10, "high"])
def test_compression_level_range_is_validated(level: object) -> None:
    with pytest.raises(UsageError, match="compression_level"):
        resolve_config({"compression_level": level}, environ={})


def test_legacy_toml_cannot_set_create_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[parxtract]\ncreate_format = 'zip'\n", encoding="utf-8")

    with pytest.raises(UsageError, match="unknown config option"):
        resolve_config({}, config_path=config_path, environ={})
