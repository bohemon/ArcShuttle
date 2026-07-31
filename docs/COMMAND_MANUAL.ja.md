---
title: parxtract コマンド・オプションマニュアル
language: ja
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

# `parxtract` コマンド・オプションマニュアル

この文書は、`parxtract` 0.1.0を人間とAIエージェントの双方が安全かつ一貫して操作するための規範的なリファレンスである。概要や背景は `README.md`、厳密なコマンド契約は本書を参照すること。

本文中の「必須」「禁止」「のみ変更可」は規範的な要件を表す。「既定」はCLI、環境変数、明示TOMLのどれでも上書きされていない場合を表す。

## 1. 最小契約

AIエージェントは、まず次の契約を守ること。

1. コマンド名の後にサブコマンドを書く。共通オプションもサブコマンドの後に置く。
2. `plan`または`extract`では、`PATH...`、`--files-from`、`--files0-from`のうち正確に1種類だけを指定する。
3. 標準出力はUTF-8 JSON Linesとして扱い、人間向けメッセージは標準エラーから読む。
4. `plan`の全出力をEOFまで受け取ってから`run`へ渡す。
5. 外部フィルターは、許可された6フィールド以外を変更してはならない。
6. `parxtract run`をGNU Parallelなどから複数起動してはならない。
7. 終了コード0以外を直ちに「出力なし」と解釈しない。コード1でも有効なJSON Linesが出る場合がある。
8. 既定では元アーカイブも失敗時ステージングも削除しない。

最小の直接展開:

```sh
parxtract extract archive1.7z archive2.zip
```

計画を検査してから実行:

```sh
parxtract plan archive1.7z archive2.zip > plan.jsonl
parxtract run --manifest plan.jsonl > result.jsonl
```

## 2. コマンド構文

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

注意:

- `--version`と最上位の`--help`だけがサブコマンドより前のオプションである。
- 共通オプションは`parxtract --quiet plan ...`ではなく、`parxtract plan --quiet ...`と書く。
- `-`で始まる位置引数を明示するときは、オプション終端の`--`を使用できる。

```sh
parxtract plan -- ./-archive.zip
```

## 3. コマンド選択

| コマンド | 入力 | 標準出力 | 使用目的 |
|---|---|---|---|
| `plan` | アーカイブパス | `job` JSON Lines | 検査、分類、出力先確認、外部フィルター連携 |
| `run` | `plan`マニフェスト | `result`群と最後の`summary` | 検証済み計画の実行 |
| `extract` | アーカイブパス | `result`群と最後の`summary` | 外部フィルターが不要な一括処理 |

### 3.1 `plan`

`plan`は全入力を読み切り、正規化、分割アーカイブ統合、必要な7-Zip検査、分類、出力衝突検査を行う。`plan_index`は正規化後の入力順を保持する。実行優先順への並べ替えは`run`で行う。

```sh
parxtract plan --output-dir /data/out a.7z b.zip
parxtract plan --files-from paths.txt
parxtract plan --files0-from paths.bin
cat paths.txt | parxtract plan --files-from -
find /data/in -type f -print0 | parxtract plan --files0-from -
```

`--on-input-error=fail`では、1件でも重大な入力エラーがあれば標準出力へ部分的な計画を出さず、終了コード64になる。`skip`では有効なジョブだけを出し、終了コード1になる。

検査警告がある計画は有効だが、終了コード1になることがある。

### 3.2 `run`

`run`はマニフェスト全体をEOFまで読み、すべてのレコードと出力衝突を検証してからジョブを開始する。

```sh
parxtract run --manifest plan.jsonl
cat plan.jsonl | parxtract run --manifest -
```

`--manifest` `FILE`は`run`の必須オプションである。`FILE`はUTF-8 JSON Linesファイル、`-`は標準入力を表す。位置引数でマニフェストを渡すことはできない。

