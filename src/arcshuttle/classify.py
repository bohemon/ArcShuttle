"""Conservative archive classification heuristics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Classification:
    """Scheduling fields derived from archive metadata."""

    profile: str
    reason: str
    cpu_tokens: int
    threads: int
    io_tokens: int = 1


def classify(
    *,
    packed_size: int,
    small_threshold: int,
    archive: dict[str, Any],
    cpu_budget: int,
    heavy_threads: int,
    inspection_failed: bool = False,
) -> Classification:
    """Classify an archive without making unsupported performance promises."""

    if packed_size < small_threshold:
        return Classification("small", "below-small-threshold", 1, 1)
    if inspection_failed:
        return Classification("heavy-serial", "inspection-failed", 1, 1)
    methods = {str(method).lower() for method in archive.get("methods") or []}
    if any("bzip2" in method for method in methods):
        tokens = min(heavy_threads, cpu_budget)
        return Classification("heavy-scalable", "bzip2-method", tokens, tokens)
    blocks = archive.get("blocks")
    if str(archive.get("format", "")).lower() == "7z" and isinstance(blocks, int) and blocks > 1:
        tokens = min(heavy_threads, cpu_budget)
        return Classification("heavy-scalable", "multi-block-7z", tokens, tokens)
    return Classification("heavy-serial", "conservative-fallback", 1, 1)
