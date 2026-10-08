# 第二／四階段：模式、帳號復原與裝置管理驗收

紀錄日期：2026-10-08（Asia/Taipei）。本次為基底 `05ff0bd` 上的未提交工作樹；以下區分已實作、已執行本機檢查及尚待部署／實機驗收。程式與本機驗證已完成，尚未提交或部署，不沿用舊版 CI 當作本次證據。

## 已實作範圍

| 範圍 | 行為 |
| --- | --- |
| 首次管理員 | 主機 `setup-code` 產生限時、單次設定碼；`/setup` 經 HTTPS 建立第一位管理員；已有帳號不能再次綁定 |
| 雙向切換 | `/mode` 重新驗證 admin 密碼，明確選定主要使用者、預覽啟用／休眠空間；self 須確認共用管理 |
| 原子保存 | 共享寫入鎖內核對預覽 revision／generation，先保存完整私人備份，再原子寫入模式與主要使用者；失敗不合併或複製帳號 |
| 私人資料空間 | 原資料留在根目錄；新增帳號使用 `owners/<owner_id>/`，保留 ID、來源引用、設定與排程；self 修改繼續留在原 owner |
| 帳號基礎 | managed 提供 admin／member、建立與停用；必要帳號受保護，刪除其他帳號只封存身分與資料，不自動公開 |
| 休眠與快取 | self 只提供主要使用者內容；休眠 owner 無法讀寫或取得來源／排程／裝置內容，模式切換撤銷 session／程式 token 並更新資料範圍；本機提醒保留 |
| 完整還原 | 涵蓋主要、休眠及封存帳號；旋轉授權秘密、關閉加入碼、撤銷歷史裝置與程式憑證、清除 session／首次設定碼，保留帳密與內容 |
| 更新安全 | 使用目前主要 owner 的設定／提醒；受保護 self 保留授權底線，不能還原無帳號舊備份或回復至不支援多帳號的舊程式並啟動 |
| 裝置統一入口 | `/schedules#devices` 切換全體／群組／單台；顯示操作裝置與目標的關係，未知保持未知，沿用外觀繼承、內容覆寫與草稿保護 |
| 指派與公告 | 沿用單台 > 群組 > 全體逐欄繼承、內容清單取代、0／false、恢復繼承、版本衝突與群組／裝置公告 |

