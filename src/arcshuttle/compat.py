"""Compatibility entry points for the historical :mod:`parxtract` interface."""

from __future__ import annotations

from collections.abc import Sequence

from .cli import main


def parxtract_main(argv: Sequence[str] | None = None) -> int:
    """Run the legacy extraction-only command surface."""

    return main(argv, program_name="parxtract", legacy=True)
