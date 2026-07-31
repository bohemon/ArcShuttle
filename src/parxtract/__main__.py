"""Compatibility entry point for ``python -m parxtract``."""

from __future__ import annotations

from arcshuttle.compat import parxtract_main

if __name__ == "__main__":
    raise SystemExit(parxtract_main())
