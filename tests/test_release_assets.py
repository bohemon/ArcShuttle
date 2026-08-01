from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
BUILDER = ROOT / "scripts" / "build_powershell_assets.py"
VERSION = "0.2.0"
ASSET_NAME = f"ArcShuttle-PowerShell-{VERSION}.zip"
CHECKSUM_NAME = f"{ASSET_NAME}.sha256"
EXPECTED_MEMBERS = {
    f"ArcShuttle/{VERSION}/ArcShuttle.psd1",
    f"ArcShuttle/{VERSION}/ArcShuttle.psm1",
    f"ArcShuttle/{VERSION}/LICENSE",
    f"Parxtract/{VERSION}/Parxtract.psd1",
    f"Parxtract/{VERSION}/Parxtract.psm1",
    f"Parxtract/{VERSION}/LICENSE",
}


def build_assets(output_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BUILDER), "--output-dir", str(output_dir)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def normalized_text(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def test_powershell_release_asset_is_deterministic_and_self_verifying(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    for output_dir in (first, second):
        completed = build_assets(output_dir)
        assert completed.returncode == 0, completed.stderr

    first_asset = first / ASSET_NAME
    second_asset = second / ASSET_NAME
    assert first_asset.read_bytes() == second_asset.read_bytes()

    digest = hashlib.sha256(first_asset.read_bytes()).hexdigest()
    assert (first / CHECKSUM_NAME).read_text(encoding="ascii") == (f"{digest}  {ASSET_NAME}\n")

    with zipfile.ZipFile(first_asset) as archive:
        assert set(archive.namelist()) == EXPECTED_MEMBERS
        assert archive.read(f"ArcShuttle/{VERSION}/ArcShuttle.psd1") == normalized_text(
            ROOT / "powershell" / "ArcShuttle.psd1"
        )
        assert archive.read(f"ArcShuttle/{VERSION}/ArcShuttle.psm1") == normalized_text(
            ROOT / "powershell" / "ArcShuttle.psm1"
        )
        assert archive.read(f"Parxtract/{VERSION}/Parxtract.psd1") == normalized_text(
            ROOT / "powershell" / "Parxtract.psd1"
        )
        assert archive.read(f"Parxtract/{VERSION}/Parxtract.psm1") == normalized_text(
            ROOT / "powershell" / "Parxtract.psm1"
        )
        assert archive.read(f"ArcShuttle/{VERSION}/LICENSE") == normalized_text(ROOT / "LICENSE")
        assert archive.read(f"Parxtract/{VERSION}/LICENSE") == normalized_text(ROOT / "LICENSE")