現在の実装では、ジョブ結果は実行中に逐次標準出力へ流さず、全ジョブの終了後にまとめて出力し、最後に`summary`を出す。呼び出し側はEOFまで読むこと。

1件の失敗は既定で他ジョブを停止しない。`--fail-fast`は失敗検出後の新規開始だけを止め、実行中ジョブは終了を待つ。開始されなかったジョブは`skipped`になる。

### 3.3 `extract`

`extract`は内部で`plan`と`run`を連続実行する。計画JSONを外部編集する必要がなければ、通常はこれを使う。

```sh
parxtract extract --output-dir /data/out --existing rename a.7z b.zip
```

重大な入力エラーがある場合、既定では1件も展開しない。

## 4. 入力ソースオプション

`plan`と`extract`だけで使用する。

| 指定 | 内容 | エンコーディング | 注意 |
|---|---|---|---|
| `PATH...` | 1件以上の位置引数 | OSの引数規則 | シェルのクォートが必要 |
| `--files-from FILE` | 1行1パス | UTF-8 | パス中の改行は表現不可 |
| `--files-from -` | 標準入力から改行区切り | UTF-8 | 暗黙のstdin読み込みはしない |
| `--files0-from FILE` | NUL区切りパス | UTF-8 | 改行を含むパスも表現可能 |
| `--files0-from -` | 標準入力からNUL区切り | UTF-8 | `find -print0`、`fd --print0`向け |

規則:

- 3種類は排他的である。
- 明示した入力が空でもエラーになる。
- 相対パスは`parxtract`プロセスのカレントディレクトリ基準で絶対化する。
- 存在しないパスとディレクトリは拒否する。
- Windowsでは大文字小文字を無視して重複排除する。
- 同一の正規化パスは最初の1件だけを残す。
- コマンドライン長が問題になる場合は`--files-from`または`--files0-from`を使う。

## 5. 共通オプション一覧

すべてのサブコマンドが次のオプションを構文上は受理する。ただし「作用」列にないフェーズでは実質的な効果を持たない。

作用記号:

- `P`: 計画時に作用する。
- `R`: 実行時に作用する。
- `P/R`: 両方に作用する。
- `-`: 構文上は受理されるが、そのフェーズでは使用されない。

| オプション | 値 | 既定 | 作用 | 説明 |
|---|---|---:|:---:|---|
| `--7z PATH` | パスまたはコマンド名 | 自動探索 | P/R | 使用する7-Zip CLI。検査と展開に使う |
| `--output-dir DIR` | ディレクトリ | 各アーカイブの親 | P | 計画される最終出力ルート。`run`ではマニフェストの`output_dir`が優先され、この指定は使われない |
| `--existing {fail,skip,rename}` | 列挙値 | `fail` | R | 最終出力がすでに存在する場合の非破壊ポリシー |
| `--cpu-budget N|auto` | 1以上または`auto` | `max(1, CPU数-1)` | P/R | 分類時の重ジョブ割当てと実行時のCPUトークン総量 |
| `--max-processes N` | 1以上の整数 | `min(4,cpu_budget)` | R | 同時7-Zipプロセス数。`auto` I/Oスロットの派生値にもなる |
| `--storage-profile {auto,hdd,ssd,nvme}` | 列挙値 | `auto` | R | `--io-slots`未指定時のI/Oスロット既定を選ぶ |
| `--io-slots N` | 1以上の整数 | プロファイル依存 | R | 全ジョブで共有するI/Oトークン総量 |
| `--heavy-threads N` | 1以上の整数 | `min(4,cpu_budget)` | P | `heavy-scalable`計画時の最大CPUトークン/7-Zipスレッド数 |
| `--small-threshold SIZE` | サイズ | `64M` | P | この圧縮サイズ未満を`small`にする |
| `--inspect-threshold SIZE` | サイズ | `64M` | P | このサイズ以上の既知形式をtechnical listingで検査する |
| `--inspect-timeout SECONDS` | 0以上の数 | `30` | P | 1アーカイブの検査タイムアウト |
| `--reservation-delay SECONDS` | 0以上の数 | `30` | R | 待機先頭ジョブの資源予約を始めるまでの秒数 |
| `--sequential-if-total-below SIZE` | サイズ | `0` | R | 合計圧縮サイズが閾値以下ならプロセス/I/Oスロットを1にする。0は無効 |
| `--log-dir DIR` | ディレクトリ | `./.parxtract/logs` | R | 実行ログのルート |
| `--config FILE` | TOMLファイル | なし | P/R | 明示設定ファイル。暗黙のグローバル設定は読まない |
| `--quiet` | フラグ | false | P/R | 選択7-Zip、警告以外の進捗表示を抑制。JSON出力は抑制しない |
| `--fail-fast` | フラグ | false | R | 最初の失敗後に新規ジョブ開始を止める |
| `--allow-changed` | フラグ | false | R | 計画後にサイズ/mtimeが変わった元ファイルを警告付きで実行する |
| `--on-input-error {fail,skip}` | 列挙値 | `fail` | P | 無効な入力パスがあるとき、全体失敗または有効分だけ計画 |
| `-h`, `--help` | フラグ | - | P/R | 対象サブコマンドのヘルプを表示 |

