"""Build and verify ArcShuttle release artifacts in an isolated environment."""

from __future__ import annotations

import argparse
import configparser
import os
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
VERSION = "0.2.0"
WHEEL_NAME = f"arcshuttle-{VERSION}-py3-none-any.whl"
SDIST_NAME = f"arcshuttle-{VERSION}.tar.gz"
DIST_INFO = f"arcshuttle-{VERSION}.dist-info"

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
    "arcshuttle/powershell/Parxtract.psm1",
    "arcshuttle/docs/COMMAND_MANUAL.en.md",
    "arcshuttle/docs/COMMAND_MANUAL.ja.md",
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
    f"arcshuttle-{VERSION}/powershell/Parxtract.psm1",
    f"arcshuttle-{VERSION}/docs/COMMAND_MANUAL.en.md",
    f"arcshuttle-{VERSION}/docs/COMMAND_MANUAL.ja.md",
    f"arcshuttle-{VERSION}/scripts/verify_release.py",
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
    """Build the wheel and source distribution through Hatch."""

    hatch = shutil.which("hatch")
    if hatch is None:
        raise VerificationError("hatch is not installed or not available on PATH")
    completed = checked_run([hatch, "build"])
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
            ([str(arcshuttle), "--version"], "arcshuttle 0.2.0"),
            ([str(arcshuttle), "plan", "create", "--help"], "plan create"),
            ([str(arcshuttle), "plan", "extract", "--help"], "plan extract"),
            ([str(arcshuttle), "run", "--help"], "--manifest"),
            ([str(parxtract), "--version"], "parxtract 0.2.0"),
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
        for artifact in (wheel, sdist):
            if not artifact.is_file():
                raise VerificationError(f"release artifact is missing: {artifact}")
        inspect_wheel(wheel)
        inspect_sdist(sdist)
        smoke_installed_wheel(wheel)
    except (OSError, VerificationError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 1
    print(
        "release verification passed: artifacts, dependency metadata, console scripts, "
        "and clean-wheel smoke tests"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
