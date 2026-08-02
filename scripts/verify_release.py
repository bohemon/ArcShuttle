"""Build and verify ArcShuttle release artifacts in an isolated environment."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import os
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION = str(runpy.run_path(str(ROOT / "src" / "arcshuttle" / "__init__.py"))["__version__"])
WHEEL_NAME = f"arcshuttle-{VERSION}-py3-none-any.whl"
SDIST_NAME = f"arcshuttle-{VERSION}.tar.gz"
DIST_INFO = f"arcshuttle-{VERSION}.dist-info"
POWERSHELL_ASSET_NAME = f"ArcShuttle-PowerShell-{VERSION}.zip"
POWERSHELL_CHECKSUM_NAME = f"{POWERSHELL_ASSET_NAME}.sha256"

EXPECTED_CLASSIFIERS = {
    "Environment :: Console",
    "Operating System :: Microsoft :: Windows",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: System :: Archiving :: Compression",
}

EXPECTED_PROJECT_URLS = {
    "Documentation": "https://github.com/bohemon/ArcShuttle/blob/main/docs/COMMAND_MANUAL.en.md",
    "Issues": "https://github.com/bohemon/ArcShuttle/issues",
    "Release notes": "https://github.com/bohemon/ArcShuttle/releases",
    "Source": "https://github.com/bohemon/ArcShuttle",
}

REQUIRED_WHEEL_FILES = {
    "arcshuttle/__init__.py",
    "arcshuttle/__main__.py",
    "arcshuttle/cli.py",
    "arcshuttle/operations/create.py",
    "arcshuttle/operations/extract.py",
    "parxtract/__init__.py",
    "parxtract/__main__.py",
    "arcshuttle/powershell/ArcShuttle.psm1",
    "arcshuttle/powershell/ArcShuttle.psd1",
    "arcshuttle/powershell/Parxtract.psm1",
    "arcshuttle/powershell/Parxtract.psd1",
    "arcshuttle/docs/COMMAND_MANUAL.en.md",
    "arcshuttle/docs/COMMAND_MANUAL.ja.md",
    "arcshuttle/docs/INSTALLATION.en.md",
    "arcshuttle/docs/INSTALLATION.ja.md",
    f"{DIST_INFO}/METADATA",
    f"{DIST_INFO}/entry_points.txt",
    f"{DIST_INFO}/licenses/LICENSE",
}

REQUIRED_SDIST_FILES = {
    f"arcshuttle-{VERSION}/README.md",
    f"arcshuttle-{VERSION}/pyproject.toml",
    f"arcshuttle-{VERSION}/src/arcshuttle/__init__.py",
    f"arcshuttle-{VERSION}/src/parxtract/__init__.py",
    f"arcshuttle-{VERSION}/powershell/ArcShuttle.psm1",
    f"arcshuttle-{VERSION}/powershell/ArcShuttle.psd1",
    f"arcshuttle-{VERSION}/powershell/Parxtract.psm1",
    f"arcshuttle-{VERSION}/powershell/Parxtract.psd1",
    f"arcshuttle-{VERSION}/docs/COMMAND_MANUAL.en.md",
    f"arcshuttle-{VERSION}/docs/COMMAND_MANUAL.ja.md",
    f"arcshuttle-{VERSION}/docs/INSTALLATION.en.md",
    f"arcshuttle-{VERSION}/docs/INSTALLATION.ja.md",
    f"arcshuttle-{VERSION}/scripts/verify_release.py",
    f"arcshuttle-{VERSION}/scripts/build_powershell_assets.py",
}

REQUIRED_POWERSHELL_ASSET_FILES = {
    f"ArcShuttle/{VERSION}/ArcShuttle.psd1",
    f"ArcShuttle/{VERSION}/ArcShuttle.psm1",
    f"ArcShuttle/{VERSION}/LICENSE",
    f"Parxtract/{VERSION}/Parxtract.psd1",
    f"Parxtract/{VERSION}/Parxtract.psm1",
    f"Parxtract/{VERSION}/LICENSE",
}


class VerificationError(RuntimeError):
    """A release artifact does not satisfy the distribution contract."""


def checked_run(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    """Run a verification subprocess and include captured output on failure."""

    completed = subprocess.run(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        rendered = subprocess.list2cmdline(command)
        raise VerificationError(
            f"command failed ({completed.returncode}): {rendered}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def build_artifacts() -> None:
    """Build Python and PowerShell distribution artifacts."""

    hatch = shutil.which("hatch")
    if hatch is None:
        raise VerificationError("hatch is not installed or not available on PATH")
    completed = checked_run([hatch, "build"])
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip(), file=sys.stderr)
    completed = checked_run([sys.executable, str(ROOT / "scripts/build_powershell_assets.py")])
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip(), file=sys.stderr)


def require_files(actual: set[str], required: set[str], artifact: Path) -> None:
    """Require every expected normalized archive member."""

    missing = sorted(required - actual)
    if missing:
        raise VerificationError(f"{artifact.name} is missing: {', '.join(missing)}")


def inspect_wheel(wheel: Path) -> None:
    """Validate packages, entry points, and dependency-free wheel metadata."""

    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
        require_files(members, REQUIRED_WHEEL_FILES, wheel)
        shims = sorted(
            member
            for member in members
            if member.startswith("parxtract/") and member.endswith(".py")
        )
        if shims != ["parxtract/__init__.py", "parxtract/__main__.py"]:
            raise VerificationError(f"parxtract compatibility package is not minimal: {shims}")

        metadata = BytesParser().parsebytes(archive.read(f"{DIST_INFO}/METADATA"))
        if metadata["Name"] != "arcshuttle" or metadata["Version"] != VERSION:
            raise VerificationError(
                f"unexpected wheel identity: {metadata['Name']} {metadata['Version']}"
            )
        if metadata["Requires-Python"] != ">=3.11":
            raise VerificationError(f"unexpected Python requirement: {metadata['Requires-Python']}")
        if metadata["License-Expression"] != "MIT":
            raise VerificationError(
                f"unexpected license expression: {metadata['License-Expression']}"
            )
        if metadata.get_all("License-File", []) != ["LICENSE"]:
            raise VerificationError(
                f"unexpected license files: {metadata.get_all('License-File', [])}"
            )
        classifiers = set(metadata.get_all("Classifier", []))
        if classifiers != EXPECTED_CLASSIFIERS:
            raise VerificationError(f"unexpected classifiers: {sorted(classifiers)}")
        project_urls = {}
        for value in metadata.get_all("Project-URL", []):
            label, separator, url = value.partition(", ")
            if not separator:
                raise VerificationError(f"malformed project URL metadata: {value}")
            if label in project_urls:
                raise VerificationError(f"duplicate project URL label: {label}")
            project_urls[label] = url
        if project_urls != EXPECTED_PROJECT_URLS:
            raise VerificationError(f"unexpected project URLs: {project_urls}")
        runtime_dependencies = metadata.get_all("Requires-Dist", [])
        if runtime_dependencies:
            raise VerificationError(
                f"runtime dependencies must remain empty: {runtime_dependencies}"
            )

        entry_points = configparser.ConfigParser()
        entry_points.read_string(archive.read(f"{DIST_INFO}/entry_points.txt").decode("utf-8"))
        scripts = dict(entry_points["console_scripts"])
        expected = {
            "arcshuttle": "arcshuttle.cli:main",
            "parxtract": "arcshuttle.compat:parxtract_main",
        }
        if scripts != expected:
            raise VerificationError(f"unexpected console scripts: {scripts}")


def inspect_sdist(sdist: Path) -> None:
    """Validate the source distribution's release and compatibility assets."""

    with tarfile.open(sdist, "r:gz") as archive:
        members = {member.name.replace("\\", "/") for member in archive.getmembers()}
    require_files(members, REQUIRED_SDIST_FILES, sdist)


