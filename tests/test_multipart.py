from __future__ import annotations

from pathlib import Path

import pytest

from arcshuttle.multipart import archive_stem, canonicalize, identify


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.7z", "a"),
        ("b.tar.gz", "b"),
        ("c.7z.001", "c"),
        ("d.part01.rar", "d"),
        ("e.tar.bz2", "e"),
        ("f.zip.001", "f"),
        (".zip", "archive"),
    ],
)
def test_output_stems(name: str, expected: str) -> None:
    assert archive_stem(Path(name)) == expected


def test_numbered_7z_collapses_to_first(tmp_path: Path) -> None:
    first = tmp_path / "data.7z.001"
    second = tmp_path / "data.7z.002"
    first.write_bytes(b"1")
    second.write_bytes(b"2")

    infos, errors = canonicalize([second, first])

    assert not errors
    assert [info.first_volume for info in infos] == [first.resolve()]


@pytest.mark.parametrize(
    ("name", "first"),
    [
        ("x.part02.rar", "x.part01.rar"),
        ("x.part2.rar", "x.part1.rar"),
        ("x.r04", "x.rar"),
        ("x.z02", "x.zip"),
    ],
)
def test_later_volume_maps_to_first(name: str, first: str) -> None:
    assert identify(Path(name)).first_volume == Path(first)


def test_non_first_without_first_is_error(tmp_path: Path) -> None:
    second = tmp_path / "x.z02"
    second.write_bytes(b"x")

    infos, errors = canonicalize([second])

    assert infos == []
    assert "first volume not found" in errors[0]
