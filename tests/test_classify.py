from __future__ import annotations

import pytest

from parxtract.classify import Classification, classify


def classify_archive(size: int, archive: dict[str, object], failed: bool = False) -> Classification:
    return classify(
        packed_size=size,
        small_threshold=100,
        archive=archive,
        cpu_budget=8,
        heavy_threads=4,
        inspection_failed=failed,
    )


def test_small() -> None:
    result = classify_archive(99, {})
    assert (result.profile, result.cpu_tokens, result.threads) == ("small", 1, 1)


@pytest.mark.parametrize(
    ("archive", "failed", "reason"),
    [
        ({"format": "zip"}, False, "conservative-fallback"),
        ({}, True, "inspection-failed"),
    ],
)
def test_heavy_serial(archive: dict[str, object], failed: bool, reason: str) -> None:
    result = classify_archive(100, archive, failed)
    assert result.profile == "heavy-serial"
    assert result.reason == reason


def test_bzip2_is_scalable() -> None:
    result = classify_archive(100, {"format": "zip", "methods": ["BZip2"]})
    assert (result.profile, result.reason, result.cpu_tokens) == (
        "heavy-scalable",
        "bzip2-method",
        4,
    )


def test_multiblock_7z_is_scalable() -> None:
    result = classify_archive(100, {"format": "7z", "blocks": 2})
    assert result.reason == "multi-block-7z"
