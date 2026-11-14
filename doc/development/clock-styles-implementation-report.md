# 時鐘樣式實作報告（第四輪：深淺色盤）

狀態：四款樣式、各款深色／淺色色盤、自動化與桌面真實瀏覽器回歸完成；**iPad mini 1／iOS 9.3.5／9.3.6 實機驗收仍未執行**。本報告不宣稱三款相容樣式已通過 iPad 實機，也不代表已發布。

## 1. 預覽與正式頁尺寸不一致：根因、修正與前後量測

### 1.1 現象與追查

使用者在正式 `/` 選 flip／segment／paper 後，看到時間比管理頁預覽小；預覽雖然有放大，切到正式頁仍不夠大。這一輪先不改字級，而是用隔離服務（127.0.0.1:8898、暫存 state）在管理頁儲存樣式，再開正式 `/`，逐項確認：

- `/api/status` 回傳的 `clock_style` 與管理頁儲存值一致。
- 正式頁 `body` 有正確的 `clock-style-<id>` 與 `clock-style-enhanced`。
- `/static/clock-styles.css`、`/static/clock-styles.js` 載入成功，沒有 404、快取舊版或 inline CSS 覆蓋。
- `#time`／`#clock-style-surface` 的 DOM 結構與 preview 相同。
- 同一個 viewport（例如 1024×650）下，正式頁與 `/admin/preview` 的時間 font-size、元素框、容器位置**完全相同**。

真正的差異不是兩套 CSS，而是**量測時的 viewport 高度不同**：

- 管理頁預覽 iframe 以固定 4:3 畫布呈現，實際可用高度是 768。
- 正式 `/` 在有瀏覽器工具列／網址列時，headless 與一般視窗量到的高度是 650。
- 第二輪的 flip／segment／paper 主時間與幾何使用 `vh`。高度從 768 變成 650 時，時間跟著縮小約 15%；預覽仍以 768 呈現，所以看起來「預覽比較大、正式頁比較小」。
- 同一高度下兩邊本來就一致，因此只放大 preview 或再加一層 preview 專用 CSS 都會掩蓋根因，不能解決正式頁。

### 1.2 修正位置

- `static/clock-styles.css`
  - flip 的面板高度、數字、冒號、秒數、日期與訊息改以 `vw` 為主：無秒數面板 `37.5vw`、數字 `34.5vw`；有秒數 `32.2vw`／`27vw`。
  - segment 的數字幾何改以 `vw` 為主：無秒數 `20vw × 34vw`；有秒數 `13.5vw × 22.5vw`；秒數 `5.5vw × 10vw`。
  - paper 主時間改為 `34.5vw`、秒數 `27vw`，日期與訊息同步改為 `vw`。
  - 僅保留 `@media (max-height: 600px) and (orientation: landscape)` 的 `vh` 上限，處理 844×390 這類短橫向，避免高度不足時裁切；1024×650 不觸發此上限。
  - 直向使用既有的 `@media (orientation: portrait)` 寬度規則，讓三款與 classic 一樣受寬度限制。
- `templates/index.html`／`templates/clock_preview.html`
  - 正式頁與預覽頁仍載入同一份 `clock-styles.css`、`clock-styles.js`，使用同一個 `#clock-container`、`#clock-style-surface` 與 renderer。
  - 沒有新增 preview 專用字級、transform 縮放或 `!important`。
- `tests/browser_clock_styles.js`
  - 新增正式頁與 preview 在相同 viewport、時間、設定、訊息狀態下的 computed font-size、時間框寬高與位置斷言。
  - 新增「正式頁時間 ink height ≥ 同條件 classic 的 90%」斷言。
  - 這組斷言在第二輪的 `vh` 版本會失敗：1024×650 正式頁 flip 只有 299px，preview 為 353.28px。

### 1.3 修正前後數字（1024 寬）

量測時間固定為 `2026-11-14 10:28:36`（24 小時制、`m/d`、繁中、日期與星期開啟）。`ink` 是 Canvas `actualBoundingBoxAscent + Descent` 的實際字形高度；segment 以七段幾何框高計算，不是 line box。

