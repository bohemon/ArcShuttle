"""Build deterministic PowerShell module Release assets."""

from __future__ import annotations

import argparse
import hashlib
import runpy
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION = str(runpy.run_path(str(ROOT / "src" / "arcshuttle" / "__init__.py"))["__version__"])
ASSET_NAME = f"ArcShuttle-PowerShell-{VERSION}.zip"
CHECKSUM_NAME = f"{ASSET_NAME}.sha256"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

MODULES = {
    "ArcShuttle": ("ArcShuttle.psd1", "ArcShuttle.psm1"),
    "Parxtract": ("Parxtract.psd1", "Parxtract.psm1"),
}


def normalized_text(path: Path) -> bytes:
    """Return UTF-8 text with stable LF line endings."""

    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def archive_entries() -> dict[str, bytes]:
    """Return the exact versioned module layout for the Release zip."""

    entries: dict[str, bytes] = {}
    license_content = normalized_text(ROOT / "LICENSE")
    for module, files in MODULES.items():
        prefix = f"{module}/{VERSION}"
        for filename in files:
            entries[f"{prefix}/{filename}"] = normalized_text(ROOT / "powershell" / filename)
        entries[f"{prefix}/LICENSE"] = license_content
    return entries


def write_entry(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    """Write one cross-platform deterministic zip member."""

    info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content)


def build_assets(output_dir: Path) -> tuple[Path, Path]:
    """Build the module archive and its SHA-256 checksum file."""

    output_dir.mkdir(parents=True, exist_ok=True)
    asset = output_dir / ASSET_NAME
    checksum = output_dir / CHECKSUM_NAME
    with zipfile.ZipFile(asset, "w") as archive:
        for name, content in sorted(archive_entries().items()):
            write_entry(archive, name, content)
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {asset.name}\n", encoding="ascii", newline="\n")
    return asset, checksum


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DIST,
        help="directory for the zip and checksum (default: repository dist directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    asset, checksum = build_assets(args.output_dir.resolve())
    print(asset)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
