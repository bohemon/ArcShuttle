# ArcShuttle

ArcShuttle is a resource-aware command-line tool for creating, extracting, and verifying multiple archives through the 7-Zip CLI.

It runs on Windows and Linux with Python 3.11+, gives all jobs in one invocation a shared CPU/process/I/O budget, and publishes outputs only after safe staging. Standard output is reserved for UTF-8 JSON Lines; diagnostics and progress go to standard error.

The normative references are the [English command manual](docs/COMMAND_MANUAL.en.md) and [日本語コマンドマニュアル](docs/COMMAND_MANUAL.ja.md). For installation alternatives, see the [English installation guide](docs/INSTALLATION.en.md) or [日本語インストールガイド](docs/INSTALLATION.ja.md).

## Requirements

- Windows or Linux
- Python 3.11 or later
- a current `7zz`, `7z`, or `7za` command
- PowerShell 7 only for the optional object-pipeline modules

## Install

Install the published v0.3.1 Release wheel in an isolated environment with [`pipx`](https://pipx.pypa.io/):

```sh
pipx install "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.1/arcshuttle-0.3.1-py3-none-any.whl"
arcshuttle --version
```

`arcshuttle` is the primary CLI. The distribution also includes `parxtract` for compatibility with the extraction-only 0.1 command syntax and schema-v1 manifests. The installation guides cover virtual environments, tagged-source installation, updates, removal, and checksum-verified PowerShell modules.

## Quick start

Create one independent archive per source:

```sh
arcshuttle create --format 7z --level 5 folder-a folder-b file.dat
```

The default outputs are `folder-a.7z`, `folder-b.7z`, and `file.dat.7z`. A directory's contents become the archive root without an extra source-directory prefix.

Extract independent archives:

```sh
arcshuttle extract --output-dir extracted one.7z two.zip
```

These direct commands work in PowerShell and POSIX shells. Use separate `plan` and `run` commands when jobs must be inspected, edited, combined, or persisted; the command manuals document JSON Lines workflows, arbitrary-path input, configuration, scheduling, and exit handling.

## Safety and output

ArcShuttle does not provide a destructive overwrite mode and never modifies or deletes a source.

- `--existing fail`, `skip`, and `rename` handle existing destinations without overwriting them.
- creation and extraction use private staging and publish only after their required checks succeed;
- failed or interrupted owned staging is retained for inspection;
- unsafe path relationships and non-regular creation inputs are rejected without following them;
- one invocation enforces one shared CPU, process, and I/O budget;
- `plan` writes JSON Lines jobs, while execution writes results followed by a summary.

Consumers must keep stdout and stderr separate and read stdout through EOF even when the process exits 1 or 2. See the command manuals for the complete safety contract, manifest editing rules, statuses, and exit codes.

## PowerShell 7

The optional module provides object-oriented pipelines:

```powershell
Import-Module ArcShuttle

Get-ChildItem C:\Data -Directory |
    Invoke-ArcShuttleCreatePlan -Format 7z -Level 5 |
    Invoke-ArcShuttleRun
```

Plan functions emit `PSCustomObject` records for in-session pipelines, not manifest text. Use the native CLI for portable JSON Lines files and CLIXML for PowerShell-only snapshots. The [PowerShell output and persistence contract](docs/COMMAND_MANUAL.en.md#111-output-contracts-and-persistence) explains both workflows; the installation guides cover the Release modules.

## Compatibility

New workflows should use `arcshuttle`. Existing `parxtract` commands, the compatibility PowerShell module, and schema-v1 extraction manifests remain supported. Existing `.parxtract` data is not migrated, renamed, claimed, or deleted.

## Development

Clone the repository only for development, then use Hatch for the complete local gate:

```sh
git clone https://github.com/bohemon/ArcShuttle.git
cd ArcShuttle
python -m pip install hatch
hatch run check
```

The installed CLI has no third-party runtime dependencies.
