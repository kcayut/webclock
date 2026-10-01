# WebClock Server：集中管理と端末 API

[繁體中文](server-api.md) · [English](server-api_en.md) · **日本語** · [README](../README_jp.md)

このプロジェクトは、予定、台湾の勤務日データ、端末登録、同期リビジョン、端末状態を管理し、セルフホスト時計でブラウザーアラームを実行します。`/schedules` でアラームを編集・プレビューし、`/` で内蔵音と赤い枠の通知を表示します。`/admin` は表示設定、購読カレンダー、文字リマインダーを別に管理します。

ファームウェア、音声ファイル、スピーカー、音量、スヌーズ、RTC、ボタン、単独オフライン実行は将来のハードウェアプロジェクトに属します。端末は HTTP/JSON API を使用し、このプロジェクトの Python モジュールを読み込む必要はありません。

現在は 1 つの共有管理領域で、**すべての端末が同じ予定とカレンダーを使用します**。端末ごとの割り当て、マルチテナント、ユーザーアカウントは未実装です。

## 起動と構成

`python app.py`、Docker Compose、または既存の systemd サービスを使用します。`/admin` からアラーム管理に進むか、`/schedules` を直接開きます。

```text
app.py / setup.sh / update_clock.py / update_clock.sh  互換デプロイ入口
webclock/
  app.py                     時計、設定、カレンダー、起動
  api/
    management.py            管理画面と予定／端末管理 API
    device.py                端末設定、予定、カレンダー、状態 API
  services/                  予定、休日、端末、JSON 保存サービス
  translations/              Web UI 文言
  data/taiwan_calendar.json  読み取り専用カレンダーと出典
templates/                   セルフホスト HTML
static/                      Web CSS / JavaScript
scripts/                     インストールと更新
tests/                       Server、API、Web 回帰テスト
doc/                         ガイドと API 契約
webclock_state/              非公開の実行データ。Git に追加しない
```

ルートには互換入口と公開時計のファイルを残します。GitHub Pages が公開するのは公開時計だけで、管理画面、API、非公開カレンダー、端末データはオフラインキャッシュに含めません。

## 予定と勤務日

予定の最小入力は `name` と `time` です。Server が `id` を生成し、既定で `type=alarm`、毎日、有効にします。

```json
{
  "id": "work_alarm",
  "name": "出勤通知",
  "type": "alarm",
  "time": "07:30",
  "rule": {"weekdays": [1, 2, 3, 4, 5]},
  "skip_holidays": true,
  "browser_sound": "bell",
  "enabled": true,
  "skipped_occurrences": []
}
```

- `type`：`alarm`、`reminder`、`announcement`。時計ページが実行するのは `alarm` だけで、カレンダー予定や文字リマインダーは自動でアラームになりません。
- `rule`：毎日の `{}`、`{"weekdays":[1,3,5]}`、`{"workday_only":true}`、`{"holiday_only":true}`、`{"dates":["2026-10-03"]}` のいずれかです。
- `skip_holidays`：毎日・曜日・指定日の休日を除外します。振替出勤日は勤務日です。`holiday_only=true` との併用は 400 を返します。
- `browser_sound`：`bell`、`beep`、`digital`、`silent`。旧ハードウェアの音声項目とは独立しています。
- 曜日は ISO の月曜 `1` から日曜 `7` です。旧リマインダー API の `0–6` とは異なります。
- 予定は大時計の表示タイムゾーンとは別に、常に `Asia/Taipei` を使います。
- `skipped_occurrences` はタイムゾーン付きの完全な日時です。次回をスキップしても予定は無効になりません。
- `next_occurrence` と `next_event` はプレビューで、実行記録やイベントキューではありません。

アラームには `calendar_link` を指定できます。省略または `null` の場合は固定時刻です。

```json
{"calendar_link":{"mode":"event","source_ids":["local","work"],"offset_minutes":15}}
```

