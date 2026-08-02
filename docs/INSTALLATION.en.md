# ArcShuttle Installation Guide

This guide installs ArcShuttle without a source checkout. Commands are pinned to v0.3.0 so an
installation does not change when `main` changes.

## Requirements

- Windows or Linux
- Python 3.11 or later
- a current `7zz`, `7z`, or `7za` executable
- PowerShell 7 only when using the optional object-pipeline modules

## Install the CLI

### Recommended: isolated installation with pipx

[`pipx`](https://pipx.pypa.io/) installs command-line applications into isolated environments
and exposes their commands on `PATH`. After installing pipx for your platform, run:

```sh
pipx install "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.0/arcshuttle-0.3.0-py3-none-any.whl"
arcshuttle --version
parxtract --version
```

Upgrade or reinstall this pinned release with:

```sh
pipx install --force "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.0/arcshuttle-0.3.0-py3-none-any.whl"
```

Remove it with `pipx uninstall arcshuttle`.

### Existing virtual environment

Activate the environment, then install the Release wheel directly:

```sh
python -m pip install "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.0/arcshuttle-0.3.0-py3-none-any.whl"
arcshuttle --version
```

Use a virtual environment instead of modifying an operating-system-managed Python installation.
Update that environment to a newer Release wheel by changing the version in the URL and adding
`--upgrade` to the command. Remove it with `python -m pip uninstall arcshuttle`.

### Install from Git

Use a tag or commit when the Release wheel is unsuitable but a reproducible source installation
is required:

```sh
pipx install "arcshuttle @ git+https://github.com/bohemon/ArcShuttle.git@v0.3.0"
```

Replace `pipx install` with `python -m pip install` inside an existing virtual environment.
Installing `@main` intentionally tracks unreleased changes and is not recommended for a stable
end-user installation.

## Install the PowerShell modules

The v0.3.0 Release contains both `ArcShuttle` and the `Parxtract` compatibility module. The
following PowerShell 7 commands download the archive and its checksum, verify it, and install the
versioned module directories for the current user. They never execute downloaded text.

```powershell
$version = '0.3.0'
$release = "https://github.com/bohemon/ArcShuttle/releases/download/v$version"
$assetName = "ArcShuttle-PowerShell-$version.zip"
$downloadDir = Join-Path ([System.IO.Path]::GetTempPath()) "ArcShuttle-$version"
New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
$archive = Join-Path $downloadDir $assetName
$checksumFile = "$archive.sha256"

Invoke-WebRequest "$release/$assetName" -OutFile $archive
Invoke-WebRequest "$release/$assetName.sha256" -OutFile $checksumFile
$expected = ((Get-Content -LiteralPath $checksumFile -Raw).Trim() -split '\s+')[0]
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
if ($actual -ne $expected.ToLowerInvariant()) {
    throw "SHA-256 mismatch for $assetName"
}

if ($IsWindows) {
    $moduleRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\Modules'
} else {
    $moduleRoot = Join-Path $HOME '.local/share/powershell/Modules'
}
New-Item -ItemType Directory -Force -Path $moduleRoot | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $moduleRoot -Force

Test-ModuleManifest (Join-Path $moduleRoot "ArcShuttle/$version/ArcShuttle.psd1")
Import-Module ArcShuttle -RequiredVersion $version -Force
Get-Command -Module ArcShuttle
```

The `arcshuttle` CLI must also be on `PATH`; the PowerShell module invokes it rather than bundling
Python or 7-Zip. Import the compatibility module with
`Import-Module Parxtract -RequiredVersion 0.3.0` when required.

To remove the modules, close sessions using them and delete only these version directories:

```powershell
Remove-Item -LiteralPath (Join-Path $moduleRoot 'ArcShuttle/0.3.0') -Recurse
Remove-Item -LiteralPath (Join-Path $moduleRoot 'Parxtract/0.3.0') -Recurse
```

To update, set `$version` to the new published version and repeat the download, verification, and
extraction steps. PowerShell keeps each version in a separate directory; verify the new manifest
before deleting the old version directory.

Do not use `Invoke-Expression` (`iex`) on remote installation scripts. Downloading an artifact,
verifying its published checksum, and then expanding it keeps the executed code inspectable.

## Development checkout

A clone is needed only to modify ArcShuttle or run its complete test suite:

```sh
git clone https://github.com/bohemon/ArcShuttle.git
cd ArcShuttle
python -m pip install hatch
hatch run check
```

See the [command manual](COMMAND_MANUAL.en.md) for all commands, options, machine-readable output,
and safety contracts.
