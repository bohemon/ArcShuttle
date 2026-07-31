from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from arcshuttle.config import Config
from arcshuttle.manifest import validate_manifest
from arcshuttle.operations.create import (
    inventory_source,
    make_create_plan,
    normalize_create_paths,
)


def test_file_and_empty_directory_inventory(tmp_path: Path) -> None:
    source_file = tmp_path / "空 白.dat"
    source_file.write_bytes(b"payload")
    empty = tmp_path / "empty"
    empty.mkdir()

    file_inventory = inventory_source(source_file)
    empty_inventory = inventory_source(empty)

    assert (file_inventory.kind, file_inventory.size, file_inventory.file_count) == (
        "file",
        7,
        1,
    )
    assert file_inventory.entry_count == 1
    assert (empty_inventory.kind, empty_inventory.size, empty_inventory.entry_count) == (
        "directory",
        0,
        0,
    )
    assert empty_inventory.identity.startswith("sha256:")


def test_nested_inventory_counts_empty_directories_and_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "nested" / "empty").mkdir(parents=True)
    (source / "nested" / "b.txt").write_bytes(b"bb")
    (source / "a.txt").write_bytes(b"a")

    first = inventory_source(source)
    second = inventory_source(source)

    assert first.size == 3
    assert first.file_count == 2
    assert first.directory_count == 2
    assert first.entry_count == 4
    assert first.digest == second.digest
    assert first.identity == second.identity
    assert [entry.relative_path for entry in first.entries] == [
        "a.txt",
        "nested",
        "nested/b.txt",
        "nested/empty",
    ]


def test_inventory_identity_changes_with_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    child = source / "data.bin"
    child.write_bytes(b"one")
    before = inventory_source(source)

    child.write_bytes(b"longer")
    after = inventory_source(source)

    assert before.identity != after.identity
    assert before.digest != after.digest


def test_normalize_create_paths_accepts_files_and_directories(tmp_path: Path) -> None:
    source_file = tmp_path / "file"
    source_file.write_bytes(b"x")
    source_directory = tmp_path / "dir"
    source_directory.mkdir()

    paths, errors = normalize_create_paths(
        [source_file.name, source_directory.name, source_file.name], tmp_path
    )

    assert paths == [source_file, source_directory]
    assert errors == []


def test_symlink_is_rejected_without_following(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks is unavailable")

    paths, errors = normalize_create_paths([str(link)])

    assert paths == []
    assert "links" in errors[0]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are not supported")
def test_non_regular_entry_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    fifo = source / "pipe"
    os.mkfifo(fifo)

    result = make_create_plan([source], Config())

    assert result.jobs == []
    assert "non-regular" in result.errors[0]


def test_create_plan_builds_one_valid_job_per_source(tmp_path: Path) -> None:
    first = tmp_path / "first"
    first.mkdir()
    (first / "data").write_bytes(b"123")
    second = tmp_path / "second.dat"
    second.write_bytes(b"4567")
    config = replace(Config(), small_threshold=0, cpu_budget=6, heavy_threads=3)

    result = make_create_plan([first, second], config)
    jobs = validate_manifest(result.jobs, config)

    assert result.errors == []
    assert [job["operation"] for job in jobs] == ["create", "create"]
    assert [job["destination"]["path"] for job in jobs] == [
        str(tmp_path / "first.7z"),
        str(tmp_path / "second.dat.7z"),
    ]
    assert jobs[0]["archive"] == {
        "format": "7z",
        "method": "LZMA2",
        "compression_level": 5,
    }
    assert jobs[0]["scheduling"]["classification_reason"] == "create-7z-lzma2"
    assert jobs[0]["scheduling"]["cpu_tokens"] == 3


@pytest.mark.parametrize(
    ("size", "level", "archive_format", "profile", "reason", "threads"),
    [
        (3, 9, "7z", "small", "create-below-small-threshold", 1),
        (20, 0, "7z", "heavy-serial", "create-store-mode", 1),
        (20, 5, "zip", "heavy-scalable", "create-zip-deflate", 2),
    ],
)
def test_create_scheduling(
    tmp_path: Path,
    size: int,
    level: int,
    archive_format: str,
    profile: str,
    reason: str,
    threads: int,
) -> None:
    source = tmp_path / f"source-{level}-{archive_format}"
    source.write_bytes(b"x" * size)
    config = replace(
        Config(),
        small_threshold=10,
        compression_level=level,
        create_format=archive_format,
        cpu_budget=2,
        heavy_threads=4,
    )

    job = make_create_plan([source], config).jobs[0]

    assert job["scheduling"]["profile"] == profile
    assert job["scheduling"]["classification_reason"] == reason
    assert job["scheduling"]["threads"] == threads
    assert job["archive"]["method"] == ("LZMA2" if archive_format == "7z" else "Deflate")


def test_output_collision_is_an_input_error(tmp_path: Path) -> None:
    left = tmp_path / "left" / "same"
    right = tmp_path / "right" / "same"
    left.parent.mkdir()
    right.parent.mkdir()
    left.write_bytes(b"left")
    right.write_bytes(b"right")

    result = make_create_plan([left, right], replace(Config(), output_dir=tmp_path / "out"))

    assert len(result.jobs) == 2
    assert "output collision" in result.errors[0]


@pytest.mark.parametrize("unsafe_kind", ["output", "log"])
def test_directory_source_rejects_internal_output_or_log(tmp_path: Path, unsafe_kind: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    changes = (
        {"output_dir": source / "out"} if unsafe_kind == "output" else {"log_dir": source / "logs"}
    )

    result = make_create_plan([source], replace(Config(), **changes))

    assert result.jobs == []
    assert "inside the source directory" in result.errors[0]
