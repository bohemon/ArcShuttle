from __future__ import annotations

from pathlib import Path

import pytest

from arcshuttle.output import (
    create_staging,
    default_output_path,
    finalize,
    resolve_existing,
    retain_failed,
)


def test_default_output_for_compound_name() -> None:
    archive = Path("/tmp/example.tar.gz")
    assert default_output_path(archive, Path("/out")) == Path("/out/example").resolve(strict=False)


def test_existing_policies(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()

    with pytest.raises(FileExistsError):
        resolve_existing(output, "fail")
    assert resolve_existing(output, "skip") == (output, True)
    renamed, skipped = resolve_existing(output, "rename")
    assert renamed.name == "out (2)"
    assert skipped is False


def test_successful_finalization_removes_marker(tmp_path: Path) -> None:
    final = tmp_path / "out"
    staging = create_staging(final, "abcdef")
    (staging / "file.txt").write_text("ok")

    finalize(staging, final)

    assert (final / "file.txt").is_file()
    assert not (final / ".arcshuttle-owned").exists()


def test_failed_staging_is_retained(tmp_path: Path) -> None:
    final = tmp_path / "out"
    staging = create_staging(final, "abcdef")

    retained = retain_failed(staging)

    assert retained.is_dir()
    assert retained.name.endswith(".failed")


def test_legacy_staging_is_never_claimed_or_renamed(tmp_path: Path) -> None:
    staging = tmp_path / ".parxtract-existing.failed"
    staging.mkdir()
    (staging / ".parxtract-owned").write_text("legacy\n", encoding="utf-8")

    with pytest.raises(OSError, match="unowned"):
        retain_failed(staging)

    assert staging.is_dir()
    assert (staging / ".parxtract-owned").is_file()