| 樣式 | 修正前正式 `/`（可用高 650） | 修正前 preview（高 768） | 修正後正式 `/`（650） | 修正後 preview（650／768） |
| --- | ---: | ---: | ---: | ---: |
| flip 無秒數 | 299px（ink 217.4） | 353.28px（ink 256.8） | 353.28px（ink 256.8） | 353.28px（ink 256.8） |
| flip 有秒數 | 234px（ink 170.1） | 276.48px（ink 201.0） | 276.48px（ink 201.0） | 276.48px（ink 201.0） |
| segment 無秒數 | 幾何 292.5px | 幾何 345.6px | 幾何 348.2px | 幾何 348.2px |
| segment 有秒數 | 幾何 195.0px | 幾何 230.4px | 幾何 230.4px | 幾何 230.4px |
| paper 無秒數 | 299px（ink 217.5） | 353.3px（ink 257.0） | 353.3px（ink 257.0） | 353.3px（ink 257.0） |
| paper 有秒數 | 234px（ink 170.2） | 276.5px（ink 201.2） | 276.5px（ink 201.2） | 276.5px（ink 201.2） |

修正後正式頁不再隨工具列壓縮的高度縮小；1024×650 與 1024×768 的正式頁時間同為 353.28px（flip／paper）與 348.2px（segment 幾何）。

### 1.4 如何確保 preview 與正式頁一致

- 兩邊共用 `static/clock-styles.css`、`static/clock-styles.js` 與相同的 DOM 生成函式；預覽頁只提供固定範例資料，不另外排版。
- 主要矩陣逐一比較實際 `/` 與 `/admin/preview`：同 viewport、同 12／24 小時制、同秒數／日期／星期、同有無訊息。
- 自動斷言要求兩邊 font-size 差 ≤1px、時間元素寬高差 ≤1px；目前 36 個主要狀態全部吻合（實際量測見 `doc/development/clock-styles-metrics.json`）。
- 預覽頁也套用固定範例日 2026-11-14 的假日強調，讓日期／星期顏色與同條件的正式頁一致；這是固定範例內容，不讀取私人資料。
- 管理頁 iframe 只做外框等比縮放；不改變 iframe 內的 `vw` 基準，所以預覽不會反過來比正式頁大。

## 2. 每款樣式都有深色與淺色

### 2.1 設定與預設

新增 `clock_theme`，值為 `auto`、`dark`、`light`，預設 `auto`：

- `auto`：跟隨樣式的既有外觀。classic／flip／segment 使用深色，paper 使用淺色，既有安裝升級後不變。
- `dark`／`light`：使用者的明確選擇，套用到所有樣式；切換樣式時保留。
- 夜間時段仍強制深色色盤，避免淺色背景在低亮度房間過亮；退出夜間後恢復原本選擇。
- 管理頁「時鐘樣式」標題右側新增色彩模式膠囊切換：跟隨樣式／深色／淺色；四張樣式縮圖會同步切換成對應深／淺版本。它和樣式共用草稿、還原與儲存；預覽網址帶 `theme`，預覽與正式頁都只會有一個 `clock-theme-*` body class。
- 群組與裝置頁也提供相同三種選項與「沿用」；缺欄位表示繼承，不明確寫入 `auto`。

### 2.2 四款色盤

| 樣式 | 深色 | 淺色 |
| --- | --- | --- |
| classic | 黑底 `#000000`、白字 | 米白底 `#F4F1E8`、深字 `#1F2328` |
| flip | 背景 `#101214`、面板 `#24282D`、數字 `#F5F2EA` | 背景 `#F4F1E8`、白色面板、數字 `#1F2328`、秒數 `#9A5B13` |
| segment | 背景 `#070B09`、亮段 `#FFD166`、暗段 `#263028` | 背景 `#F4F1E8`、亮段 `#1F2328`（黑）、暗段 `#D8D2C4`、訊息時間 `#1F2328` |
| paper | 背景 `#171A1D`、主字 `#EAE4D9`、次字 `#BFB8AE` | 背景 `#F2EEE5`、主字 `#252B30`、次字 `#5D6267` |

深淺只改色盤，不改時間 DOM、字級、幾何、日期／訊息布局或 90% classic 門檻。

### 2.3 實作位置

