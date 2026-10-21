<img src="static/brand/logo.svg" width="64" height="64" alt="WebClock logo">

# WebClock

[繁體中文](README.md) · [English](README_en.md) · **日本語**

[ドキュメント一覧](doc/README.md) · [ディレクトリ構成と保守](doc/development/repository-layout.md)（繁体字中国語）

**[GitHub の公開時計を開く](https://kcayut.github.io/webclock/)** · [ダウンロードとオフライン利用](doc/installation.md#no-server)（繁体字中国語）

iPad、タブレット、使っていない画面を大きな時計にできます。公開版はそのまま利用でき、セルフホスト版ではカレンダー、リマインダー、ブラウザーアラーム、ナイトモード、バックアップを使えます。

> [!IMPORTANT]
> ブラウザーアラームは、画面を点灯したままページを前面に表示する必要があります。iOS の画面ロックや App の切り替え後は、音声とタイマーの継続を保証できません。

## 3 つの利用方法

- **公開版を使う：**[公開時計](https://kcayut.github.io/webclock/)を開くだけで利用できます。アカウントやサーバーは不要で、時刻とタイムゾーンは端末の設定に従います。
- **オフライン時計をダウンロード：**パソコンで [ZIP をダウンロードして展開](doc/installation.md#offline-download)し、一番外側の `index.html` をブラウザーで開きます。サーバーのインストールは不要です。タブレットは[オフラインキャッシュと iOS 9 の制限](doc/installation.md#offline-cache)を参照してください（繁体字中国語）。
- **セルフホスト：**パソコン、NAS、Raspberry Pi で完全版を実行します。`/admin` で表示・カレンダー・文字リマインダーを、`/schedules` でアラームと端末状態を管理します。

セルフホスト版は繁体字中国語・英語・日本語と、Google・Apple iCloud などの ICS カレンダーに対応します。端末をグループで管理し、完全な `.webclock` バックアップでアカウントと設定を移行できます。[利用ガイド](doc/guides/guide_jp.md)を参照してください。

## インストール方法

| 方法 | 対象環境 |
| --- | --- |
| **Bare metal** | Raspberry Pi OS、Debian、Ubuntu。systemd による自動起動 |
| **Docker** | Docker Compose が使えるパソコン、NAS、Linux |
| **Home Assistant** | HA OS に App リポジトリを追加してインストール。統合と同梱カードは HACS で導入 |

**Linux／Raspberry Pi を 1 行でインストール：**

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh
```

**Docker を 1 行でインストール：**

```bash
curl -fsSL https://github.com/kcayut/webclock/releases/latest/download/install.sh -o /tmp/webclock-install.sh && bash /tmp/webclock-install.sh --docker
```

インストーラーは [GitHub の最新正式版](https://github.com/kcayut/webclock/releases/latest)を取得し、ヘルスチェック後に時計と管理画面の URL を表示します。Docker は同じ版のビルド済みイメージを取得します。

**[HA App をインストール](doc/installation.md#home-assistant)** · **[HA 統合とカードをインストール](doc/home-assistant.md#安裝整合)**

Linux／Docker の既定はログイン不要の self モードです。信頼できる LAN 内で使用してください。管理者ログインには [managed](doc/installation.md#https) を使用します。既定は HTTPS ですが、信頼できる LAN では二段階の確認後に HTTP を選べます。HA App は HA ログインで保護され、managed バックアップの読み込み後は元の WebClock アカウントも必要です。

- [インストールガイド](doc/installation.md)：前提条件、初回設定、トラブル対応。
- [端末の表示設定](doc/guides/display-devices.md)：ホーム画面、全画面表示、スリープ防止。初代 iPad mini／iOS 9 を含みます。
- [日本語ガイド](doc/guides/guide_jp.md)：カレンダー、アラーム、グループ、バックアップ。
- [更新と復元](doc/operations/update-operations.md) · [HTTPS とアカウント管理](doc/operations/accounts-and-https.md)。
- [端末 API](doc/api/server-api_jp.md) · [ESP32-S3 プロトタイプ](firmware/README.md) · [リリースと実機検証](doc/ha-release.md)。

インストール・保守・ハードウェアの文書は繁体字中国語です。

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
