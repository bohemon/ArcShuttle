---
title: ArcShuttle Command and Option Manual
language: en
manual_version: 2
applies_to_cli_version: 0.3.1
jsonl_schema_version: 2
audience:
  - human
  - ai-agent
source_of_truth:
  - src/arcshuttle/cli.py
  - src/arcshuttle/config.py
  - src/arcshuttle/manifest.py
  - src/arcshuttle/operations
  - powershell/ArcShuttle.psm1
  - powershell/Parxtract.psm1
---

# ArcShuttle command and option manual

This is the normative human/AI reference for ArcShuttle 0.3.1. “Must,” “must not,” and “may only” describe requirements. Stdout means the process standard-output byte stream; stderr means standard error.

## 1. Minimum safe contract

1. Use `arcshuttle` for new work. Use `parxtract` only for compatibility with the extraction-only 0.1 syntax.
2. Put the operation after `plan`: use `arcshuttle plan extract`, not `arcshuttle plan` by itself.
3. Select exactly one path source: positional `PATH...`, `--files-from`, or `--files0-from`.
4. Treat stdout as UTF-8 JSON Lines only. Diagnostics, the selected 7-Zip version, and progress are on stderr.
5. Read stdout through EOF even when the exit is 1 or 2. Valid results and a summary can accompany either exit.
6. Validate a complete manifest before execution. External filters may edit only the allowlisted fields in section 9.
7. Never delete a source, an existing destination, or a retained `.failed` staging path to make an operation succeed.
8. Run one `arcshuttle run` for jobs that must share one resource budget; do not wrap several runs in GNU Parallel.

```sh
arcshuttle create folder-a file.dat
arcshuttle extract one.7z two.zip
arcshuttle plan create folder-a > create.jsonl
arcshuttle run --manifest create.jsonl > results.jsonl
```

## 2. Commands and syntax

```text
arcshuttle [--help] [--version] COMMAND ...

arcshuttle plan extract [OPTIONS] PATH...
arcshuttle plan extract [OPTIONS] --files-from FILE
arcshuttle plan extract [OPTIONS] --files0-from FILE
arcshuttle plan create  [OPTIONS] PATH...
arcshuttle plan create  [OPTIONS] --files-from FILE
arcshuttle plan create  [OPTIONS] --files0-from FILE
arcshuttle run --manifest FILE [OPTIONS]
arcshuttle extract [OPTIONS] PATH...
arcshuttle create  [OPTIONS] PATH...

parxtract plan [OPTIONS] PATH...
parxtract run --manifest FILE [OPTIONS]
parxtract extract [OPTIONS] PATH...
```

`-h` and `--help` display help at their parser level. `--version` prints the CLI name and version. Common options belong after the selected subcommand. The compatibility `parxtract plan` emits schema v1; primary `arcshuttle plan extract` and `plan create` emit schema v2.

| Command | Input | Stdout | Purpose |
|---|---|---|---|
| `plan extract` | archive files | schema-v2 `job` records | inspect and plan extraction |
| `plan create` | regular files or directories | schema-v2 `job` records | inventory and plan independent archives |
| `run` | v1/v2 JSON Lines manifest | `result` records, then `summary` | validate and execute one shared schedule |
| `extract` | archive files | `result` records, then `summary` | plan and extract in one invocation |
| `create` | regular files or directories | `result` records, then `summary` | plan, create, test, and commit archives |

`run --manifest -` reads JSON Lines from stdin. No path command reads stdin implicitly.

## 3. Path input

| Form | Encoding | Contract |
|---|---|---|
| `PATH...` | OS argument encoding | one or more shell-quoted paths |
| `--files-from FILE` | UTF-8 | one path per line; empty lines ignored |
| `--files-from -` | UTF-8 | explicit newline-delimited stdin |
| `--files0-from FILE` | UTF-8 | NUL-delimited paths; trailing NUL allowed |
| `--files0-from -` | UTF-8 | explicit NUL-delimited stdin |

