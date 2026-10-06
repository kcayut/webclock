# B 批次：群組、六碼與裝置授權驗收

驗收日期：2026-10-06（Asia/Taipei）。B0–B4 與 B5-1 的軟體、文件、本機及 Linux CI 已完成；B5-2 iPad mini 1／iOS 9 實機仍待驗收。此文件不表示已部署至使用中的主機。

## 本次交付

- 管理員登入、同源六碼加入、每台獨立憑證、群組設定與內容隔離；公開時間不依賴私人資料授權。
- 管理端逐台移組、停用／恢復、刪除授權；裝置可自行退出。移組與停用保留名稱、能力、ACK、原憑證及邀請已用額度，只有實際變更增加 assignment revision。撤銷或歷史還原後失效的憑證不能恢復，必須重新加入。
- 行事曆來源 → 週期系列 → 單次選取，支援 Shift 同層連續選取。已選項與文字提醒依時間列在目前列表；當日、提前天／小時／分鐘與單次自訂區間只控制顯示，不改行程及鬧鐘。
- 行事曆／提醒與鬧鐘列表顯示套用群組，可個別指定或套用保存當下的全部群組。裝置群組內容的伺服器提醒提供全選，鬧鐘排程放在下一列；舊式來源不明裝置留在後方可收合區塊。
- 時鐘設定面板加大、加入成功隱藏六碼並顯示群組／退出／重新確認；本機提醒時間語意與管理頁面名稱已修正。鬧鐘紅邊提示固定啟用。

## 驗證狀態

