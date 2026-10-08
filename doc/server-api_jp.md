# WebClock Server：集中管理と端末 API

プログラムからの書き込み：管理画面「プログラムアクセス」(`/integrations`) で個別の認証情報を発行し、`/api/v1/control/*` からアラーム、ローカル予定、表示期間、グループ／端末への割り当てを編集できます。self でもプログラム認証が必要です。managed では管理者による発行と HTTPS が必要で、表示用の参加コードに書き込み権限はありません。[契約と使用例（繁體中文）](control-api.md)を参照してください。音声ファイルのアップロードは含みません。

Home Assistant のネイティブ参加: `POST /api/v2/device/token/prepare`, `token/join`, `token/leave`; JSON + `X-WebClock-Client: native-v1`, no browser cookies/headers. See the [native transport contract](server-api.md#非瀏覽器加入home-assistant) and [installation guide](home-assistant.md).

## B0–B4 管理・グループ・受管端末（2026-10-06）

管理者session、owner別グループ、招待、原子的な参加、認証に基づく表示・アラーム、グループ管理に対応します。既存環境は `self` を維持し、`managed` はホスト側で明示的に有効化します。端末の退出と、管理者による個別移動・無効化／再開・取り消しが可能です。操作は[ガイド](guide_jp.md)、保存と更新・復元は [B0–B1 契約](b0-b1-contract.md)を参照してください。

公開 `GET /api/time` は時刻のみを返します。managed の `/api/status` は時刻と空の予定、旧 `/api/v1/device/*` は 403、`/api/v1/browser-alarms` は 401 を返します。管理 session は端末認証を代替しません。非公開情報を含まない `/api/health` の `managed_device_schema: 3` と `managed_devices_ready: true` は endpoint の実装を示し、本番移行や実機検収の完了ではありません。以下の旧 schema 2 API は self が前提です。旧 ESP codec が自動的に schema 3 に対応するわけではありません。

### グループ管理 API

managed は管理 session、両モードの書き込みは CSRF が必要です。`/schedules#devices` で同じ操作を行えます。

| パス | メソッドと用途 |
| --- | --- |
| `/api/v1/groups` | GET 一覧、POST 新規作成。内容選択は既定で空 |
| `/api/v1/groups/initialize` | POST 既存内容を取り込む既定グループの明示的な初期化 |
| `/api/v1/groups/<id>` | GET、PATCH 名前・有効状態・表示設定・内容、DELETE メンバーのないグループ |
| `/api/v1/groups/catalog` | GET 表示既定値と内容の ID・ラベル。参照元 URL は含めない |
| `/api/v1/groups/<id>/members` | GET メンバーの認証状態と安全な観察項目。認証情報は含めない |
| `/api/v1/groups/<id>/invite` | POST 生成・再生成、GET 状態、DELETE 終了 |
| `/api/management/language` | POST `{"language":"ja"}`。ブラウザー session の管理言語だけを変更 |

`display_overrides` で省略した項目は共通設定を継承し、`night` 内も項目ごとに継承します。`false` と `0` は有効な指定値です。`content` は `calendar_source_ids`、`manual_note_ids`、`schedule_ids` と任意の `calendar_targets` を含み、空配列は選択なし、メモ ID は正の整数です。グループの表示言語は管理画面言語と独立し、共通の表示 `language` は引き続き `/api/control` で更新します。

グループの GET／一覧／保存応答は、グループ内容と有効表示設定を含む `revision` を返します。PATCH に取得時の版を指定でき、不一致は書き込まず 409 `group_settings_changed` です。共通設定は `GET /api/control` で `{settings, revision}` を取得し、既存の設定オブジェクトを `If-Match: "<revision>"` 付きで POST します。不一致は 409 `settings_changed`、成功は最新の `settings`／`revision` を返します。管理画面は常に版を送信し、同一画面の共通設定保存を順番に処理します。版を付けない旧 CLI／API の無条件更新は互換性のため維持します。ハッシュは現在状態の比較値で、変更履歴ではありません。

`calendar_targets` は `{source_id, uid, scope, recurrence_id}` の配列で、表示専用の `title` は任意です。`scope` は `series` または `occurrence`。`recurrence_id` は系列・繰り返さない予定では空文字列、繰り返しの個別予定では元の `RECURRENCE-ID` を使い、日時変更後も追跡します。参照元全体は引き続き `calendar_source_ids` で指定します。除外指定がない場合、正規化では参照元や系列に含まれる重複選択を除きます。除外指定がある場合は必要な個別選択を維持します。参照元・系列の全選択は今後の予定も含みます。`calendar_targets` がない旧データや `[]` は互換で、PATCH は省略したリストを維持します。一覧の 366 日の範囲外でも選択済みの対象は保持します。

各グループの招待は 6 文字、600 秒有効、既定 5 台（1–100）、全体で最大 100 台です。平文は生成 POST の応答だけに含み、GET・永続状態・メンバー一覧には含めません。終了・再生成は参加済みメンバーを変更しません。期限切れ・満員・終了済み・グループ無効時は参加できません。参加関連の制限は送信元ごとに 60 秒 10 回、全体で 100 回で、429 に `Retry-After` を付けます。

### Schema 3 端末 API

| パス | メソッドと用途 |
| --- | --- |
| `/api/v2/device/join/prepare` | POST `{}`。10 分の試行を作成・再利用し、`attempt_id`・`expires_at` と待機 Cookie を返す |
| `/api/v2/device/identity` | GET Cookie 往復確認。`pending` 試行は group を含まず、`active` は `{status: "active", identity, group: {id, name}}` を返す |
| `/api/v2/device/join` | POST `{"attempt_id":"…","code":"ABC234"}`。枠消費と参加を原子的に保存。初回 201、同じ確定済み試行の再送は 200 |
| `/api/v2/device/leave` | POST `{}`。Cookie と同一オリジンの CSRF のみ。この端末の認可と観測記録を削除し、200 `{status: "left"}` を返して同じパスの Cookie を削除する |
| `/api/v2/device/display` | GET 端末／グループの有効設定、選択済み予定、次の予定、対象のお知らせ |
| `/api/v2/device/browser-alarms` | GET 選択済みアラームと計算結果 |
| `/api/v2/device/status` | POST 名前・能力・revision・指令 ACK。認証情報から端末を決定し、`id`・`group_id` の自己指定は不可 |

ブラウザーは prepare → identity による Cookie 確認 → join の順で参加します。待機中の秘密は確定後も同じ端末認証情報として使用するため、成功応答を失って再送しても二重に枠を消費しません。コードは URL やブラウザー保存領域に書きません。`webclock_device` は host-only・HttpOnly・SameSite=Lax、パス `/api/v2/device` の Cookie です。managed は HTTPS と Secure Cookie を要求します。prepare・join・leave は Bearer を拒否し、それ以外は独立した端末 Bearer を受け付けます。管理 session や旧共有 `DEVICE_API_TOKEN` は使用できません。Cookie 書き込みには同一オリジンと CSRF が必要です。有効な端末 Bearer は Cookie CSRF を免除しますが、Origin は検査し、クロスオリジン読み取りを許可しません。

退出と管理者による個別アクセスの取り消しは、対象端末の認可、完了済み参加試行、`devices.json` の観測記録を削除します。管理一覧からも消え、全体の上限 100 台の枠を解放します。旧認証情報と旧参加試行の再送は永久に無効となり、API は直ちに拒否します。オフライン端末には既存の最大 300 秒のリースが適用されます。他のメンバー、グループ、ローカルのリマインダーは保持し、元の招待の使用済み枠は戻しません。無効化されたグループからも退出できます。成功後は再度 prepare し、新しい招待で新しい端末 ID として参加できます。保存失敗は 500（端末の退出は `storage_failure`）を返し、Cookie を削除せず、成功とも報告しません。観測記録の削除後に認可の保存が失敗した場合、元の認可は有効なままで、観測記録は次回の status で再作成されます。複数ファイルの原子的なロールバックは保証しません。無効化と移動は認証情報・観察記録を維持します。取り消し後は直接再開できません。

display・alarms は `schema_version: 3`、`identity`、config・schedule・holiday revision、ミリ秒 `server_timestamp`、最大 300 秒の `lease` を返します。identity は owner・device・group ID、認証世代、割り当て revision、`identity_revision` を含みます。304 を含む応答の直前に現在の認証と内容範囲を再確認し、I/O 中の範囲変更は古い内容ではなく 409 `display_scope_changed` を返します。ETag 応答は `private, no-cache` と `Vary: Cookie, Authorization` を使い、304 は `X-WebClock-Server-Timestamp`、`X-WebClock-Lease-Expires-At`、`X-WebClock-Identity-Revision` で期限を更新します。参加・identity 応答は `no-store` です。

非公開キャッシュは端末認証の範囲で分離します。401・403、認証の変更、期限切れで非公開予定・お知らせ・ブラウザーアラームを消去し、通信エラー時はその実行中の期限内データだけを維持できます。アラームはグループの表示タイムゾーンと独立して `Asia/Taipei` で計算します。連動参照元が欠ける場合は該当アラームを除外し、毎日発音へ戻しません。ESP の 7 日間オフライン発生一覧や、旧 iPad・ロック画面音声・実機検収を意味する機能ではありません。

[繁體中文](server-api.md) · [English](server-api_en.md) · **日本語** · [README](../README_jp.md)

このプロジェクトは、予定、台湾の勤務日データ、端末登録、同期リビジョン、端末状態を管理します。self モードのセルフホスト時計ではブラウザーアラームも実行します。`/schedules` でアラームを編集・プレビューし、`/` で内蔵音と赤い枠の通知を表示します。`/admin` は表示設定、購読カレンダー、文字リマインダーを別に管理します。参加済みの schema 3 時計は所属グループの非公開内容だけを取得します。

端末での実行はファームウェアが担当します。[`firmware/`](../firmware/README.md) にはクロスコンパイル済みの ESP32-S3／ESPHome 試作版があり、OLED、固定ルールのアラーム同期、永続キャッシュ、圧電ブザー、停止ボタンを実装しています。実機は未検証です。カレンダー連動、ブラウザー音色の忠実な再現／音声ファイル、スヌーズ、電池バックアップ RTC、OTA、汎用の公開ファームウェアは未提供です。端末は HTTP/JSON API を使用し、このプロジェクトの Python モジュールを読み込む必要はありません。

現在の試作版の使用手順と制限は [ESPHome 端末ガイド](esp-home.md)、完全な応答例は [API 詳細](server-api.md#裝置-api)を参照してください。どちらも繁体字中国語です。起動のたびに時刻の取得と Server 設定の検証が成功してからアラームを有効にします。その後の通信断ではキャッシュで動作しますが、オフライン再起動時に自動で有効にはしません。

現在の管理領域は 1 owner 分です。**旧 self モードの端末は同じ予定とカレンダーを使用します**。schema 3 は認証済み端末に端末指定とグループを解決した内容を配信します。複数ユーザーアカウントとマルチテナントは未実装です。

### 項目ごとのグループ割り当てと表示区間

`GET /api/v1/groups/assignments` は現在の管理者のグループとリマインダー・予定の割り当てを返します。カレンダー項目の割り当ては `GET /api/calendar/display-items` に含まれます。`PUT /api/v1/groups/assignments` は `item`（`{kind:"manual_note",id}`、`{kind:"schedule",id}`、`{kind:"calendar",target}`）と `group_ids` を受け取り、関連グループを一度に原子的に保存します。空配列は割り当て解除です。`all:true` は保存時点の全グループを指し、今後作成するグループは含みません。系列の `keep_partial_group_ids` は未操作の部分割り当てを維持し、選択済みグループと重複できません。不明な項目や別管理者のグループは書き込み全体を拒否します。

各 assignment は `revision` を含みます。PUT に取得時の版を渡せ、不一致は 409 `assignment_changed` です。`GET /api/v1/groups/assignments?item=<URLエンコードJSON>` は単一項目の再読み込み用に `{groups, assignment}` を返します。版には現在のグループ一覧と当該項目の割り当て、関連する系列・個別予定の選択／除外を含めます。部分割り当ての表示が同じでも新しい例外を上書きしません。無関係な項目の変更は保存を妨げず、項目別変更は古いグループ全体の編集を無効化します。版なしの旧呼び出しは互換ですが、現在の管理画面は必ず版を渡し、409 後は自動再送しません。

任意の `content.calendar_exclusions` は `calendar_targets` と同じ識別形式を使用し、省略時は空です。表示認可は個別除外、個別選択、系列除外、系列選択、参照元全体の順で決定します。継承された個別予定の解除ではその予定だけを除外し、参照元や将来の予定は維持します。系列全体の選択・解除はその系列の個別例外を置き換えます。アラームの参照元認可は独立しています。

`/api/calendar` の PATCH は `calendar_targets` 全体と任意の `display_window` も受け付けます。省略または `{mode:"day"}` は予定当日、`{mode:"relative",before_minutes:180,end:"day_end"}` は3時間前から当日終了までです。終了は `event_end` も指定でき、分数は0–525600の整数です。個別予定は `{mode:"absolute",start:"2026-10-06T08:00",end:"2026-10-07T10:00"}` も使用できます。管理表示タイムゾーンで開始を含み終了を含まず、系列は各回の実際の時刻に従い個別指定を優先します。元の予定とアラームの時刻は変更しません。

`GET /api/calendar/display-items` は選択済み予定、安全な参照元名、時刻、表示区間、グループ割り当て、未検出状態を時刻順に返します。明示的に選んだ系列は代表カード1件にまとめ、個別例外は別に表示します。非公開URLを含まず、取得失敗は空の選択ではなく503です。ホストバックアップには保存されますが、管理画面のversion 1 JSONは引き続きsettingsとnotesのみです。


### 対象を指定するお知らせ

お知らせは `manual_notes.json` と既存のフォームルートを使います。POST `/add` で追加、POST `/schedule/<id>` で編集、POST `/toggle/<id>` で一時停止・再開、POST `/delete/<id>` で削除します。管理認証と CSRF の規則は従来どおりです。フォームは `announcement=1` と複数の `announcement_group_ids`／`announcement_device_ids` を送ります。任意の `expires_at` は `YYYY-MM-DDTHH:MM` で、管理表示タイムゾーンからタイムゾーン付き ISO 8601 に変換します。通常のリマインダーは `announcement` を空にし、お知らせの期限を持ちません。

保存する note に `announcement_targets: {group_ids: [], device_ids: []}` と `expires_at` を追加できます。各 ID 配列は最大 100 件で、保存時に重複を除きます。ID は ASCII `[A-Za-z0-9_-]` の 1–128 文字です。`expires_at` はタイムゾーン付き ISO 8601 文字列で、空文字列は追加の絶対期限なしを意味します。グループまたは端末のどちらかに一致し、現在の端末・グループ認可が有効なら配信します。空の対象には配信しません。日付、range／daily、曜日、enabled、絶対期限は管理タイムゾーンで判定し、アラームの `Asia/Taipei` 規則とは独立しています。

`GET /api/v2/device/display` に `announcements: [{id, text, visible_until}]` を追加します。`visible_until` は Unix ミリ秒で、現在のスナップショットの最長 300 秒、絶対期限、現在の表示区間終了の最も早い値です。display／アラーム全体のリースは短縮しません。`events`、`next_event`、サーバー側 local カレンダー、browser-alarms には混ぜず、`schedules.type=announcement` も使いません。旧 schema 1／2 の契約は維持します。匿名 self 状態のお知らせは空で、登録済みの self 端末は v2 から対象のお知らせを取得できます。ブラウザーには永続保存せず、認可喪失、認証・範囲変更、リース期限、個別期限で消去します。

フォームは空の対象を配信なしで保存できますが、存在しない対象や他 owner の対象は拒否します。version 1 `/api/backup` は `notes` のお知らせ欄を保持し、読み込み時に構造と存在する対象の所有者を検証します。存在しない過去の ID は保持できますが、認可や対象の新規作成は行いません。完全ホストバックアップはデータを保持し、履歴復元時は端末資格情報を無効化します。操作は[お知らせガイド](guide_jp.md#グループ端末を指定するお知らせ)を参照してください。

## 起動と構成

`python app.py`、Docker Compose、または既存の systemd サービスを使用します。`/admin` からアラーム管理に進むか、`/schedules` を直接開きます。

```text
app.py / setup.sh / update_clock.py / update_clock.sh  互換デプロイ入口
webclock/
  app.py                     時計、設定、カレンダー、起動
  api/
    management.py            管理画面と予定／端末管理 API
    device.py                self モードの旧 schema 2 端末 API
    managed_device.py        schema 3 参加・認証・グループ表示・状態
    groups.py                グループ・招待・内容目録・メンバー
  services/                  予定、休日、端末、JSON 保存サービス
  translations/              Web UI 文言
  data/taiwan_calendar.json  読み取り専用カレンダーと出典
templates/                   セルフホスト HTML
static/                      Web CSS / JavaScript
scripts/                     インストールと更新
tests/                       Server、API、Web 回帰テスト
doc/                         ガイドと API 契約
firmware/                    ESP32-S3 ESPHome YAML、同期コンポーネント、ホストテスト。コンパイル済み・実機未検証
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

API は JSON を受け取ります。一致した API ルートのエラーは `{"error":"..."}` で返し、データ検証は 400、存在しない項目は 404、保存失敗は該当ファイルの以前のデータを保持して 500 です。退出・アクセス取り消しの複数ファイル保存時の制限は前述のとおりです。その他の HTTP エラーは後述します。不明な URL、非対応メソッド、プロキシの応答は JSON とは限りません。本文の上限は 1 MiB です。

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
| `/api/v1/devices/<id>` | PATCH `{"name":"リビングの時計"}`、200 と `device` を返す。DELETE は現在の owner の独立した端末認可を取り消し、200 `{status: "revoked"}` を返す |
| `/api/v1/devices/<id>/authorization` | PATCH `{"group_id":"移動先グループID","enabled":false}`。片方の項目だけでも可。移動または無効化／再開し、200 と安全な `device` 認可情報を返す |
| `/api/v1/devices/<id>/content-settings` | GET/PATCH 端末の内容指定・継承・有効プレビュー。PATCH は revision が必須 |
| `/api/v1/devices/<id>/commands` | POST `{"action":"sync"}`、202 を返す |

managed の `GET /api/v1/devices` は現在の owner の認可済み端末を、未報告でも `can_revoke: true` として表示します。`reported: false` では管理画面の改名・同期操作を無効にします。self は旧観測一覧を維持し、legacy 端末は `can_revoke: false` です。既存の出所不明な観測記録は過去の退出による残存か判定できないため、推測で削除せず保持します。DELETE は存在しない端末、他の owner、共有 token のみの旧端末に 404 を返します。共有 token は端末ごとに失効できません。

`GET /api/v1/devices/<id>/display-settings` は `{display_overrides, inherited_settings, effective_settings, sources, revision}` を返します。`sources` は `brightness`、`night.enabled` などのパスに `device|group|default` を返します。端末一覧の各行と認可変更の応答にも `display_settings` を追加します。同じ URL への PATCH は `{"revision":"取得時の版","display_overrides":{"brightness":10}}` で個別指定全体を置換し、省略項目は継承、`{}` は全継承です。表示項目のみ受け付け、`night` は 5 項目すべてが必要です。`false`／`0` を保持し、内容・認証情報・非公開参照元は受け付けません。端末 > グループ > 共通設定で計算し、移動時も個別指定を保持します。表示変更は `assignment_revision` を変更せず、有効値の変更で `config_revision`／ETag が変わります。アラームは引き続き台北時間です。版には端末・上位設定と所属が含まれ、競合は 409 `display_settings_changed` で保存しません。不存在・他 owner・legacy は 404、再参加が必要なら 409 `device_rejoin_required`。入力・CSRF・保存・破損状態は既存の 400／403／500／503 に従います。

`GET /api/v1/devices/<id>/content-settings` は `{content_overrides, inherited_content, effective_content, sources, revision}` を返します。`sources` の `calendar`、`manual_note_ids`、`schedule_ids` は `device|group` です。端末一覧と認可変更応答にも `content_settings` を含みます。PATCH は `{"revision":"取得時の版","content_overrides":{"manual_note_ids":[],"schedule_ids":["alarm-id"]}}` を必須とし、個別指定全体を置換します。省略した種類は継承、`{}` は全継承、明示的な空リストは配信なしです。カレンダー個別指定は `calendar_source_ids` が必須で、`calendar_targets`／`calendar_exclusions` と一組です。後二者の省略は空リストです。既存 ID を検証・重複排除し、非公開 URL や共通原本の変更は受け付けません。

実際の変更は原子的に保存して `assignment_revision` を増やし、旧 identity／ETag を無効化します。同値の再送は書き込みません。移動時は端末指定を保持し、継承項目を新グループから再計算します。読み取りには有効な端末認可が必要で、削除した参照元・予定を全内容へフォールバックしません。版は上位内容と端末割り当てを含み、古い保存は 409 `content_settings_changed` です。404、再参加が必要な 409、400／403／500／503 は端末表示設定と同じです。完全ホストバックアップと過去の復元は `content_overrides` を保持し、旧認証情報は失効します。管理画面の version 1 JSON は端末認可データを含みません。

`PATCH /api/v1/devices/<id>/authorization` は、`enabled`（真偽値）と／または `group_id`（既存グループ ID）だけを持つ空でないオブジェクトを受け付けます。別の移動先は同じ owner に属し、有効である必要があります。現在のグループが無効でも端末の無効化・再開・移動は可能ですが、端末を再開してもグループは有効になりません。成功応答は `{device: {id, group_id, group_name, group_enabled, enabled, authorization_status, assignment_revision, rejoin_required}, display_settings, content_settings}` です。GET 端末一覧にも同じ項目を追加し、端末の `name` は維持します。`authorization_status` は `active|disabled|revoked`。`rejoin_required: true` は、取り消し済みまたは認証情報が消去された過去の記録も含みます。認証情報とその digest は返しません。

認可ファイルを一度の原子的な書き込みで保存します。実際の変更で `assignment_revision` が一度増え、同じ値の再送では書き込みません。移動・無効化／再開は認証情報、端末名、能力、報告、同期 ACK を保持し、招待の使用数を変えません。無効化後の非公開 API は拒否され、再開後は元の cookie で再び本人確認できます。移動後は新しいグループ範囲と revision を返し、旧 ETag や読み込み途中の旧データ／304 を許可しません。オフラインの非公開内容には最長 300 秒の lease が適用されます。

入力不正は 400。存在しない端末、他 owner、legacy 観測だけの端末、および存在しない／他 owner の移動先は 404 `not_found` です。無効なグループへの移動は 409 `group_disabled`。取り消し済み、再参加が必要、または認証情報が消去済みの記録は 409 `device_rejoin_required` で、過去の認証情報を復活させません。管理認証／CSRF エラーは 401／403、保存失敗は 500 で元の認可ファイルを保持し、破損した認可データは 503 `access_not_ready` です。改名は従来の PATCH `/api/v1/devices/<id>` に分け、複数ファイルの一括更新にはしません。

自用モードは信頼できる LAN の共通管理を維持し、managed モードは管理 session を要求します。Origin/CSRF は認証ではありません。外部公開には HTTPS と適切なプロキシ設定が必要です。

管理用 POST／PUT／PATCH／DELETE はすべて CSRF token と同じセッションの `webclock_csrf` cookie が必要です。設定、リマインダー、バックアップ読み込み、プレビュー、端末への同期要求も含みます。管理画面は自動で送信します。外部 client は GET `/api/csrf` の cookie を保持し、応答の `csrf_token` を `X-CSRF-Token` で送信してください。HTML フォームでは hidden の `csrf_token` を使います。managed では HTTPS の `/login` でログインし、成功後に更新された CSRF token を使います。Origin を省略しても token は必要です。CSRF token の不足・不一致は 403 `csrf_failed`、管理 session の不足・失効は API/JSON 要求の管理書き込み前に 401 `authentication_required` です。クロスオリジン情報は 403 で拒否し、managed の権限チェックでは `cross_origin_forbidden`、CSRF チェックでは `csrf_failed` を返します。[要求例](server-api.md#管理-api)を参照してください。

リマインダー削除 `/delete/<id>` は token 付き POST のみ受け付け、GET／HEAD は 405 です。管理 HTML、エラーページ、token 応答は `no-store` で、クロスオリジン読み取りを許可しません。未初期化の自用モードは一時署名秘密を使うため、再起動で CSRF cookie が失効します。初期化後の署名秘密は通常の再起動で維持されます。ログイン/ログアウトで CSRF token を更新し、ホストのパスワード復元で全管理 session を失効させます。失効後は管理画面を再読み込みするか、新しい CSRF token を取得してください。公開時計に CSRF cookie は不要です。`/api/v1/device/*` の独立した `DEVICE_API_TOKEN` と CSRF 不要の契約は self モードのみで、managed はこれらの旧端末呼び出しを拒否します。CSRF 対策自体は利用者の認証ではありません。

`/api/calendar` の各参照元は `id`、`name`、`provider`、`url`、`display_enabled` を持ち、`local_display_enabled` がローカルリマインダーを制御します。アラームが参照するため、更新時は ID を維持してください。POST は参照元全体を保存し、PATCH は ID・表示フラグ・上記の項目表示規則を受け付けます。URL は専用管理応答にだけ現れ、時計、予定、端末、バックアップ、オフラインキャッシュには出力しません。

`GET /api/v1/calendar-events` は既存の参照元 ID を受け取り、`events` と `server_time` を返します。予定項目は `source_id`、`uid`、`text`、`starts_at`、`ends_at`、`all_day`、`recurring`、`recurrence_id` です。時刻は Unix ミリ秒で、購読 URL は含みません。取り消し・削除された予定は一覧から消えますが、保存済みの指定先が別の予定へ変わることはありません。 指定した参照元の読み込みが一つでも失敗すると 503 `calendar_not_ready` を返し、一部または空の一覧を成功として返しません。管理画面は現在の選択を保持します。

`POST /api/v1/schedules/preview` は `server_time`、`timezone`、`next_occurrence` を返し、`skip_next: true` では `skipped_occurrence` も返します。編集画面の次回までの残り時間は Server 時刻を使用します。再開カウントダウンはスキップ時刻までで、その次の発音時刻までではありません。`PUT /api/v1/schedules/<id>` は編集内容と `skip_next: "プレビューの完全な日時"` を保存できます。`POST /api/v1/schedules/<id>/skip-next` の `expected_occurrence` と異なる場合は 400 `Occurrence changed; preview again` を返します。無期限の無効化は `enabled=false`、早めの再開は過去のスキップを維持して未来のスキップを除き、`enabled=true` にします。

## ブラウザーアラーム

self モードの `GET /api/v1/browser-alarms` の主な項目を以下に示します。managed では管理者 session があっても 401 `device_authorization_required` です。

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

端末 API は `/api/v1/device/*` を使用し、設定応答の **`schema_version` は 2** です。旧ハードウェアの再生項目は公開しません。`browser_sound` と `browser_volume` はブラウザー再生を表し、汎用のハードウェア指令ではありません。ESPHome 試作版では、無音以外の音色を同じビープ音に変換し、端末の上限値で音量を調整します。[ハードウェア側の対応](esp-home.md#顯示聲音與按鍵)を参照してください。schema 1 の試作 client は更新が必要です。

| パス | メソッドと用途 |
| --- | --- |
| `/api/v1/device/config` | GET schema、タイムゾーン、3 種類の revision |
| `/api/v1/device/schedules` | GET revision と予定 |
| `/api/v1/device/holidays` | GET カレンダー、出典、範囲、revision |
| `/api/v1/device/register` | POST 端末 `id` と `name`、201 を返す |
| `/api/v1/device/status` | POST 状態と確認、端末と未確認指令を返す |

予定と休日 API は読み取り専用です。self モードでは `.env` に `DEVICE_API_TOKEN` を設定し、すべての端末呼び出しで `Authorization: Bearer <token>` を送信します。空の場合は信頼 LAN からの共通アクセスになります。これは端末ごとの ID ではなく共通 token で、管理 API は保護せず、managed の旧端末 endpoint を利用する権限にもなりません。

### 通信、取得範囲、入力制限

POST は `Content-Type: application/json` と JSON オブジェクトを使用します。未定義の項目は拒否し、要求本文の上限は 1 MiB です。GET の `Cache-Control` は `private, no-cache`、登録・状態報告は `no-store` です。Origin を送る場合は Server の origin と一致させ、HTTPS では端末側で証明書を検証してください。

GET は事前登録を必要とせず、端末 ID、日付範囲、ページで絞り込みません。予定には無効な項目と alarm 以外の種類も含み、端末がルールを評価します。カレンダー連動予定は丸ごと除外されます。休日応答は購読行程ではなく政府勤務日表の全体で、現在 1826 日、JSON は形式によって約 122 KB 以上です。`days` は日付をキーとするオブジェクトで、各値は `type`、`name`、`makeup_workday` を持ちます。範囲外の日付は存在せず、未知として扱います。config に Server 時刻はなく、別の時刻源が必要です。

| 要求 | 受け付ける入力 |
| --- | --- |
| register | 必須の `id` と `name`、任意の `device_type` と `capabilities`。ID は英数字・下線・ハイフンの 1–64 文字。name は空白のみ不可、入力長 100 文字以下で、保存時に前後の空白を除去 |
| status | 必須の `id` と、任意の `firmware`、`config_revision`、`schedule_revision`、`holiday_revision`、`acknowledged_commands`、`device_type`、`capabilities` のみ |
| 状態の文字列 | 各入力長 128 文字以下、空白のみ不可。保存時に前後の空白を除去。省略すると以前の値を維持し、null や空文字で消去不可 |
| `device_type` | 任意の自報文字列。空白のみ不可、入力長 50 文字以下、保存時に前後の空白を除去。特定の機種一覧には制限せず、省略時は以前の値を維持 |
| `capabilities` | 空でないオブジェクト。キーは `display`、`audio`、`notifications`、`background`、`calendar` のみ、値は JSON の真偽値。空オブジェクト、null、不明なキー、`0`／`1` は拒否 |
| ACK 配列 | 最大 100 個。各 ID は端末 ID と同じ形式 |

`capabilities` を指定すると以前の能力オブジェクト全体を置き換え、Server が `capabilities_reported_at` を更新します。省略時はデータと時刻を維持します。未報告の能力は不明で、`false` ではありません。未報告の `device_type`、`capabilities`、`capabilities_reported_at` は `null` です。端末の自報情報であり、実機検証結果やアクセス権限を表しません。

管理 PATCH `/api/v1/devices/<id>` は `{"name":"リビングの時計"}` のみを受け付け、管理 CSRF token が必要です。入力は 100 文字以下の空白のみでない文字列で、保存時に前後の空白を除去します。空文字、空白のみ、null、追加項目は 400 です。成功時は `{"device":{...}}` を返します。表示用 `name` は `admin_name` を優先し、未設定時は `reported_name` を使います。初期の `admin_name` は `null` です。再登録では自報名だけを更新し、管理名を上書きしません。`name` のみを持つ旧記録も読み取れます。名前と能力情報は `devices.json` に保存され、再起動後も残ります。管理名の消去 API は未対応です。

再登録も 201 を返し、自報名を更新して以前の状態と指令を維持します。登録だけでは heartbeat を更新せず、新規端末は `online: false`、`sync_status: {"state":"idle"}` で `last_seen` がありません。status は 200 と `device`、`commands` を返し、同じ待機指令が `device.commands` にも入ります。登録・状態報告・指令時刻は Server 生成の UTC ISO 文字列で、Unix ミリ秒とは異なります。RTC、Wi-Fi、電池、エラー、発音記録の項目は未対応です。revision は自報文字列として保存するだけで、端末の保存や実行を証明しません。

入力検証は 400、token 不一致は 401、Origin 不一致は 403、未登録端末は 404、未対応メソッドは 405、本文超過は 413、JSON Content-Type 不足は 415、保存 I/O 失敗は 500 です。アプリの API ルートエラーは JSON ですが、代理サーバーのエラーページは HTML の場合があるため、解析前に HTTP 状態と Content-Type を確認してください。一時的な失敗は間隔を延ばして再試行し、同期失敗を ACK したり、認証失敗後に空 token へ切り替えたりしないでください。完全な応答例と管理 API の入力制限は[繁体字中国語の詳細](server-api.md#裝置-api)を参照してください。

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

`online` は 120 秒以内に状態報告を受けたことを示します。約 60 秒ごとの報告は一般的な推奨値です。ESPHome 試作版は約 30 秒ごとに確認・報告し、失敗時は再試行間隔を延ばします。「同期を要求」は `sync` 指令だけを追加し、確認されるまで応答に残ります。繰り返し要求しても未確認指令は 1 件です。端末は指令 ID で重複を除き、永続保存と適用が成功した後だけ確認してください。

各 `device` は `sync_status` も返します。指令取得と ACK の入力契約は変わりません。

| `state` | 意味と追加項目 |
| --- | --- |
| `idle` | 未確認指令も保存済み ACK もない |
| `pending` | ACK 待ち。`command_id`、`requested_at`、`timeout_at` |
| `timed_out` | 要求から 300 秒以上経過しても ACK がない。項目は `pending` と同じ |
| `confirmed` | 最新の一致する ACK を保存済み。`command_id`、`requested_at`、`acknowledged_at` |

時刻は Server 生成の UTC ISO 文字列です。タイムアウトで指令を取り消すことはなく、再要求でも元の ID と要求時刻を維持し、遅れて到着した一致する ACK でも確認できます。不明な ID、他端末の指令 ID、重複 ACK は別の指令を確認せず、保存済み確認時刻も変更しません。未確認指令と最新 ACK は Server 再起動後も残ります。新たな同期要求があれば、その `pending` が優先されます。報告 revision の一致は ACK を生成しません。`confirmed` は端末の確認であり、実際の音声・画面出力の成功を証明しません。

要求 → ポーリング → ACK の再現手順（ID は例）：

1. `POST /api/v1/device/register` に `{"id":"bedroom","name":"Bedroom"}` を送ります。
2. 管理側から `POST /api/v1/devices/bedroom/commands` に `{"action":"sync"}` を送ります。返った `command.id` を `C` とします。202 は受付で、完了ではありません。
3. 端末が `POST /api/v1/device/status` に `{"id":"bedroom"}` を送り、`commands` から `C` を取得します。ACK なしの再送や Server 再起動後も同じ未確認指令が残ります。
4. 上記の同期手順で取得・検証・永続保存した後、3 種類の保存済み revision と `"acknowledged_commands":["C"]` を `status` に送ります。
5. 応答から `C` が消え、管理一覧の再読込後も未確認指令が消えます。成功応答を受け取れなければ ACK を再送できます。同期失敗時は旧キャッシュを維持し、ACK は送りません。対象端末の一致する指令だけが削除されます。

「同期を要求済み」、`online`、revision の一致、未確認指令の消去はいずれもハードウェアの発音成功を示しません。

### 今後の拡張

有効期限付きの今後 7 日分などの発生一覧は提案段階で、対応 endpoint や schema はありません。`/api/v1/browser-alarms` はそのオフライン一覧ではありません。新契約では、参照元変更、設定が同じ場合の期間補充、削除、容量、権限範囲を扱い、既存 schema 2 の意味を変えない必要があります。B2–B4 はブラウザー参加、端末別の認証情報、グループ表示、個別の認可ライフサイクル操作を提供します。ホストで `--enable-managed` を指定して明示的に切り替えられ、旧 `--enable-managed-test` は互換エイリアスです。ESP の新契約への対応は今後の対象です。開発段階と実機検収は [ESPHome ガイド](esp-home.md)（繁体字中国語）を参照してください。

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
node tests/test_group_ui.js
node tests/test_device_enrollment.js
bash -n setup.sh scripts/setup.sh update_clock.sh
```

テストは管理 CRUD、勤務日、振替出勤日、スキップ、revision、アクセス検査、端末報告・確認、旧データ保持を対象にします。更新統合テストは実際の旧／新 Server process と Git・データの復元を検査しますが、systemd、pip、Linux サービス照会は模擬です。対象ホストへの導入や実機ハードウェアの検収を証明するものではありません。

本機検証、iPad mini 1／iOS 9 の未実施検収と 2027 年以降の勤務日データ更新は[第 1 段階の検収記録](phase1-acceptance.md)を参照してください（繁体字中国語）。
