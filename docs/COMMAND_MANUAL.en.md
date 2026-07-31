---
title: parxtract Command and Option Manual
language: en
manual_version: 1
applies_to_cli_version: 0.1.0
jsonl_schema_version: 1
audience:
  - human
  - ai-agent
source_of_truth:
  - src/parxtract/cli.py
  - src/parxtract/config.py
  - src/parxtract/manifest.py
  - powershell/Parxtract.psm1
---

# `parxtract` Command and Option Manual

This is the normative reference for humans and AI agents operating `parxtract` 0.1.0 safely and consistently. See `README.md` for an overview; use this manual for the precise command contract. The words **must**, **must not**, and **may only** express normative requirements. A “default” is used when the CLI, an environment variable, and an explicit TOML file do not override it.

## 1. Minimum contract

1. Put the subcommand immediately after the command name and common options after the subcommand.
2. For `plan` or `extract`, specify exactly one input source: `PATH...`, `--files-from`, or `--files0-from`.
3. Treat stdout as UTF-8 JSON Lines and read human-facing messages from stderr.
4. Read all `plan` output through EOF before passing it to `run`.
5. An external filter may modify only the six fields listed in section 11.3.
6. Do not start multiple `parxtract run` processes through GNU Parallel or a similar tool.
7. Do not interpret every nonzero exit as “no output.” Exit 1 can accompany valid JSON Lines.
8. Source archives and failed staging directories are not deleted by default.

```sh
parxtract extract archive1.7z archive2.zip
parxtract plan archive1.7z archive2.zip > plan.jsonl
parxtract run --manifest plan.jsonl > result.jsonl
```

## 2. Command syntax

```text
parxtract [--version] {plan|run|extract} ...

parxtract plan    [COMMON_OPTIONS] [PATH ...]
parxtract plan    [COMMON_OPTIONS] --files-from FILE
parxtract plan    [COMMON_OPTIONS] --files0-from FILE
parxtract run     [COMMON_OPTIONS] --manifest FILE
parxtract extract [COMMON_OPTIONS] [PATH ...]
parxtract extract [COMMON_OPTIONS] --files-from FILE
parxtract extract [COMMON_OPTIONS] --files0-from FILE
```

Only `--version` and top-level `--help` precede the subcommand. Write `parxtract plan --quiet ...`, not `parxtract --quiet plan ...`. Use the option terminator for a positional path beginning with `-`:

```sh
parxtract plan -- ./-archive.zip
```

## 3. Choosing a command

| Command | Input | Stdout | Purpose |
|---|---|---|---|
| `plan` | Archive paths | `job` JSON Lines | Inspection, classification, output review, and filtering |
| `run` | A `plan` manifest | `result` records followed by `summary` | Execute a validated plan |
| `extract` | Archive paths | `result` records followed by `summary` | One-step operation without external filtering |

### 3.1 `plan`

`plan` reads all input, normalizes paths, consolidates multipart archives, performs required 7-Zip inspection, classifies jobs, and checks output collisions. `plan_index` preserves normalized input order; `run` applies execution priority.

```sh
parxtract plan --output-dir /data/out a.7z b.zip
parxtract plan --files-from paths.txt
find /data/in -type f -print0 | parxtract plan --files0-from -
```

With `--on-input-error=fail`, one fatal input error prevents a partial plan from reaching stdout and produces exit 64. With `skip`, valid jobs are emitted and the process exits 1. Inspection warnings also leave the plan valid but can produce exit 1.

### 3.2 `run`

`run` reads the complete manifest through EOF and validates every record and output collision before starting a job.

```sh
parxtract run --manifest plan.jsonl
cat plan.jsonl | parxtract run --manifest -
```

`--manifest` is required and takes `FILE`. `FILE` is a UTF-8 JSON Lines file; `-` means stdin. It cannot be a positional argument. The current implementation writes results after all jobs finish and then writes a final `summary`; callers must read through EOF.

One failure does not stop other jobs by default. `--fail-fast` prevents new starts after a detected failure, waits for running jobs, and marks jobs that never start as `skipped`.

### 3.3 `extract`

`extract` performs `plan` followed by `run` internally. Use it when no plan editing is needed.

```sh
parxtract extract --output-dir /data/out --existing rename a.7z b.zip
```

