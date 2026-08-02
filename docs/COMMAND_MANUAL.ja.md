---
title: ArcShuttle コマンド・オプションマニュアル
language: ja
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

# ArcShuttle コマンド・オプションマニュアル

本書は、ArcShuttle 0.3.1の利用者とAIエージェント向けの規範的なリファレンスである。「必須」「禁止」「～のみ許可」は安全上の要件を表す。標準出力（`stdout`）はプロセスの標準出力バイト列、標準エラー出力（`stderr`）はプロセスの標準エラー出力を意味する。

## 1. 安全に利用するための基本要件

1. 新規利用では`arcshuttle`を使う。`parxtract`は展開専用の0.1構文との互換用途に限る。
2. `plan`の直後に操作名を置く。`arcshuttle plan`単体ではなく、`arcshuttle plan extract`のように書く。
3. パス入力は位置引数`PATH...`、`--files-from`、`--files0-from`のうち厳密に1種類だけ選ぶ。
4. 標準出力はUTF-8 JSON Lines専用とする。診断、選択した7-Zipのバージョン、進捗は標準エラー出力へ書き込まれる。
5. 終了コードが1または2でも標準出力をEOFまで読む。有効な結果と`summary`が出力されている場合がある。
6. 完全なマニフェストを検証してから実行する。外部フィルターが変更できるのは9章の許可リストにあるフィールドだけである。
7. 処理を成功させるために、入力元、既存の出力先、保持された`.failed`ステージングを削除してはならない。
8. 同じ資源予算で扱うジョブ群は、1つの`arcshuttle run`コマンドへ渡す。複数の`run`コマンドをGNU Parallelなどから並列実行しない。

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

`-h`と`--help`は、各パーサー階層に対応するヘルプを表示する。`--version`はCLI名とバージョンを表示する。共通オプションは、選択したサブコマンドの後ろへ置く。互換用の`parxtract plan`コマンドはスキーマv1を出力し、主要な`arcshuttle plan extract`コマンドと`arcshuttle plan create`コマンドはスキーマv2を出力する。

| コマンド | 入力 | 標準出力 | 用途 |
|---|---|---|---|
| `plan extract` | アーカイブファイル | スキーマv2の`job`レコード | 検査して展開計画を作る |
| `plan create` | 通常ファイルまたはディレクトリ | スキーマv2の`job`レコード | インベントリを作り、独立したアーカイブを計画する |
| `run` | v1/v2のJSON Linesマニフェスト | `result`の後に`summary` | 全ジョブを1つのスケジュールで検証・実行する |
| `extract` | アーカイブファイル | `result`の後に`summary` | 1回の呼び出しで計画・展開する |
| `create` | 通常ファイルまたはディレクトリ | `result`の後に`summary` | 1回の呼び出しで計画・作成・検証・確定する |

`run --manifest -`だけがマニフェストを標準入力から読み込む。パスを受け付けるコマンドは標準入力を暗黙には読み込まない。

## 3. パス入力

| 形式 | 文字コード | 仕様 |
|---|---|---|
| `PATH...` | OS引数の文字コード | シェルで引用した1件以上のパス |
| `--files-from FILE` | UTF-8 | 1行1パス。空行は無視 |
| `--files-from -` | UTF-8 | 明示的な改行区切り標準入力 |
| `--files0-from FILE` | UTF-8 | NUL区切り。末尾NUL可 |
| `--files0-from -` | UTF-8 | 明示的なNUL区切り標準入力 |

3形式は相互排他である。明示的に空のリストを渡すと入力エラーになる。相対パスはプロセスの作業ディレクトリを基準に正規化し、重複時は最初の1件を残す。

`extract`コマンドは通常のアーカイブファイルだけを受け付け、一般的な分割アーカイブ名は先頭ボリュームのパスに正規化する。`create`コマンドは通常のファイルまたはディレクトリを受け付ける。シンボリックリンク、ジャンクション／再解析ポイント、ソケット、デバイスなどの特殊なエントリはたどらず、入力元またはその配下に1件でも含まれていれば入力エラーとする。空のディレクトリはインベントリに含めて保持する。