- `event`：時刻付き予定の 0–1440 分前に発生し、終日予定は無視します。
- `day`：選択した参照元に当日の予定があれば、予定の固定 `time` に発生します。終日・複数日の予定も含みます。
- `source_ids` は安定した参照元 ID で、`local` はローカルリマインダーです。時計の表示選択とは独立しています。
- 曜日、指定日、休日フィルターは実際のアラーム日の台湾日付で判定します。プレビューは最大 366 日先まで検索します。
- 日付や固定時間帯のない常設文字は対象外です。参照元を取得できない場合、毎日アラームや古いデータへフォールバックしません。
- 連動アラームはブラウザー用に Server が計算します。旧ハードウェアの誤動作を防ぐため、schema 2 の端末応答からは除外します。

台湾カレンダーの範囲は **2023-01-01 から 2027-12-31** です。政府機関の勤務日カレンダーに基づき、すべての会社、台風休業、個人シフトを表すものではありません。範囲外は `unknown` とし、休日依存のルールを推測しません。

## 管理 API

API は JSON を受け取り、エラーを `{"error":"..."}` で返します。不正入力は 400、未存在は 404、書き込み失敗は 500 で、保存済みデータは上書きしません。要求上限は 1 MiB です。

| パス | メソッドと用途 |
| --- | --- |
| `/api/v1/schedules` | GET 予定とプレビュー、POST 新規予定 |
| `/api/calendar` | GET/POST カレンダー参照元、PATCH 表示選択のみ |
| `/api/v1/schedules/<id>` | PUT 指定項目、DELETE 予定 |
| `/api/v1/schedules/<id>/skip-next` | POST 次回をスキップ |
| `/api/v1/browser-alarms` | GET 次のブラウザーアラームと休日データ状態 |
| `/api/v1/holidays?date=2026-09-30` | GET 日付分類。省略時は台湾の今日 |
| `/api/v1/devices` | GET 登録端末と未確認指令 |
| `/api/v1/devices/<id>/commands` | POST `{"action":"sync"}`、202 を返す |

管理 API は信頼できる LAN を前提とし、ログイン機能はありません。異なる Origin のブラウザー要求を拒否しますが、完全な認証ではありません。外部公開時はリバースプロキシでアクセスを制限し、HTTPS を有効にしてください。

`/api/calendar` の各参照元は `id`、`name`、`provider`、`url`、`display_enabled` を持ち、`local_display_enabled` がローカルリマインダーを制御します。アラームが参照するため、更新時は ID を維持してください。POST は参照元全体を保存し、PATCH は ID と表示フラグだけを受け付けます。URL は専用管理応答にだけ現れ、時計、予定、端末、バックアップ、オフラインキャッシュには出力しません。

## ブラウザーアラーム

`GET /api/v1/browser-alarms` の主な項目：

| 項目 | 内容 |
| --- | --- |
| `server_timestamp` | 発生時刻の補正に使う Unix ミリ秒 |
| `enabled_count`、`enabled_ids` | 次回が未確定のものを含む有効アラーム |
| `alarms` | 固定アラームの次回と、現在／次の連動予定。最大 1000 件 |
| `alarms[].occurrence_id` | 重複再生を防ぐ発生 ID |
| `alarms[].starts_at` | Unix ミリ秒の発生時刻 |
| `alarms[].sound` | `browser_sound` の Web 音色 |
| `holiday_coverage`、`holiday_known` | 休日データ範囲と既知状態 |

API 遅延で直前のアラームを飛ばさないよう、現在の分から検索します。これは完全なオフライン予定スナップショットではありません。時計ページは約 15 秒ごとに更新します。短い切断中は読み込み済みの次回分を実行できますが、再起動やそれ以降の取得には接続が必要です。60 秒を超えて遅れたアラームは再生しません。

時計ページは Web Audio で 3 つの音色を合成します。ページを開くたびにベルをタップし、確認音を聞く必要があります。iOS は App・タブの切り替えや画面ロックで音声とタイマーを中断することがあるため、時計ページを前面に表示し、画面を点灯してください。バックグラウンドやロック中のアラームは保証されません。

視覚通知は赤い枠を 2 秒周期で点滅させます。設定で常時表示に変更でき、`prefers-reduced-motion` に対応するブラウザーも常時表示にします。2 回の別々のタップで、現在ページの今回分だけを停止します。予定や他の端末は変更しません。

## 端末 API

端末 API は `/api/v1/device/*` を使用し、設定応答の **`schema_version` は 2** です。旧ハードウェアの再生項目は公開しません。`browser_sound` は Web ページ専用です。schema 1 の試作 client は更新が必要です。

