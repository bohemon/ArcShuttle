# ArcShuttle インストールガイド

このガイドでは、ソースコードをチェックアウトせずに行う、エンドユーザー向けの安定した
インストール方法を中心に説明する。コマンドはv0.3.1に固定し、`main`ブランチの変更によって
インストール結果が変わらないようにしている。タグ付きソースからのインストールと開発用
チェックアウトは、別の選択肢として後半で説明する。

## 必要環境

- WindowsまたはLinux
- Python 3.11以降
- 現行の`7zz`、`7z`、または`7za`の実行ファイル
- PowerShell 7（任意のオブジェクトパイプライン用モジュールを使う場合のみ）

## CLIのインストール

### 推奨：pipxによる仮想環境へのインストール

[pipx](https://pipx.pypa.io/)はコマンドラインアプリケーションごとに仮想環境を作り、
コマンドを`PATH`から実行できるようにする。利用するプラットフォームに合う方法でpipxを
インストールした後、次を実行する：

```sh
pipx install "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.1/arcshuttle-0.3.1-py3-none-any.whl"
arcshuttle --version
parxtract --version
```

同じバージョンを更新または再インストールする場合は、次を実行する：

```sh
pipx install --force "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.1/arcshuttle-0.3.1-py3-none-any.whl"
```

削除は`pipx uninstall arcshuttle`で行う。

### 既存の仮想環境

仮想環境を有効化し、GitHubリリースのwheelファイルを直接インストールする：

```sh
python -m pip install "https://github.com/bohemon/ArcShuttle/releases/download/v0.3.1/arcshuttle-0.3.1-py3-none-any.whl"
arcshuttle --version
```

OSが管理するPython環境を直接変更せず、仮想環境を使用する。
GitHubリリースの新しいwheelファイルへ更新する場合は、URL中のバージョンを変更し、コマンドに
`--upgrade`を追加する。
削除は`python -m pip uninstall arcshuttle`で行う。

### 代替：タグ付きソースからのインストール

GitHubリリースのwheelファイルが適さず、ソースから再現可能な形でインストールする必要がある場合は、
タグまたはコミットを指定する：

```sh
pipx install "arcshuttle @ git+https://github.com/bohemon/ArcShuttle.git@v0.3.1"
```

既存の仮想環境では、`pipx install`を`python -m pip install`へ置き換える。`@main`からの
インストールは未リリースの変更へ追従するため、エンドユーザー向けの安定したインストールには
推奨しない。

## PowerShell モジュールのインストール

v0.3.1のリリースには、`ArcShuttle`モジュールと互換用の`Parxtract`モジュールが含まれる。
次のコマンドをPowerShell 7で実行すると、アーカイブとチェックサムをダウンロードして検証した後、
`CurrentUser`用のバージョン別モジュールディレクトリへインストールする。ダウンロードした
テキストを実行することはない。

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

PowerShell モジュールはPythonや7-Zipを同梱せず、`arcshuttle` CLIを呼び出すため、CLIも
`PATH`上に必要となる。互換モジュールが必要な場合は、
`Import-Module Parxtract -RequiredVersion $version`でインポートする。

モジュールを削除する場合は、利用中のセッションを閉じ、次のバージョン別ディレクトリだけを
削除する：

```powershell
$removeVersion = '0.3.1'
if ($IsWindows) {
    $moduleRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\Modules'
} else {
    $moduleRoot = Join-Path $HOME '.local/share/powershell/Modules'
}
Remove-Item -LiteralPath (Join-Path $moduleRoot "ArcShuttle/$removeVersion") -Recurse
Remove-Item -LiteralPath (Join-Path $moduleRoot "Parxtract/$removeVersion") -Recurse
```

更新する場合は、`$version`を公開済みの新しいバージョンへ変更し、ダウンロード、検証、展開を
再実行する。PowerShellではバージョンごとに別のディレクトリへ配置されるため、新しい
モジュール マニフェストを検証してから旧バージョンのディレクトリを削除する。

リモートインストールスクリプトを`Invoke-Expression`（`iex`）へ渡してはならない。
成果物をダウンロードし、公開チェックサムを検証してから展開すれば、実行対象のコードを
検査できる状態に保てる。

## 開発用チェックアウト

ArcShuttleを変更する場合や、完全なテストスイートを実行する場合にのみクローンが必要となる：

```sh
git clone https://github.com/bohemon/ArcShuttle.git
cd ArcShuttle
python -m pip install hatch
hatch run check
```

すべてのコマンド、オプション、機械可読出力、安全性仕様については、
[コマンドマニュアル](COMMAND_MANUAL.ja.md)を参照する。