The forms are mutually exclusive. An explicitly empty list is an input error. Relative paths are normalized from the process working directory, and duplicates preserve their first occurrence.

Extraction accepts regular archive files only and consolidates common multipart names to the first volume. Creation accepts a regular file or directory. It does not follow symlinks, junctions/reparse points, sockets, devices, or other non-regular entries; any such source or descendant is an input error. Empty directories are inventoried and preserved.

## 4. Complete option reference

The scope column uses P for both plan operations, R for `run`, E for `extract`, C for `create`, and A for all four operation parsers.

| Option | Value | Default | Scope | Meaning |
|---|---|---|---|---|
| `-h`, `--help` | flag | - | all parser levels | show contextual help |
| `--version` | flag | - | top level | print version and exit |
| `--7z PATH` | path or command | discovery | A | select the 7-Zip executable |
| `--output-dir DIR` | path | source parent | A | root for independent final outputs |
| `--existing {fail,skip,rename}` | enum | `fail` | A | non-destructive existing-output policy |
| `--cpu-budget N or auto` | integer or `auto` | logical CPUs minus one | A | total CPU tokens |
| `--max-processes N` | positive integer | `min(4,cpu_budget)` | A | concurrent 7-Zip process limit |
| `--storage-profile {auto,hdd,ssd,nvme}` | enum | `auto` | A | runtime detection or a fixed I/O-slot profile |
| `--io-slots N` | positive integer | auto/profile-derived | A | total I/O tokens; an explicit value wins |
| `--heavy-threads N` | positive integer | `min(4,cpu_budget)` | A | scalable-job CPU/thread cap |
| `--small-threshold SIZE` | size | `64M` | A | classify smaller inputs as `small` |
| `--inspect-threshold SIZE` | size | `64M` | A | extraction inspection threshold |
| `--inspect-timeout SECONDS` | nonnegative number | `30` | A | extraction listing timeout |
| `--reservation-delay SECONDS` | nonnegative number | `30` | A | wait before reserving for queue head |
| `--sequential-if-total-below SIZE` | size | `0` | A | force small batches to one process/I/O slot |
| `--log-dir DIR` | path | `.arcshuttle/logs` | A | run-log root |
| `--config FILE` | path | none | A | explicit TOML file; no global file is implicit |
| `--quiet` | flag | false | A | suppress version/progress stderr, not errors |
| `--fail-fast` | flag | false | A | stop new starts after a failed job |
| `--allow-changed` | flag | false | A | continue after a safe source identity change warning |
| `--on-input-error {fail,skip}` | enum | `fail` | A | suppress all plan output or retain valid jobs |
| `--files-from FILE` | path or `-` | none | P/E/C | explicit newline path source |
| `--files0-from FILE` | path or `-` | none | P/E/C | explicit NUL path source |
| `--manifest FILE` | path or `-` | required | R | complete JSON Lines manifest |
| `--format {7z,zip}` | enum | `7z` | create plan/C | output archive format |
| `--level 0..9` | integer | `5` | create plan/C | compression level; 0 is store mode |

Size values are nonnegative integers with optional binary suffixes `K`, `M`, `G`, `T`, `P`, or `E`, with optional `B` or `iB`. For example, `64M` and `1GiB` are accepted; `1.5G` is not.

`--existing rename` produces `name (2).7z`, `name (3).zip`, or the equivalent extraction directory. There is no overwrite option.

## 5. Creation contract

Creation makes exactly one independent archive per input source. It does not combine several inputs into one archive.

| Source | Default destination | Stored archive root |
|---|---|---|
| directory `photos/` | `photos.7z` | contents of `photos/`, not an extra `photos/` prefix |
| file `data.bin` | `data.bin.7z` | basename `data.bin` only |

`--output-dir DIR` places each default archive name directly below `DIR`. `--format zip` changes the suffix to `.zip`. Levels are 0–9; the planned methods are LZMA2 for 7z and Deflate for zip. Level 0 tells 7-Zip to store rather than compress. Arbitrary raw 7-Zip options are not accepted.

