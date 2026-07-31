"""Discovery and safe subprocess management for the 7-Zip CLI."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .inspect import Inspection, parse_technical_listing
from .util import UsageError, isoformat, utc_now


@dataclass(frozen=True, slots=True)
class InspectionResult:
    """Best-effort metadata plus a non-fatal inspection failure reason."""

    inspection: Inspection
    error: str | None = None
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    """The result of one 7-Zip extraction process."""

    exit_code: int | None
    interrupted: bool
    error: str | None = None


def find_executable(explicit: str | None) -> Path:
    """Find 7-Zip using explicit configuration, PATH, then Windows defaults."""

    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return candidate.resolve(strict=True)
        found = shutil.which(explicit)
        if found:
            return Path(found).resolve(strict=True)
        raise UsageError(f"7-Zip executable not found: {explicit}")
    for name in ("7zz", "7z", "7za"):
        found = shutil.which(name)
        if found:
            return Path(found).resolve(strict=True)
    if os.name == "nt":
        candidates: list[Path] = []
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            value = os.environ.get(env_name)
            if value:
                candidates.append(Path(value) / "7-Zip" / "7z.exe")
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve(strict=True)
    raise UsageError("7-Zip not found; use --7z or ARCSHUTTLE_7Z")


class SevenZip:
    """Run one configured 7-Zip executable without a command shell."""

    def __init__(self, executable: Path, *, command_prefix: Sequence[str] = ()) -> None:
        self.executable = executable
        self.command_prefix = tuple(command_prefix)
        self._active: set[subprocess.Popen[bytes]] = set()
        self._lock = threading.Lock()

    def _command(self, arguments: Sequence[str]) -> list[str]:
        return [str(self.executable), *self.command_prefix, *arguments]

    def version(self) -> str:
        """Return the first non-empty version banner line."""

        try:
            completed = subprocess.run(
                self._command([]),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"version unavailable ({exc})"
        text = completed.stdout.decode("utf-8", errors="replace")
        return next(
            (line.strip() for line in text.splitlines() if line.strip()), "version unavailable"
        )

    def inspect(self, archive: Path, timeout: float) -> InspectionResult:
        """Read a technical listing with closed stdin and bounded runtime."""

        arguments = ["l", "-slt", "-ba", "-sccUTF-8", "-p-", "--", str(archive)]
        try:
            completed = subprocess.run(
                self._command(arguments),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or b"").decode("utf-8", errors="replace")
            return InspectionResult(parse_technical_listing(output), "inspection timed out", True)
        except OSError as exc:
            return InspectionResult(Inspection(), f"inspection could not start: {exc}")
        output = completed.stdout.decode("utf-8", errors="replace")
        inspection = parse_technical_listing(output)
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            message = f"7-Zip inspection exited {completed.returncode}"
            if detail:
                message += f": {detail.splitlines()[-1]}"
            return InspectionResult(inspection, message)
        return InspectionResult(inspection)

    def extract(
        self,
        *,
        archive: Path,
        staging: Path,
        threads: int,
        log_directory: Path,
        cpu_tokens: int,
        stop_event: threading.Event,
    ) -> ProcessOutcome:
        """Extract one archive, streaming process output directly into log files."""

        arguments = [
            "x",
            "-y",
            "-bd",
            "-bb1",
            "-bso1",
            "-bse1",
            "-bsp0",
            f"-mmt={threads}",
            f"-o{staging}",
            "-p-",
            "--",
            str(archive),
        ]
        command = self._command(arguments)
        log_directory.mkdir(parents=True, exist_ok=True)
        started = utc_now()
        metadata_path = log_directory / "metadata.json"
        metadata: dict[str, object] = {
            "command": command,
            "started_at": isoformat(started),
            "cpu_tokens": cpu_tokens,
            "threads": threads,
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if stop_event.is_set():
            outcome = ProcessOutcome(None, True, "cancelled before process start")
            (log_directory / "stdout.log").touch()
            (log_directory / "stderr.log").touch()
            metadata.update(
                {
                    "finished_at": isoformat(utc_now()),
                    "exit_code": None,
                    "interrupted": True,
                    "error": outcome.error,
                }
            )
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            return outcome

        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            with (
                (log_directory / "stdout.log").open("wb") as stdout_log,
                (log_directory / "stderr.log").open("wb") as stderr_log,
            ):
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_log,
                    stderr=stderr_log,
                    shell=False,
                    start_new_session=(os.name != "nt"),
                    creationflags=creationflags,
                )
                with self._lock:
                    self._active.add(process)
                try:
                    exit_code = process.wait()
                finally:
                    with self._lock:
                        self._active.discard(process)
        except OSError as exc:
            outcome = ProcessOutcome(None, False, f"7-Zip could not start: {exc}")
        else:
            interrupted = stop_event.is_set()
            outcome = ProcessOutcome(exit_code, interrupted)

        metadata.update(
            {
                "finished_at": isoformat(utc_now()),
                "exit_code": outcome.exit_code,
                "interrupted": outcome.interrupted,
                "error": outcome.error,
            }
        )
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return outcome

    def interrupt_all(self, grace_seconds: float = 3.0) -> None:
        """Request graceful termination, then kill surviving child process groups."""

        with self._lock:
            processes = list(self._active)
        for process in processes:
            if process.poll() is not None:
                continue
            try:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
        deadline = time.monotonic() + grace_seconds
        while processes and time.monotonic() < deadline:
            processes = [process for process in processes if process.poll() is None]
            if processes:
                time.sleep(0.05)
        for process in processes:
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