- `webclock/services/display_settings.py`：`CLOCK_THEMES`、欄位驗證、`effective_clock_theme()`。
- `webclock/app.py`：`DEFAULT_SETTINGS['clock_theme'] = 'auto'`；preview 路由接受 `theme` 並解析 `auto`、夜間強制深色。
- `templates/index.html`：default／copy／normalize 加入 `clock_theme`；`applyDisplay()` 依 `clockTheme()` 與夜間狀態切換 body class。
- `templates/admin.html`：色彩模式 radio、草稿、還原、儲存、409 與預覽 URL。
- `templates/clock_preview.html`：初始 `clock-theme-*` body class。
- `static/clock.js`：`clockTheme()` 解析 auto；時間資料帶 `theme`。
- `static/clock-styles.css`：四款深色底色盤、classic／flip／segment 淺色覆寫、paper 深色覆寫。
- `static/device-settings.js`、translations：群組／裝置色彩模式選單與三語文案。
- `scripts/update_clock.py`：updater defaults、snapshot 驗證與 migration。
- `tests/`：theme API／繼承／非法值、夜間強制深色、四款 × 深淺 actual/preview 色盤與幾何 parity。

### 2.4 驗證

- 四款 × 深色／淺色：實際 `/` 與 `/admin/preview` 的 body class、背景色、時間色、flip 面板色、segment 亮段色完全一致，時間 font-size／框高差 ≤1px。
- 深色與淺色的 backdrop、時間色、面板／段色確實不同；不是只換 class。
- 管理頁色彩模式切換會更新 `data-theme-mode` 與四張縮圖：`auto` 時 flip 深色、paper 淺色；`light`／`dark` 時四張同步切換，並以 opacity 過場。
- 夜間即使 `clock_theme=light`，實際頁 body 為 `clock-theme-dark`，paper 背景 `rgb(23, 26, 29)`。
- 截圖：`theme-pair-<style>.png`（actual 深色左、淺色右）與 `theme-actual-vs-preview-<style>-<theme>.png`（actual 左、preview 右），共 20 張。

## 3. 移除玻璃光影與光環大字

### 3.1 已移除的內容

- 管理頁樣式卡只保留四張：classic、flip、segment、paper；`glass`／`orbit` 的 SVG 縮圖、名稱、說明與 badge 全部移除。
- `static/device-settings.js` 的群組／裝置樣式選單只保留四個合法值。
- `static/clock-styles.js` 的 renderer、`STYLE_IDS`、能力降級分支、`effectiveStyle`、光環進度計算與相關測試全部移除；不再有 `glass-matte`／`orbit-simple`。
- `static/clock-styles.css` 的玻璃面板、光暈、光環、進度與降級樣式全部移除。
- `templates/index.html`、`templates/clock_preview.html`、`templates/admin.html` 不再傳送或顯示 preview 簡化狀態、今日進度等專用文案。
- 繁中／英文／日文翻譯、目前版本指南、API 文件、CHANGELOG 與 `doc/development/clock-styles-spec.md` 已同步為四款。
- 第二輪以前含 glass／orbit 的截圖移至 `doc/development/screenshots/clock-styles-history/round1` 與 `round2`，只作歷史對照。

### 3.2 舊資料遷移

只對已存在資料做最小、明確的遷移；不做 additive compatibility，也不把新 API 重新打開。

| 路徑 | 行為 |
| --- | --- |
| `webclock/app.py`：`load_display_settings`（global／owner 設定） | 讀到 `glass`／`orbit` 時回傳 `classic`，保留 brightness、language 等其他值；不重寫檔案。缺 `clock_style` 仍繼承預設。 |
| `webclock/app.py`：legacy `/api/backup` 匯入 | 舊備份的 `glass`／`orbit` 映射 `classic` 後驗證；其他設定保留。 |
| `webclock/services/portable_backup.py` | 可攜備份 validation 對 retired style 做同樣映射。 |
| `scripts/update_clock.py`：`migrated_settings`／snapshot 檢查 | updater 讀到舊值映射 `classic`；精確比對接受「舊值 → classic」的遷移結果，非法值仍拒絕。 |
| `webclock/services/device_access_service.py`：stored group／device overrides | 讀取時只把 stored `glass`／`orbit` 映射成明確 `classic`；缺欄位仍缺欄位，維持繼承；不重寫 `device-access.json`。 |
| 新 `/api/control`、群組／裝置寫入 API | 白名單只有四個值；`glass`／`orbit` 回 400，不默默存成 classic。 |