Planning records a deterministic inventory and source identity, then inventories the source again immediately before execution. An identity change fails by default; `--allow-changed` permits safe metadata or content-set changes with a warning, but never permits a source-kind change or non-regular entry.

The destination, staging directory, and log root must not be inside a directory source. The check uses normalized/resolved path relationships, not name-based exclusions.

Create scheduling:

| Rule | Profile | CPU tokens and threads |
|---|---|---:|
| size below `small_threshold` | `small` | 1 |
| level 0 and not small | `heavy-serial` | 1 |
| other 7z or zip creation | `heavy-scalable` | `min(heavy_threads,cpu_budget)` |

CPU tokens and `-mmt=N` do not strictly bound memory; LZMA2 memory use also depends on dictionary and method settings.

## 6. Extraction contract

The default extraction directory removes known archive and multipart suffixes: `a.7z` becomes `a/`, `b.tar.gz` becomes `b/`, `c.7z.001` becomes `c/`, and `d.part01.rar` becomes `d/`.

Recognized multipart families include `.7z.001`, `.zip.001`, `.part1.rar`, `.part01.rar`, old `.rar` plus `.r00`, and `.zip` plus `.z01`. Supplying a later volume locates the first volume in the same directory or produces an input error.

Large or unknown-format archives receive a bounded `7z l -slt` inspection. Missing metadata remains null. A timeout/failure warns and classifies conservatively. Positively identified encrypted archives fail at execution; password input and password search are not supported.

Extraction profiles are `small`, `heavy-scalable` for evidence such as BZip2 or multiple independent 7z blocks, and `heavy-serial` for conservative/failed-inspection cases.

## 7. Configuration

Precedence, highest first:

```text
CLI
ARCSHUTTLE_* environment
PARXTRACT_* legacy environment
[arcshuttle] TOML
[parxtract] legacy TOML
legacy root-level TOML
built-in defaults
```

New names override legacy names. Legacy environment/TOML/root forms accept only fields that existed before creation; `create_format` and `compression_level` are new-only. Unknown TOML keys are errors. A TOML file is read only when `--config` names it.

```toml
[arcshuttle]
sevenzip = "/opt/7zip/7zz"
output_dir = "/data/out"
existing = "rename"
cpu_budget = 8
storage_profile = "auto"
create_format = "7z"
compression_level = 5
```

The following table lists every supported configuration key and environment-variable alias; omitted keys use the defaults in section 4.

| TOML key | New environment | Legacy environment |
|---|---|---|
| `sevenzip` | `ARCSHUTTLE_7Z` | `PARXTRACT_7Z` |
| `output_dir` | `ARCSHUTTLE_OUTPUT_DIR` | `PARXTRACT_OUTPUT_DIR` |
| `existing` | `ARCSHUTTLE_EXISTING` | `PARXTRACT_EXISTING` |
| `cpu_budget` | `ARCSHUTTLE_CPU_BUDGET` | `PARXTRACT_CPU_BUDGET` |
| `max_processes` | `ARCSHUTTLE_MAX_PROCESSES` | `PARXTRACT_MAX_PROCESSES` |
| `storage_profile` | `ARCSHUTTLE_STORAGE_PROFILE` | `PARXTRACT_STORAGE_PROFILE` |
| `io_slots` | `ARCSHUTTLE_IO_SLOTS` | `PARXTRACT_IO_SLOTS` |
| `heavy_threads` | `ARCSHUTTLE_HEAVY_THREADS` | `PARXTRACT_HEAVY_THREADS` |
| `small_threshold` | `ARCSHUTTLE_SMALL_THRESHOLD` | `PARXTRACT_SMALL_THRESHOLD` |
| `inspect_threshold` | `ARCSHUTTLE_INSPECT_THRESHOLD` | `PARXTRACT_INSPECT_THRESHOLD` |
| `inspect_timeout` | `ARCSHUTTLE_INSPECT_TIMEOUT` | `PARXTRACT_INSPECT_TIMEOUT` |
| `reservation_delay` | `ARCSHUTTLE_RESERVATION_DELAY` | `PARXTRACT_RESERVATION_DELAY` |
| `sequential_if_total_below` | `ARCSHUTTLE_SEQUENTIAL_IF_TOTAL_BELOW` | `PARXTRACT_SEQUENTIAL_IF_TOTAL_BELOW` |
| `log_dir` | `ARCSHUTTLE_LOG_DIR` | `PARXTRACT_LOG_DIR` |
| `quiet` | `ARCSHUTTLE_QUIET` | `PARXTRACT_QUIET` |
| `fail_fast` | `ARCSHUTTLE_FAIL_FAST` | `PARXTRACT_FAIL_FAST` |
| `allow_changed` | `ARCSHUTTLE_ALLOW_CHANGED` | `PARXTRACT_ALLOW_CHANGED` |
| `on_input_error` | `ARCSHUTTLE_ON_INPUT_ERROR` | `PARXTRACT_ON_INPUT_ERROR` |
| `create_format` | `ARCSHUTTLE_CREATE_FORMAT` | not accepted |
| `compression_level` | `ARCSHUTTLE_COMPRESSION_LEVEL` | not accepted |