def normalized_text(path: Path) -> bytes:
    """Return source text in the normalized form stored in the PowerShell asset."""

    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def inspect_powershell_asset(asset: Path, checksum: Path) -> None:
    """Validate the versioned module layout, contents, and checksum."""

    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    expected_checksum = f"{digest}  {asset.name}\n"
    if checksum.read_text(encoding="ascii") != expected_checksum:
        raise VerificationError(f"unexpected PowerShell checksum file: {checksum}")

    with zipfile.ZipFile(asset) as archive:
        members = set(archive.namelist())
        if members != REQUIRED_POWERSHELL_ASSET_FILES:
            raise VerificationError(f"unexpected PowerShell asset members: {sorted(members)}")
        expected_sources = {
            f"ArcShuttle/{VERSION}/ArcShuttle.psd1": ROOT / "powershell/ArcShuttle.psd1",
            f"ArcShuttle/{VERSION}/ArcShuttle.psm1": ROOT / "powershell/ArcShuttle.psm1",
            f"Parxtract/{VERSION}/Parxtract.psd1": ROOT / "powershell/Parxtract.psd1",
            f"Parxtract/{VERSION}/Parxtract.psm1": ROOT / "powershell/Parxtract.psm1",
        }
        for member, source in expected_sources.items():
            if archive.read(member) != normalized_text(source):
                raise VerificationError(f"PowerShell asset content differs from source: {member}")
        license_content = normalized_text(ROOT / "LICENSE")
        for member in (
            f"ArcShuttle/{VERSION}/LICENSE",
            f"Parxtract/{VERSION}/LICENSE",
        ):
            if archive.read(member) != license_content:
                raise VerificationError(f"PowerShell asset license differs from source: {member}")