回歸測試確認：其他值保留、明確 override 仍為 group／device 來源、缺欄位仍繼承、讀取遷移不重寫檔案、新寫入拒絕。`glass`／`orbit` 只出現在遷移用的 `RETIRED_CLOCK_STYLES` 與對應測試，不再出現在產品選項或 renderer。

## 4. 四款樣式與實際頁尺度

### 4.1 量測方法

- 真實 Chrome（headless new，CDP）開正式 `/`，用 `setClockBase()` 固定同一時間，再讀 `getBoundingClientRect()` / `getComputedStyle()`。
- 時間 `ink height` 使用 Canvas 對實際字串量 `actualBoundingBoxAscent + Descent`；segment 使用七段幾何框高，避免把 line-height 當字高。
- classic 作為同 viewport、同設定、同訊息狀態的參考；三款新增樣式的主時間須 ≥ classic 的 90%。
- 日期、訊息、viewport 邊界與 scrollWidth／scrollHeight 同時斷言，避免用縮小時間換取不重疊。

### 4.2 1024×768 橫向（無訊息／有訊息）

| 樣式 | 無訊息 ink／幾何 | 對 classic 262.2 | 有訊息 ink／幾何 | 對 classic 221.1 |
| --- | ---: | ---: | ---: | ---: |
| classic | 262.2px | 100% | 221.1px | 100% |
| flip | 256.8px | 97.9% | 256.8px | 116.1% |
| segment | 348.2px（幾何） | 132.8% | 348.2px（幾何） | 157.5% |
| paper | 257.0px | 98.0% | 257.0px | 116.2% |

秒數開啟（classic 無訊息 172.7px、有訊息 172.7px）：flip 201.0px（116.4%）、segment 230.4px（133.4%）、paper 201.2px（116.5%）。

### 4.3 768×1024 直向

| 樣式 | 無秒數 ink／幾何 | 對 classic 196.6 | 有秒數 ink／幾何 | 對 classic 129.5 |
| --- | ---: | ---: | ---: | ---: |
| flip | 189.8px | 96.5% | 139.6px | 107.8% |
| segment | 261.1px（幾何） | 132.8% | 184.3px（幾何） | 142.3% |
| paper | 190.0px | 96.6% | 134.1px | 103.6% |

### 4.4 1024×650 短橫向與 preview 一致性

| 樣式 | 正式 `/` 無秒數 | preview 無秒數 | 正式 `/` 有秒數 | preview 有秒數 |
| --- | ---: | ---: | ---: | ---: |
| flip | 353.28px | 353.28px | 276.48px | 276.48px |
| segment | 348.2px（幾何） | 348.2px（幾何） | 230.4px（幾何） | 230.4px（幾何） |
| paper | 353.3px | 353.3px | 276.5px | 276.5px |

`doc/development/clock-styles-metrics.json` 內含 baseline、actual、preview 三組原始量測；36 個主要狀態的 font-size／時間框寬高在 actual 與 preview 間差異均 ≤1px。

### 4.5 其他布局完成條件

- 390×844、844×390、1920×1080：四款皆無水平或垂直捲動、時間未超出 viewport、時間不與日期或訊息重疊。
- 12 小時制＋`yyyy-mm-dd` 長日期＋英文星期：三款皆能顯示，時間不與日期重疊。
- 日期與星期關閉：三款皆收回上方資訊；paper 同時取消預留 padding。
- 有訊息／無訊息、秒數開關：主時間尺寸不因訊息而縮到 classic 90% 以下；輔助元素先讓位。
- 夜間、亮度 0、亮度 20、黑畫面：backdrop 與容器 opacity 正確；paper 夜間使用深色紙面，黑畫面全黑。
- optional `clock-styles.js` 被延遲時，核心 `#time` 與 1000ms 計時器仍先啟動；renderer 例外或 CSS 未就緒時回退 classic。

## 5. 測試結果

### 5.1 Python

```sh
/Users/smallmac/work/code/WebClock/venv/bin/python -m pytest -q tests
```

結果：**560 passed, 725 subtests passed**。

涵蓋四個合法 ID、三種 `clock_theme`、缺值預設、非法值與 retired 值拒絕、global／owner／群組／裝置遷移、繼承與明確 override、legacy backup／portable backup、updater migration、revision／owner 隔離、預覽純顯示與既有 clock／夜間／黑畫面／鬧鐘／裝置回歸。

