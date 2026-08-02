---
title: ArcShuttle コマンド・オプションマニュアル
language: ja
manual_version: 2
applies_to_cli_version: 0.2.0
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

# ArcShuttle コマンド・オプションマニュアル

本書はArcShuttle 0.2.0を操作する人間およびAIエージェント向けの規範的リファレンスである。「必須」「禁止」「のみ許可」は安全上の要件を表す。stdoutはプロセスの標準出力バイト列、stderrは標準エラーを意味する。

## 1. 最小安全契約

1. 新規利用では`arcshuttle`を使う。`parxtract`は展開専用0.1構文との互換用途に限る。
2. `plan`の直後にoperationを置く。`arcshuttle plan`単体ではなく`arcshuttle plan extract`のように書く。
3. パス入力は位置引数`PATH...`、`--files-from`、`--files0-from`のうち厳密に1種類だけ選ぶ。
4. stdoutはUTF-8 JSON Lines専用とする。診断、選択した7-Zipバージョン、進捗はstderrへ出る。
5. 終了1または2でもstdoutをEOFまで読む。有効な結果とsummaryが出ている場合がある。
6. 完全なmanifestを検証してから実行する。外部filterが変更できるのは9章のallowlistだけである。
7. 成功させるためにsource、既存destination、保持された`.failed` stagingを削除してはならない。
8. 同一資源予算で扱うjob群は1つの`arcshuttle run`へ渡す。複数runをGNU Parallel等で包まない。

```sh
arcshuttle create folder-a file.dat
arcshuttle extract one.7z two.zip
arcshuttle plan create folder-a > create.jsonl
arcshuttle run --manifest create.jsonl > results.jsonl
```

## 2. コマンド構文

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

`-h`と`--help`は各parser階層のhelpを表示する。`--version`はCLI名とversionを表示する。共通optionは選択したsubcommandの後ろへ置く。互換`parxtract plan`はschema v1、primaryの`arcshuttle plan extract`と`plan create`はschema v2を出力する。

| コマンド | 入力 | stdout | 用途 |
|---|---|---|---|
| `plan extract` | archive file | schema-v2 `job` record | 検査して展開計画を作る |
| `plan create` | 通常fileまたはdirectory | schema-v2 `job` record | inventoryを作り、独立archiveを計画する |
| `run` | v1/v2 JSON Lines manifest | `result`後に`summary` | 全jobを1つのscheduleで検証・実行する |
| `extract` | archive file | `result`後に`summary` | 1回で計画・展開する |
| `create` | 通常fileまたはdirectory | `result`後に`summary` | 1回で計画・作成・検査・commitする |

`run --manifest -`だけがmanifestをstdinから読む。パスを受けるcommandはstdinを暗黙に読まない。

## 3. パス入力

| 形式 | 文字コード | 契約 |
|---|---|---|
| `PATH...` | OS引数の文字コード | shellでquoteした1件以上のパス |
| `--files-from FILE` | UTF-8 | 1行1パス。空行は無視 |
| `--files-from -` | UTF-8 | 明示的な改行区切りstdin |
| `--files0-from FILE` | UTF-8 | NUL区切り。末尾NUL可 |
| `--files0-from -` | UTF-8 | 明示的なNUL区切りstdin |

3形式は相互排他である。明示した空listは入力エラーとなる。相対パスはprocess working directory基準で正規化し、重複は最初の1件を残す。

展開は通常archive fileだけを受け、一般的なmultipart名を先頭volumeへ統合する。作成は通常fileまたはdirectoryを受ける。symlink、junction/reparse point、socket、deviceなどの非通常entryは追跡せず、source自身または子孫に1件でもあれば入力エラーとする。空directoryはinventoryに含め、保持する。

## 4. 全オプション一覧

適用範囲のPは両plan operation、Rは`run`、Eは`extract`、Cは`create`、Aは4つのoperation parserすべてを表す。