## 4. 全オプション一覧

適用範囲のPは2つの`plan`操作、Rは`run`、Eは`extract`、Cは`create`、Aは4つの操作パーサーすべてを表す。

| オプション | 値 | 既定値 | 範囲 | 意味 |
|---|---|---|---|---|
| `-h`, `--help` | フラグ | - | 全パーサー階層 | 対象のヘルプを表示 |
| `--version` | フラグ | - | 最上位 | バージョンを表示して終了 |
| `--7z PATH` | パスまたはコマンド | 自動探索 | A | 7-Zip実行ファイルを選択 |
| `--output-dir DIR` | パス | 入力元の親 | A | 各出力先の基準ディレクトリ |
| `--existing {fail,skip,rename}` | 列挙値 | `fail` | A | 既存出力を非破壊で扱う方針 |
| `--cpu-budget Nまたはauto` | 整数または`auto` | 論理CPU数-1 | A | CPUトークンの総数 |
| `--max-processes N` | 正整数 | `min(4,cpu_budget)` | A | 同時に実行する7-Zipプロセスの上限 |
| `--storage-profile {auto,hdd,ssd,nvme}` | 列挙値 | `auto` | A | 実行時判定または固定I/Oスロットプロファイル |
| `--io-slots N` | 正整数 | 自動判定／プロファイル依存 | A | I/Oトークンの総数。明示値を優先 |
| `--heavy-threads N` | 正整数 | `min(4,cpu_budget)` | A | 並列化可能なジョブのCPU／スレッド上限 |
| `--small-threshold SIZE` | サイズ | `64M` | A | これ未満の入力を`small`に分類 |
| `--inspect-threshold SIZE` | サイズ | `64M` | A | 展開検査を行うサイズ閾値 |
| `--inspect-timeout SECONDS` | 非負数 | `30` | A | 展開時の一覧取得タイムアウト |
| `--reservation-delay SECONDS` | 非負数 | `30` | A | キュー先頭への予約を始める待ち時間 |
| `--sequential-if-total-below SIZE` | サイズ | `0` | A | 小規模バッチを1プロセス／1 I/Oスロットで実行 |
| `--log-dir DIR` | パス | `.arcshuttle/logs` | A | 実行ログの基準ディレクトリ |
| `--config FILE` | パス | なし | A | 明示的なTOMLファイル。グローバルファイルは暗黙に読まない |
| `--quiet` | フラグ | `false` | A | バージョン／進捗の標準エラー出力を抑制。エラーは残す |
| `--fail-fast` | フラグ | `false` | A | ジョブ失敗後に新しいジョブの開始を停止 |
| `--allow-changed` | フラグ | `false` | A | 安全な入力元の同一性変更を、警告を出して許可 |
| `--on-input-error {fail,skip}` | 列挙値 | `fail` | A | 計画全体の出力を抑止、または有効なジョブだけを保持 |
| `--files-from FILE` | パスまたは`-` | なし | P/E/C | 明示的な改行区切りパス入力 |
| `--files0-from FILE` | パスまたは`-` | なし | P/E/C | 明示的なNUL区切りパス入力 |
| `--manifest FILE` | パスまたは`-` | 必須 | R | 完全なJSON Linesマニフェスト |
| `--format {7z,zip}` | 列挙値 | `7z` | `plan create`/C | 出力アーカイブ形式 |
| `--level 0..9` | 整数 | `5` | `plan create`/C | 圧縮レベル。0は無圧縮で格納 |

サイズ値には、非負整数と二進接尾辞`K`、`M`、`G`、`T`、`P`、`E`を指定でき、`B`または`iB`も付けられる。例：`64M`、`1GiB`。`1.5G`は指定できない。

`--existing rename`は`name (2).7z`、`name (3).zip`、または同様の名前を持つ展開先ディレクトリを選ぶ。上書きオプションは存在しない。

## 5. `create`コマンドの動作仕様

