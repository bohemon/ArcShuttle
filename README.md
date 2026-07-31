# parxtract

`parxtract` is a Python 3.11+ command-line tool that safely extracts many independent archives through the 7-Zip CLI. It schedules small archives across processes while reserving weighted CPU tokens for large archives whose internal structure can benefit from 7-Zip threads. The same Python scheduler is used on Windows and Linux; the PowerShell module only converts object pipelines to and from JSON Lines.

Version 1 never deletes source archives, overwrites an existing output, searches for passwords, or recursively extracts nested archives.

## Requirements and installation

- Python 3.11 or later
- A current 7-Zip CLI (`7zz`, `7z`, or `7za`)
- PowerShell 7 only when using the optional object-pipeline wrapper

```sh
python -m pip install hatch
hatch run parxtract --version
```

To install the CLI outside the Hatch development environment:

```sh
python -m pip install .
parxtract --version
```

The 7-Zip executable is selected in this order: `--7z`, `PARXTRACT_7Z`, `7zz`, `7z`, `7za`, then the usual Windows install directories. The selected path and version are written to standard error unless `--quiet` is used. Standard output is reserved for JSON Lines.

## Commands

`plan` collects all input before validation and emits one job object per line in original input order:

```sh
parxtract plan --output-dir /data/out one.7z two.zip > plan.jsonl
parxtract plan --files-from paths.txt > plan.jsonl
find /data/in -type f -print0 | parxtract plan --files0-from - > plan.jsonl
```

`run` reads the complete manifest before starting work, emits one result object per completed job, and ends with a `record_type: "summary"` object:

```sh
parxtract run --manifest plan.jsonl
```

`extract` performs both phases without exposing the intermediate manifest:

```sh
parxtract extract --output-dir /data/out one.7z two.zip
```

The three input forms—positional paths, `--files-from`, and `--files0-from`—are mutually exclusive. There is no implicit stdin input. Newline files are UTF-8; NUL input makes every character except NUL safe in a path. Directory inputs are deliberately rejected.

### Filtering a plan

Because `plan` and `run` use JSON Lines, an external tool can filter or tune a plan:

```sh
find /data/in -type f -print0 |
  parxtract plan --files0-from - --output-dir /data/out |
  jq -c 'select(.archive.encrypted != true)' |
  parxtract run --manifest -
```

With `fd`:

```sh
fd --type f --print0 . /data/in |
  parxtract plan --files0-from - --output-dir /data/out |
  parxtract run --manifest -
```

Do not start several `parxtract run` processes through GNU Parallel: doing so splits CPU and I/O accounting.

## Scheduling model

Every running job consumes one process slot, one I/O slot, and its declared CPU-token count. The scheduler always maintains:

```text
sum(cpu_tokens) <= cpu_budget
running_jobs     <= max_processes
sum(io_tokens)  <= io_slots
```

Jobs are ordered by explicit priority, then `heavy-scalable`, `heavy-serial`, `small`, estimated unpacked size (largest first), and input order. If the first waiting job does not fit, a smaller job may backfill unused resources. Once that head job has waited for `reservation_delay`, new backfill stops until enough resources become available.

Classification is deliberately conservative:

| Profile | Rule | CPU tokens / 7-Zip threads |
|---|---|---|
| `small` | packed size below `small_threshold` | 1 / 1 |
| `heavy-scalable` | BZip2 method, multiple independent 7z blocks, or manifest override | up to `heavy_threads` |
| `heavy-serial` | large archive without evidence of internal scaling, timeout, or failed inspection | 1 / 1 |

The plan records `classification_reason`. These are heuristics, not performance guarantees: `-mmt` effectiveness depends on format, compression method, and archive structure. In particular, raising parallelism on a rotational HDD can make extraction slower.

Built-in defaults are conservative starting points:

```text
cpu_budget               = max(1, os.cpu_count() - 1)
max_processes             = min(4, cpu_budget)
heavy_threads             = min(4, cpu_budget)
small_threshold           = 64 MiB
inspect_threshold         = 64 MiB
inspect_timeout           = 30 seconds
reservation_delay         = 30 seconds
sequential_if_total_below = 0 (disabled)
storage_profile           = auto
I/O slots                 = hdd:1, ssd:2, nvme:4, auto:min(2,max_processes)
```

`--io-slots` overrides the profile. When `--sequential-if-total-below SIZE` is nonzero and the combined packed size is at most that value, the effective process and I/O limits are both one.

## Safe outputs and recovery

The default final directory is beside each archive with all archive suffixes removed (`a.7z` → `a/`, `b.tar.gz` → `b/`, `c.7z.001` → `c/`, `d.part01.rar` → `d/`). `--output-dir` puts these independent subdirectories under one root.