Boolean environment values accept `1/0`, `true/false`, `yes/no`, and `on/off` without case sensitivity.

7-Zip discovery uses explicit `--7z` or configured value, then `7zz`, `7z`, `7za` on PATH, then standard Windows install locations. The selected executable/version is printed on stderr unless `--quiet` is set.

## 8. Shared scheduling

One mixed manifest uses one scheduler and always maintains:

```text
sum(cpu_tokens) <= cpu_budget
running_jobs     <= max_processes
sum(io_tokens)  <= io_slots
```

Scheduling considers priority, profile, estimated weight, and plan index. A fitting later job may use otherwise idle capacity, but `reservation_delay` eventually reserves resources for the queue head to prevent starvation.

With `storage_profile = "auto"` and no explicit `--io-slots`, `run`, `extract`, and `create` inspect the validated source and destination devices immediately before execution. The capacity map is HDD = 1, SSD = 2, NVMe = 4, and unknown = 2 I/O slots; the slowest distinct device wins and `max_processes` remains the upper bound. Detection failures use the unknown fallback without preventing execution. Standalone `plan` does not probe storage, so manifests remain portable. An explicit `--io-slots` value takes precedence, while an explicit `hdd`, `ssd`, or `nvme` profile uses its fixed default. The effective value and reason are written to stderr unless `--quiet` is set.

`--fail-fast` stops new starts after a failed result, lets already running jobs finish, and reports unstarted jobs as skipped. Interruption stops new starts, signals managed child process groups, waits/terminates them safely, and reports interruption. The final v2 result order is deterministic plan order, not completion order.

## 9. Manifest contract

### 9.1 Schema v2

Both primary planners emit records shaped as follows:

```json
{
  "schema_version": 2,
  "record_type": "job",
  "operation": "create",
  "job_id": "deterministic-id",
  "plan_index": 0,
  "source": {
    "path": "/absolute/source",
    "kind": "directory",
    "size": 1048576,
    "mtime_ns": 123456789,
    "entry_count": 42,
    "identity": "sha256:..."
  },
  "destination": {"path": "/absolute/source.7z", "kind": "archive"},
  "archive": {"format": "7z", "method": "LZMA2", "compression_level": 5},
  "scheduling": {
    "profile": "heavy-scalable",
    "profile_source": "auto",
    "classification_reason": "create-7z-lzma2",
    "priority": 0,
    "estimated_weight": 1048576,
    "cpu_tokens": 4,
    "threads": 4,
    "io_tokens": 1
  },
  "tags": [],
  "warnings": [],
  "integrity": "sha256:..."
}
```