`create`コマンドは、入力元1件につき独立したアーカイブを1個作る。複数の入力を1個のアーカイブには結合しない。

| 入力元 | 既定の出力先 | アーカイブのルートに格納するもの |
|---|---|---|
| ディレクトリ`photos/` | `photos.7z` | `photos/`の内容。上位に余分な`photos/`階層を追加しない |
| ファイル`data.bin` | `data.bin.7z` | ベース名`data.bin`だけ |

`--output-dir DIR`は、既定の各アーカイブ名を`DIR`直下へ置く。`--format zip`は拡張子を`.zip`にする。圧縮レベルは0～9で、計画上の方式は`7z`がLZMA2、`zip`がDeflateである。レベル0は圧縮せずに格納する。利用者が指定する任意の未加工7-Zipオプションは受け付けない。

`plan create`コマンドは、決定的なインベントリと入力元の同一性情報を記録し、実行直前に再度インベントリを取得する。同一性情報が変化していると既定では失敗する。`--allow-changed`は、安全なメタデータまたは内容集合の変更に限り、警告を出したうえで許可する。`source.kind`の変更や特殊なエントリは許可しない。

出力先、ステージング、ログの基準ディレクトリを入力元ディレクトリの内部に置く構成は禁止する。名前による除外ではなく、正規化・解決したパスの関係で判定する。

作成ジョブの分類：

| 条件 | プロファイル | CPUトークン／スレッド |
|---|---|---:|
| サイズが`small_threshold`未満 | `small` | 1 |
| `small`ではなく圧縮レベル0 | `heavy-serial` | 1 |
| その他の`7z`または`zip`作成 | `heavy-scalable` | `min(heavy_threads,cpu_budget)` |

CPUトークンと`-mmt=N`はメモリを厳密には制限しない。LZMA2のメモリ使用量は、辞書や圧縮方式の設定にも依存する。

## 6. `extract`コマンドの動作仕様

既定の展開先ディレクトリ名は、既知のアーカイブ拡張子や分割アーカイブ接尾辞を除いて決める。`a.7z`は`a/`、`b.tar.gz`は`b/`、`c.7z.001`は`c/`、`d.part01.rar`は`d/`となる。

`.7z.001`、`.zip.001`、`.part1.rar`、`.part01.rar`、旧形式の`.rar`+`.r00`、`.zip`+`.z01`を認識する。後続ボリュームを渡すと同じディレクトリの先頭ボリュームを探し、見つからなければ入力エラーとする。

大きいアーカイブまたは形式不明のアーカイブは、タイムアウト付きの`7z l -slt`で検査する。不明なメタデータは`null`のままにする。タイムアウトまたは検査失敗は警告となり、保守的な分類を使う。暗号化されていることが確定したアーカイブは実行時に失敗する。パスワードの入力や探索には対応しない。

展開プロファイルは`small`、BZip2や独立した`7z`ブロックなどの根拠がある場合の`heavy-scalable`、保守的な判定または検査失敗時の`heavy-serial`である。

## 7. 設定

高い順の優先順位：

```text
CLI
ARCSHUTTLE_* 環境変数
PARXTRACT_* 旧環境変数
[arcshuttle] TOML
[parxtract] 旧TOML
従来のルートレベルTOML
組み込み既定値
```

新名称は旧名称より優先する。旧環境変数、旧TOML、従来のルートレベルTOMLは、`create`コマンドの導入前から存在したフィールドだけを受け付ける。`create_format`と`compression_level`は新しい名前空間でだけ指定できる。未知のTOMLキーはエラーとなる。TOMLファイルは`--config`で指定した場合だけ読み込む。

```toml
[arcshuttle]
sevenzip = "C:/Program Files/7-Zip/7z.exe"
output_dir = "D:/ArcShuttleOutput"
existing = "rename"
cpu_budget = 8
storage_profile = "auto"
create_format = "7z"
compression_level = 5
```

対応するすべての設定キーと環境変数の別名を次の表に示す。省略したキーには4章の既定値を使う。

| TOMLキー | 新環境変数 | 旧環境変数 |
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

