"""ArcShuttle and compatibility command-line parsing and JSON Lines orchestration."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from .config import Config, resolve_config
from .input import collect_paths, normalize_paths
from .manifest import validate_manifest
from .multipart import canonicalize
from .operations.extract import (
    PlanningResult,
    make_extract_plan,
    make_legacy_plan,
)
from .runner import execute_manifest
from .sevenzip import SevenZip, find_executable
from .util import UsageError, emit_jsonl, read_json_lines


class Parser(argparse.ArgumentParser):
    """Argument parser that maps usage failures to ArcShuttle exit code 64."""

    def error(self, message: str) -> None:
        raise UsageError(message)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--7z", dest="sevenzip", metavar="PATH", default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--existing", choices=("fail", "skip", "rename"), default=None)
    parser.add_argument("--cpu-budget", default=None, metavar="N|auto")
    parser.add_argument("--max-processes", type=int, default=None)
    parser.add_argument("--storage-profile", choices=("auto", "hdd", "ssd", "nvme"), default=None)
    parser.add_argument("--io-slots", type=int, default=None)
    parser.add_argument("--heavy-threads", type=int, default=None)
    parser.add_argument("--small-threshold", default=None, metavar="SIZE")
    parser.add_argument("--inspect-threshold", default=None, metavar="SIZE")
    parser.add_argument("--inspect-timeout", type=float, default=None, metavar="SECONDS")
    parser.add_argument("--reservation-delay", type=float, default=None, metavar="SECONDS")
    parser.add_argument("--sequential-if-total-below", default=None, metavar="SIZE")
    parser.add_argument("--log-dir", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true", default=None)
    parser.add_argument("--fail-fast", action="store_true", default=None)
    parser.add_argument("--allow-changed", action="store_true", default=None)
    parser.add_argument("--on-input-error", choices=("fail", "skip"), default=None)


def _add_input(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("paths", nargs="*", metavar="PATH")
    parser.add_argument("--files-from", metavar="FILE")
    parser.add_argument("--files0-from", metavar="FILE")


def build_parser(
    *, program_name: str = "arcshuttle", legacy: bool = False
) -> argparse.ArgumentParser:
    """Build the primary or legacy public CLI parser."""

    parser = Parser(
        prog=program_name,
        description="Resource-aware archive creation and extraction backed by 7-Zip",
    )
    parser.add_argument("--version", action="version", version=f"{program_name} 0.2.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="inspect inputs and emit a JSON Lines manifest")
    if legacy:
        _add_common(plan)
        _add_input(plan)
    else:
        plan_operations = plan.add_subparsers(dest="plan_operation", required=True)
        plan_extract = plan_operations.add_parser("extract", help="plan archive extraction")
        _add_common(plan_extract)
        _add_input(plan_extract)

    run = subparsers.add_parser("run", help="execute a complete JSON Lines manifest")
    _add_common(run)
    run.add_argument("--manifest", required=True, metavar="FILE")

    extract = subparsers.add_parser("extract", help="plan and run extraction in one invocation")
    _add_common(extract)
    _add_input(extract)
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    ignored = {
        "command",
        "plan_operation",
        "paths",
        "files_from",
        "files0_from",
        "manifest",
        "config",
    }
    values = {key: value for key, value in vars(args).items() if key not in ignored}
    return resolve_config(values, config_path=args.config)


def _open_manifest(path: str) -> tuple[TextIO, bool]:
    if path == "-":
        return sys.stdin, False
    try:
        return Path(path).open("r", encoding="utf-8"), True
    except OSError as exc:
        raise UsageError(f"cannot read manifest {path}: {exc}") from exc


def _show_sevenzip(sevenzip: SevenZip, quiet: bool, program_name: str) -> None:
    if not quiet:
        print(
            f"{program_name}: 7-Zip: {sevenzip.executable} ({sevenzip.version()})",
            file=sys.stderr,
        )


def _plan_extract(
    args: argparse.Namespace,
    config: Config,
    sevenzip: SevenZip,
    *,
    legacy: bool,
) -> tuple[PlanningResult, bool]:
    raw_paths = collect_paths(args.paths, files_from=args.files_from, files0_from=args.files0_from)
    if not raw_paths:
        result = PlanningResult([], ["input contains no paths"], [])
        return result, config.on_input_error == "skip"
    normalized, errors = normalize_paths(raw_paths)
    multipart, multipart_errors = canonicalize(normalized)
    planner = make_legacy_plan if legacy else make_extract_plan
    result = planner(multipart, config, sevenzip.inspect)
    all_errors = [*errors, *multipart_errors, *result.errors]
    result.errors = all_errors
    if all_errors and config.on_input_error == "fail":
        return result, False
    return result, True


def _run_command(
    args: argparse.Namespace, config: Config, sevenzip: SevenZip, program_name: str
) -> int:
    stream, should_close = _open_manifest(args.manifest)
    try:
        records = read_json_lines(stream, args.manifest)
    finally:
        if should_close:
            stream.close()
    jobs = validate_manifest(records, config)
    results, summary, exit_code = execute_manifest(
        jobs, config, sevenzip, program_name=program_name
    )
    for record in results:
        emit_jsonl(record)
    emit_jsonl(summary)
    return exit_code


def _report_plan_diagnostics(result: PlanningResult, program_name: str) -> None:
    for warning in result.warnings:
        print(f"{program_name}: warning: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"{program_name}: input error: {error}", file=sys.stderr)


def main(
    argv: Sequence[str] | None = None,
    *,
    program_name: str = "arcshuttle",
    legacy: bool = False,
) -> int:
    """Run the primary or compatibility CLI and return its process exit code."""

    try:
        args = build_parser(program_name=program_name, legacy=legacy).parse_args(argv)
        config = _config_from_args(args)
        sevenzip = SevenZip(find_executable(config.sevenzip))
        _show_sevenzip(sevenzip, config.quiet, program_name)
        if args.command == "run":
            return _run_command(args, config, sevenzip, program_name)

        planning, usable = _plan_extract(args, config, sevenzip, legacy=legacy)
        _report_plan_diagnostics(planning, program_name)
        if not usable:
            return 64
        if args.command == "plan":
            for job in planning.jobs:
                emit_jsonl(job)
            return 1 if planning.errors or planning.warnings else 0

        jobs = validate_manifest(planning.jobs, config) if planning.jobs else []
        if not jobs:
            return 1 if planning.errors else 64
        results, summary, exit_code = execute_manifest(
            jobs, config, sevenzip, program_name=program_name
        )
        for record in results:
            emit_jsonl(record)
        emit_jsonl(summary)
        if planning.errors and exit_code == 0:
            return 1
        return exit_code
    except UsageError as exc:
        print(f"{program_name}: error: {exc}", file=sys.stderr)
        return 64
    except KeyboardInterrupt:
        print(f"{program_name}: interrupted", file=sys.stderr)
        return 130