With the default input-error policy, a fatal input error prevents all extraction.

## 4. Input-source options

These apply only to `plan` and `extract`.

| Form | Meaning | Encoding | Notes |
|---|---|---|---|
| `PATH...` | One or more positional paths | OS argument rules | Shell quoting may be required |
| `--files-from FILE` | One path per line | UTF-8 | Cannot represent a newline in a path |
| `--files-from -` | Newline-delimited stdin | UTF-8 | stdin is never read implicitly |
| `--files0-from FILE` | NUL-delimited paths | UTF-8 | Can represent newlines in paths |
| `--files0-from -` | NUL-delimited stdin | UTF-8 | For `find -print0` or `fd --print0` |

The three forms are mutually exclusive, and explicitly empty input is an error. Relative paths become absolute from the process working directory. Missing paths and directories are rejected. Normalized duplicates retain their first occurrence; matching is case-insensitive on Windows. Prefer file input when command-line length is a concern.

## 5. Common options

All subcommands accept these options syntactically. `P` means planning and `R` means execution.

| Option | Value | Default | Phase | Meaning |
|---|---|---:|:---:|---|
| `--7z PATH` | Path or command | auto-discovery | P/R | 7-Zip CLI for inspection and extraction |
| `--output-dir DIR` | Directory | archive parent | P | Planned final-output root; `run` uses manifest `output_dir` instead |
| `--existing {fail,skip,rename}` | Enum | `fail` | R | Non-destructive policy for existing final output |
| `--cpu-budget N|auto` | Positive integer or `auto` | `max(1, CPU count-1)` | P/R | Shared CPU-token total and heavy-job planning limit |
| `--max-processes N` | Positive integer | `min(4,cpu_budget)` | R | Maximum simultaneous 7-Zip processes |
| `--storage-profile {auto,hdd,ssd,nvme}` | Enum | `auto` | R | Select default I/O slots |
| `--io-slots N` | Positive integer | profile-dependent | R | Shared I/O-token total |
| `--heavy-threads N` | Positive integer | `min(4,cpu_budget)` | P | Maximum tokens/threads planned for `heavy-scalable` |
| `--small-threshold SIZE` | Size | `64M` | P | Smaller compressed files are `small` |
| `--inspect-threshold SIZE` | Size | `64M` | P | Known formats at or above this receive technical listing |
| `--inspect-timeout SECONDS` | Nonnegative number | `30` | P | Inspection timeout per archive |
| `--reservation-delay SECONDS` | Nonnegative number | `30` | R | Wait before reserving resources for the queue head |
| `--sequential-if-total-below SIZE` | Size | `0` | R | Below threshold use one process/I/O slot; 0 disables |
| `--log-dir DIR` | Directory | `./.parxtract/logs` | R | Execution-log root |
| `--config FILE` | TOML file | none | P/R | Explicit configuration; no implicit global config |
| `--quiet` | Flag | false | P/R | Suppress selected-7-Zip and non-warning progress, not JSON |
| `--fail-fast` | Flag | false | R | Stop starting jobs after the first failure |
| `--allow-changed` | Flag | false | R | Run with warning after source size/mtime changes |
| `--on-input-error {fail,skip}` | Enum | `fail` | P | Reject all input or plan only valid input |
| `-h`, `--help` | Flag | - | P/R | Show subcommand help |

Warnings and errors remain visible with `--quiet`.

### 5.1 Size values

A size is a nonnegative integer with an optional case-insensitive binary suffix: `K`, `M`, `G`, `T`, `P`, `E`, their `KB` forms, or their `KiB` forms. Thus `64M` is 64 × 1024² bytes and `1GiB` is 1024³ bytes. Decimal forms such as `1.5G` are rejected.

### 5.2 Existing-output policy

`--existing fail` marks the job `failed` without starting 7-Zip. `skip` marks it `skipped`. `rename` selects `name (2)`, `name (3)`, and so on. There is no `overwrite` value or destructive existing-output option.

### 5.3 Storage profiles

Without explicit `--io-slots`, `hdd` uses 1, `ssd` uses 2, `nvme` uses 4, and `auto` uses `min(2,max_processes)`. Storage hardware is not detected; `auto` is a conservative formula, not device identification.

## 6. Configuration

Precedence is:

```text
CLI > environment variable > --config TOML > built-in default
```