真偽値の環境変数は、大文字小文字を区別せず`1/0`、`true/false`、`yes/no`、`on/off`を受け付ける。

7-Zipは、明示した`--7z`または設定値、`PATH`上の`7zz`、`7z`、`7za`、Windowsの標準インストール先の順で探す。選択した実行ファイルとバージョンは、`--quiet`がなければ標準エラー出力へ表示する。

## 8. 共有スケジューラ

異なる操作が混在するマニフェストも1つのスケジューラを使い、常に次を満たす。

```text
sum(cpu_tokens) <= cpu_budget
running_jobs     <= max_processes
sum(io_tokens)  <= io_slots
```

スケジュールは、優先度、プロファイル、推定負荷、計画上の順序を考慮する。利用可能な資源に収まる後続ジョブは空き資源を利用できるが、`reservation_delay`経過後はキューの先頭へ資源を予約して飢餓状態を防ぐ。

`storage_profile = "auto"`かつ`--io-slots`が明示されていない場合、`run`、`extract`、`create`の各コマンドは、実行直前に検証済みの入力元と出力先が属するデバイスを調べる。割り当てはHDD = 1、SSD = 2、NVMe = 4、不明 = 2 I/Oスロットであり、重複しないデバイスのうち最小値を採用して`max_processes`を上限とする。判定に失敗した場合は不明時の代替値を使い、実行を妨げない。単独の`plan`コマンドはストレージを調査しないため、マニフェストを別のマシンへ移して利用できる。明示的な`--io-slots`を最優先し、明示的な`hdd`、`ssd`、`nvme`プロファイルには固定の既定値を使う。有効値と理由は、`--quiet`がなければ標準エラー出力へ書き込む。

`--fail-fast`は、ステータスが`failed`の`result`レコードが出た後に、新しいジョブの開始を止める。実行中のジョブは完了させ、未開始のジョブは`skipped`にする。割り込み時は新しいジョブの開始を止め、管理対象の子プロセスグループへ通知し、安全に待機または終了して`interrupted`を返す。v2の`result`レコードは、完了順ではなく決定的な計画順で最終出力する。

## 9. マニフェスト仕様

### 9.1 スキーマv2

`arcshuttle plan extract`と`arcshuttle plan create`は、次の共通構造を出力する。

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

展開操作では、`operation`に`extract`、`source.kind`に`file`、`destination.kind`に`directory`を使い、可能な範囲で取得したアーカイブ検査フィールドを含める。

外部フィルターが変更できるフィールドは次のものに限る。

```text
destination.path
scheduling.profile
scheduling.priority
scheduling.cpu_tokens
scheduling.threads
tags
```

その他のフィールドは`integrity`で保護する。変更後の`destination.path`も絶対パスで、一意かつ安全でなければならない。CPUトークン／スレッドの上書き値は、型検査後に設定済みCPU予算の範囲内へ収め、必要に応じて警告を付ける。I/Oトークンは変更できず、予算内でなければならない。`integrity`を再計算または削除してはならない。

```sh
arcshuttle plan create dir-a dir-b |
  jq -c 'if .tags | index("urgent") then .scheduling.priority = 100 else . end' |
  arcshuttle run --manifest -
```

### 9.2 スキーマv1互換

`parxtract plan`は、`path`と`output_dir`を持つ展開専用のv1構造を変更せずに出力する。`arcshuttle run`と`parxtract run`はv1を読み込み、内部で展開ジョブへ変換する。v1の許可リストは、`output_dir`、同じ4つのスケジューリング上書きフィールド、`tags`のままである。v1の結果形式にv2限定フィールドは追加しない。

v1の展開ジョブとv2のジョブは、同じマニフェストに混在できる。v2入力が1件でもあれば、全体の`summary`はスキーマv2となる。

## 10. ステージング、検証、結果、ログ

### 10.1 展開