本次不新增跨帳號公開內容；預覽的公開清單為空，既有私人資料不會自動升格。第五階段的公開註冊、email、忘記密碼、audit、公有與私人排程合併仍待完成。完整操作與還原命令見[安裝指南](installation.md#mode-switch)。

## 已執行本機檢查

| 檢查 | 狀態 | 已覆蓋／限制 |
| --- | --- | --- |
| 授權、帳號與主機 CLI | **35 項通過** | 設定碼錯誤／過期／重用、已有管理員保護、競爭初始化；A／B 往返、admin 密碼與主要帳號、同時切換、寫入失敗、重啟、protected self 損壞不降級、封存及密碼復原 |
| 完整備份與更新安全 | **63 項通過** | managed／self 多帳號還原、主要與休眠檔案、封存資料、舊 session／程式 token／加入碼失效、設定碼不復活、自訂目錄、還原失敗回復、巢狀 owner 驗證與舊程式啟動拒絕 |
| Flask API 與全專案回歸 | **365 項 Python 測試通過** | A／B 往返及選 B 為主要、A／B／C 裝置外觀隔離、冷啟動、來源快取、跨 owner 匯入拒絕、設定碼 HTTP／HTTPS、舊 CSRF、切換預覽／備份失敗、舊待加入憑證失效與重新加入、裝置指派及公告 |
| 瀏覽器／JavaScript | **13 套 Node 測試、Chrome 桌機／手機操作通過** | 新模式頁建立成員／往返、三語保留草稿；裝置目標、0／false、15 秒輪詢焦點、全體新分頁；legacy 啟動與 ES5 相容檢查仍通過，不等於舊 Safari 實機 |
| Docker 安裝腳本 | **5 項安裝測試與 shell 語法通過** | Compose 已加入獨立模式備份掛載、初始化建立私人目錄；測試模擬 Docker 命令，容器重建持久化尚待真實 Docker 驗收 |
| CI／發布／正式部署 | **未執行** | 未提交 SHA、未觸發本次 CI、未更新正式主機或映像 |
| Raspberry Pi／ARM、iPad mini 1／iOS 9、斷電 | **未驗收** | 本機 mock、執行緒競爭與磁碟錯誤注入不能代替實機或斷電 |

可重現的針對性檢查：

```bash
venv/bin/python -m unittest tests.test_auth_service tests.test_auth_accounts tests.test_manage_auth
venv/bin/python -m unittest tests.test_backup_clock tests.test_update_safety
venv/bin/python -m unittest tests.test_mode_spaces tests.test_mode_restart tests.test_device_mode_scope tests.test_installation
venv/bin/python -m unittest discover -s tests
for test in tests/*.js; do node "$test"; done
bash -n setup.sh scripts/setup.sh
git diff --check
```

完整備份／還原測試使用臨時目錄與合成帳號；其中 4 項升級整合測試在沙箱外啟動隔離的本機伺服器，未操作正式服務。更新器的 systemd 流程仍以模擬驗證，不表示本次在 Linux 真正更新服務。設定碼、密碼、私人網址與憑證不納入驗收輸出。

## 瀏覽器驗證

Browser plugin 未提供，使用既有 Playwright／Chrome；未新增套件。兩個隔離 HTTPS 環境分別為 `https://127.0.0.1:5137/schedules#devices` 與 `https://127.0.0.1:5147/mode`，桌機 `1365×900`、手機 `390×844`。頁面身份、非空白、無錯誤覆蓋層、console error／warn 為 0、無橫向溢位及實際操作均通過。測試伺服器與瀏覽器已關閉。

- 裝置流程：概覽 → 群組 → 單台 → 全體；同台／他台、群組內外和未知狀態正確。往返保留群組／單台草稿，保存 0／false、語言切換、15 秒輪詢焦點及全體新分頁皆通過。
- 模式流程：以 A 登入 → 建立 member → 三語切換保留輸入 → 選 B 預覽（A 休眠／B 運作）→ 切 self 只見 B 提醒 → 再驗 admin 密碼切 managed → A 原密碼可登入且只見 A 提醒。預覽只有私人網址計數；2 份備份及父目錄權限為 `0700`、manifest 為 `0600`。
- 臨時重現與截圖：`/private/tmp/webclock-stage4-qa/verify.js`、`desktop-target.png`、`mobile-target.png`；`/private/tmp/webclock-mode-qa/verify-mode.js`、`managed-preview-desktop.png`、`managed-preview-mobile.png`。這些是本機臨時證據，不納入套件或 Git。

## 待實際部署與裝置驗收

1. 記錄精確 SHA、主機／OS、服務帳號、有效 state／notes／備份路徑及 HTTPS 拓樸；實際建立、驗證與還原模式備份，再測重啟與容器重建保留。
2. 使用 A／B 兩帳號各建私人來源、提醒、排程與裝置；選 A 切 self，修改後回 managed，確認 A 保留、B 未輪詢／執行／外洩，ID 與裝置歸屬沒有改派。
3. 實測切換時離線、租約到期、重連、跨午夜與錯過不補響；驗證本機提醒不被刪除、休眠裝置不取得主要使用者內容。
4. 在可復原的測試副本於切換／還原的不同時點中斷或斷電，保留副本與暫存資料，確認重啟保持一致或封閉等待主機復原，不能意外免登入。
5. 在 iOS 9 與不同能力裝置驗收外觀繼承、清單取代、移組、revision／快取、公告時段／絕對到期與失權清除；黑畫面、亮度 0 與時間可讀性分別記錄。

實機結果可追加至本文件及 [B 批次驗收](phase-b-acceptance.md)，未執行項目保持待驗收。
