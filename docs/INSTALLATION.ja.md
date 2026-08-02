# ArcShuttle インストールガイド

このガイドでは、sourceをcheckoutせずにArcShuttleをinstallする。commandはv0.3.1へ固定し、
`main`が変更されてもinstall結果が変わらないようにする。

## 必要環境

- WindowsまたはLinux
- Python 3.11以降
- 現行の`7zz`、`7z`、または`7za`実行file
- optionalなobject-pipeline moduleを使う場合のみPowerShell 7

## CLIのinstall

### 推奨: pipxによる分離install

[`pipx`](https://pipx.pypa.io/)はCLI applicationごとに分離環境を作り、commandを`PATH`へ
公開する。platformに合う方法でpipxをinstallした後、次を実行する:

```sh
pipx install "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.1/arcshuttle-0.3.1-py3-none-any.whl"
arcshuttle --version
parxtract --version
```

この固定releaseをupgradeまたは再installする:

```sh
pipx install --force "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.1/arcshuttle-0.3.1-py3-none-any.whl"
```

削除は`pipx uninstall arcshuttle`で行う。

### 既存のvirtual environment

environmentをactivateし、Release wheelを直接installする:

```sh
python -m pip install "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.1/arcshuttle-0.3.1-py3-none-any.whl"
arcshuttle --version
```

OSが管理するPython環境を直接変更せず、virtual environmentを使用する。
新しいRelease wheelへ更新する場合はURL中のversionを変更してcommandへ`--upgrade`を追加する。
削除は`python -m pip uninstall arcshuttle`で行う。

### Gitからのinstall

Release wheelが適さず、再現可能なsource installが必要な場合はtagまたはcommitを指定する:

```sh
pipx install "arcshuttle @ git+https://github.com/bohemon/ArcShuttle.git@v0.3.1"
```

既存virtual environmentでは`pipx install`を`python -m pip install`へ置き換える。`@main`の
installは未releaseの変更へ追従するため、安定したend-user installには推奨しない。

## PowerShell moduleのinstall

v0.3.1 Releaseには`ArcShuttle`と互換用`Parxtract` moduleの両方が含まれる。次の
PowerShell 7 commandはarchiveとchecksumをdownloadし、検証してからCurrentUser用のversion付き
module directoryへinstallする。downloadしたtextを実行することはない。

```powershell
$version = '0.3.1'
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

PowerShell moduleはPythonや7-Zipを同梱せず`arcshuttle` CLIを呼び出すため、CLIも`PATH`上に
必要となる。互換moduleが必要な場合は
`Import-Module Parxtract -RequiredVersion 0.3.1`でimportする。

moduleを削除する場合は、利用中のsessionを閉じ、次のversion directoryだけを削除する:

```powershell
Remove-Item -LiteralPath (Join-Path $moduleRoot 'ArcShuttle/0.3.1') -Recurse
Remove-Item -LiteralPath (Join-Path $moduleRoot 'Parxtract/0.3.1') -Recurse
```

更新する場合は`$version`を公開済みの新versionへ変更し、download、検証、展開を再実行する。
PowerShellではversionごとに別directoryへ配置されるため、新manifestを検証してから旧version
directoryを削除する。

remote install scriptを`Invoke-Expression`（`iex`）へ渡してはならない。artifactをdownloadし、
公開checksumを検証してから展開すれば、実行対象codeを検査可能な状態に保てる。

## 開発用checkout

ArcShuttleを変更する場合や完全なtest suiteを実行する場合にのみcloneが必要となる:

```sh
git clone https://github.com/bohemon/ArcShuttle.git
cd ArcShuttle
python -m pip install hatch
hatch run check
```

全command、option、machine-readable output、安全性contractは
[コマンドマニュアル](COMMAND_MANUAL.ja.md)を参照する。