| オプション | 値 | 既定値 | 範囲 | 意味 |
|---|---|---|---|---|
| `-h`, `--help` | flag | - | 全parser階層 | 対象helpを表示 |
| `--version` | flag | - | 最上位 | versionを表示して終了 |
| `--7z PATH` | pathまたはcommand | 自動探索 | A | 7-Zip実行ファイルを選択 |
| `--output-dir DIR` | path | sourceの親 | A | 各独立最終出力のroot |
| `--existing {fail,skip,rename}` | enum | `fail` | A | 非破壊の既存出力policy |
| `--cpu-budget Nまたはauto` | integerまたは`auto` | 論理CPU数-1 | A | CPU token総数 |
| `--max-processes N` | 正整数 | `min(4,cpu_budget)` | A | 同時7-Zip process上限 |
| `--storage-profile {auto,hdd,ssd,nvme}` | enum | `auto` | A | 保守的I/O slot既定値の選択 |
| `--io-slots N` | 正整数 | profile依存 | A | I/O token総数 |
| `--heavy-threads N` | 正整数 | `min(4,cpu_budget)` | A | scalable jobのCPU/thread上限 |
| `--small-threshold SIZE` | size | `64M` | A | これ未満を`small`分類 |
| `--inspect-threshold SIZE` | size | `64M` | A | 展開検査のsize閾値 |
| `--inspect-timeout SECONDS` | 非負数 | `30` | A | 展開listingのtimeout |
| `--reservation-delay SECONDS` | 非負数 | `30` | A | queue先頭への予約を始める待ち時間 |
| `--sequential-if-total-below SIZE` | size | `0` | A | 小batchを1 process/1 I/O slot化 |
| `--log-dir DIR` | path | `.arcshuttle/logs` | A | run log root |
| `--config FILE` | path | なし | A | 明示TOML。global fileは暗黙に読まない |
| `--quiet` | flag | false | A | version/progress stderrを抑制。errorは残す |
| `--fail-fast` | flag | false | A | job失敗後の新規startを停止 |
| `--allow-changed` | flag | false | A | 安全なsource identity変更を警告付き許可 |
| `--on-input-error {fail,skip}` | enum | `fail` | A | 全plan抑制または有効jobだけ保持 |
| `--files-from FILE` | pathまたは`-` | なし | P/E/C | 明示的な改行パス入力 |
| `--files0-from FILE` | pathまたは`-` | なし | P/E/C | 明示的なNULパス入力 |
| `--manifest FILE` | pathまたは`-` | 必須 | R | 完全なJSON Lines manifest |
| `--format {7z,zip}` | enum | `7z` | create plan/C | 出力archive形式 |
| `--level 0..9` | integer | `5` | create plan/C | 圧縮level。0はstore mode |

sizeは非負整数に二進接尾辞`K`、`M`、`G`、`T`、`P`、`E`を付けられ、`B`または`iB`も許可する。例:`64M`、`1GiB`。`1.5G`は不可。

`--existing rename`は`name (2).7z`、`name (3).zip`、または同様の展開directoryを選ぶ。overwrite optionは存在しない。

## 5. 圧縮作成契約

圧縮第1版は入力source 1件ごとに独立archive 1個を作る。複数inputを1 archiveへ結合しない。将来は明示的なmulti-source manifestとして追加し得る。

| Source | 既定destination | Archive rootへ格納するもの |
|---|---|---|
| directory `photos/` | `photos.7z` | `photos/`の内容。余分な`photos/` prefixなし |
| file `data.bin` | `data.bin.7z` | basename `data.bin`だけ |

`--output-dir DIR`は各既定archive名を`DIR`直下へ置く。`--format zip`はsuffixを`.zip`にする。levelは0–9、計画methodは7zがLZMA2、zipがDeflateである。level 0は圧縮せずstoreする。利用者の任意raw 7-Zip optionは受け付けない。

planは正規化相対path、entry kind、通常file size、nanosecond mtimeを再帰inventoryし、通常file合計size、file数、directory数、最新mtime、決定的digest、source identityを記録する。実行直前に再inventoryする。identity変更は既定で失敗し、`--allow-changed`はmetadata/content集合の変更だけを警告付きで許可する。source kind変更や非通常entryは許可しない。

destination、staging、log rootがdirectory source内部へ入る構成は禁止する。名前除外ではなく、正規化・解決したpath関係で判定する。

作成job分類:

| 条件 | Profile | CPU token/thread | 理由 |
|---|---|---:|---|
| sizeが`small_threshold`未満 | `small` | 1 | `create-below-small-threshold` |
| smallでなくlevel 0 | `heavy-serial` | 1 | `create-store-mode` |
| その他の7z | `heavy-scalable` | `min(heavy_threads,cpu_budget)` | `create-7z-lzma2` |
| その他のzip | `heavy-scalable` | `min(heavy_threads,cpu_budget)` | `create-zip-deflate` |

