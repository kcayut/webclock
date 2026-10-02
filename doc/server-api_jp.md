# WebClock Server：集中管理と端末 API

[繁體中文](server-api.md) · [English](server-api_en.md) · **日本語** · [README](../README_jp.md)

このプロジェクトは、予定、台湾の勤務日データ、端末登録、同期リビジョン、端末状態を管理し、セルフホスト時計でブラウザーアラームを実行します。`/schedules` でアラームを編集・プレビューし、`/` で内蔵音と赤い枠の通知を表示します。`/admin` は表示設定、購読カレンダー、文字リマインダーを別に管理します。

ファームウェア、スピーカー、ハードウェア音量、スヌーズ、RTC、ボタン、単独オフライン実行は端末側の責務で、まだ実装していません。[`firmware/`](../firmware/README.md) は開発準備用で、コンパイル可能な ESPHome 設定、書き込み用バイナリー、Web インストーラー、OTA 更新サービスはありません。端末は HTTP/JSON API を使用し、このプロジェクトの Python モジュールを読み込む必要はありません。

予定する開発手順は [ESPHome 端末ガイド](esp-home.md)、完全な応答例は [API 詳細](server-api.md#裝置-api)を参照してください。どちらも繁体字中国語です。

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
firmware/                    ESPHome 開発準備。ビルド可能なファームウェアは未提供
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
  "browser_volume": 100,
  "enabled": true,
  "skipped_occurrences": []
}
```

- `type`：`alarm`、`reminder`、`announcement`。時計ページが実行するのは `alarm` だけで、カレンダー予定や文字リマインダーは自動でアラームになりません。
- `rule`：毎日の `{}`、`{"weekdays":[1,3,5]}`、`{"workday_only":true}`、`{"holiday_only":true}`、`{"dates":["2026-10-03"]}` のいずれかです。
- `skip_holidays`：毎日・曜日・指定日の休日を除外します。振替出勤日は勤務日です。`holiday_only=true` との併用は 400 を返します。
- `browser_sound`：`bell`、`beep`、`digital`、`chime`、`melody`、`pulse`、`sonar`、`silent`。旧ハードウェアの音声項目とは独立しています。
- `browser_volume`：アラームごとの 0–100 の整数。新規・既存とも未設定なら 100。試聴と実際の再生に適用し、0 は画面表示のみです。端末の音量にも依存し、旧ハードウェアの `volume` は引き継ぎません。
- 曜日は ISO の月曜 `1` から日曜 `7` です。旧リマインダー API の `0–6` とは異なります。
- 予定は大時計の表示タイムゾーンとは別に、常に `Asia/Taipei` を使います。
- `skipped_occurrences` はタイムゾーン付きの完全な日時です。1 回停止でも `enabled=true` を維持し、スキップ時刻の後に繰り返しアラームの有効表示が戻ります。未来のスキップが残る間、次のスキップは 400 `Occurrence already skipped; wait for resume` を返します。
- `next_occurrence` と `next_event` はプレビューで、実行記録やイベントキューではありません。

アラームには `calendar_link` を指定できます。省略または `null` の場合は固定時刻です。

```json
{"calendar_link":{"mode":"event","source_ids":["local","work"],"offset_minutes":15}}
```

- `event`：時刻付き予定の 0–1440 分前に発生し、終日予定は無視します。
- `day`：選択した参照元に当日の予定があれば、予定の固定 `time` に発生します。終日・複数日の予定も含みます。
- `source_ids` は安定した参照元 ID で、`local` は `/admin` の Server 側ローカルリマインダーで、時計パネルのブラウザー内リマインダーではありません。時計の表示選択とは独立しています。
- 任意の `target` で予定を指定できます：`{"source_id":"work","uid":"meeting","scope":"occurrence","recurrence_id":"2026-09-30T02:30:00+00:00","title":"定例会議"}`。`scope=occurrence` は今回のみ、`scope=series` はシリーズ全体で、未指定なら参照元の全予定が対象です。
- 識別子は下記の予定一覧 API から取得します。単発予定・シリーズの `recurrence_id` は空文字列で、繰り返しの今回分は変更前の `RECURRENCE-ID` を維持します。`title` は表示専用です。日時変更・取り消しは更新後の予定から判定し、購読キャッシュによって反映まで最大 5 分かかります。
- 曜日、指定日、休日フィルターは実際のアラーム日の台湾日付で判定します。プレビューは最大 366 日先まで検索します。
- 日付や固定時間帯のない常設文字は対象外です。参照元を取得できない場合、毎日アラームや古いデータへフォールバックしません。
- 連動アラームはブラウザー用に Server が計算します。旧ハードウェアの誤動作を防ぐため、schema 2 の端末応答からは除外します。

台湾カレンダーの範囲は **2023-01-01 から 2027-12-31** です。政府機関の勤務日カレンダーに基づき、すべての会社、台風休業、個人シフトを表すものではありません。範囲外は `unknown` とし、休日依存のルールを推測しません。

## 管理 API

API は JSON を受け取ります。一致した API ルートのエラーは `{"error":"..."}` で返し、データ検証は 400、存在しない項目は 404、保存失敗は以前のデータを保持して 500 です。その他の HTTP エラーは後述します。不明な URL、非対応メソッド、プロキシの応答は JSON とは限りません。本文の上限は 1 MiB です。

| パス | メソッドと用途 |
| --- | --- |
| `/api/v1/schedules` | GET 予定とプレビュー、POST 新規予定 |
| `/api/calendar` | GET/POST カレンダー参照元、PATCH 表示選択のみ |
| `/api/v1/calendar-events?source_id=work` | GET 参照元の今後 366 日の予定一覧。複数は `source_id` を繰り返す |
| `/api/v1/schedules/preview` | POST 草稿。`skip_next: true` でスキップと次回を保存せず確認 |
| `/api/v1/schedules/<id>` | PUT 指定項目、DELETE 予定 |
| `/api/v1/schedules/<id>/skip-next` | POST 次回をスキップ |
| `/api/v1/browser-alarms` | GET 次のブラウザーアラームと休日データ状態 |
| `/api/v1/holidays?date=2026-09-30` | GET 日付分類。省略時は台湾の今日 |
| `/api/v1/devices` | GET 登録端末と未確認指令 |
| `/api/v1/devices/<id>/commands` | POST `{"action":"sync"}`、202 を返す |

管理 API は信頼できる LAN を前提とし、ログイン機能はありません。異なる Origin のブラウザー要求を拒否しますが、完全な認証ではありません。外部公開時はリバースプロキシでアクセスを制限し、HTTPS を有効にしてください。

`/api/calendar` の各参照元は `id`、`name`、`provider`、`url`、`display_enabled` を持ち、`local_display_enabled` がローカルリマインダーを制御します。アラームが参照するため、更新時は ID を維持してください。POST は参照元全体を保存し、PATCH は ID と表示フラグだけを受け付けます。URL は専用管理応答にだけ現れ、時計、予定、端末、バックアップ、オフラインキャッシュには出力しません。

`GET /api/v1/calendar-events` は既存の参照元 ID を受け取り、`events` と `server_time` を返します。予定項目は `source_id`、`uid`、`text`、`starts_at`、`ends_at`、`all_day`、`recurring`、`recurrence_id` です。時刻は Unix ミリ秒で、購読 URL は含みません。取り消し・削除された予定は一覧から消えますが、保存済みの指定先が別の予定へ変わることはありません。

`POST /api/v1/schedules/preview` は `server_time`、`timezone`、`next_occurrence` を返し、`skip_next: true` では `skipped_occurrence` も返します。編集画面の次回までの残り時間は Server 時刻を使用します。再開カウントダウンはスキップ時刻までで、その次の発音時刻までではありません。`PUT /api/v1/schedules/<id>` は編集内容と `skip_next: "プレビューの完全な日時"` を保存できます。`POST /api/v1/schedules/<id>/skip-next` の `expected_occurrence` と異なる場合は 400 `Occurrence changed; preview again` を返します。無期限の無効化は `enabled=false`、早めの再開は過去のスキップを維持して未来のスキップを除き、`enabled=true` にします。

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
| `alarms[].volume` | `browser_volume` の 0–100。新版ページでは旧応答に項目がなければ 100 |
| `holiday_coverage`、`holiday_known` | 休日データ範囲と既知状態 |

API 遅延で直前のアラームを飛ばさないよう、現在の分から検索します。これは完全なオフライン予定スナップショットではありません。時計ページは約 15 秒ごとに更新します。短い切断中は読み込み済みの次回分を実行できますが、再起動やそれ以降の取得には接続が必要です。60 秒を超えて遅れたアラームは再生しません。

時計ページは Web Audio で 7 種類の音色を合成し、`silent`（無音）も選べます。ページを開くたびにベルをタップし、確認音を聞く必要があります。iOS は App・タブの切り替えや画面ロックで音声とタイマーを中断することがあるため、時計ページを前面に表示し、画面を点灯してください。バックグラウンドやロック中のアラームは保証されません。

視覚通知は赤い枠を 2 秒周期で点滅させます。設定で常時表示に変更でき、`prefers-reduced-motion` に対応するブラウザーも常時表示にします。2 回の別々のタップで、現在ページの今回分だけを停止します。予定や他の端末は変更しません。

## 端末 API

端末 API は `/api/v1/device/*` を使用し、設定応答の **`schema_version` は 2** です。旧ハードウェアの再生項目は公開しません。`browser_sound` と `browser_volume` はブラウザー再生用で、ハードウェアの音色・音量指令ではありません。schema 1 の試作 client は更新が必要です。

| パス | メソッドと用途 |
| --- | --- |
| `/api/v1/device/config` | GET schema、タイムゾーン、3 種類の revision |
| `/api/v1/device/schedules` | GET revision と予定 |
| `/api/v1/device/holidays` | GET カレンダー、出典、範囲、revision |
| `/api/v1/device/register` | POST 端末 `id` と `name`、201 を返す |
| `/api/v1/device/status` | POST 状態と確認、端末と未確認指令を返す |

予定と休日 API は読み取り専用です。`.env` に `DEVICE_API_TOKEN` を設定し、すべての端末呼び出しで `Authorization: Bearer <token>` を送信できます。空の場合は信頼 LAN モードです。これは端末ごとの ID ではなく共通 token で、管理 API は保護しません。

### 通信、取得範囲、入力制限

POST は `Content-Type: application/json` と JSON オブジェクトを使用します。未定義の項目は拒否し、要求本文の上限は 1 MiB です。GET の `Cache-Control` は `private, no-cache`、登録・状態報告は `no-store` です。Origin を送る場合は Server の origin と一致させ、HTTPS では端末側で証明書を検証してください。

GET は事前登録を必要とせず、端末 ID、日付範囲、ページで絞り込みません。予定には無効な項目と alarm 以外の種類も含み、端末がルールを評価します。カレンダー連動予定は丸ごと除外されます。休日応答は購読行程ではなく政府勤務日表の全体で、現在 1826 日、JSON は形式によって約 122 KB 以上です。`days` は日付をキーとするオブジェクトで、各値は `type`、`name`、`makeup_workday` を持ちます。範囲外の日付は存在せず、未知として扱います。config に Server 時刻はなく、別の時刻源が必要です。

| 要求 | 受け付ける入力 |
| --- | --- |
| register | 必須の `id` と `name` のみ。ID は英数字・下線・ハイフンの 1–64 文字。name は空白のみ不可、入力長 100 文字以下で、保存時に前後の空白を除去 |
| status | 必須の `id` と、任意の `firmware`、`config_revision`、`schedule_revision`、`holiday_revision`、`acknowledged_commands` のみ |
| 状態の文字列 | 各入力長 128 文字以下、空白のみ不可。保存時に前後の空白を除去。省略すると以前の値を維持し、null や空文字で消去不可 |
| ACK 配列 | 最大 100 個。各 ID は端末 ID と同じ形式 |

再登録も 201 を返し、名前だけを更新して以前の状態と指令を維持します。登録だけでは heartbeat を更新せず、新規端末は `online: false` で `last_seen` がありません。status は 200 と `device`、`commands` を返し、同じ待機指令が `device.commands` にも入ります。登録・状態報告・指令時刻は Server 生成の UTC ISO 文字列で、Unix ミリ秒とは異なります。RTC、Wi-Fi、電池、エラー、発音記録の項目は未対応です。revision は自報文字列として保存するだけで、端末の保存や実行を証明しません。

入力検証は 400、token 不一致は 401、Origin 不一致は 403、未登録端末は 404、未対応メソッドは 405、本文超過は 413、JSON Content-Type 不足は 415、保存 I/O 失敗は 500 です。解析前に HTTP 状態と Content-Type を確認してください。ルートエラーや代理サーバーのページは HTML の場合があります。一時的な失敗は間隔を延ばして再試行し、同期失敗を ACK したり、認証失敗後に空 token へ切り替えたりしないでください。完全な応答例と管理 API の入力制限は[繁体字中国語の詳細](server-api.md#裝置-api)を参照してください。

### 同期フロー

1. 固定した端末 `id` で登録します。
2. `config` を取得し、`schema_version=2` を確認します。
3. revision を比較し、変更した予定または休日だけを取得します。初回は全データを取得します。
4. 取得した各 revision が最初の config と一致することを確認し、再度 `config` を取得します。途中で版が変わった場合は再試行します。検証と永続保存の成功後だけ、設定・予定・休日・各 revision を一括で切り替えます。
5. 保存済み revision を `status` で報告します。Server はダウンロードをハードウェア実行成功とは見なしません。

revision は SHA-256 文字列です。3 つの GET リソースは `If-None-Match` または `?revision=...` に対応し、同じ場合は 304 を返します。`config` では `config_revision` ではなく応答 ETag を使用してください。ETag は予定と休日の revision も含みます。休日スナップショットの `schema_version=1` はその形式だけを表し、端末設定 schema 2 とは別契約です。

revision は不透明な識別値として扱い、HTTP 本文全体のハッシュや日時順の比較には使いません。リソースごとに ETag を保持します。304 に本文はなく、検証済みの完全なローカルデータがある場合だけ再利用できます。キャッシュが欠落・破損した場合は条件なしで再取得します。2 回目の config は、同じ同期処理で最初に得た config と比較してください。

検証と永続保存の成功後だけ完全なスナップショットを置き換え、削除や正しい空配列も反映します。容量超過を黙って切り捨ててはいけません。通信、解析、schema、保存の失敗時は以前の完全な有効データを維持し、新版の報告や ACK を行いません。ポーリングは本機の時計や発音を止めないようにします。現行契約には認可の有効期限やオフライン端末への即時失効機能はありません。

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

要求 → ポーリング → ACK の再現手順（ID は例）：

1. `POST /api/v1/device/register` に `{"id":"bedroom","name":"Bedroom"}` を送ります。
2. 管理側から `POST /api/v1/devices/bedroom/commands` に `{"action":"sync"}` を送ります。返った `command.id` を `C` とします。202 は受付で、完了ではありません。
3. 端末が `POST /api/v1/device/status` に `{"id":"bedroom"}` を送り、`commands` から `C` を取得します。ACK なしの再送や Server 再起動後も同じ未確認指令が残ります。
4. 上記の同期手順で取得・検証・永続保存した後、3 種類の保存済み revision と `"acknowledged_commands":["C"]` を `status` に送ります。
5. 応答から `C` が消え、管理一覧の再読込後も未確認指令が消えます。成功応答を受け取れなければ ACK を再送できます。同期失敗時は旧キャッシュを維持し、ACK は送りません。対象端末の一致する指令だけが削除されます。

「同期を要求済み」、`online`、revision の一致、未確認指令の消去はいずれもハードウェアの発音成功を示しません。

### 今後の拡張

有効期限付きの今後 7 日分などの発生一覧は提案段階で、対応 endpoint や schema はありません。`/api/v1/browser-alarms` はそのオフライン一覧ではありません。新契約では、参照元変更、設定が同じ場合の期間補充、削除、容量、権限範囲を扱い、既存 schema 2 の意味を変えない必要があります。端末別の認証情報、ペアリング、アカウント帰属、デプロイモードの切り替えも未実装です。開発段階と実機検収は [ESPHome ガイド](esp-home.md)（繁体字中国語）を参照してください。

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
node tests/test_time_format.js
node tests/test_offline.js
node tests/test_schedule_ui.js
node tests/test_alarms.js
node tests/test_calendar_ui.js
node tests/test_management_navigation.js
node tests/test_management_theme.js
bash -n setup.sh scripts/setup.sh update_clock.sh
```

テストは管理 CRUD、勤務日、振替出勤日、スキップ、revision、アクセス検査、端末報告・確認、旧データ保持を対象にします。更新統合テストは実際の旧／新 Server process と Git・データの復元を検査しますが、systemd、pip、Linux サービス照会は模擬です。対象ホストへの導入や実機ハードウェアの検収を証明するものではありません。

本機検証、iPad mini 1／iOS 9 の未実施検収と 2027 年以降の勤務日データ更新は[第 1 段階の検収記録](phase1-acceptance.md)を参照してください（繁体字中国語）。