`--existing` supports only safe policies:

- `fail` (default): record a failed job.
- `skip`: do not launch 7-Zip and record a skipped job.
- `rename`: choose `name (2)`, `name (3)`, and so on.

Each archive is extracted to a unique `.parxtract-<job-id>-<random>.tmp` directory beside the final path. Exit code 0 is atomically renamed into place after a second collision check. A 7-Zip warning (exit 1), failure, or interruption is renamed to `.failed` and retained. The result's `staging_dir` gives the recovery path; inspect it and move wanted files manually. parxtract never removes an unmarked directory.

Per-job logs default to `.parxtract/logs/<run-id>/<job-id>/` and contain `metadata.json`, `stdout.log`, and `stderr.log`. `--log-dir` changes the log root. Arguments are passed as an array with `shell=False`, stdin is closed, and no password is accepted or logged. Archives positively identified as encrypted are rejected in version 1.

Common multipart families are collapsed to one first-volume job: `.7z.001`, `.zip.001`, `.part01.rar`, `.part1.rar`, old `.rar`/`.r00`, and `.zip`/`.z01`. If only a later volume is supplied, the first is located in the same directory or reported as an input error.

## Configuration

Precedence is CLI, `PARXTRACT_*` environment variables, explicitly named TOML, then built-in defaults. No implicit user-global file is read.

```toml
[parxtract]
sevenzip = "/opt/7zip/7zz"
cpu_budget = 8
max_processes = 4
storage_profile = "ssd"
small_threshold = "64M"
```

Use it with `--config parxtract.toml`. In addition to `PARXTRACT_7Z`, configuration fields have uppercase environment names such as `PARXTRACT_CPU_BUDGET` and `PARXTRACT_IO_SLOTS`.

## JSON Lines contract

Plan jobs use `schema_version: 1` and include `job_id`, `plan_index`, absolute `path`/`output_dir`, source size and nanosecond mtime, best-effort archive metadata, scheduling fields, tags, warnings, and an integrity digest. Unknown inspection fields are `null`.

After `plan`, filters may change only:

- `output_dir`
- `scheduling.profile`
- `scheduling.priority`
- `scheduling.cpu_tokens`
- `scheduling.threads`
- `tags`

The integrity digest protects other fields. `run` rejects invalid immutable data or output collisions, clamps CPU/thread overrides to the configured budget with a warning, and rejects impossible I/O requests. By default a changed source size or mtime fails that job; `--allow-changed` logs a warning and proceeds.

Result statuses are `success`, `warning`, `failed`, `skipped`, or `interrupted`. One failed job does not stop others. `--fail-fast` stops launching new jobs but lets already-running jobs finish. The final summary counts each status.

## PowerShell 7

```powershell
Import-Module ./powershell/Parxtract.psm1

Get-ChildItem C:\Archives -File -Recurse |
    Where-Object Length -gt 1MB |
    Invoke-ParxtractPlan -OutputDir C:\Extracted |
    Where-Object { -not $_.archive.encrypted } |
    Invoke-ParxtractRun
```

`Invoke-ParxtractPlan` accepts strings and `FileSystemInfo` objects. `Invoke-ParxtractRun` accepts plan objects and returns result/summary objects. `Invoke-Parxtract` chains both. Temporary UTF-8 files avoid Windows command-line limits and are removed in `finally`; Python stderr remains visible to the user. `$LASTEXITCODE` retains the CLI status.

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | every job succeeded |
| 1 | warnings or skips, but no failures |
| 2 | at least one failed job |
| 64 | CLI, configuration, input-format, or manifest error |
| 130 | user interruption |

With `--on-input-error fail` (default), any serious input error suppresses the entire plan. With `skip`, valid inputs are planned and the command returns 1.

## Development

Hatch creates and manages the pytest development environment. The suite uses pytest fixtures and a controllable fake 7-Zip process:

```sh
hatch run test
hatch run test-verbose
hatch run lint
hatch run format-check
hatch run format
hatch run check
hatch build
```

GitHub Actions runs it on Ubuntu and Windows with Python 3.11 and 3.12.

### Dependency policy

The installed CLI intentionally keeps zero third-party runtime dependencies. Its command parsing, TOML loading, manifest validation, process-group handling, JSON Lines output, and plain stderr progress are all covered by the Python 3.11 standard library without weakening the documented behavior.

Development dependencies are selected where they provide a distinct safety benefit: `pytest-timeout` prevents a scheduler or subprocess regression from hanging CI indefinitely, and Ruff provides import sorting, linting, Python 3.11 compatibility checks, and deterministic formatting. They are isolated in the Hatch development environment and are not installed with the `parxtract` wheel.