def installed_command(environment: Path, name: str) -> Path:
    """Return an installed console-script path for the current platform."""

    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    candidate = scripts / (f"{name}.exe" if os.name == "nt" else name)
    if not candidate.is_file():
        raise VerificationError(f"installed console script is missing: {candidate}")
    return candidate


def smoke_installed_wheel(wheel: Path) -> None:
    """Install the wheel without an index and exercise both console entry points."""

    with tempfile.TemporaryDirectory(prefix="arcshuttle-release-") as temporary:
        environment = Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        checked_run(
            [
                str(python),
                "-m",
                "pip",
                "--disable-pip-version-check",
                "install",
                "--no-index",
                "--no-deps",
                str(wheel),
            ]
        )
        arcshuttle = installed_command(environment, "arcshuttle")
        parxtract = installed_command(environment, "parxtract")
        smoke_commands = (
            ([str(arcshuttle), "--version"], f"arcshuttle {VERSION}"),
            ([str(arcshuttle), "plan", "create", "--help"], "plan create"),
            ([str(arcshuttle), "plan", "extract", "--help"], "plan extract"),
            ([str(arcshuttle), "run", "--help"], "--manifest"),
            ([str(parxtract), "--version"], f"parxtract {VERSION}"),
        )
        for command, expected in smoke_commands:
            completed = checked_run(command, cwd=environment)
            output = completed.stdout + completed.stderr
            if expected not in output:
                raise VerificationError(
                    f"expected {expected!r} from {subprocess.list2cmdline(command)}; got {output!r}"
                )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="verify existing dist artifacts instead of running hatch build",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.skip_build:
            build_artifacts()
        wheel = DIST / WHEEL_NAME
        sdist = DIST / SDIST_NAME
        powershell_asset = DIST / POWERSHELL_ASSET_NAME
        powershell_checksum = DIST / POWERSHELL_CHECKSUM_NAME
        for artifact in (wheel, sdist, powershell_asset, powershell_checksum):
            if not artifact.is_file():
                raise VerificationError(f"release artifact is missing: {artifact}")
        inspect_wheel(wheel)
        inspect_sdist(sdist)
        inspect_powershell_asset(powershell_asset, powershell_checksum)
        smoke_installed_wheel(wheel)
    except (OSError, VerificationError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 1
    print(
        "release verification passed: Python and PowerShell artifacts, dependency metadata, "
        "console scripts, and clean-wheel smoke tests"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