最終ディレクトリの隣に`.arcshuttle-<job-id>-<random>.tmp`を作り、`.arcshuttle-owned`を書き込んで7-Zipを実行する。終了コード0の場合だけ、出力先を再確認してから確定する。警告、失敗、割り込みが発生した場合は、所有マーカーを確認できるステージングを`.failed`として保持する。所有を確認できないパスは移動または削除しない。

### 10.2 作成

作成は次の順序を厳守する。

1. パスの関係、入力元の同一性情報、非破壊の`--existing`方針を検証する。
2. 出力先の隣に、非公開の所有マーカー付きステージングディレクトリを作る。
3. 引数配列、`shell=False`、閉じた標準入力、制御された作業ディレクトリを使って`7z a`を実行する。
4. ステージング済みの通常アーカイブと、`7z t`による検証の成功を必須とする。
5. 出力先が存在しないことを再確認して原子的に公開し、所有を確認した空のステージングだけを削除する。

作成または検証で警告、失敗、割り込みが発生した場合や、確定前に問題が発生した場合は、ステージングを`.failed`として保持する。入力元は移動、変更、削除しない。

### 10.3 結果

`status`は`success`、`warning`、`failed`、`skipped`、`interrupted`のいずれかである。すべてのv2の`result`レコードは、`operation`、`output_path`、`staging_path`と、旧形式の別名である`output_dir`／`staging_dir`を含む。作成結果は`create_exit_code`と`verification_exit_code`も含み、対象プロセスが未起動の場合は`null`になり得る。`log_path`は、存在するジョブログを指す。

最後のレコードは必ず`summary`であり、5つのステータスの件数、合計、`duration_ms`を持つ。

| プロセス終了コード | 意味 | JSON Linesの可能性 |
|---:|---|:---:|
| 0 | 全ジョブが警告なしで成功 | あり |
| 1 | 警告、スキップ、または結果の警告があり、失敗はない | あり |
| 2 | 1件以上が失敗 | あり |
| 64 | 使用方法、設定、入力、またはマニフェストのエラー | 通常なし |
| 130 | 割り込み | あり |

### 10.4 ログ

既定の基準ディレクトリは`<cwd>/.arcshuttle/logs/<run-id>/<job-id>/`である。

展開ログは`metadata.json`、`stdout.log`、`stderr.log`である。作成ログは`metadata.json`、`create.stdout.log`、`create.stderr.log`、`test.stdout.log`、`test.stderr.log`である。作成時のメタデータには、安全な実引数配列、作業ディレクトリ、割り当てたCPU／スレッド、プロセスの時刻／終了コード、エラー、確定結果を記録する。7-Zipの出力をJSON Linesの標準出力へ混ぜない。

## 11. PowerShell 7

```powershell
Import-Module ./powershell/ArcShuttle.psm1

Get-ChildItem C:\Sources -Directory |
    Invoke-ArcShuttleCreatePlan -Format 7z -Level 5 |
    Invoke-ArcShuttleRun

Get-ChildItem C:\Archives -File |
    Invoke-ArcShuttleExtract -OutputDir C:\Extracted
```

| 関数 | パイプライン入力 | 対応する操作 |
|---|---|---|
| `Invoke-ArcShuttleExtractPlan` | 文字列または`FileSystemInfo` | `plan extract` |
| `Invoke-ArcShuttleCreatePlan` | 文字列または`FileSystemInfo` | `plan create`。各項目は独立 |
| `Invoke-ArcShuttleRun` | ジョブオブジェクト | `run` |
| `Invoke-ArcShuttleExtract` | 文字列または`FileSystemInfo` | 展開計画後に`run` |
| `Invoke-ArcShuttleCreate` | 文字列または`FileSystemInfo` | 作成計画後に`run` |

PowerShellでは、対応するパラメーターとして次の名前を使う：`-ArcShuttleCommand`、`-SevenZip`／`-7z`、`-OutputDir`、`-Existing`、`-CpuBudget`、`-MaxProcesses`、`-StorageProfile`、`-IoSlots`、`-HeavyThreads`、`-SmallThreshold`、`-InspectThreshold`、`-InspectTimeout`、`-ReservationDelay`、`-SequentialIfTotalBelow`、`-LogDir`、`-Config`、`-OnInputError`、`-Quiet`、`-FailFast`、`-AllowChanged`。作成計画関数と作成一括実行関数は、`-Format`と`-Level`も受け付ける。