| パス | メソッドと用途 |
| --- | --- |
| `/api/v1/device/config` | GET schema、タイムゾーン、3 種類の revision |
| `/api/v1/device/schedules` | GET revision と予定 |
| `/api/v1/device/holidays` | GET カレンダー、出典、範囲、revision |
| `/api/v1/device/register` | POST 端末 `id` と `name`、201 を返す |
| `/api/v1/device/status` | POST 状態と確認、端末と未確認指令を返す |

予定と休日 API は読み取り専用です。`.env` に `DEVICE_API_TOKEN` を設定し、すべての端末呼び出しで `Authorization: Bearer <token>` を送信できます。空の場合は信頼 LAN モードです。これは端末ごとの ID ではなく共通 token で、管理 API は保護しません。

### 同期フロー

1. 固定した端末 `id` で登録します。
2. `config` を取得し、`schema_version=2` を確認します。
3. revision を比較し、変更した予定または休日だけを取得します。初回は全データを取得します。
4. 取得後に再度 `config` を確認します。途中で変更された場合は再試行し、検証成功後だけローカルキャッシュを置き換えます。
5. 保存済み revision を `status` で報告します。Server はダウンロードをハードウェア実行成功とは見なしません。

revision は SHA-256 文字列です。3 つの GET リソースは `If-None-Match` または `?revision=...` に対応し、同じ場合は 304 を返します。`config` では `config_revision` ではなく応答 ETag を使用してください。ETag は予定と休日の revision も含みます。休日スナップショットの `schema_version=1` はその形式だけを表し、端末設定 schema 2 とは別契約です。

### 状態と指令確認

最小状態は `{"id":"bedroom"}` です。省略した任意文字列項目は以前の値を維持します。

```json
{
  "id": "bedroom",
  "firmware": "0.1.0",
  "config_revision": "保存済み設定 revision",
  "schedule_revision": "保存済み予定 revision",
  "holiday_revision": "保存済み休日 revision",
  "acknowledged_commands": ["完了した同期指令 ID"]
}
```

`online` は 120 秒以内に状態報告を受けたことを示します。約 60 秒ごとの報告を推奨します。「同期を要求」は `sync` 指令だけを追加し、確認されるまで応答に残ります。繰り返し要求しても未確認指令は 1 件です。端末は指令 ID で重複を除き、成功後だけ確認してください。

## 旧データと保存

- 旧音声 API、音声ファイル、ハードウェア音声サービス、Python 模擬端末は削除済みです。現在の端末指令は `sync` だけです。
- 旧予定・端末項目は既存ファイルに残りますが、公開・適用しません。新 API は受け付けません。
- `webclock_state/sounds/` や `webclock_state/fake-device/` の既存ユーザーデータは削除しませんが、Server は読みません。
- 旧ルートの `manual_notes.json` は状態ディレクトリへ一度だけコピーします。`NOTES_FILE` と `WEBCLOCK_STATE_DIR` の上書きは引き続き利用できます。

状態ディレクトリ全体、リマインダー、`.env` をバックアップしてください。`/admin` の JSON 出力は表示設定と手動リマインダーだけで、予定や端末は含みません。更新と移行は[日本語ガイド](guide_jp.md#バックアップデータ更新)を参照してください。

JSON を書き込む Server process は 1 つで、上限は予定 1000 件、端末 100 台です。複数 worker を追加する前に、プロセス間 transaction に対応する保存方式へ移行してください。

## 検証

```bash
python -m unittest discover -s tests -p 'test_*.py'
node tests/test_clock.js
node tests/test_offline.js
node tests/test_schedule_ui.js
node tests/test_alarms.js
node tests/test_calendar_ui.js
node tests/test_management_navigation.js
bash -n setup.sh scripts/setup.sh update_clock.sh
```

テストは管理 CRUD、勤務日、振替出勤日、スキップ、revision、アクセス検査、端末報告・確認、旧データ保持を対象にします。更新統合テストは実際の旧／新 Server process と Git・データの復元を検査しますが、systemd、pip、Linux サービス照会は模擬です。対象ホストへの導入や実機ハードウェアの検収を証明するものではありません。
