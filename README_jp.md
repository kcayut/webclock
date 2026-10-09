<img src="static/brand/logo.svg" width="64" height="64" alt="WebClock logo">

# WebClock

[繁體中文](README.md) · [English](README_en.md) · **日本語**

**[GitHub の公開時計を開く](https://kcayut.github.io/webclock/)** · [ダウンロードとオフライン利用](doc/installation.md#no-server)（繁体字中国語）

iPad、タブレット、使っていない画面を大きな時計にできます。公開版はそのまま利用でき、セルフホスト版ではカレンダー、リマインダー、ブラウザーアラーム、ナイトモード、バックアップを使えます。

> [!IMPORTANT]
> ブラウザーアラームは、画面を点灯したままページを前面に表示する必要があります。iOS の画面ロックや App の切り替え後は、音声とタイマーの継続を保証できません。

## 3 つの利用方法

- **公開版を使う：**[公開時計](https://kcayut.github.io/webclock/)を開くだけで利用できます。アカウントやサーバーは不要で、時刻とタイムゾーンは端末の設定に従います。
- **オフライン時計をダウンロード：**パソコンで [ZIP をダウンロードして展開](doc/installation.md#offline-download)し、一番外側の `index.html` をブラウザーで開きます。サーバーのインストールは不要です。タブレットは[オフラインキャッシュと iOS 9 の制限](doc/installation.md#offline-cache)を参照してください（繁体字中国語）。
- **セルフホスト：**パソコン、NAS、Raspberry Pi で完全版を実行します。`/admin` で表示・カレンダー・文字リマインダーを、`/schedules` でアラームと端末状態を管理します。

セルフホスト版の UI は繁体字中国語、英語、日本語に対応し、Google、Apple iCloud、その他の ICS カレンダーを購読できます。非公開 URL は公開時計、状態応答、旧 JSON 出力には含まれません。管理画面から完全バックアップを1つの `.webclock` ファイルとして保存し、アカウント・非公開カレンダー・端末設定を新サーバーや HA App に移行できます。初期設定ではパスワードで暗号化しますが、暗号化せずに保存することもできます。[バックアップと移行](doc/guide.md#完整備份與搬家)（繁体字中国語）を参照してください。

時計は時刻・日付・曜日を先に表示し、読み込み済みで前面実行中のページは通信・保存領域・追加機能の失敗で停止しない設計です。端末管理では名前、自報能力、同期確認状態を扱えます。グループ、6文字の参加コード、端末別認可、移動、無効化・再開、取り消しに対応します。managedモードはホスト側で明示的に有効化し、既存環境は既定でselfを維持します。操作と制限は[ガイド](doc/guide_jp.md#端末同期状態)、現在の検証と未実施項目は [A 段階の検収記録](doc/phase-a-acceptance.md) / [B 段階のグループ・認証検証](doc/phase-b-acceptance.md)（繁体字中国語）を参照してください。CI と iPad mini 1／iOS 9 の実機検収は分けて記録します。

## インストール方法

| 方法 | 対象環境 |
| --- | --- |
| **Bare metal** | Raspberry Pi OS、Debian、Ubuntu。systemd による自動起動 |
| **Docker** | Docker Compose が使えるパソコン、NAS、Linux |
| **Home Assistant** | HA OS に App リポジトリを追加してインストール。統合と同梱カードは HACS で導入 |

**[HA App をインストール](doc/installation.md#home-assistant)** · **[HA 統合とカードをインストール](doc/home-assistant.md#安裝整合)**

**[インストールガイドへ →](doc/installation.md)**（繁体字中国語）：3 種類の手順、前提条件、self／managed の有効化、HTTPS 設定をまとめています。

**[端末を時計として使う →](doc/display-devices.md)**（繁体字中国語）：iPad／iPhone、Android、Windows、Mac のホーム画面アイコン、全画面表示、スリープ防止をバージョン別に説明。初代 iPad mini／iOS 9 も含みます。

Linux／Docker は **self（自用）** が既定です。管理者ログインと端末別認可が必要な場合、新規導入に `--managed` を追加し、HTTPS を設定します。HA App は HA ログインで管理画面を保護し、managed 完全バックアップを読み込んだ場合は元の WebClock アカウントでもログインします。初回イメージの公開と HA OS 実機検証はまだ完了していません。[リリース状況](doc/ha-release.md)を確認してください。開発用のローカルビルドも利用できます。

**詳しい説明：**[日本語ガイド](doc/guide_jp.md) · [Home Assistant 統合とカード](doc/home-assistant.md) · [端末 API](doc/server-api_jp.md) · [ESPHome 開発](doc/esp-home.md) · [ファームウェア](firmware/README.md)（HA・ファームウェア関連は繁体字中国語）。

## 開発支援

WebClock の全機能は無料で利用できます。役に立った場合は、今後の開発を支援していただけるとうれしいです。

<!-- Brand assets: https://www.paypalobjects.com/paypal-ui/logos/svg/paypal-mark-color.svg | https://storage.ko-fi.com/cdn/cup-border.png | O’Pay and ECPay logos supplied by the project owner -->
<table>
  <tr>
    <td align="center" width="160"><a href="https://www.paypal.com/paypalme/oilstuck"><img src="doc/images/support/paypal.svg" height="48" alt="PayPal で開発を支援"><br><strong>PayPal</strong></a></td>
    <td align="center" width="160"><a href="https://ko-fi.com/kcayut"><img src="doc/images/support/ko-fi.png" height="48" alt="Ko-fi で開発を支援"><br><strong>Ko-fi</strong></a></td>
    <td align="center" width="220"><a href="https://payment.opay.tw/Broadcaster/Donate/6CF8CF9E519E0ED13E244399607ADDD7"><img src="doc/images/support/opay.png" height="48" alt="O’Pay で開発を支援"><br><strong>O’Pay</strong></a><br>O’Pay 会員番号: 2218408</td>
    <td align="center" width="160"><a href="https://p.ecpay.com.tw/A2FA21C"><img src="doc/images/support/ecpay.png" height="48" alt="ECPay で開発を支援"><br><strong>ECPay</strong></a></td>
  </tr>
</table>

## フィードバック

問題の報告や提案は [Issues](https://github.com/kcayut/webclock/issues) へお願いします。
