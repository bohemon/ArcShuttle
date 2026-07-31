from __future__ import annotations

import io
from pathlib import Path

from parxtract.input import normalize_paths, read_line_paths, read_nul_paths


def test_newline_input_and_unicode() -> None:
    assert read_line_paths(io.StringIO("one.zip\r\n日本語.7z\n\n")) == ["one.zip", "日本語.7z"]


def test_nul_input() -> None:
    assert read_nul_paths(io.BytesIO("a.zip\0空 白.7z\0".encode())) == ["a.zip", "空 白.7z"]


def test_relative_paths_and_duplicates(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    archive.write_bytes(b"x")

    paths, errors = normalize_paths(["a.zip", str(archive)], tmp_path)

    assert paths == [archive.resolve()]
    assert errors == []


def test_missing_and_directory_are_errors(tmp_path: Path) -> None:
    paths, errors = normalize_paths(["missing.zip", "."], tmp_path)

    assert paths == []
    assert len(errors) == 2
