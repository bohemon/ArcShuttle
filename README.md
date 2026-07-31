# ArcShuttle

ArcShuttle is a resource-aware command-line tool for creating, extracting, and verifying multiple archives through the 7-Zip CLI.

It runs on Windows and Linux with Python 3.11+, gives all jobs one shared CPU/process/I/O budget, and publishes outputs only after safe staging. Standard output is reserved for UTF-8 JSON Lines; diagnostics and progress go to standard error.

The normative human/AI references are the [English command manual](docs/COMMAND_MANUAL.en.md) and [日本語コマンドマニュアル](docs/COMMAND_MANUAL.ja.md).

## Install and verify

Requirements:

- Python 3.11 or later
- a current `7zz`, `7z`, or `7za` command
- PowerShell 7 only for the optional object-pipeline modules

For development, Hatch owns the environment:

```sh
python -m pip install hatch
hatch run arcshuttle --version
hatch run check
```

For a local CLI installation:

```sh
python -m pip install .
arcshuttle --version
parxtract --version
```

`arcshuttle` is the primary 0.2.0 CLI. `parxtract` remains a compatibility alias for the 0.1 extraction syntax and schema-v1 planning.

## Quick start

Create one independent archive per source:

```sh
arcshuttle create --format 7z --level 5 folder-a folder-b file.dat
```

The default outputs are `folder-a.7z`, `folder-b.7z`, and `file.dat.7z`. A directory's contents become the archive root; its parent path and the source directory name are not stored as an extra prefix.

Extract independent archives:

```sh
arcshuttle extract --output-dir /data/extracted one.7z two.zip
```

Separate planning from execution when a human or program must inspect or edit the jobs:

```sh
arcshuttle plan create --format zip folder-a folder-b > create.jsonl
arcshuttle plan extract one.7z two.zip > extract.jsonl
cat create.jsonl extract.jsonl | arcshuttle run --manifest - > results.jsonl
```

Mixed schema-v2 create/extract manifests use one scheduler and one resource budget. `run` validates the complete manifest before it starts any job.

For arbitrary path characters, use explicit NUL-delimited input:

```sh
find /data/source -mindepth 1 -maxdepth 1 -print0 |
  arcshuttle plan create --files0-from - > create.jsonl
```

The positional, `--files-from`, and `--files0-from` forms are mutually exclusive. Stdin is never read implicitly.

## Safety model

ArcShuttle does not provide a destructive overwrite mode and never deletes or modifies a source.

- `--existing fail` fails a job if its destination exists.
- `--existing skip` starts no 7-Zip process for that job.
- `--existing rename` chooses `name (2).ext`, `name (3).ext`, and so on.
- extraction commits an ownership-marked staging directory only after 7-Zip exit 0;
- creation re-inventories the source, runs `7z a` into a sibling staging directory, requires `7z t` exit 0, and commits without clobbering an existing path;
- warnings, failures, verification failures, and interruptions retain owned staging as `.failed`;
- symlinks, junctions/reparse points, sockets, devices, and other non-regular create entries are rejected without following them;
- a create destination, staging location, or log location inside a directory source is rejected;
- encrypted extraction and password discovery/input are outside the 0.2.0 scope;
- raw user-supplied 7-Zip arguments are not accepted.

Create memory consumption depends on 7-Zip method and dictionary settings. CPU tokens limit concurrency and threads, but they are not a strict memory limit.

## Scheduling

Every running job consumes one process slot, one I/O token, and its declared CPU tokens. The shared scheduler maintains:

```text
sum(cpu_tokens) <= cpu_budget
running_jobs     <= max_processes
sum(io_tokens)  <= io_slots
```

Jobs are ordered by priority, profile, estimated weight, and plan index. Backfill may use idle capacity until the queue head reaches `reservation_delay`. `--sequential-if-total-below SIZE` makes small batches use one process and one I/O slot.

Do not wrap several `arcshuttle run` commands in GNU Parallel: separate processes cannot share resource accounting.

## JSON Lines and exits

`plan` writes only `job` records. `run`, `extract`, and `create` write one `result` per job followed by one `summary`. Exit 1 or 2 can still accompany complete, useful JSON Lines, so consumers must read stdout through EOF and inspect the summary.

| Exit | Meaning |
|---:|---|
| 0 | all jobs succeeded without warnings |
| 1 | warning, skip, or result warning; no failed job |
| 2 | at least one failed job |
| 64 | CLI, configuration, input, or manifest usage error |
| 130 | interruption |

Schema v2 protects immutable job fields with `integrity`. Filters may change only `destination.path`, four scheduling override fields (`profile`, `priority`, `cpu_tokens`, `threads`), and `tags`. Schema-v1 extraction manifests remain readable.

## Configuration and migration

Precedence is:

```text
CLI
ARCSHUTTLE_* environment
PARXTRACT_* legacy environment (existing extraction fields only)
[arcshuttle] TOML
[parxtract] legacy TOML
legacy root-level TOML
built-in defaults
```

New creation settings are `ARCSHUTTLE_CREATE_FORMAT` and `ARCSHUTTLE_COMPRESSION_LEVEL`; they are accepted only through the new namespace, `[arcshuttle]`, or CLI options.

Existing `.parxtract` logs/staging/data are not migrated, renamed, claimed, or deleted. ArcShuttle uses `.arcshuttle/logs`, `.arcshuttle-*` staging names, and `.arcshuttle-owned` markers.

See the manuals' migration sections for exact command, environment, TOML, and manifest compatibility.

## PowerShell 7

```powershell
Import-Module ./powershell/ArcShuttle.psm1

Get-ChildItem C:\Data -Directory |
    Invoke-ArcShuttleCreatePlan -Format 7z -Level 5 |
    Invoke-ArcShuttleRun
```

The module exports `Invoke-ArcShuttleExtractPlan`, `Invoke-ArcShuttleCreatePlan`, `Invoke-ArcShuttleRun`, `Invoke-ArcShuttleExtract`, and `Invoke-ArcShuttleCreate`. It uses BOM-free UTF-8 temporary files, converts JSON Lines to objects, replays stderr, preserves `$LASTEXITCODE`, and removes temporary files in `finally`.

`powershell/Parxtract.psm1` and its three `Invoke-Parxtract*` functions remain available for compatibility.

## Development and dependency policy

```sh
hatch run test
hatch run lint
hatch run format-check
hatch run check
hatch build
hatch run verify-release
```

The installed CLI intentionally has no third-party runtime dependencies. Python 3.11 provides TOML, JSON, subprocess, hashing, path, and concurrency facilities needed by the safety contract. Development-only `pytest`, `pytest-timeout`, and Ruff provide test isolation, hang protection, linting, compatibility checks, and deterministic formatting inside Hatch.

Creation v1 intentionally supports one source per archive, `7z` and `zip`, levels 0–9, and no split/encrypted archive creation. Combining several sources into one archive is reserved for a future multi-source manifest design.