CPU tokenと`-mmt=N`はmemoryを厳密に制限しない。LZMA2のmemory使用量はdictionaryやmethod設定にも依存する。ArcShuttle 0.2.0はmemory tokenや動的memory controllerを持たない。

## 6. 展開契約

既定の展開directory名は既知archive/multipart suffixを除く。`a.7z`は`a/`、`b.tar.gz`は`b/`、`c.7z.001`は`c/`、`d.part01.rar`は`d/`となる。

`.7z.001`、`.zip.001`、`.part1.rar`、`.part01.rar`、旧`.rar`+`.r00`、`.zip`+`.z01`を認識する。後続volumeを渡すと同directoryの先頭volumeを探し、なければ入力エラーとする。

大きいarchiveまたは形式不明archiveはtimeout付き`7z l -slt`で検査する。不明metadataはnullのままにする。timeout/失敗はwarningとなり、保守的に分類する。暗号化が確定したarchiveは実行時失敗とし、password入力や探索は対応しない。

展開profileは`small`、BZip2や独立7z block等の根拠がある`heavy-scalable`、保守的/検査失敗時の`heavy-serial`である。

## 7. 設定

高い順の優先順位:

```text
CLI
ARCSHUTTLE_* environment
PARXTRACT_* legacy environment
[arcshuttle] TOML
[parxtract] legacy TOML
legacy root-level TOML
built-in defaults
```

新名称は旧名称より優先する。legacy環境変数/TOML/rootはcreate導入前から存在したfieldだけを受ける。`create_format`と`compression_level`は新namespace限定である。未知TOML keyはerror。TOMLは`--config`で指定した場合だけ読む。

```toml
[arcshuttle]
sevenzip = "C:/Program Files/7-Zip/7z.exe"
output_dir = "D:/ArcShuttleOutput"
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
log_dir = "D:/ArcShuttleLogs"
quiet = false
fail_fast = false
allow_changed = false
on_input_error = "fail"
create_format = "7z"
compression_level = 5
```

| TOML key | 新環境変数 | 旧環境変数 |
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
| `create_format` | `ARCSHUTTLE_CREATE_FORMAT` | 受付不可 |
| `compression_level` | `ARCSHUTTLE_COMPRESSION_LEVEL` | 受付不可 |

boolean環境変数は大文字小文字を区別せず`1/0`、`true/false`、`yes/no`、`on/off`を受ける。

7-Zipは明示`--7z`または設定値、PATH上の`7zz`、`7z`、`7za`、Windows標準install先の順で探す。選択した実行ファイル/versionは`--quiet`がなければstderrへ表示する。

## 8. 共有スケジューラ

混在manifestも1つのschedulerを使い、常に次を満たす。

```text
sum(cpu_tokens) <= cpu_budget
running_jobs     <= max_processes
sum(io_tokens)  <= io_slots
```

順序はpriority降順、profile順位（`heavy-scalable`、`heavy-serial`、`small`）、estimated weight降順、plan indexである。queue先頭が入らない間は、収まる後続jobをbackfillできる。先頭が`reservation_delay`待つと新規backfillを止め、実行可能になるまで資源を予約する。

`--fail-fast`はfailed result後の新規startを止め、実行中jobを完了させ、未開始jobをskippedにする。割り込みは新規startを止め、管理child process groupへ通知し、安全に待機/終了してinterruptedを返す。v2 resultの最終出力順は完了順でなく決定的なplan順である。

## 9. Manifest契約

### 9.1 Schema v2

primary plannerは次の共通構造を出す。

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

展開はoperation `extract`、source kind `file`、destination kind `directory`とbest-effort archive検査fieldを使う。

外部filterが変更できるfieldは次だけである。

```text
destination.path
scheduling.profile
scheduling.priority
scheduling.cpu_tokens
scheduling.threads
tags
```

その他はintegrityで保護する。変更後destinationも絶対path、一意、安全でなければならない。CPU/thread上書きは型検査後に設定CPU予算までclampし、warningを付ける。I/O tokenは変更不可で予算内が必須。`integrity`を再計算・削除してはならない。

```sh
arcshuttle plan create dir-a dir-b |
  jq -c 'if .tags | index("urgent") then .scheduling.priority = 100 else . end' |
  arcshuttle run --manifest -
```

### 9.2 Schema-v1互換

`parxtract plan`は`path`と`output_dir`を持つ展開専用v1構造を変更せず出す。`arcshuttle run`と`parxtract run`はv1を読み、内部でextract jobへ変換する。v1 allowlistは`output_dir`、同じ4 scheduling上書きfield、`tags`のままである。v1 result shapeへv2限定fieldを追加しない。