TOML settings may be in `[parxtract]` or at the file root. Unknown keys are errors. A file is read only when named by `--config`. The key is `sevenzip`, not `7z`.

```toml
[parxtract]
sevenzip = "C:/Program Files/7-Zip/7z.exe"
output_dir = "D:/Extracted"
existing = "rename"
cpu_budget = 8
max_processes = 4
storage_profile = "ssd"
io_slots = 2
heavy_threads = 4
small_threshold = "64M"
inspect_threshold = "64M"
inspect_timeout = 30
reservation_delay = 30
sequential_if_total_below = 0
log_dir = "D:/Logs/parxtract"
quiet = false
fail_fast = false
allow_changed = false
on_input_error = "fail"
```

| TOML key | Environment variable |
|---|---|
| `sevenzip` | `PARXTRACT_7Z` |
| `output_dir` | `PARXTRACT_OUTPUT_DIR` |
| `existing` | `PARXTRACT_EXISTING` |
| `cpu_budget` | `PARXTRACT_CPU_BUDGET` |
| `max_processes` | `PARXTRACT_MAX_PROCESSES` |
| `storage_profile` | `PARXTRACT_STORAGE_PROFILE` |
| `io_slots` | `PARXTRACT_IO_SLOTS` |
| `heavy_threads` | `PARXTRACT_HEAVY_THREADS` |
| `small_threshold` | `PARXTRACT_SMALL_THRESHOLD` |
| `inspect_threshold` | `PARXTRACT_INSPECT_THRESHOLD` |
| `inspect_timeout` | `PARXTRACT_INSPECT_TIMEOUT` |
| `reservation_delay` | `PARXTRACT_RESERVATION_DELAY` |
| `sequential_if_total_below` | `PARXTRACT_SEQUENTIAL_IF_TOTAL_BELOW` |
| `log_dir` | `PARXTRACT_LOG_DIR` |
| `quiet` | `PARXTRACT_QUIET` |
| `fail_fast` | `PARXTRACT_FAIL_FAST` |
| `allow_changed` | `PARXTRACT_ALLOW_CHANGED` |
| `on_input_error` | `PARXTRACT_ON_INPUT_ERROR` |

Boolean environment values accept `1/0`, `true/false`, `yes/no`, and `on/off`.

## 7. 7-Zip discovery and inspection

Discovery order is `--7z`, `PARXTRACT_7Z`, `7zz` on `PATH`, `7z` on `PATH`, `7za` on `PATH`, then Windows `Program Files/7-Zip/7z.exe`. The selected executable and version go to stderr unless `--quiet` is set.

7-Zip starts with an argument array, closed stdin, and `shell=False`; `--` precedes the archive path. Automatically recognized extensions are:

```text
.7z .zip .rar .tar .tar.gz .tgz .tar.bz2 .tbz2
.tar.xz .txz .gz .bz2 .xz
```

Unknown extensions supplied directly are inspected rather than rejected by suffix alone. Technical listing occurs when compressed size is at least `inspect_threshold` or format is unknown. Unavailable values remain `null`. Inspection failure/timeout adds a warning and selects conservative `heavy-serial`. Confirmed encryption fails the job during execution.

## 8. Multipart archives

The following sets become one job for their first volume: `name.7z.001`, `name.zip.001`, `name.part1.rar`, `name.part01.rar`, `name.rar` with `.r00` parts, and `name.zip` with `.z01` parts. Supplying a later volume searches its directory for the first; absence is an input error. Never execute parts as separate jobs.

## 9. Classification and scheduling

| Profile | Automatic rule | CPU tokens | Threads |
|---|---|---:|---:|
| `small` | Below `small_threshold` | 1 | 1 |
| `heavy-scalable` | BZip2 or multi-block 7z | `min(heavy_threads,cpu_budget)` | CPU tokens |
| `heavy-serial` | Large without scaling evidence, or failed inspection | 1 | 1 |

Every job uses one I/O token. Classification is not a performance guarantee. Runtime always preserves:

```text
sum(cpu_tokens) <= cpu_budget
running_jobs     <= max_processes
sum(io_tokens)  <= io_slots
```