### 5.1 サイズ値

サイズは非負整数と、次の大文字小文字を区別しない二進接尾辞を受け付ける。

```text
K, M, G, T, P, E
KB, MB, GB, ...
KiB, MiB, GiB, ...
```

例:

```text
0       = 0 byte
4096    = 4096 byte
64M     = 64 * 1024^2 byte
1GiB    = 1024^3 byte
```

小数形式（例:`1.5G`）は受理しない。

### 5.2 `--existing`

| 値 | 動作 | 7-Zip起動 |
|---|---|:---:|
| `fail` | そのジョブを`failed`にする | しない |
| `skip` | そのジョブを`skipped`にする | しない |
| `rename` | `name (2)`、`name (3)`…の未使用名を選ぶ | する |

`overwrite`は存在しない。既存出力を破壊する指定は提供しない。

### 5.3 ストレージプロファイルとI/Oスロット

`--io-slots`が明示されていない場合:

| プロファイル | I/Oスロット |
|---|---:|
| `hdd` | 1 |
| `ssd` | 2 |
| `nvme` | 4 |
| `auto` | `min(2,max_processes)` |

ストレージ種別は自動検出しない。`auto`は装置判定ではなく、保守的なスロット既定値である。

## 6. 設定の優先順位

同じ項目は次の優先順位で解決する。

```text
CLI > 環境変数 > --config TOML > 組み込み既定値
```

### 6.1 TOML

設定は`[parxtract]`テーブル内、またはファイル直下へ書ける。未知のキーはエラーになる。再現性のため、設定ファイルは`--config`で明示しなければ読まれない。