Extraction uses operation `extract`, source kind `file`, destination kind `directory`, and best-effort archive inspection fields.

External filters may change only:

```text
destination.path
scheduling.profile
scheduling.priority
scheduling.cpu_tokens
scheduling.threads
tags
```

All other fields are integrity-protected. An edited destination must remain absolute, unique, and safe. CPU/thread overrides are type-checked and clamped to the configured CPU budget with warnings; I/O tokens are immutable and must fit. Do not recalculate or remove `integrity`.

```sh
arcshuttle plan create dir-a dir-b |
  jq -c 'if .tags | index("urgent") then .scheduling.priority = 100 else . end' |
  arcshuttle run --manifest -
```

### 9.2 Schema-v1 compatibility

`parxtract plan` still emits the unchanged extraction-only v1 structure with `path` and `output_dir`. `arcshuttle run` and `parxtract run` accept v1 and convert it internally to extraction jobs. The v1 editable allowlist remains `output_dir`, the same four scheduling override fields, and `tags`. V1 results retain their legacy shape and do not acquire v2-only fields.

A manifest may mix v1 extraction jobs with v2 jobs; the overall summary is schema v2 when any v2 input is present.

## 10. Staging, verification, results, and logs

### 10.1 Extraction

Extraction creates `.arcshuttle-<job-id>-<random>.tmp` beside the final directory, writes `.arcshuttle-owned`, and runs 7-Zip there. Exit 0 commits after a second destination check. Warning, failure, or interruption retains owned staging as `.failed`. Unowned paths are never moved or deleted.

### 10.2 Creation

Creation performs this order:

1. validate path relationships, source identity, and the non-destructive `--existing` policy;
2. create a private, ownership-marked staging directory beside the destination;
3. run `7z a` through an argument array with `shell=False`, closed stdin, and a controlled working directory;
4. require a regular staged archive and successful `7z t` verification;
5. recheck that the destination is absent, publish atomically, and remove only an owned empty staging directory.

Any create/test warning, failure, interruption, or pre-commit problem retains staging as `.failed`. Source paths are never moved, modified, or deleted.

### 10.3 Results

Statuses are `success`, `warning`, `failed`, `skipped`, and `interrupted`. Every v2 result includes `operation`, `output_path`, `staging_path`, and the legacy aliases `output_dir`/`staging_dir`. Create results also include `create_exit_code` and `verification_exit_code`; either can be null if that process did not start. `log_path` points to job logs when present.

The final record is a `summary` with total and counts for all five statuses plus `duration_ms`.

| Process exit | Meaning | JSON Lines may exist |
|---:|---|:---:|
| 0 | all jobs succeeded without warnings | yes |
| 1 | warning/skip/result warning and no failure | yes |
| 2 | at least one failed job | yes |
| 64 | usage, configuration, input, or manifest error | normally no |
| 130 | interrupted | yes |

### 10.4 Logs

Default root: `<cwd>/.arcshuttle/logs/<run-id>/<job-id>/`.

Extraction logs are `metadata.json`, `stdout.log`, and `stderr.log`. Creation logs are `metadata.json`, `create.stdout.log`, `create.stderr.log`, `test.stdout.log`, and `test.stderr.log`. Creation metadata records safe actual argument arrays, working directories, allocated CPU/threads, process times/exits, errors, and commit outcome. 7-Zip output never enters JSON stdout.

## 11. PowerShell 7

```powershell
Import-Module ./powershell/ArcShuttle.psm1

Get-ChildItem C:\Sources -Directory |
    Invoke-ArcShuttleCreatePlan -Format 7z -Level 5 |
    Invoke-ArcShuttleRun

Get-ChildItem C:\Archives -File |
    Invoke-ArcShuttleExtract -OutputDir C:\Extracted
```