Order is descending `scheduling.priority`, then `heavy-scalable`, `heavy-serial`, `small`, descending `estimated_weight`, and ascending `plan_index`. Later fitting jobs may backfill when the head does not fit. After the head waits `reservation_delay`, new backfills stop so resources can drain for it.

## 10. Output and staging

The default output is beside the archive, without archive suffixes: `a.7z` → `a`, `b.tar.gz` → `b`, `c.7z.001` → `c`, `d.part01.rar` → `d`. Planning-time `--output-dir DIR` produces `DIR/<output-name>`.

Execution creates `.parxtract-<job-id>-<random>.tmp` beside final output, writes an ownership marker, and extracts into it. Only a 7-Zip exit 0 followed by a final nonexistence check commits it through an atomic same-filesystem rename. Exit 1, exit 2+, interruption, or commit failure retains it as `.failed`; consult `staging_dir`. A directory without verified ownership is never deleted or renamed.

## 11. JSON Lines contract

UTF-8 is required. Each nonempty line is one complete JSON object. Stdout contains no non-JSON text. Current `schema_version` is `1`; unknown values are `null`.

### 11.1 Plan records

Each `record_type: "job"` record includes deterministic `job_id`, input-order `plan_index`, absolute `path` and `output_dir`, planning-time `source.size` and `source.mtime_ns`, best-effort `archive` data, `scheduling`, `tags`, `warnings`, and an `integrity` digest protecting immutable fields.

### 11.2 Editable fields

An external filter may change exactly these six fields:

```text
output_dir
scheduling.profile
scheduling.priority
scheduling.cpu_tokens
scheduling.threads
tags
```

It must not modify `path`, `job_id`, `source`, `archive`, `plan_index`, `scheduling.io_tokens`, `scheduling.estimated_weight`, `scheduling.classification_reason`, `warnings`, or `integrity`. Do not recalculate `integrity` after permitted edits.

`run` clamps CPU tokens to `cpu_budget` and threads to assigned CPU tokens, adding a warning. A manifest whose I/O tokens exceed budget is rejected. A profile override is recorded as `manifest-override`.

```sh
jq -c '
  select(.archive.encrypted != true)
  | if (.tags | index("urgent")) then .scheduling.priority = 100 else . end
' plan.jsonl > filtered.jsonl
```

### 11.3 Results and summary

Result status is `success` only for 7-Zip exit 0 and successful commit. `warning` means 7-Zip exit 1; `failed` covers validation, launch, 7-Zip, or commit failure; `skipped` covers existing output or a fail-fast non-start; `interrupted` means user interruption. Only success commits final output. `exit_code` can be `null` if 7-Zip never started. `staging_dir` is `null` on success or an absolute retained path.

The final record is always `record_type: "summary"` and contains `run_id`, `total`, `success`, `warning`, `failed`, `skipped`, `interrupted`, and `duration_ms`.

## 12. Logs

The default is `<current-directory>/.parxtract/logs/<run-id>/<job-id>/`. Each job directory contains `metadata.json`, `stdout.log`, and `stderr.log`. Metadata records actual arguments, timestamps, resources, exit status, interruption, and launch errors. 7-Zip output streams directly to files instead of accumulating in memory.

## 13. Process exit codes

| Code | Meaning | JSON possible |
|---:|---|:---:|
| 0 | All jobs succeeded without warnings | Yes |
| 1 | Warning or skip, no failure | Yes |
| 2 | One or more failures | Yes |
| 64 | CLI, configuration, input-format, or manifest error | Normally no |
| 130 | User interruption | Possibly |

An AI agent must parse complete results and the summary when present after exit 1 or 2. JSON parsing failure is distinct from job failure.

## 14. PowerShell 7 module

```powershell
Import-Module ./powershell/Parxtract.psm1
```

`Invoke-ParxtractPlan` accepts `string` or `FileSystemInfo` pipeline input and emits plan objects. `Invoke-ParxtractRun` accepts plan objects and emits result/summary objects. `Invoke-Parxtract` accepts paths and performs both phases.