```toml
[parxtract]
sevenzip = "C:/Program Files/7-Zip/7z.exe"
output_dir = "D:/Extracted"
existing = "rename"
cpu_budget = 8
max_processes = 4
storage_profile = "ssd"
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

TOMLキー名は`sevenzip`であり、`7z`ではない。

### 6.2 環境変数

| TOMLキー | 環境変数 |
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

環境変数の真偽値は`1/0`、`true/false`、`yes/no`、`on/off`を受け付ける。

## 7. 7-Zip

### 7.1 探索順

1. `--7z`
2. `PARXTRACT_7Z`
3. `PATH`上の`7zz`
4. `PATH`上の`7z`
5. `PATH`上の`7za`
6. Windowsの`Program Files/7-Zip/7z.exe`

選択した実行ファイルとバージョンは標準エラーへ表示する。`--quiet`で抑制できる。

7-Zipは必ず引数配列、閉じた標準入力、`shell=False`で起動する。アーカイブパスの前に`--`を置き、スイッチに見える名前を安全に扱う。

### 7.2 自動認識拡張子

```text
.7z .zip .rar .tar .tar.gz .tgz .tar.bz2 .tbz2
.tar.xz .txz .gz .bz2 .xz
```

直接指定された未知拡張子も拡張子だけでは拒否せず、7-Zip検査を試みる。

### 7.3 technical listing

次の場合に検査する。

- 圧縮ファイルサイズが`inspect_threshold`以上。
- 拡張子から形式を推定できない。

取得できないフィールドは`null`のままにする。検査失敗やタイムアウトはジョブ警告となり、分類は保守的な`heavy-serial`になる。暗号化が確認されたジョブは実行時に`failed`となる。

## 8. 分割アーカイブ

次の命名を認識し、先頭ボリューム1件へ統合する。

| 形式 | 先頭ボリューム |
|---|---|
| `name.7z.001`, `.002`, ... | `name.7z.001` |
| `name.zip.001`, `.002`, ... | `name.zip.001` |
| `name.part1.rar`, `.part2.rar`, ... | `name.part1.rar` |
| `name.part01.rar`, `.part02.rar`, ... | `name.part01.rar` |
| `name.rar`, `.r00`, `.r01`, ... | `name.rar` |
| `name.zip`, `.z01`, `.z02`, ... | `name.zip` |

後続ボリュームだけを入力した場合は同じディレクトリから先頭を探す。見つからなければ入力エラーになる。複数パートを別ジョブとして実行しない。

## 9. 分類とスケジューリング

### 9.1 プロファイル

| プロファイル | 自動判定 | CPUトークン | 7-Zipスレッド | 理由例 |
|---|---|---:|---:|---|
| `small` | サイズが`small_threshold`未満 | 1 | 1 | `below-small-threshold` |
| `heavy-scalable` | BZip2、または複数ブロック7z | `min(heavy_threads,cpu_budget)` | CPUトークンと同じ | `bzip2-method`, `multi-block-7z` |
| `heavy-serial` | 大きいが並列化根拠なし、または検査失敗 | 1 | 1 | `conservative-fallback`, `inspection-failed` |

すべてのジョブはI/Oトークンを1つ使う。分類は性能保証ではない。

### 9.2 資源不変条件

実行中は常に次を満たす。

```text
sum(cpu_tokens) <= cpu_budget
running_jobs     <= max_processes
sum(io_tokens)  <= io_slots
```

### 9.3 優先順

1. `scheduling.priority`降順
2. `heavy-scalable`
3. `heavy-serial`
4. `small`
5. `estimated_weight`降順
6. `plan_index`昇順

キュー先頭が空き資源に収まらない場合、収まる後続ジョブをバックフィルする。先頭が`reservation_delay`以上待つと新しいバックフィルを止め、先頭用に資源を空ける。

## 10. 出力先とステージング

### 10.1 出力名

既定ではアーカイブと同じ親に、アーカイブ接尾辞を除いたディレクトリを作る。

| アーカイブ | 出力ディレクトリ名 |
|---|---|
| `a.7z` | `a` |
| `b.tar.gz` | `b` |
| `c.7z.001` | `c` |
| `d.part01.rar` | `d` |

`--output-dir DIR`を計画時に指定すると、`DIR/<出力名>`になる。

### 10.2 確定手順

1. 最終出力と同じ親に`.parxtract-<job-id>-<random>.tmp`を作る。
2. 所有マーカーを作り、7-Zipをステージングへ実行する。
3. 7-Zip終了コード0のときだけ、最終出力の不存在を再確認する。
4. 同一ファイルシステム内で最終名へ原子的にリネームする。

7-Zip終了コード1、2以上、割り込み、確定失敗の場合、ステージングは`.failed`へリネームして残す。結果の`staging_dir`を参照すること。ツールが所有確認できないディレクトリは削除もリネームもしない。

## 11. JSON Lines契約

### 11.1 共通規則

- 文字コードはUTF-8。
- 1行が1つの完全なJSONオブジェクト。
- 空行は入力時に無視する。
- 標準出力へJSON以外を混ぜない。
- `schema_version`は現在`1`。
- 数値はJSON number、真偽値はJSON boolean、未知値は`null`とする。

### 11.2 計画ジョブ

例:

```json
{
  "schema_version": 1,
  "record_type": "job",
  "job_id": "34af91be1202b0d84333224a",
  "plan_index": 0,
  "path": "/data/in/archive.7z",
  "output_dir": "/data/out/archive",
  "source": {
    "size": 123456,
    "mtime_ns": 1234567890000000000
  },
  "archive": {
    "format": "7z",
    "methods": ["LZMA2"],
    "packed_size": 123456,
    "unpacked_size": 987654,
    "entries": 100,
    "solid": true,
    "blocks": 4,
    "encrypted": false,
    "multipart": false
  },
  "scheduling": {
    "profile": "heavy-scalable",
    "profile_source": "auto",
    "classification_reason": "multi-block-7z",
    "priority": 0,
    "estimated_weight": 987654,
    "cpu_tokens": 4,
    "threads": 4,
    "io_tokens": 1
  },
  "tags": [],
  "warnings": [],
  "integrity": "sha256:..."
}
```

主要フィールド:

| パス | 型 | 意味 |
|---|---|---|
| `job_id` | string | 正規化パス、サイズ、mtimeから生成した決定的ID |
| `plan_index` | integer | 計画入力順 |
| `path` | string | 絶対アーカイブパス |
| `output_dir` | string | 絶対最終出力パス |
| `source.size` | integer | 計画時のファイルサイズ |
| `source.mtime_ns` | integer | 計画時の更新時刻 |
| `archive.*` | object | best-effort検査情報 |
| `scheduling.priority` | integer | 高い値ほど優先 |
| `scheduling.estimated_weight` | integer | 展開後サイズ、未知なら圧縮サイズ |
| `tags` | string[] | 外部利用者向けタグ |
| `warnings` | string[] | 計画・正規化警告 |
| `integrity` | string | 変更禁止フィールドの整合性ダイジェスト |

### 11.3 外部フィルターが変更できるフィールド

次の6フィールドだけを変更できる。

```text
output_dir
scheduling.profile
scheduling.priority
scheduling.cpu_tokens
scheduling.threads
tags
```

禁止事項:

- `path`、`job_id`、`source`、`archive`、`plan_index`を変更しない。
- `scheduling.io_tokens`、`estimated_weight`、`classification_reason`を変更しない。
- `warnings`や`integrity`を変更・削除しない。
- 許可フィールドを変更した後に`integrity`を再計算する必要はない。

`run`はCPUトークンを`cpu_budget`まで切り詰め、スレッド数を割当てCPUトークンまで切り詰める。この場合は警告が追加される。I/Oトークンが予算を超えるマニフェストは拒否する。プロファイル上書きは`manifest-override`として記録される。

安全な`jq`例:

```sh
jq -c '
  select(.archive.encrypted != true)
  | if (.tags | index("urgent")) then .scheduling.priority = 100 else . end