| Function | Pipeline input | Equivalent operation |
|---|---|---|
| `Invoke-ArcShuttleExtractPlan` | string or `FileSystemInfo` | `plan extract` |
| `Invoke-ArcShuttleCreatePlan` | string or `FileSystemInfo` | `plan create`; each item is independent |
| `Invoke-ArcShuttleRun` | job objects | `run` |
| `Invoke-ArcShuttleExtract` | string or `FileSystemInfo` | plan then run extraction |
| `Invoke-ArcShuttleCreate` | string or `FileSystemInfo` | plan then run creation |

PowerShell parameters map by name: `-ArcShuttleCommand`, `-SevenZip`/`-7z`, `-OutputDir`, `-Existing`, `-CpuBudget`, `-MaxProcesses`, `-StorageProfile`, `-IoSlots`, `-HeavyThreads`, `-SmallThreshold`, `-InspectThreshold`, `-InspectTimeout`, `-ReservationDelay`, `-SequentialIfTotalBelow`, `-LogDir`, `-Config`, `-OnInputError`, `-Quiet`, `-FailFast`, and `-AllowChanged`. Create plan/combined functions also accept `-Format` and `-Level`.

The module emits only `PSCustomObject` records on the PowerShell success stream, preserves `$LASTEXITCODE`, and cleans up its temporary files. Native CLI progress and diagnostics are forwarded on stderr in real time. `-Quiet` suppresses supported informational diagnostics, but warnings and errors remain on stderr.

Keep the streams separate for a pure object pipeline. An explicit `2>&1` redirects PowerShell's error stream into its success stream, so diagnostic `ErrorRecord` values and `PSCustomObject` success records are then intentionally mixed:

```powershell
# Mixed output: useful for a combined transcript, not for a pure object pipeline.
Get-ChildItem C:\Archives -File |
    Invoke-ArcShuttleExtract -StorageProfile nvme 2>&1
```

`powershell/Parxtract.psm1` remains available with `Invoke-ParxtractPlan`, `Invoke-ParxtractRun`, and `Invoke-Parxtract` for legacy examples. It follows the same object-output contract.

### 11.1 Output contracts and persistence

Choose persistence by the output surface:

| Surface | Success output | Primary use |
|---|---|---|
| `arcshuttle plan` / `parxtract plan` | canonical UTF-8 JSON Lines | portable manifest files and non-PowerShell tools |
| `Invoke-ArcShuttle*Plan` / `Invoke-ParxtractPlan` | `PSCustomObject` records | in-session PowerShell object pipelines |
| `Export-Clixml` / `Import-Clixml` | PowerShell object snapshots | PowerShell-only persistence across sessions |

Keep plans as objects when planning and running in one PowerShell session:

```powershell
$plans = @(
    Get-ChildItem C:\Archives -File |
        Invoke-ArcShuttleExtractPlan
)

$plans | Select-Object plan_index, operation, source, destination
$plans | Invoke-ArcShuttleRun
```

A filename extension does not select a serializer. Redirecting a plan object invokes PowerShell display formatting and **does not** create a manifest:

```powershell
# Invalid persistence: the files contain lossy display formatting, not JSON Lines.
Get-ChildItem C:\Archives -File |
    Invoke-ArcShuttleExtractPlan > extract.jsonl
```

Do not pass such a file to `run` or attempt to repair it; re-plan from the sources.

Use the native CLI from PowerShell when canonical JSON Lines are required:

```powershell
$archives = @(Get-ChildItem C:\Archives -File | Select-Object -ExpandProperty FullName)
arcshuttle plan extract -- $archives > extract.jsonl
Get-Content -LiteralPath .\extract.jsonl |
    ConvertFrom-Json -Depth 100 |
    Select-Object plan_index, operation, source, destination
```

For path sets too large for a native command line, use `--files0-from` as described in section 3. Valid JSON Lines files may be concatenated as record streams. ArcShuttle validates the complete combined manifest, rejects duplicate `job_id` values and output collisions, and permits repeated `plan_index` values from independent plans. Do not renumber them because `plan_index` is protected by `integrity`.