| PowerShell | CLI |
|---|---|
| `-ParxtractCommand` | command to invoke, default `parxtract` |
| `-SevenZip` or `-7z` | `--7z` |
| `-OutputDir` | `--output-dir` |
| `-Existing` | `--existing` |
| `-CpuBudget` | `--cpu-budget` |
| `-MaxProcesses` | `--max-processes` |
| `-StorageProfile` | `--storage-profile` |
| `-IoSlots` | `--io-slots` |
| `-HeavyThreads` | `--heavy-threads` |
| `-SmallThreshold` | `--small-threshold` |
| `-InspectThreshold` | `--inspect-threshold` |
| `-InspectTimeout` | `--inspect-timeout` |
| `-ReservationDelay` | `--reservation-delay` |
| `-SequentialIfTotalBelow` | `--sequential-if-total-below` |
| `-LogDir` | `--log-dir` |
| `-Config` | `--config` |
| `-OnInputError` | `--on-input-error` |
| `-Quiet` | `--quiet` |
| `-FailFast` | `--fail-fast` |
| `-AllowChanged` | `--allow-changed` |

The wrapper uses a BOM-free UTF-8 temporary file and invokes the Python CLI once. It removes temporary files in `finally`, displays Python stderr, parses only stdout with `ConvertFrom-Json`, and exposes status through `$LASTEXITCODE`.

## 15. POSIX integration

```sh
find /data/in -type f -print0 |
  parxtract plan --files0-from - --output-dir /data/out |
  jq -c 'select(.archive.encrypted != true)' |
  parxtract run --manifest -
```

Use `set -o pipefail` in Bash when whole-pipeline status matters, but account for a valid plan accompanied by warning exit 1.

```sh
parxtract plan --files0-from paths.bin > plan.jsonl
jq -e -c 'select(.record_type == "job")' plan.jsonl > checked.jsonl
parxtract run --manifest checked.jsonl > results.jsonl
jq -s 'last | select(.record_type == "summary")' results.jsonl
```

## 16. AI-agent procedure

1. Check presence/version with `parxtract --version`.
2. Confirm targets are files; do not pass directories.
3. Use NUL-delimited input for many or arbitrary paths.
4. Use `plan` for filtering or priority edits; otherwise use `extract`.
5. Read only plan stdout as JSON Lines through EOF.
6. Confirm `record_type == "job"` and edit only permitted fields.
7. Preserve one JSON object per line for `run --manifest -` or a file.
8. Read run stdout through EOF and require a final `summary`.
9. Evaluate process exit, each `status`, and `warnings` together.
10. Report `staging_dir` and `log_path` for non-success results.

AI agents must not parse stderr as JSON; alter forbidden manifest fields; remove or regenerate `integrity`; guess archive passwords; delete existing output to bypass `existing=fail`; delete failed staging; modify source archives; or launch several `run` processes for one shared resource budget.

```text
records = parse_json_lines(stdout_to_eof)

if process_exit == 64 or records is empty:
    outcome = "invocation-or-output-error"
else:
    assert records[-1].record_type == "summary"

if outcome is not set:
    if process_exit == 130 or records[-1].interrupted > 0:
        outcome = "interrupted"
    else if records[-1].failed > 0:
        outcome = "partial-or-total-failure"
    else if records[-1].warning > 0 or records[-1].skipped > 0:
        outcome = "completed-with-non-success-results"
    else if any(result.warnings is not empty):
        outcome = "completed-with-warnings"
    else:
        outcome = "success"
```

## 17. Troubleshooting

| Symptom | Action |
|---|---|
| `7-Zip not found` | Check `--7z`, `PARXTRACT_7Z`, and `PATH` |
| Exit 64 with empty stdout | Read stderr; check syntax, exclusive input, absolute `output_dir`, and integrity |
| Exit 1 after extraction | Inspect summary, `warnings`, and `skipped` |
| `source ... changed` | Plan again; use `--allow-changed` only when intended |
| `immutable manifest fields were modified` | Start from the original plan and edit only six fields |
| `output collision` | Make each `output_dir` unique |
| A `.failed` directory remains | Inspect `log_path` and manually recover partial output |
| HDD throughput is poor | Use `--storage-profile hdd` or `--io-slots 1` |
| A heavy job waits | Inspect resource budget and `reservation_delay`; reservation is expected |

## 18. Out of scope

Version 0.1.0 does not provide runtime thread changes, measurement-driven CPU/I/O control, physical-disk detection, recursive nested extraction, source-archive deletion, destructive overwrite, interactive password entry or discovery, a GUI, or watched folders. An AI agent must not silently emulate these features with external destructive actions.