モジュールは、PowerShellの成功ストリームへ`PSCustomObject`レコードだけを出力し、`$LASTEXITCODE`を保持して一時ファイルを削除する。ネイティブCLIの進捗と診断は標準エラー出力へリアルタイムで転送する。`-Quiet`は対応する情報レベルの診断を抑制するが、警告とエラーは引き続き標準エラー出力へ書き込む。

純粋なオブジェクトパイプラインではストリームを分離する。明示的な`2>&1`はPowerShellのエラーストリームを成功ストリームへリダイレクトするため、診断の`ErrorRecord`と成功出力の`PSCustomObject`が意図的に混在する：

```powershell
# 混合出力：一体のトランスクリプトには有用だが、純粋なオブジェクトパイプラインではない。
Get-ChildItem C:\Archives -File |
    Invoke-ArcShuttleExtract -StorageProfile nvme 2>&1
```

互換用の`powershell/Parxtract.psm1`は、`Invoke-ParxtractPlan`、`Invoke-ParxtractRun`、`Invoke-Parxtract`を維持する。同じオブジェクト出力仕様に従う。

### 11.1 出力形式と保存方法

出力形式に応じて保存方法を選ぶ：

| 出力元 | 成功時の出力 | 主な用途 |
|---|---|---|
| `arcshuttle plan`／`parxtract plan` | 正規のUTF-8 JSON Lines | 可搬性のあるマニフェストファイルとPowerShell以外のツール |
| `Invoke-ArcShuttle*Plan`／`Invoke-ParxtractPlan` | `PSCustomObject`レコード | 同一セッション内のPowerShellオブジェクトパイプライン |
| `Export-Clixml`／`Import-Clixml` | PowerShellオブジェクトのスナップショット | PowerShell専用のセッション間保存 |

同じPowerShellセッション内で計画して実行する場合は、オブジェクトのまま扱う：

```powershell
$plans = @(
    Get-ChildItem C:\Archives -File |
        Invoke-ArcShuttleExtractPlan
)

$plans | Select-Object plan_index, operation, source, destination
$plans | Invoke-ArcShuttleRun
```

保存形式は、ファイルの拡張子だけでは選択されない。計画オブジェクトをリダイレクトするとPowerShellの表示形式が適用され、マニフェストは作成**されない**：

```powershell
# 無効な保存：ファイル内容はJSON Linesではなく、一部の情報が失われた表示用の形式となる。
Get-ChildItem C:\Archives -File |
    Invoke-ArcShuttleExtractPlan > extract.jsonl
```

このファイルを`run`コマンドへ渡したり修復を試みたりせず、入力元から計画を作り直す。

正規のJSON Linesが必要な場合は、PowerShellからネイティブCLIを使う：

```powershell
$archives = @(Get-ChildItem C:\Archives -File | Select-Object -ExpandProperty FullName)
arcshuttle plan extract -- $archives > extract.jsonl
Get-Content -LiteralPath .\extract.jsonl |
    ConvertFrom-Json -Depth 100 |
    Select-Object plan_index, operation, source, destination
```

ネイティブコマンドラインの上限を超えるパス集合には、3章の`--files0-from`を使う。有効なJSON Linesファイルは、レコードストリームとして連結できる。ArcShuttleは結合したマニフェスト全体を検証し、重複する`job_id`と出力先の衝突を拒否する。独立した計画間では`plan_index`が重複してもよい。`plan_index`は`integrity`で保護されるため、連番へ振り直してはならない。

PowerShell専用のセッション間スナップショットには、CLIXMLを明示的に使う：

```powershell
$plans | Export-Clixml -LiteralPath .\plans.clixml -Depth 100
$plans = @(Import-Clixml -LiteralPath .\plans.clixml)
$plans | Invoke-ArcShuttleRun
```

