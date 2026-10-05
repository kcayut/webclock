# A 批次：時鐘保底與裝置管理驗收

驗收日期：2026-10-05（Asia/Taipei）。程式基線為 `c1c3e6d06b877a49a40f0512686ea61e0476256b` 加目前 A3–A5 工作樹及本次 A6 回歸測試。這是未提交工作樹的驗收，不能用舊提交的 CI 結果代替。B 批次的登入、六碼加入、群組與逐台授權尚未實作。

## 最高原則

頁面已載入、瀏覽器允許執行時，時間、日期與星期先啟動並持續更新，不等待網路、儲存、選用功能或管理功能成功。系統故障不自動顯示主畫面警告、遮罩或登入跳轉；主動開啟的連線面板與本機提醒仍可使用。

使用者明確設定的亮度 0、手動黑畫面及夜間黑畫面保留，其間底層時間仍更新；夜間結束恢復有效日間設定。這不承諾 iOS 9 離線重新開頁、背景／鎖屏執行，也不以放行未授權私人資料達成保底。

## 交付與驗收狀態

| 項目 | 本次結果 | 證據及界線 |
| --- | --- | --- |
| A0–A2：核心時計、設定驗證、請求隔離、安靜畫面 | 既有實作保留，自動化回歸通過 | `tests/test_clock.js`、`tests/test_alarms.js`；設定整包拒絕、來源／世代／回應順序、錯誤與選用程式故障 |
| A3：管理名稱、自報名稱、類型與能力 | 通過 | `tests/test_device_service.py`、`tests/test_server_api.py`、`tests/test_csrf.py`；不把未知能力標成不支援 |
| A4：同步與持久 ACK | 通過 | 等待／300 秒逾時／晚 ACK／重啟保存／另一裝置及重複 ACK；新增跨兩筆同步與寫入失敗重試回歸 |
| A5：既有裝置面板 | 自動化及真實瀏覽器通過 | `tests/test_schedule_ui.js`；刷新、切語言、延遲保存、失敗恢復保留草稿／焦點／新回報 |
| A6：Python 完整回歸 | **129 項通過，無跳過** | macOS 26.6.2 arm64、專案 venv Python 3.14.6；包含暫存 localhost 的升級測試 |
| A6：JavaScript 完整回歸 | **8 組通過** | Node.js v22.17.1；下方列可重現命令 |
| A6：真實瀏覽器 | **14 組通過** | Chrome 154.0.8037.93／Playwright 1.62.1；768×1024、1440×1000、390×844 |
| 舊時鐘路徑語法 | **9 段通過 ES5 解析** | 既有 Acorn 8.15.0、`ecmaVersion: 5`；不等於 iOS 9 實機通過 |
| Shell 語法、差異空白檢查 | 通過 | `bash -n` 與 `git diff --check` |
| 本次工作樹 Linux CI／真實 systemd 演練 | **待執行** | 尚未發布本次程式；開發 Mac 無可用的隔離 Linux runtime |
| commit／push | **未執行** | 目前驗收對象仍為工作樹；TODO 是 Git 忽略的本機計劃，正式紀錄保存於本文件 |
| 實際主機部署 | **未執行** | 沒有修改使用中服務或正式資料 |
| iPad mini 1／iOS 9 Safari | **待實機驗收** | 現代瀏覽器及視窗大小模擬均不能代替實機 |

Python 初次在 sandbox 內執行時，3 項 migration 測試因 localhost 啟動回報 `Operation not permitted`；在允許啟動暫存服務的環境重跑，128 項全過。新增 A4 回歸後再次完整執行，129 項全過；沒有把環境失敗改成跳過測試。

## 已驗證的故障與相容範圍

| 範圍 | 必須維持的結果 | 自動化依據 |
| --- | --- | --- |
| 核心先啟動 | 無現代選用 API、儲存不可用、網路未回應、選用腳本解析／執行失敗時仍走時與跨日 | `test_clock.js` |
| 損壞顯示設定 | 壞時區、null／空字串亮度、未知值或錯誤 night 整包忽略；保留有效設定、可見時間／日期／星期 | `test_clock.js` |
| 明確黑畫面 | 亮度 0、手動及夜間黑畫面仍生效，底層時計不停；夜間結束恢復日間設定 | `test_clock.js` |
| 請求順序與來源 | 舊成功／錯誤／逾時、A → B → A、同 URL 重連及重複回呼不能覆蓋新狀態；慢於輪詢的有效回應仍能校時 | `test_clock.js` |
| 連線／授權形式的錯誤 | 401／403、登入 HTML、壞 JSON、逾時與網路失敗不跳頁、不自動展開面板或提示，斷線續走 | `test_clock.js`、`test_alarms.js`；模擬錯誤碼不代表已有登入功能 |
| 既有提醒與鬧鐘 | 本機提醒、時間輸入、音訊手勢、靜音視覺、停止操作及原排程語意保留 | `test_clock.js`、`test_alarms.js`、時間格式與 Python 排程測試 |
| 裝置資料 | 再註冊／回報不覆蓋管理名稱；舊 name-only 資料可讀；能力時間只隨能力回報更新；寫入失敗保留原檔 | `test_device_service.py`、`test_server_api.py` |
| 同步確認 | 重複 sync 共用待處理指令；逾時不刪；舊 ACK 不能確認新指令；ACK 原子保存失敗後可重試且不遺失前次紀錄 | `test_device_service.py` |
| 管理面板 | 15 秒刷新／切語言保留草稿、焦點與選取範圍；失敗保留最後成功列表；慢回應不倒退名稱、能力及 ACK | `test_schedule_ui.js` |
| 既有 API／資料 | 排程、行事曆、備份／還原、更新／失敗回復、schema 2、ETag／304、CSRF 維持 | 完整 Python 套件；本機模擬不等於 Linux systemd 或實際部署 |