v1 extract jobとv2 jobを同一manifestへ混在できる。v2 inputが1件でもあれば全体summaryはschema v2となる。

## 10. Staging・検査・result・log

### 10.1 展開

最終directoryの隣に`.arcshuttle-<job-id>-<random>.tmp`を作り、`.arcshuttle-owned`を書いて7-Zipを実行する。終了0だけをdestination再確認後にcommitする。warning、failure、interruptionは所有stagingを`.failed`として保持する。所有確認できないpathは移動・削除しない。

### 10.2 作成

作成は次の順序を厳守する。

1. unsafeなsource/destination/log関係を拒否する。
2. 再inventoryしてsource identityを比較する。
3. 上書きせず`--existing`を解決する。
4. 最終archiveの隣にprivateな所有marker付きstaging directoryを作る。
5. 制御working directory、相対source引数、閉じたstdin、引数配列、`shell=False`で`7z a`を実行する。
6. create終了0と通常staged archiveを必須にする。
7. `7z t`を実行し、verification終了0を必須にする。
8. destination不存在を再確認し、既存pathをclobberせず原子的に公開する。
9. 所有確認した空stagingだけを削除する。

create/testのwarning、failure、interruption、commit前問題ではstagingを`.failed`として保持する。sourceを移動・変更・削除しない。

### 10.3 Result

statusは`success`、`warning`、`failed`、`skipped`、`interrupted`である。すべてのv2 resultは`operation`、`output_path`、`staging_path`とlegacy aliasの`output_dir`/`staging_dir`を含む。create resultは`create_exit_code`と`verification_exit_code`も含み、process未起動ならnullになり得る。`log_path`は存在するjob logを指す。

最後のrecordは必ず`summary`で、5 statusの件数、total、`duration_ms`を持つ。

| Process終了 | 意味 | JSON Linesの可能性 |
|---:|---|:---:|
| 0 | 全jobがwarningなし成功 | あり |
| 1 | warning/skip/result warningがありfailureなし | あり |
| 2 | 1件以上failed | あり |
| 64 | usage、設定、入力、manifest error | 通常なし |
| 130 | interrupted | あり |

### 10.4 Log

既定rootは`<cwd>/.arcshuttle/logs/<run-id>/<job-id>/`。

展開logは`metadata.json`、`stdout.log`、`stderr.log`。作成logは`metadata.json`、`create.stdout.log`、`create.stderr.log`、`test.stdout.log`、`test.stderr.log`。作成metadataは安全な実引数配列、working directory、割当CPU/thread、process時刻/終了、error、commit結果を記録する。7-Zip出力をJSON stdoutへ混ぜない。

## 11. PowerShell 7

```powershell
Import-Module ./powershell/ArcShuttle.psm1

Get-ChildItem C:\Sources -Directory |
    Invoke-ArcShuttleCreatePlan -Format 7z -Level 5 |
    Invoke-ArcShuttleRun

Get-ChildItem C:\Archives -File |
    Invoke-ArcShuttleExtract -OutputDir C:\Extracted
```

| 関数 | Pipeline入力 | 対応operation |
|---|---|---|
| `Invoke-ArcShuttleExtractPlan` | stringまたは`FileSystemInfo` | `plan extract` |
| `Invoke-ArcShuttleCreatePlan` | stringまたは`FileSystemInfo` | `plan create`。各itemは独立 |
| `Invoke-ArcShuttleRun` | job object | `run` |
| `Invoke-ArcShuttleExtract` | stringまたは`FileSystemInfo` | 展開plan後run |
| `Invoke-ArcShuttleCreate` | stringまたは`FileSystemInfo` | 作成plan後run |

PowerShell parameterは名前対応する:`-ArcShuttleCommand`、`-SevenZip`/`-7z`、`-OutputDir`、`-Existing`、`-CpuBudget`、`-MaxProcesses`、`-StorageProfile`、`-IoSlots`、`-HeavyThreads`、`-SmallThreshold`、`-InspectThreshold`、`-InspectTimeout`、`-ReservationDelay`、`-SequentialIfTotalBelow`、`-LogDir`、`-Config`、`-OnInputError`、`-Quiet`、`-FailFast`、`-AllowChanged`。create plan/combined functionは`-Format`と`-Level`も受ける。