同じ方法を`Invoke-ParxtractPlan`と`Invoke-ParxtractRun`にも使える。CLIXMLはArcShuttleのマニフェストではなく、`arcshuttle run --manifest`では受理しない。複数のスナップショットを扱う場合は、未加工のCLIXMLを連結せず、インポート後のオブジェクトリストを結合する。

## 12. POSIX例

```sh
# 作成ジョブを確認してから実行する。
find /data/source -mindepth 1 -maxdepth 1 -print0 |
  arcshuttle plan create --files0-from - --format 7z > create.jsonl
jq -e -c 'select(.record_type == "job")' create.jsonl |
  arcshuttle run --manifest - > results.jsonl

# 直接展開する。
fd --type f --print0 . /data/archives |
  arcshuttle extract --files0-from - --output-dir /data/out
```

シェルパイプライン全体の終了状態が必要な場合は`set -o pipefail`を使う。ただし、`plan`コマンドの終了コードが1でも有効なジョブがあるため、警告の扱いが重要な場合は、計画の標準出力と終了コードを別々に保存する。

## 13. parxtract 0.1からの移行

- 配布名`arcshuttle`には、両方のコンソールスクリプトが含まれる。新しいCLIとPowerShellワークフローでは`arcshuttle`を使う。
- 既存の`parxtract`コマンド、互換モジュール、スキーマv1マニフェストは、展開用途で引き続き利用できる。
- `ARCSHUTTLE_*`と`[arcshuttle]`を優先する。新名称が優先され、作成設定に旧形式の別名はない。
- 既存の`.parxtract`データは移行、改名、所有、削除しない。ArcShuttleは新しい`.arcshuttle`パスへ書き込む。

## 14. AIエージェント手順

1. `plan`コマンドを実行する前に、バージョン、7-Zipの利用可否、操作、出力形式、安全な出力先を確認する。自動生成したパスや任意の文字を含むパスにはNUL区切り入力を使う。
2. 標準出力と標準エラー出力を分離し、計画内の全`job`について、`operation`と出力先の一意性を確認する。
3. フィルターではv2の許可リストにあるフィールドだけを変更する。`integrity`を再生成せず、保護された入力元、アーカイブ、インベントリ、I/Oフィールドを変更しない。
4. 完全なストリームを1つの`run`プロセスへ渡し、標準出力をEOFまで読み、すべての`result`、最後の`summary`、プロセスの終了コードを合わせて判定する。
5. `null`でない`staging_path`と`log_path`を報告する。保持されたデータを削除せず、入力元の変更、拒否対象リンクの追跡、上書き保護の迂回を行わない。

機械判定の概要：

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

## 15. 制限事項とトラブルシューティング

作成機能は、入力元1件につきアーカイブ1個、`7z`／`zip`、圧縮レベル0～9、通常エントリ、ローカルの非分割出力に対応する。複数入力元の結合、分割、暗号化アーカイブの作成、パスワード入力、未加工の圧縮方式調整、厳密なメモリ予算、GUI、監視サービスには対応しない。

| 症状 | 確認 | 安全な対処 |
|---|---|---|
| `7-Zip not found` | `--7z`、`ARCSHUTTLE_7Z`、`PATH` | 対応実行ファイルを設定 |
| 終了コード64かつ標準出力が空 | 標準エラー出力にある使用方法／入力／マニフェストエラー | 構文を修正するか計画を作り直す。レコードを捏造しない |
| 終了コード1で出力あり | 警告、スキップ、結果の警告 | `summary`を解析して詳細を報告 |
| `source identity changed` | 計画後の変更 | 計画を作り直す。意図した変更の場合だけ`--allow-changed`を使う |
| `immutable field modified` | 外部フィルター | 元の計画から許可リストのフィールドだけを編集し直す |
| `output collision` | 派生または編集したパスの重複 | 出力先を一意にする |
| `.failed`が残る | 作成／検証／展開時の警告または失敗 | ログ確認後に必要なデータを手動で回収 |
| HDDのスループット低下 | I/O競合 | `hdd`または`--io-slots 1`を選択 |