' plan.jsonl > filtered.jsonl
```

### 11.4 実行結果

```json
{
  "schema_version": 1,
  "record_type": "result",
  "run_id": "20260731T120000Z-ab12cd34",
  "job_id": "34af91be1202b0d84333224a",
  "path": "/data/in/archive.7z",
  "status": "success",
  "exit_code": 0,
  "started_at": "2026-07-31T12:00:00.000Z",
  "finished_at": "2026-07-31T12:00:02.430Z",
  "duration_ms": 2430,
  "assigned_cpu_tokens": 4,
  "assigned_threads": 4,
  "output_dir": "/data/out/archive",
  "staging_dir": null,
  "log_path": "/work/.parxtract/logs/run/job-id",
  "warnings": []
}
```

| `status` | 意味 | 最終出力確定 |
|---|---|:---:|
| `success` | 7-Zip終了0、確定成功 | する |
| `warning` | 7-Zip終了1 | しない |
| `failed` | 検証、起動、7-Zip、確定の失敗 | しない |
| `skipped` | 既存出力、fail-fast未開始など | しない |
| `interrupted` | ユーザー割り込み | しない |

`exit_code`は7-Zipを起動していない場合に`null`になり得る。`staging_dir`は成功時`null`、部分出力を保持した場合は絶対パスになる。

### 11.5 サマリー

標準出力の最後のレコードは必ず次の形になる。

```json
{
  "schema_version": 1,
  "record_type": "summary",
  "run_id": "20260731T120000Z-ab12cd34",
  "total": 12,
  "success": 10,
  "warning": 1,
  "failed": 1,
  "skipped": 0,
  "interrupted": 0,
  "duration_ms": 12345
}
```

## 12. ログ

既定:

```text
<current-directory>/.parxtract/logs/<run-id>/<job-id>/
```

ジョブディレクトリ:

| ファイル | 内容 |
|---|---|
| `metadata.json` | 実際の引数配列、開始/終了時刻、CPUトークン、スレッド、終了コード、割り込み、起動エラー |
| `stdout.log` | 7-Zip標準出力 |
| `stderr.log` | 7-Zip標準エラー |

7-Zip出力はメモリへ全量保持せず、直接ログファイルへ書く。

## 13. 終了コード

| コード | 意味 | JSON出力の可能性 |
|---:|---|:---:|
| 0 | 全ジョブ成功、警告なし | あり |
| 1 | 警告またはスキップあり、失敗なし | あり |
| 2 | 1件以上の失敗 | あり |
| 64 | CLI、設定、入力形式、マニフェストのエラー | 通常なし |
| 130 | ユーザー割り込み | あり得る |

AIエージェントは、終了コード1または2でも標準出力に完全な結果/サマリーがあれば解析すること。JSON Linesの解析失敗とジョブ失敗を混同しないこと。

## 14. PowerShell 7モジュール

```powershell
Import-Module ./powershell/Parxtract.psm1
```

公開関数:

| 関数 | パイプライン入力 | 出力 |
|---|---|---|
| `Invoke-ParxtractPlan` | `string`または`FileSystemInfo` | 計画PowerShellオブジェクト |
| `Invoke-ParxtractRun` | 計画PowerShellオブジェクト | 結果/サマリーPowerShellオブジェクト |
| `Invoke-Parxtract` | `string`または`FileSystemInfo` | 結果/サマリーPowerShellオブジェクト |

共通PowerShellパラメーターとCLI対応:

| PowerShell | CLI |
|---|---|
| `-ParxtractCommand` | 実行する`parxtract`コマンド。既定`parxtract` |
| `-SevenZip`または`-7z` | `--7z` |
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

ラッパーはパスまたはJSON LinesをBOMなしUTF-8一時ファイルへ書き、Python CLIを1回だけ呼ぶ。一時ファイルは`finally`で削除する。Pythonの標準エラーは表示し、標準出力だけを`ConvertFrom-Json`する。終了状態は`$LASTEXITCODE`で確認する。

例:

```powershell
Get-ChildItem C:\Archives -File -Recurse |
    Invoke-ParxtractPlan -OutputDir C:\Extracted |
    Where-Object { $_.archive.encrypted -ne $true } |
    ForEach-Object {
        if ($_.tags -contains 'urgent') { $_.scheduling.priority = 100 }
        $_
    } |
    Invoke-ParxtractRun -Existing Rename