moduleはBOMなしUTF-8 NUL入力またはJSON Linesを一時fileへ書き、native CLI stdoutだけを`ConvertFrom-Json`し、PowerShell success streamへ`PSCustomObject` recordを出力し、stderrを再表示し、`$LASTEXITCODE`を保持し、`finally`で一時fileを削除する。

互換用`powershell/Parxtract.psm1`は`Invoke-ParxtractPlan`、`Invoke-ParxtractRun`、`Invoke-Parxtract`を維持する。同じobject出力contractに従う。

### 11.1 出力contractと永続化

native CLIとPowerShell moduleは意図的に異なるsurfaceを公開する:

| Surface | Success出力 | 主な用途 |
|---|---|---|
| `arcshuttle plan` / `parxtract plan` | canonical UTF-8 JSON Lines | portable manifest、永続保存、連結、PowerShell以外のtool |
| `Invoke-ArcShuttle*Plan` / `Invoke-ParxtractPlan` | `PSCustomObject` record | PowerShellでの確認、編集、変数保持、object pipeline |

同一PowerShell session内でplanして実行する場合はobjectのまま扱う:

```powershell
$plans = @(
    Get-ChildItem C:\Archives -File |
        Invoke-ArcShuttleExtractPlan
)

$plans | Select-Object plan_index, operation, source, destination
$plans | Invoke-ArcShuttleRun
```

file拡張子はserializerを選択しない。次のcommandはPowerShell display formattingを起動し、manifestを作成**しない**:

```powershell
# 無効な永続化: file内容はJSON Linesではなく、情報を失ったdisplay formattingとなる。
Get-ChildItem C:\Archives -File |
    Invoke-ArcShuttleExtractPlan > extract.jsonl
Get-ChildItem C:\Sources -Directory |
    Invoke-ArcShuttleCreatePlan > create.jsonl
Get-ChildItem C:\Archives -File |
    Invoke-ParxtractPlan > legacy.jsonl
```

`name : value`、`@{...}`、`System.Object[]`のようなtextから安全に復元することはできない。このfileを`run`へ渡したり修復を試みたりせず、sourceから再planする。

canonical JSON Linesが必要な場合はPowerShellからnative CLIを使う:

```powershell
$archives = @(
    Get-ChildItem C:\Archives -File |
        Select-Object -ExpandProperty FullName
)
$sources = @(
    Get-ChildItem C:\Sources |
        Select-Object -ExpandProperty FullName
)

arcshuttle plan extract -- $archives > extract.jsonl
arcshuttle plan create --format 7z -- $sources > create.jsonl
parxtract plan -- $archives > legacy-extract.jsonl

Get-Content -LiteralPath .\extract.jsonl |
    ConvertFrom-Json -Depth 100 |
    Select-Object plan_index, operation, source, destination

arcshuttle run --manifest .\extract.jsonl > results.jsonl
```

native command lineの上限を超えるpath集合には、3章のCLI `--files0-from`入力を使う。

有効なJSON Lines manifestはrecord streamであり、PowerShell objectへparseせずに結合できる:

```powershell
Get-Content -LiteralPath .\extract-a.jsonl, .\extract-b.jsonl |
    Set-Content -LiteralPath .\combined.jsonl -Encoding utf8NoBOM

arcshuttle run --manifest .\combined.jsonl > results.jsonl
```

各入力fileは、空白でない物理行ごとに完全なJSON objectを1つだけ含む必要がある。ArcShuttleはjob開始前に結合manifest全体を検証する。重複する`job_id`とoutput collisionは拒否する。独立したplan間では`plan_index`が重複してもよい。`plan_index`は`integrity`で保護されるため、連番へ振り直してはならない。

PowerShell専用のsession間snapshotには、CLIXMLでobjectを明示的にserializeする:

```powershell
$planA | Export-Clixml -LiteralPath .\plan-a.clixml -Depth 100
$planB | Export-Clixml -LiteralPath .\plan-b.clixml -Depth 100

$plans = @(
    Import-Clixml -LiteralPath .\plan-a.clixml
    Import-Clixml -LiteralPath .\plan-b.clixml
)
$plans | Invoke-ArcShuttleRun
```

同じpatternを`Invoke-ParxtractPlan`と`Invoke-ParxtractRun`にも使える。CLIXMLはPowerShell object snapshotであり、ArcShuttle manifestではない。`arcshuttle run --manifest`は受理せず、完全なCLIXML documentをraw textとして連結することもできない。各snapshotをimportし、得られたobject listを結合する。deserialize後のobjectはrun commandに必要なmanifest data propertyを保持するが、元のmethodを持つlive objectではなくsnapshotである。

