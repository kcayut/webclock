# WebClock 文件

第一次使用，從[安裝指南](installation.md)選擇線上／離線、裸機、Docker 或 Home Assistant；安裝後的升級與故障復原見[更新維護](operations/update-operations.md)。

自己維護主機時，手動與可攜更新工具的用途、位置及命令見 [`scripts/update/`](../scripts/update/README.md)。

| 資料夾／文件 | 內容 |
| --- | --- |
| [`installation.md`](installation.md) | Linux／Docker／HA 安裝指令、首次設定與排錯 |
| [`guides/`](guides/guide.md) | [繁中](guides/guide.md)、[English](guides/guide_en.md)、[日本語](guides/guide_jp.md)使用指南、[HA 整合與卡片](home-assistant.md)、[顯示裝置](guides/display-devices.md)、[ESPHome](guides/esp-home.md) |
| [`api/`](api/server-api.md) | Server／裝置 API、[程式寫入 API](api/control-api.md)與多語參考 |
| [`operations/`](operations/update-operations.md) | [更新與復原](operations/update-operations.md)、[HTTPS 與帳號管理](operations/accounts-and-https.md) |
| [`development/`](development/repository-layout.md) | [原始碼與本機安裝](development/source-installation.md)、[目錄分工](development/repository-layout.md)、[發行流程](ha-release.md)、[儲存與授權契約](development/b0-b1-contract.md)、[Docker／HA 更新設計](development/docker-ha-update-plan.md) |
| [`acceptance/`](acceptance/docker-ha-update-acceptance.md) | [更新驗證](acceptance/docker-ha-update-acceptance.md)、[第一階段](acceptance/phase1-acceptance.md)、[第二／四階段](acceptance/phase2-acceptance.md)、[A 階段](acceptance/phase-a-acceptance.md)、[B 階段](acceptance/phase-b-acceptance.md)驗收與未完成項目 |
| [`releases/`](releases/v1.1.0.md) | 各版本的公開 Release 說明 |
| `images/` | GitHub 文件使用的圖片；應用程式資產在根目錄的 `static/` |

歷史驗收只代表該紀錄列出的提交與環境，不能用來宣稱目前工作目錄已發布或完成實機驗證。