if ($LASTEXITCODE -ge 2) {
    Write-Error "parxtract failed with $LASTEXITCODE"
}
```

## 15. POSIX連携例

### 15.1 `find` + `jq`

```sh
find /data/in -type f -print0 |
  parxtract plan --files0-from - --output-dir /data/out |
  jq -c 'select(.archive.encrypted != true)' |
  parxtract run --manifest -
```

パイプライン全体の終了状態が必要なBashでは`set -o pipefail`を使う。ただし`plan`の警告終了1でも有効な出力があるため、運用ポリシーに応じて段階ごとの終了コードを扱うこと。

### 15.2 `fd`

```sh
fd --type f --print0 . /data/in |
  parxtract extract --files0-from - --output-dir /data/out
```

### 15.3 計画の保存と監査

```sh
parxtract plan --files0-from paths.bin > plan.jsonl
jq -e -c 'select(.record_type == "job")' plan.jsonl > checked.jsonl
parxtract run --manifest checked.jsonl > results.jsonl
jq -s 'last | select(.record_type == "summary")' results.jsonl
```

## 16. AIエージェント実行手順

### 16.1 推奨プロトコル

1. `parxtract --version`でCLI存在とバージョンを確認する。
2. 対象がファイルであることを確認する。ディレクトリを直接渡さない。
3. パスが多数、または任意文字を含む場合はNUL区切り入力を選ぶ。
4. 外部選別や優先度変更が必要なら`plan`、不要なら`extract`を選ぶ。
5. `plan`の標準出力だけをJSON LinesとしてEOFまで読む。
6. `record_type == "job"`を確認し、許可されたフィールドだけを変更する。
7. 変更後も1行1JSONを保ち、`run --manifest -`またはファイルへ渡す。
8. `run`の標準出力をEOFまで読み、最後が`summary`か確認する。
9. 終了コードと各`status`、`warnings`を合わせて判定する。
10. `failed`/`warning`/`interrupted`では`staging_dir`と`log_path`を利用者へ提示する。

### 16.2 AI向け禁止事項

- stdout上の進捗文字列を想定しない。stdoutはJSON Lines専用である。
- stderrをJSONとして解析しない。
- 許可外マニフェストフィールドを「修正」しない。
- `integrity`を削除、空文字化、独自再生成しない。
- 暗号化アーカイブのパスワードを推測・注入しない。
- 既存出力を削除して`existing=fail`を回避しない。
- 失敗ステージングを自動削除しない。
- 元アーカイブを削除、移動、更新しない。
- 1つの資源予算を共有すべきジョブ群に複数の`run`プロセスを起動しない。

### 16.3 機械判定の擬似コード

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

## 17. トラブルシューティング

| 症状 | 確認事項 | 対処 |
|---|---|---|
| `7-Zip not found` | `--7z`、`PARXTRACT_7Z`、PATH | 実行ファイルを明示する |
| 終了64、stdout空 | stderrのCLI/入力/マニフェストエラー | 構文、排他入力、絶対`output_dir`、integrityを確認 |
| 終了1だが展開済み | `warnings`または`skipped` | summaryと各resultを確認 |
| `source ... changed` | plan後にサイズ/mtime変更 | 再度planする。必要時のみ`--allow-changed` |
| `immutable manifest fields were modified` | 外部フィルターが許可外フィールドを変更 | 元planから許可6フィールドだけ変更し直す |
| `output collision` | 同名出力または編集後`output_dir`重複 | `output_dir`を一意にする |
| `.failed`が残る | 7-Zip警告/失敗/割り込み | `log_path`と部分出力を確認し、手動回収する |
| HDDで遅い | I/O競合 | `--storage-profile hdd`または`--io-slots 1` |
| 重ジョブが待つ | CPUトークン不足 | 正常な予約動作。予算と`reservation_delay`を確認 |

## 18. 対象外

バージョン0.1.0では次を提供しない。

- 実行中7-Zipのスレッド数変更
- CPU/I/O実測値による動的制御
- 物理ディスク自動判定
- 入れ子アーカイブの再帰展開
- 元アーカイブ削除
- 既存出力の破壊的上書き
- 対話的パスワード入力またはパスワード探索
- GUI、監視フォルダ

これらをAIエージェントが外部処理で暗黙に補ってはならない。