## 12. POSIX例

```sh
# 作成jobを確認してから実行する。
find /data/source -mindepth 1 -maxdepth 1 -print0 |
  arcshuttle plan create --files0-from - --format 7z > create.jsonl
jq -e -c 'select(.record_type == "job")' create.jsonl |
  arcshuttle run --manifest - > results.jsonl

# 直接展開する。
fd --type f --print0 . /data/archives |
  arcshuttle extract --files0-from - --output-dir /data/out
```

shell pipeline全体のstatusが必要なら`set -o pipefail`を使う。ただしplan終了1でも有効jobがあるため、warning policyが重要な場合はplan stdoutと終了statusを別々に保存する。

## 13. parxtract 0.1からの移行

- 配布名`arcshuttle`をinstallする。両console scriptを含む。
- schema-v2計画へ移るとき`parxtract plan ...`を`arcshuttle plan extract ...`へ変更する。
- 準備できたら`parxtract extract ...`を`arcshuttle extract ...`へ変更する。互換commandも動作を維持する。
- 既存schema-v1 manifestは引き続き受理し、内部でextract jobへ変換する。
- 新primary planはoperation/source/destination identity/integrityを持つschema v2を出す。
- `ARCSHUTTLE_*`を優先して使う。新旧の対応変数が同時指定なら新名称を優先する。
- `[arcshuttle]`を優先する。`[parxtract]`とroot-level値を上書きする。
- create fieldにlegacy環境変数/TOML aliasはない。
- 既存`.parxtract` dataは移行、改名、所有、削除しない。手動確認し、ArcShuttleは新しい`.arcshuttle`名へ書く。
- 新PowerShell workflowは`ArcShuttle.psm1`をimportする。`Parxtract.psm1`は互換維持する。

## 14. AIエージェント手順

1. plan前に`arcshuttle --version`、7-Zip利用可否、operation、出力formatを確認する。
2. 自動生成・任意文字pathにはNUL入力を使う。暗黙stdinを想定しない。
3. 作成では各sourceが独立archiveになる意図と、output/log rootがdirectory source外であることを確認する。
4. stdout/stderrを分離し、stdoutをEOFまでJSON Lines解析する。
5. 全plan recordが意図したoperationの`job`で、destinationが一意か確認する。
6. filter時はv2 allowlistだけを変更する。`integrity`を再生成せず、source/archive/inventory/I/O fieldを変更しない。
7. 完全streamを1つの`run` processへ渡し、資源上限をglobalに保つ。
8. 全resultと最後のsummaryを読み、status、warning、process終了を合わせて判定する。
9. nullでない`staging_path`と`log_path`を報告し、保持物を自動削除しない。
10. password/raw 7-Zip option注入、既存出力削除、source変更、拒否link追跡、外部overwrite回避をしない。

機械判定概要:

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

## 15. 依存policy・制限・troubleshooting

install packageは意図的にthird-party runtime dependencyを持たない。標準libraryによるpath、TOML、JSON、hash、scheduling、process safety実装を監査可能に保つ。Hatch development環境だけが`pytest`、`pytest-timeout`、Ruffを使い、test分離、timeout、lint、formatの明確なCI価値を得る。

圧縮第1版は1 source/1 archive、7z/zip、level 0–9、通常entry、local非分割出力だけを扱う。multi-source archive、分割作成、暗号化作成、password、nested再帰処理、raw method調整、実行中資源再配分、disk自動判定、memory予算、GUI、watch serviceは対象外である。

| 症状 | 確認 | 安全な対処 |
|---|---|---|
| `7-Zip not found` | `--7z`、`ARCSHUTTLE_7Z`、PATH | 対応実行ファイルを設定 |
| 終了64かつstdout空 | stderrのusage/input/manifest error | 構文修正または再plan。recordを捏造しない |
| 終了1で出力あり | warning/skip/result warning | summaryを解析し詳細報告 |
| source identity changed | plan後の変更 | 再plan。意図時だけ`--allow-changed` |
| immutable field modified | 外部filter | 元planからallowlistだけ編集し直す |
| output collision | 派生/編集path重複 | destinationを一意化 |
| `.failed`が残る | create/test/extract warningまたはfailure | log確認後に手動回収 |
| HDD throughput低下 | I/O競合 | `hdd`または`--io-slots 1`を選択 |
