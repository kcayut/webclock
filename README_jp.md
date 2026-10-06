<img src="static/brand/logo.svg" width="64" height="64" alt="WebClock logo">

Home Assistant：6桁の英数字コードで参加し、時刻・カレンダー・アラームカードを利用できます。[導入手順](doc/home-assistant.md)をご覧ください。

# WebClock

[繁體中文](README.md) · [English](README_en.md) · **日本語**

**[WebClock を開く](https://kcayut.github.io/webclock/)**

iPad、タブレット、使っていない画面を大きな時計にできます。公開版はそのまま利用でき、セルフホスト版ではカレンダー、リマインダー、ブラウザーアラーム、ナイトモード、バックアップを使えます。

> [!IMPORTANT]
> ブラウザーアラームは、画面を点灯したままページを前面に表示する必要があります。iOS の画面ロックや App の切り替え後は、音声とタイマーの継続を保証できません。

## 2 つの利用方法

- **公開版を使う：**[公開時計](https://kcayut.github.io/webclock/)を開くだけで利用できます。アカウントやサーバーは不要で、時刻とタイムゾーンは端末の設定に従います。
- **セルフホスト：**パソコン、NAS、Raspberry Pi で完全版を実行します。`/admin` で表示・カレンダー・文字リマインダーを、`/schedules` でアラームと端末状態を管理します。

セルフホスト版の UI は繁体字中国語、英語、日本語に対応しています。Google、Apple iCloud、その他の ICS カレンダーを購読できます。カレンダー URL はサーバー内に保存され、公開時計、状態応答、管理画面の JSON 出力には含まれません。ホスト側の完全バックアップには非公開データも含まれます。

時計は時刻・日付・曜日を先に表示し、読み込み済みで前面実行中のページは通信・保存領域・追加機能の失敗で停止しない設計です。端末管理では名前、自報能力、同期確認状態を扱えます。グループ、6文字の参加コード、端末別認可、移動、無効化・再開、取り消しに対応します。managedモードはホスト側で明示的に有効化し、既存環境は既定でselfを維持します。操作と制限は[ガイド](doc/guide_jp.md#端末同期状態)、現在の検証と未実施項目は [A 段階の検収記録](doc/phase-a-acceptance.md) / [B 段階のグループ・認証検証](doc/phase-b-acceptance.md)（繁体字中国語）を参照してください。CI と iPad mini 1／iOS 9 の実機検収は分けて記録します。

## クイックインストール

プロジェクトを取得し、設定ファイルを作成します。

```bash
git clone https://github.com/kcayut/webclock.git
cd webclock
cp .env.example .env
```

いずれか 1 つを選びます。

```bash
# Docker（既定: http://ホストIP/）
touch manual_notes.json
mkdir -p webclock_state
docker compose up -d --build

# Raspberry Pi OS / Ubuntu / Debian（既定ポート: 5000）
sudo bash setup.sh

# Python で手動実行
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

完了後、時計のトップページを開きます。管理画面は `/admin`、アラームと端末管理は `/schedules` です。

デプロイ前に `.env` の `WEBCLOCK_LANGUAGE=zh-TW`、`en`、`ja` で初期表示言語を設定できます。Linux インストーラーは `.env` の初回作成時に選択を求めます。デプロイ後も管理サイドバー下部から切り替えられ、選択結果は `webclock_state/settings.json` に保存されます。

**詳しい説明：**[日本語ガイド](doc/guide_jp.md) · [端末 API](doc/server-api_jp.md) · [ESPHome 開発ガイド](doc/esp-home.md) · [ファームウェア開発準備](firmware/README.md)（最後の 2 件は繁体字中国語。書き込み可能なファームウェアはまだありません）。

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