### 5.2 JavaScript／ES5

17 個非瀏覽器 suite 全數通過。`tests/test_clock.js` 另驗證 `clockTheme()` 的 auto／dark／light 解析；`tests/test_clock_styles.js` 涵蓋：

- flip／segment／paper 繪製、切換、20 次切換不累加 surface 或 body class。
- segment 0–9 段狀態與固定 DOM。
- CSS 未就緒、未知 style、renderer 拋錯時的 classic fallback。
- `WebClockCore.start` 在 optional CSS／JS 前的 HTML 順序靜態檢查。
- 新 clock JS／預覽 inline script 的 ES5 token 檢查。

### 5.3 真實瀏覽器

```sh
WEBCLOCK_BASE_URL=http://127.0.0.1:8898 node tests/browser_clock_styles.js
```

結果：通過。訊息：

```text
Browser checks passed: four styles with dark/light palettes, actual/preview parity,
classic 90% scale, message/seconds/12h/long-date/no-date, responsiveness,
brightness/night/black, delayed optional JS, and doc/development/screenshots/clock-styles
```

另包含管理頁四張卡片、色彩模式膠囊與縮圖切換、草稿、還原、切分頁保留、儲存成功與 409 保留草稿；全部頁面無未捕捉例外。

重跑時測試會把實際頁的固定樣本（2026-11-14，星期六）假日標記對齊 preview，避免結果依賴執行當天的星期。

### 5.4 打包與靜態檢查

```sh
/Users/smallmac/work/code/WebClock/venv/bin/python tools/build_release.py --check
/Users/smallmac/work/code/WebClock/venv/bin/python -m compileall -q webclock scripts tools tests
git diff --check
```

結果：版本 `1.4.0`，release 檢查、compileall、diff whitespace 均通過；新資源已列入打包清單。

## 6. 截圖與量測證據

目前驗收截圖：`doc/development/screenshots/clock-styles/`，共 121 張 PNG。

- `actual-vs-preview-<style>-<orientation>-<seconds>-<message>.png`（36 張）：正式 `/` 左、preview 右，同 viewport／時間／設定／訊息狀態。涵蓋 flip／segment／paper × landscape／short／portrait × 秒數開關 × 有無訊息。
- `actual-classic-vs-<style>-...png`（36 張）：同條件 classic 正式頁左、樣式正式頁右，直接比較字高與留白。
- `special-<style>-12h-long.png`、`special-<style>-no-date.png`（6 張）：12 小時制＋長日期、日期星期關閉。
- `actual-responsive-<style>-<size>.png`（12 張）：390×844、844×390、1920×1080。
- `actual-paper-brightness-0.png`、`actual-paper-brightness-20.png`、`actual-paper-night.png`、`actual-paper-black.png`（4 張）。
- `theme-pair-<style>.png`（4 張）：classic／flip／segment／paper 的深色 actual 左、淺色 actual 右。
- `theme-actual-vs-preview-<style>-<theme>.png`（8 張）：四款 × 深色／淺色，正式頁與 preview 同條件並排。
- `admin-clock-styles.png`（1 張）：四張樣式卡、色彩模式與預覽。
- `before-after-<style>-landscape-message.png`（3 張）：第二輪歷史 screenshot 與第三輪同條件對照。
- `preview-<style>-landscape-message.png`（3 張）：before／after 對照使用的第三輪 preview 原圖。

關鍵檢視：

- `actual-vs-preview-paper-landscape-no-seconds-message.png`：兩邊同為 353.3px，版面與日期位置一致。
- `actual-vs-preview-flip-short-no-seconds-message.png`：1024×650 下兩邊同為 353.28px，不再出現正式頁較小。
- `actual-vs-preview-segment-portrait-seconds-message.png`：直向秒數與訊息不重疊，幾何一致。

原始量測：`doc/development/clock-styles-metrics.json`。歷史截圖：`doc/development/screenshots/clock-styles-history/round1`、`round2`，只作歷史，不列入本輪驗收。

## 7. 本輪主要修改

