# ArcShuttle

ArcShuttle is a resource-aware command-line tool for creating, extracting, and verifying multiple archives through the 7-Zip CLI.

It runs on Windows and Linux with Python 3.11+, gives all jobs one shared CPU/process/I/O budget, and publishes outputs only after safe staging. Standard output is reserved for UTF-8 JSON Lines; diagnostics and progress go to standard error.

The normative human/AI references are the [English command manual](docs/COMMAND_MANUAL.en.md) and [日本語コマンドマニュアル](docs/COMMAND_MANUAL.ja.md). For installation choices, see the [English installation guide](docs/INSTALLATION.en.md) or [日本語インストールガイド](docs/INSTALLATION.ja.md).

## Install and verify

Requirements:

- Python 3.11 or later
- a current `7zz`, `7z`, or `7za` command
- PowerShell 7 only for the optional object-pipeline modules

For an isolated end-user CLI installation, install the verified v0.3.0 Release wheel with
[`pipx`](https://pipx.pypa.io/):

```sh
pipx install "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.0/arcshuttle-0.3.0-py3-none-any.whl"
arcshuttle --version
parxtract --version
```

In an existing virtual environment, use the same wheel without cloning the repository:

```sh
python -m pip install "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.0/arcshuttle-0.3.0-py3-none-any.whl"
arcshuttle --version
```

`arcshuttle` is the primary 0.3.0 CLI. `parxtract` remains a compatibility alias for the 0.1 extraction syntax and schema-v1 planning.

The optional PowerShell modules have a separate verified Release zip. The installation guides
cover SHA-256 verification and CurrentUser installation. Do not pipe a downloaded script into
`Invoke-Expression`.

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
- encrypted extraction and password discovery/input are outside the 0.3.0 scope;
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

When neither `--io-slots` nor a non-`auto` storage profile is configured, execution resolves the shared I/O budget from every manifest source and destination: HDD = 1, SSD = 2, NVMe = 4, and unknown = 2 slots. The slowest endpoint wins, and `max_processes` remains the upper bound. Detection failure uses the two-slot fallback. A standalone `plan` command does not inspect storage, so the manifest remains portable; `run`, `extract`, and `create` resolve the budget immediately before execution. The selected value and reason are written to stderr unless `--quiet` is set. An explicit `--io-slots` value takes precedence, while an explicit `--storage-profile hdd`, `ssd`, or `nvme` selects the corresponding fixed profile default.

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
Import-Module ArcShuttle

Get-ChildItem C:\Data -Directory |
    Invoke-ArcShuttleCreatePlan -Format 7z -Level 5 |
    Invoke-ArcShuttleRun
```

The module exports `Invoke-ArcShuttleExtractPlan`, `Invoke-ArcShuttleCreatePlan`, `Invoke-ArcShuttleRun`, `Invoke-ArcShuttleExtract`, and `Invoke-ArcShuttleCreate`. It uses BOM-free UTF-8 temporary files, converts JSON Lines to objects, replays stderr, preserves `$LASTEXITCODE`, and removes temporary files in `finally`.

PowerShell plan commands emit `PSCustomObject` records for object pipelines, not manifest text. Do not redirect their output to a `.jsonl` filename: PowerShell display formatting is not serialization. Use the native `arcshuttle plan` CLI for canonical, portable JSON Lines, or `Export-Clixml` for a PowerShell-only object snapshot. The [PowerShell output and persistence contract](docs/COMMAND_MANUAL.en.md#111-output-contracts-and-persistence) documents save, combine, inspect, and run workflows.

The Release asset also installs the `Parxtract` compatibility module and its three `Invoke-Parxtract*` functions. See the [installation guides](docs/INSTALLATION.en.md) for the checksum-verified setup.

## Development and dependency policy

Clone the repository only for development, then let Hatch own the environment:

```sh
git clone https://github.com/bohemon/ArcShuttle.git
cd ArcShuttle
python -m pip install hatch
hatch run test
hatch run lint
hatch run format-check
hatch run check
hatch build
hatch run verify-release
```

The installed CLI intentionally has no third-party runtime dependencies. Python 3.11 provides TOML, JSON, subprocess, hashing, path, and concurrency facilities needed by the safety contract. Development-only `pytest`, `pytest-timeout`, and Ruff provide test isolation, hang protection, linting, compatibility checks, and deterministic formatting inside Hatch.

Creation v1 intentionally supports one source per archive, `7z` and `zip`, levels 0–9, and no split/encrypted archive creation. Combining several sources into one archive is reserved for a future multi-source manifest design.