## 真實瀏覽器操作

使用獨立 `127.0.0.1:5136` 服務與暫存合成資料，未讀寫正式設定。Chrome 154.0.8037.93／Playwright 1.62.1 的 14 組驗證全部通過：

- 正常首屏、有效時間／日期／星期、手動連線入口。
- 401、403、500、HTML、XHR timeout、損壞 localStorage、無效 localStorage＋API 設定、storage 拒絕及選用腳本例外，均保持可見與安靜；模擬從 12/31 23:59 走至 1/1 00:01，日期／星期一起更新。
- 明確亮度 0、手動黑畫面、夜間黑畫面與日間恢復；底層時計持續更新。
- 離線本機提醒新增／刪除；實際點擊啟用 Chrome AudioContext、鬧鐘視覺效果與兩次點擊停止。沒有驗證實際喇叭音量。
- 裝置面板桌面／手機、三語／深淺色、15 秒列表更新保留草稿／焦點／選取範圍、送出後繼續編輯、舊 GET 晚到、保存失敗及重試、sync 去重到 ACK。

正常操作無非預期頁面例外。故障案例的 HTTP 401／403／500、刻意注入的腳本例外及 Playwright 阻擋 Service Worker 的工具提示皆依情境記錄，不能宣稱整輪 console 訊息為零。跨日使用測試時計，不是連續 24 小時實測。

另以未攔截 Service Worker 的瀏覽器補驗：正常載入 console 無錯誤、Service Worker ready、實際斷網後仍跨日並保持可見，以及現代 Chrome 離線重新載入均通過。這只證明本次 Chrome／localhost 環境，不能推定 iOS 9 或一般 HTTP 區網網址具備相同離線能力。

截圖視讀發現無視窗 Chrome 154 的系統字型在更新 `textContent` 後偶爾缺字；不含 WebClock 的最小靜態頁亦可重現。有視窗 Chrome 的同一最小頁與原始 WebClock 跨日頁均完整顯示，故記為測試環境的繪製限制，未修改產品字型。完整跨日畫面保存於 `/tmp/webclock-a6-clock-rollover-headed.png`。

ES5 解析涵蓋 `static/clock.js`、`time-format.js`、`time-inputs.js`、`offline.js`、`alarm-audio.js`、`alarms.js` 及 Server 實際渲染的 3 段 inline script，全部通過。沿用已安裝的 parser，未新增專案依賴。

本次原始結果與截圖保存在執行機的 `/tmp/webclock-a6-browser-results.json`、`/tmp/webclock-a6-browser-supplement.json`、`/tmp/webclock-a6-*.png`；它們是本機驗收附件，不是 repository 內的長期測試或已發布產物。驗收使用的獨立服務、暫存資料及瀏覽器 profiles 已清理。

## Linux CI 的剩餘檢查

既有 [workflow](../.github/workflows/linux-rehearsal.yml) 在 `ubuntu-24.04` 執行 Python／JavaScript／shell 回歸，再用 [rehearse_linux.py](../tests/rehearse_linux.py) 驗證真實 systemd 升級、完整備份／還原與注入故障後回復。演練取 Git HEAD，未提交的修改不會自動納入。

2026-10-05 唯讀核對的最新成功紀錄為 [執行 37221795294](https://github.com/kcayut/webclock/actions/runs/37221795294)，對應 `c1c3e6d`。它是歷史基線，不涵蓋本次 A3–A6 工作樹。不得假設相同腳本在舊提交成功就代表本次已通過，也不得繞過演練腳本對隔離 GitHub-hosted runner 的保護。

- [ ] 提交並推送本次程式後，等待該提交的 workflow 完成，記錄 SHA、run URL、結論與失敗原因（若有）。
- [ ] 確認 Python／JS 及真實 systemd 演練均通過，才補上本批次 Linux 驗收結果。
- [ ] Linux 通過仍不代表 Raspberry Pi／ARM、Docker、主機重開／斷電或 iOS 9 實機通過。

## 可重現的本機檢查

從專案根目錄執行，使用現有相依套件及暫存測試資料：

```bash
venv/bin/python -m unittest discover -s tests -p 'test_*.py'
for test in tests/test_*.js; do node "$test" || exit; done
bash -n setup.sh scripts/setup.sh update_clock.sh
git diff --check
```

## iPad mini 1／iOS 9 的交接

以下皆尚未執行。記錄程式 SHA、完整 iOS 版本、HTTP／HTTPS、測試起訖與結果；保持前景亮屏，不以模擬時間跨日代替連續顯示。管理操作可在另一台現代瀏覽器執行。

- [ ] 首屏、秒數、日期／星期；Server 未回應或選用資源失敗仍啟動。
- [ ] 已校時後斷線／重連、未校時前斷線、同 URL 重連與切換 Server；主畫面安靜、手動面板可用。
- [ ] 合法 0 亮度、手動黑畫面、夜間進入／結束；驗證底層時間未停止。
- [ ] 至少前景連續 24 小時並跨午夜，記錄誤差與日期／星期更新。
- [ ] 本機提醒新增／刪除／重開、音訊啟用、實際響鈴、靜音紅邊及兩次點擊停止。
- [ ] 喚回前景重新校時；離線重開、背景與鎖屏能力各自記錄，不一概標支援。

A 批次軟體與文件交付不代表以上實機項目已完成。下一個功能批次仍需另外交辦 B0-1；不得趁驗收加入帳號、六碼或群組功能。