- `static/clock-styles.css`：四款布局；flip／segment／paper 改為 `vw` 基準，短 landscape 才用 `vh` 上限；paper 短橫向日期與 padding 修正；增強樣式隱藏 `#event-counter`；新增四款深色／淺色色盤。
- `static/clock-styles.js`：只保留四款 ID 與 flip／segment／paper renderer；移除 glass／orbit、能力降級、`effectiveStyle`、光環進度。
- `static/clock.js`：`clockTheme()` 解析 `auto`／`dark`／`light`，時間資料帶 theme。
- `templates/admin.html`：四張樣式卡、標題右側色彩模式膠囊、深淺縮圖切換、預覽、草稿／409；移除 retired 縮圖、badge、簡化提示與今日進度。
- `templates/index.html`：四值 normalize、`clock_theme`、core 先啟動、optional 樣式後載入、backdrop、亮度與主題 body class；移除 retired 值與 preview 專用狀態。
- `templates/clock_preview.html`：純預覽頁使用同一 renderer／CSS，不輪詢、不加入裝置。
- `webclock/services/display_settings.py`：四值 allowlist、`CLOCK_THEMES`、`effective_clock_theme`、`migrate_clock_style`、`migrate_display_overrides`。
- `webclock/app.py`：global／owner 讀取與 legacy backup 遷移；預設 `clock_theme: auto` 與 preview theme 解析。
- `webclock/services/device_access_service.py`：stored group／device override 讀取遷移，保留繼承與明確來源。
- `webclock/services/portable_backup.py`、`scripts/update_clock.py`：portable backup 與 updater 遷移。
- `static/device-settings.js`、translations、guides、API docs、CHANGELOG、spec：四款與三種色彩模式一致，移除 glass／orbit。
- `tests/`：theme API／繼承／非法值、retired style 遷移／拒絕、其他值保留、不重寫、繼承回歸；瀏覽器 actual vs preview、深淺色盤與 90% 門檻。
- `sw.js`：離線 shell 版本提升至 v16，讓已安裝頁面重新取得主題 CSS／JS。

## 8. 尚未完成／限制

1. **iPad mini 1 實機待驗收**：沒有實機，未執行 iOS 9.3.5／9.3.6 Safari、主畫面入口、旋轉十次、切換二十次、30 分鐘與 8 小時長時間測試。不得把 Chrome 結果當成三款相容通過。
2. **舊 Safari 只有設計與靜態檢查**：已避免 Grid／CSS 變數等唯一呈現路徑，仍缺 Safari 9 實際字型、工具列高度、觸控與記憶體表現。
3. **5055 服務需要重啟**：目前 5055 由主 agent 啟動，執行的是舊版 template／static。完成 review 後需重啟 5055 才會看到四款選項、深淺色控制、retired 遷移與 `vw` 尺寸。本次未自行停止或修改 5055。
4. **舊頁面白名單**：舊頁面若仍持有含 `glass`／`orbit` 或缺少 `clock_theme` 的嚴格 normalize，會拒收新設定並進入 standalone；需重新載入取得新頁面。Service Worker 已提升版本，未以 additive compatibility 掩蓋。
5. **實機音訊／租約**：本輪沒有修改鬧鐘音訊、授權或租約；桌面與自動化回歸通過，但實機響鈴仍待獨立驗收。
6. **完整根目錄 pytest**：`homeassistant/tests/test_webclock.py` 需要未安裝的 `aiohttp`；本報告以 `pytest -q tests` 為正式結果。

## 9. Review 建議

- 先看 `static/clock-styles.css` 的 `vw` 尺寸與短 landscape media query，再看 `static/clock-styles.js` 的 renderer 分派。
- 用 `actual-vs-preview-*.png` 確認正式頁與 preview 同大小；用 `actual-classic-vs-*.png` 確認時間仍是主體。
- 用 `doc/development/clock-styles-metrics.json` 核對 ink height、font-size、preview 差值與 `themes` 色盤。
- 用 `theme-pair-*.png` 看四款深／淺色 actual 對照；用 `theme-actual-vs-preview-*.png` 確認同主題預覽一致。
- 確認 `glass`／`orbit` 只出現在 `RETIRED_CLOCK_STYLES` 與遷移測試，不再出現在 UI、renderer 或 CSS。
- 變更已提交於 `feat/clock-styles-deepseek`；合併、發布與 iPad mini 1 實機驗收仍待 reviewer 處理。