For a PowerShell-only snapshot across sessions, use CLIXML explicitly:

```powershell
$plans | Export-Clixml -LiteralPath .\plans.clixml -Depth 100
$plans = @(Import-Clixml -LiteralPath .\plans.clixml)
$plans | Invoke-ArcShuttleRun
```

The same pattern works with `Invoke-ParxtractPlan` and `Invoke-ParxtractRun`. CLIXML is not an ArcShuttle manifest and is not accepted by `arcshuttle run --manifest`. To combine snapshots, import them and combine the resulting object lists rather than concatenating raw CLIXML documents.

## 12. POSIX examples

```sh
# Review creation jobs before execution.
find /data/source -mindepth 1 -maxdepth 1 -print0 |
  arcshuttle plan create --files0-from - --format 7z > create.jsonl
jq -e -c 'select(.record_type == "job")' create.jsonl |
  arcshuttle run --manifest - > results.jsonl

# Extract directly.
fd --type f --print0 . /data/archives |
  arcshuttle extract --files0-from - --output-dir /data/out
```

Use `set -o pipefail` when shell pipeline status matters, but remember that plan exit 1 may still carry valid jobs. Capture plan stdout and exit separately when warning policy matters.

## 13. Migration from parxtract 0.1

- Install distribution `arcshuttle`, which includes both console scripts, and use `arcshuttle` for new CLI and PowerShell workflows.
- Existing `parxtract` commands, the compatibility module, and schema-v1 manifests remain supported for extraction.
- Prefer `ARCSHUTTLE_*` and `[arcshuttle]`; the new names take precedence, and creation settings have no legacy aliases.
- Existing `.parxtract` data is not migrated, renamed, claimed, or deleted. ArcShuttle writes new `.arcshuttle` paths.

## 14. AI-agent procedure

1. Verify the version, 7-Zip availability, operation, output format, and safe destination before planning. Use NUL input for generated or arbitrary paths.
2. Capture stdout and stderr separately. Validate every planned `job`, its operation, and destination uniqueness.
3. If filtering, edit only the v2 allowlist. Never regenerate `integrity` or edit protected source, archive, inventory, or I/O fields.
4. Pass the complete stream to one `run` process, read stdout through EOF, and evaluate every result plus the final summary and process exit.
5. Report non-null `staging_path` and `log_path`. Do not delete retained output, modify sources, follow rejected links, or bypass overwrite protection.

Machine decision outline:

```text
records = parse_json_lines(stdout_to_eof)
if exit == 64 or records is empty:
    outcome = invocation_error
else:
    require records[-1].record_type == summary
    if exit == 130 or summary.interrupted > 0: outcome = interrupted
    else if summary.failed > 0: outcome = failed_or_partial
    else if summary.warning > 0 or summary.skipped > 0: outcome = completed_non_success
    else if any(result.warnings): outcome = completed_with_warnings
    else: outcome = success
```

## 15. Limits and troubleshooting

Creation supports one source per archive, 7z/zip, levels 0–9, regular entries, and local non-split output. Multi-source, split, and encrypted creation, password input, raw method tuning, a strict memory budget, a GUI, and a watch service are not supported.

| Symptom | Check | Safe response |
|---|---|---|
| `7-Zip not found` | `--7z`, `ARCSHUTTLE_7Z`, PATH | configure a supported executable |
| exit 64 and empty stdout | stderr usage/input/manifest error | fix syntax or re-plan; do not fabricate records |
| exit 1 with output | warnings/skips/result warnings | parse summary and report details |
| source identity changed | modifications since plan | re-plan; use `--allow-changed` only intentionally |
| immutable fields modified | external filter | restart from original plan and edit only allowlist |
| output collision | duplicate derived/edited paths | select unique destinations |
| `.failed` remains | create/test/extract warning or failure | inspect logs and recover manually |
| HDD throughput drops | I/O contention | select `hdd` or `--io-slots 1` |