| 項目 | 本批結果與界線 |
| --- | --- |
| Python | 264 項通過；含加入競態、權限、跨群組、遷移、備份／還原與本機 HTTP 更新回歸 |
| JavaScript | 11 組通過；含草稿／焦點、晚回應、移組 scope、停用清除、原 cookie 恢復與核心保底 |
| 三語／Shell／差異 | 繁體中文、English、日本語介面；shell 語法與 diff check 通過 |
| 行事曆與群組瀏覽器操作 | 隔離 HTTPS Chrome，1440×1000 與 390×844 通過；詳見下段 |
| 裝置生命週期瀏覽器操作 | 隔離 HTTPS 兩個獨立 Cookie 身份通過：單台停用、原憑證恢復、移組／重開與 390×844 無水平溢出 |
| 時鐘 ES5 解析 | Acorn 8.15.0、ecmaVersion 5：8 外部腳本＋4 實際渲染 inline，12 段通過；不代替實機 |
| Linux CI／systemd | **通過**；`69c944c` 的 [執行 37359263802](https://github.com/kcayut/webclock/actions/runs/37359263802)，264 項 Python、11 組 JS 與 self／managed 真實 systemd 演練 |
| 提交與雙遠端 | 行事曆／群組 UI 已於 cf3994df13e2c826c40ba660994d4fc741aced31 同步 Gitea、GitHub；B4 實作 `4a1aeba`、演練修正 `69c944cfa5dd62de43b5c87a3b2e2af852a0b2c0` 均已同步，兩遠端獨立讀回受測 SHA；其後僅補本文件 |
| 正式部署 | 未執行；既有 self 安裝不會自動切成 managed |
| B5-2 實機 | 待 iPad mini 1／iOS 9 與實際網址；Chromium 或視窗模擬不算完成 |

## 本機與瀏覽器證據

Python 回歸涵蓋最後名額競態、成功回應遺失後重送、保存失敗不提交、owner／CSRF 邊界、單台移組／停用不影響同群其他台、同 cookie 恢復、舊 ETag／在途回應拒絕，以及歷史還原後無法重新啟用舊憑證。正式 CLI 測試由 self 資料開始，保留 owner、邀請秘密、名稱、能力、ACK、設定及來源引用；不把舊自報 ID 升格為已授權身份。缺少明確啟用參數仍拒絕。

前端回歸保留管理頁 15 秒刷新、切語言、失敗重試及慢回應期間的名稱、群組與排程草稿及焦點。移組的舊私人快取與在途鬧鐘失效；停用清除私人事件／鬧鐘，基本時計與本機提醒保留；既有身份輪詢可使用原 cookie 恢復。

隔離 HTTPS Chrome 已驗證行事曆與文字提醒混合排序、系列提前一小時／三天的可見性差異、單次絕對區間、跨來源相同 UID、Shift 範圍選取、失敗後保留列表／草稿、三語切換與手機無水平溢出。亦驗證提醒／鬧鐘全部群組指派、單次從整份來源群組移出時保留其他項目、系列部分指派不被無意抹除，以及提醒全選／鬧鐘下一列。自簽憑證只在隔離測試忽略驗證。

裝置生命週期實際操作通過：停用一台即於輪詢清除私人內容，另一台仍取得原群組資料，基本時間繼續且面板不自動開啟；恢復沿用同一 Cookie，移組後保留 ID／管理名稱，顯示第二群組內容及亮度，重開後仍留在新群組。兩台合計只消耗兩個邀請名額；另一台未儲存名稱草稿保留。手機截圖已視讀，無水平溢出及未捕捉頁面例外。

測試使用專用合成資料目錄，未讀寫正式私人資料。預期 HTTP 401／403 與刻意注入的 500／503 不算未捕捉 JavaScript 例外。跨日與租期使用自動化時鐘；不是連續 24 小時實測。

## Linux 演練

[現有 workflow](../.github/workflows/linux-rehearsal.yml) 使用標準 ubuntu-24.04 一次性 runner 與 [rehearse_linux.py](../tests/rehearse_linux.py)。保留既有 self／schema 2 Git、pip、systemd 正常更新、完整備份／還原與故障回復，再延伸以下 managed 流程：

1. 同一舊安裝先停機完整備份，以真實互動 CLI 明確切換，確認舊資料原樣保留。
2. 同一應用程序提供本機 TLS 與 HTTP health；真實 HTTPS 登入、六碼加入、Secure／HttpOnly cookie、ETag／304，拒絕匿名與 shared-token 私人讀取。
3. managed 模式真實更新成功，逐位元保留授權及資料。
4. 注入啟動故障前撤銷一台裝置；回復舊 Git／venv 時仍保留該次撤權。
5. 完整備份 → 撤銷 → 歷史還原，舊管理與裝置 cookie、邀請仍失效；使用新碼取得新身份後才能重取內容。

2026-10-06 02:52:45–02:56:15（Asia/Taipei），[執行 37359263802](https://github.com/kcayut/webclock/actions/runs/37359263802) 在 `69c944cfa5dd62de43b5c87a3b2e2af852a0b2c0` **完整成功**：上述五項及既有 self／schema 2 演練全部通過，264 項 Python、11 組 JavaScript、shell 與差異檢查通過；最後服務 active，演練 service 隨後清除。這是一次性 x86 Linux runner，不代替 Raspberry Pi／ARM、Docker、正式主機或 iOS 9 驗收。

首次執行 [37358326955](https://github.com/kcayut/webclock/actions/runs/37358326955) 在最後斷言誤以為歷史邀請應被刪除。既有還原契約保留邀請紀錄、設為關閉並輪換秘密。修正只改演練與回歸測試，並加入「尚有名額的舊碼也不能重新加入」的實際 HTTPS 檢查；產品還原行為未變。

## 正式啟用與硬體交接

先完整主機備份、停止所有寫入程序，使用服務帳號對實際 state 目錄執行，再以 HTTPS 重新啟動：

```sh
./venv/bin/python scripts/manage_auth.py --state-dir /actual/state setup --username admin --enable-managed
```

密碼由互動提示輸入。舊 `--enable-managed-test` 保留相容；不是自動更新時切換。舊 schema 2 ESP 韌體不能使用 managed 私人資料，F1 另行交辦。主機完整備份包含未加密的私人設定及授權資料，管理頁 JSON 匯出只包含既有 settings／notes。

以下 B5-2 仍未執行，需記錄精確 SHA、iOS 版本、網址／TLS 拓樸、起訖時間及實際結果：

- [ ] iPad mini 1／iOS 9 Safari 六碼輸入、Cookie 往返、加入成功隱藏輸碼、重開保留身份。
- [ ] 前景恢復、斷網／重連及租期到期；私人內容依期限清除，基本時間持續。
- [ ] 單台停用／恢復／移組／撤銷及自行退出，另一台不受影響；離線撤銷不承諾立即清除。
- [ ] 至少前景連續 24 小時且跨午夜，檢查日期、星期、夜間亮度與同步誤差。
- [ ] 本機提醒、音訊手勢、實際響鈴、固定紅邊與停止；背景、鎖屏及離線重開各自記錄能力。

## 單台顯示覆寫（2026-10-07 本機工作目錄）

沿用群組及逐台身份，伺服器依「單台 > 群組 > 全體」計算外觀；內容仍由群組明確指派。裝置卡片提供生效值／來源、恢復繼承及保存版本檢查。夜間模式整組繼承或自訂，避免上下層時段混合。舊資料不需遷移；完整主機還原保留覆寫但仍撤銷舊憑證。

- 278 項 Python、11 組 JavaScript 與差異檢查通過。涵蓋 0／false、上層更新、恢復繼承、同群組隔離、移組、跨 owner 拒絕、儲存失敗、歷史還原、請求途中變更及 config revision／ETag。
- Browser plugin not available；改以 Playwright CLI／Chromium 154.0.8037.98 在隔離本機 self 伺服器操作，桌面 1365×1000、手機 390×844 截圖視讀通過，無水平溢出。實際保存、15 秒輪詢保留草稿／焦點、三語切換、恢復繼承與移組通過；雙管理頁衝突保留草稿，重新載入確認可取消或接受。主控台只有刻意觸發的 HTTP 409，沒有其他頁面錯誤。
- 本次結果屬未提交工作目錄；尚未執行此批次 CI、部署、iOS 9／實體裝置驗收，不沿用上方舊 SHA 的 Linux 結果作為本次證明。操作與 API 見 [指南](guide.md#群組設定與裝置加入)及 [管理 API](server-api.md#管理-api)。

## 重現命令

```sh
PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m unittest discover -s tests
for test in tests/*.js; do node "$test" || exit 1; done
bash -n setup.sh scripts/setup.sh update_clock.sh
git diff --check
```
