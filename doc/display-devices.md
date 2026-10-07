# 把平板或電腦變成 WebClock 時鐘

[回到 README](../README.md) · [安裝 Server](installation.md) · [使用指南](guide.md)

**先開啟時鐘 → 建立主畫面／桌面入口 → 設定全螢幕 → 關閉自動休眠。** 顯示端不用安裝 WebClock Server；只看時間，直接使用[線上時鐘](https://kcayut.github.io/webclock/)即可。

本頁依約 **2011–2026 年**的常見系統分類，包含 **iPad mini 1／iOS 9**。版本表是操作設定對照，並非所有機型的相容性認證；選單會隨語言、廠牌與更新改名。文件核對日期：2026-10-08。

## 一眼選擇

| 裝置 | 點圖示就開時鐘 | 全螢幕方式 | 螢幕恆亮 |
| --- | --- | --- | --- |
| [iPad mini 1／iOS 9](#ipad-ios9) | Safari「加入主畫面」 | 從主畫面圖示開啟，隱藏 Safari 網址列 | 一般 → 自動鎖定 → 永不 |
| [其他 iPad／iPhone](#ipad) | Safari「加入主畫面」 | 新版另開啟「打開為網頁 App」 | 螢幕顯示與亮度 → 自動鎖定 → 永不 |
| [Android](#android) | Chrome「建立捷徑」或「加入主畫面」 | 捷徑不保證全螢幕；專用平板可選全螢幕瀏覽器 | 螢幕逾時設永不；沒有此選項時使用插電保持喚醒 |
| [Windows](#windows) | 桌面捷徑，或 Edge 安裝為應用程式 | 瀏覽器按 `F11` | 插電時關閉螢幕、睡眠都設永不 |
| [Mac](#mac) | Safari 加入 Dock（macOS 14 起）或建立書籤 | 綠色視窗按鈕 → 進入全螢幕 | 關閉顯示器設永不，停用插電自動睡眠 |
| [Linux／Chromebook](#other-computers) | 瀏覽器捷徑 | `F11`／Chromebook 全螢幕鍵 | 電源設定關閉螢幕逾時與自動睡眠 |

「主畫面圖示」是快速入口，「全螢幕」是隱藏瀏覽器介面，「恆亮」是避免裝置休眠，三者需要分別設定。**WebClock 目前不會自動要求螢幕保持喚醒**；只加入主畫面或放大全螢幕仍可能黑屏。

<a id="clock-url"></a>
## 先準備正確的時鐘網址

| 使用方式 | 要儲存的網址 |
| --- | --- |
| 不架 Server，只看時間 | `https://kcayut.github.io/webclock/` |
| Bare metal 預設 self | `http://主機IP:5000/` |
| Docker 預設 self | `http://主機IP/`；自訂連接埠就加上，例如 `:8080` |
| managed | 實際設定好的 `https://你的主機名稱/`，保留必要的連接埠 |
| Home Assistant App 的外部顯示 | 開放 App 的 `8100` 網路連接埠後，使用 `http://HA主機IP:8100/` |

把「主機IP」換成執行 Server 的電腦位址，不是平板自己的位址。另一台裝置不能使用 `localhost` 連到 Server。自架入口詳見[安裝指南](installation.md)。

請先確認頁面已顯示大字時間與日期，再建立圖示；不要儲存 `/admin`、`/schedules` 或 HA 的管理側邊欄網址。managed／HA 顯示端若要加入群組，**先建立圖示，從圖示打開後再輸入六碼**，操作見[裝置加入](guide.md#群組設定與裝置加入)。不同瀏覽器、Safari 分頁與獨立網頁 App 可能使用不同的儲存空間，不能假定原本的配對會一起帶過去。圖示網址不需放入密碼、Token 或加入碼。

<a id="ipad-ios9"></a>
## iPad mini 1／iOS 9：完整步驟

適用初代 iPad mini 使用 iOS 9.x；不是 iPad mini 2 或後續機型。可在「設定 → 一般 → 關於本機」確認版本。

### 1. 用 Safari 建立時鐘圖示

1. 將 iPad 連上 Wi-Fi，打開 **Safari**，輸入上面的時鐘網址。不要使用其他 App 裡的內嵌瀏覽器。
2. 確認時間與日期可見；把 iPad 橫放，視需要鎖定螢幕旋轉。
3. 點 Safari 的**分享按鈕**（方框向上箭頭），在分享面板找到**加入主畫面**；沒看到時滑動面板中的圖示。
4. 名稱填 `WebClock`，確認網址是時鐘頁，點「新增／加入」。
5. 按實體 **Home 鍵**回到主畫面，再點剛建立的 `WebClock` 圖示。

從這個圖示開啟才會使用接近 App 的獨立顯示方式；Safari 一般分頁仍會有網址列。WebClock 已提供 Apple 的主畫面網頁設定，但系統狀態列仍可能保留，不等於每一個像素都由網頁占滿。iOS 9 沒有新版的「打開為網頁 App」開關，也不用尋找桌面瀏覽器的 `F11`。[Apple 舊版網頁 App 說明](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/ConfiguringWebApplications/ConfiguringWebApplications.html)

### 2. 設定螢幕恆亮

1. 到 **設定 → 一般 → 自動鎖定 → 永不**。iOS 9 的入口在「一般」。
2. 到「螢幕顯示與亮度」調成適合室內的亮度，接上電源。
3. 回到主畫面，點 `WebClock`，保持頁面在前景。不要按電源鍵，也不要闔上會觸發鎖定的保護蓋。

舊版路徑依據 Apple 的 [iPad iOS 9.1 使用手冊（存檔鏡像）](https://manuals.plus/m/f03f9f2f2d3c7c1428d0b52a9ca0d040ef520a3cfef816bfde3cc9e15615f56d)。若要停止恆亮，把「自動鎖定」改回原本的分鐘數。

### 3. 選用：避免誤觸離開

iOS 9 可到「設定 → 一般 → 輔助使用 → 引導使用模式」開啟並設定密碼；回到時鐘，按三下 Home 鍵，再按「開始」。退出時再按三下 Home，輸入該密碼並結束。它用來限制離開目前 App，**不能代替上面的恆亮設定**；不要設定會中斷時鐘的使用時間限制。[iOS 9.1 原手冊的引導使用模式](https://manuals.plus/m/f03f9f2f2d3c7c1428d0b52a9ca0d040ef520a3cfef816bfde3cc9e15615f56d)

專案仍將 **iPad mini 1／iOS 9 實機驗收列為待完成**，尤其是目前網址的 HTTPS 載入、長時間顯示與 managed 配對。一般瀏覽器測試不能代替這台實機；請依[最後的檢查步驟](#check)確認你的裝置。

<a id="ipad"></a>
## 其他 iPad／iPhone：依版本選擇

| 系統世代（約略年份） | 主畫面入口 | 自動鎖定位置 |
| --- | --- | --- |
| iOS 5–8（2011–2014） | Safari → 分享 → 加入主畫面；早期分享圖示外觀不同 | 設定 → 一般 → 自動鎖定 |
| iOS 9（2015） | 使用上方 iPad mini 1 步驟 | 設定 → 一般 → 自動鎖定 |
| iOS 10–12（2016–2018） | Safari → 分享 → 加入主畫面 | 設定 → 螢幕顯示與亮度 → 自動鎖定 |
| iPadOS／iOS 13–18（2019–2024） | Safari → 分享 → 加入主畫面 | 設定 → 螢幕顯示與亮度 → 自動鎖定 |
| iPadOS／iOS 26–27（2025–2026） | 同上；若出現「打開為網頁 App」，請開啟 | 設定 → 螢幕顯示與亮度 → 自動鎖定 |

以上年份表示版本世代，不表示每台舊 iPad 都能升級。iOS 5–8 僅列舊系統的操作位置，未驗證目前網站能在這些瀏覽器正常載入。

**新版 iPad 的操作：**Safari 開啟時鐘 → 分享（有些版面要先展開選單或「檢視更多內容」）→ 加入主畫面 → 開啟「打開為網頁 App」（若有）→ 加入 → 回到主畫面點圖示。若 Safari 正在分割畫面或視窗模式，先將它展開至整個螢幕。[Apple：將網站變成 iPad App](https://support.apple.com/zh-tw/guide/ipad/ipad8f1f7a29/ipados)

**恆亮：**依表格找到自動鎖定，選「永不」；完成後回到時鐘圖示。退出時按 Home 鍵，或在沒有 Home 鍵的裝置從底部上滑。要恢復正常休眠，再將自動鎖定改回分鐘數。[Apple：iPad 自動鎖定](https://support.apple.com/zh-tw/guide/ipad/ipad11dbabaf/ipados)

iPhone 的做法相近：Safari → 分享 → 加入主畫面，新版可打開為網頁 App；小螢幕請以實際排版確認可讀性。[Apple：iPhone 主畫面網頁 App](https://support.apple.com/zh-tw/guide/iphone/iphea86e5236/ios)

新版「引導使用模式」在「設定 → 輔助使用」。若啟用，還要檢查它自己的「螢幕自動鎖定」；這個設定可能和一般自動鎖定不同。按鍵操作依系統版本與認證方式而異，請照 [Apple 當前引導使用模式說明](https://support.apple.com/zh-tw/111795)設定並先試過退出方式。

<a id="android"></a>
## Android 手機與平板

### 版本對照

| 系統世代（約略年份） | 建立入口 | 持續顯示的設定重點 |
| --- | --- | --- |
| Android 3–4.1（2011–2012） | 內建瀏覽器書籤／主畫面捷徑，依廠牌 | 顯示 → 休眠；部分機型在「開發」有插電保持喚醒 |
| Android 4.2–4.4（2012–2013） | 瀏覽器選單或書籤的加入主畫面 | 開發人員選項通常要先點版本號碼七次才能顯示 |
| Android 5–7（2014–2016） | Chrome → 選單 → 加入主畫面 | 顯示 → 螢幕逾時；必要時啟用插電保持喚醒 |
| Android 8–11（2017–2020） | Chrome 主畫面捷徑 | 廠牌可能限制逾時長度，使用下方插電做法 |
| Android 12–15（2021–2024） | Chrome 主畫面捷徑；名稱隨 Chrome 版本變動 | 顯示／顯示與觸控 → 螢幕逾時 |
| Android 16–17（2025–2026） | 新版 Chrome 可能顯示「安裝並建立捷徑」 | 同上；再確認省電模式與廠牌限制 |

Android 的選單主要取決於廠牌與瀏覽器版本；舊系統也不一定能裝最新 Chrome。Android 3–4.x 的表格僅供找設定，未承諾目前網站、TLS 或所有功能相容。

### 建立圖示與全螢幕

Chrome 開啟時鐘 → 右上 `⋮` →「加入主畫面」，或新版「安裝並建立捷徑 → 建立捷徑」→ 名稱 `WebClock` → 新增。之後從主畫面圖示開啟。[Google：Android 網站捷徑](https://support.google.com/chrome/answer/15085120?hl=zh-Hant&co=GENIE.Platform%3DAndroid)

**Android Chrome 的捷徑可能仍開在一般分頁。** WebClock 目前沒有提供保證可安裝成 Android 獨立 App 的網頁 manifest，也沒有網頁內的全螢幕按鈕。若瀏覽器提供「安裝應用程式」或「全螢幕」，可使用並確認結果；不要把滑動後暫時縮起的網址列當作固定全螢幕。

專用時鐘平板若需要確實隱藏工具列，可選用第三方 **Fully Kiosk Browser**。其目前官方列出的系統範圍為 Android 6–16；其他版本先確認相容性。本專案未做該 App 實機驗收。

1. 從官方連結安裝後，在 **Web Content Settings → Start URL** 填時鐘網址。
2. 保留預設沉浸式全螢幕；到 **Toolbars and Appearance** 關閉不需要的網址列與工具列顯示。
3. 在 **Device Management → Keep Screen On** 開啟恆亮；從左邊緣向右滑可回設定。
4. managed／HA 的六碼加入要在這個 App 裡完成。先不開鎖定裝置的 Kiosk Mode；需要它時再確認退出 PIN 與 PLUS 授權。

退出全螢幕可回設定開啟工具列，或滑出系統導覽列回主畫面；停止恆亮則關閉 Keep Screen On。[Fully 官方設定與系統需求](https://www.fully-kiosk.com/en/#configuration)

### 不另外裝 App：插電保持螢幕開啟

1. 先看「設定 → 顯示／顯示與觸控 → 螢幕逾時／休眠」，若有「永不」就選它。
2. 沒有「永不」時，Android 4.2 以後通常可到「關於手機／關於平板」找到**版本號碼／Build number**，連點七次；Samsung 常放在「軟體資訊」裡。需要時輸入裝置解鎖碼。
3. 回到設定的「開發人員選項」（部分系統在「系統」內），只開啟 **保持喚醒／Stay awake：充電時螢幕不會休眠**。不需要開 USB 偵錯。
4. 接上電源並回到時鐘；這個選項只保證插電時的行為，拔掉電源後仍遵循原本的休眠設定。

Android 4.1 或更早版本的開發選項可能已直接顯示，不一定需要點七次。設定依 [Android 官方開發選項說明](https://developer.android.com/studio/debug/dev-options)。不再當時鐘使用時，關閉保持喚醒即可；若公司或學校禁止此設定，需由管理員處理。

<a id="windows"></a>
## Windows 電腦與平板

### 桌面入口與全螢幕

**一般瀏覽器：**用 Chrome、Edge 或 Firefox 打開時鐘，建立書籤／桌面捷徑；點開後按 **`F11`** 進入全螢幕，再按一次退出。有些筆電需要 `Fn + F11`。先確認瀏覽器全螢幕，而非只有視窗最大化。[Chrome 快速鍵](https://support.google.com/chrome/answer/157179?hl=zh-Hant)、[Firefox 全螢幕](https://support.mozilla.org/en-US/kb/how-make-firefox-and-websites-go-full-screen)

**Chrome 桌面圖示：**`⋮` →「投放、儲存及分享 → 建立捷徑」→ 命名 `WebClock`。舊版可能在「更多工具」。捷徑本身不會自動按下 `F11`。[Google：電腦網站捷徑](https://support.google.com/chrome/answer/15085120?hl=zh-Hant&co=GENIE.Platform%3DDesktop)

**像 App 的獨立視窗：**新版 Edge 的 `⋯` →「更多工具 → 應用程式 → 將此網站安裝為應用程式」（有些版本直接在「應用程式」）→ 命名 `WebClock`，再釘選到開始或工作列。從該入口開啟後確認是否需要重新加入群組。若獨立視窗不接受 `F11`，改用一般瀏覽器分頁的全螢幕方式。[Microsoft：Edge 網站應用程式](https://support.microsoft.com/en-us/edge/install-manage-or-uninstall-apps-in-microsoft-edge)

### 恆亮與不休眠

| Windows 世代 | 設定位置 | 接上電源時要調整的項目 |
| --- | --- | --- |
| Windows 7／8／8.1（約 2011–2014 的常見環境） | 控制台 → 電源選項 → 變更計畫設定 | 關閉顯示器：永不；讓電腦睡眠：永不 |
| Windows 10（2015 起） | 設定 → 系統 → 電源與睡眠 | 螢幕：永不；睡眠：永不 |
| Windows 11（2021 起） | 設定 → 系統 → 電源與電池（桌機可能只叫「電源」）→ 螢幕、睡眠與休眠逾時 | 關閉螢幕：永不；裝置睡眠：永不；若另有休眠逾時也一併確認 |

只調整「插電時」就能作為固定時鐘，保留原本電池省電設定。若仍跳出動畫或黑屏，在 Windows 搜尋「變更螢幕保護裝置」，設為「無」。筆電保持上蓋打開；外接螢幕也可能有自己的省電計時。[Microsoft：Windows 11 電源設定](https://support.microsoft.com/en-us/windows/experience/power-battery/power-settings-in-windows-11)、[螢幕保護裝置](https://support.microsoft.com/en-us/windows/configure-a-screen-saver-in-windows-a9dc2a0c-dc8e-9161-d270-aaccc252082a)

Windows 7／8 的舊瀏覽器不代表仍能安全更新或支援目前網站；優先用裝置仍可支援的瀏覽器版本測試。結束固定顯示後，把電源計畫改回原本設定。

<a id="mac"></a>
## Mac：Safari、Chrome、Edge 或 Firefox

### 桌面入口與全螢幕

**macOS Sonoma 14 起：**Safari 打開時鐘 →「檔案 → 加入 Dock」（或分享 → 加入 Dock）→ 命名 `WebClock` → 加入。之後點 Dock 圖示就會開啟獨立網頁 App；managed 配對請在該視窗完成。[Apple：Safari 網頁 App](https://support.apple.com/zh-tw/104996)

**較舊 macOS：**將時鐘加入 Safari 書籤，或把網址拖到桌面建立連結；它會打開瀏覽器，不會變成 Sonoma 的網頁 App。若已使用 Chrome／Edge，可用上面的瀏覽器捷徑功能。

**全螢幕：**把游標移到左上綠色視窗按鈕，選「進入全螢幕」，或用「顯示方式 → 進入全螢幕」；支援時可按 `Control + Command + F`。退出時把游標移到頂端，再使用綠色按鈕或相同快速鍵。選單列可能在游標靠近頂端時出現。[Apple：全螢幕使用 App](https://support.apple.com/zh-tw/guide/mac-help/mchl9c21d2be/mac)

### 恆亮與不休眠

| macOS 世代（約略年份） | 設定位置與操作 |
| --- | --- |
| OS X 10.7–10.10（2011–2014） | 系統偏好設定 → 節能器；在電源轉接器頁將「顯示器睡眠」設永不，若有「電腦睡眠」也設永不 |
| OS X／macOS 10.11–10.15（2015–2019） | 系統偏好設定 → 節能器；將關閉顯示器的時間設永不，啟用防止電腦自動睡眠（若有） |
| macOS 11–12（2020–2021） | MacBook：系統偏好設定 → 電池 → 電源轉接器；桌機通常仍在「節能器」。關閉顯示器設永不 |
| macOS 13 及以後（2022–2026，包含 14／15／26／27） | 系統設定 → 鎖定畫面；將「使用電源轉接器且閒置時關閉顯示器」設永不；桌機選對應的閒置關閉顯示器選項 |

新版 MacBook 再到「系統設定 → 電池 → 選項」，開啟接上電源且顯示器關閉時防止自動睡眠；桌機在「能源／節能器」找對應選項。若螢幕保護程式會蓋住時鐘，也停用它的閒置啟動。不同機型的電源項目略有差異，以 [Apple 睡眠與喚醒說明](https://support.apple.com/zh-tw/guide/mac-help/mchle41a6ccd/mac)為準。筆電上蓋保持打開；恢復一般使用時改回原先逾時時間。

<a id="other-computers"></a>
## Linux／Chromebook

| 裝置與版本範圍 | 入口與全螢幕 | 恆亮設定 |
| --- | --- | --- |
| Linux 桌面（約 2011–2026；依桌面環境而非單看發行版） | Chrome／Firefox 書籤或捷徑，`F11` 進入／退出 | GNOME：設定 → 電源 → 螢幕空白（Screen Blank）設永不，並關閉插電時自動暫停；其他桌面在電源管理與螢幕保護設定調整 |
| Chromebook／ChromeOS（2011 起；舊版選單不同） | Chrome 捷徑；按鍵盤頂排「全螢幕」鍵進入，再按一次退出 | 新版：設定 → 系統偏好設定 → 電源 → 插電閒置時「保持開啟螢幕」；舊版可在「裝置 → 電源」找相同項目 |

GNOME 若仍自動鎖定，另檢查隱私／螢幕鎖定設定。Chromebook 保持上蓋打開；受學校或公司管理時，電源選項可能不可修改。[GNOME 螢幕空白設定](https://help.gnome.org/gnome-help/display-blank.html)、[Google：Chromebook 保持啟用](https://support.google.com/chromebook/answer/3420029?hl=zh-Hant)

<a id="troubleshooting"></a>
## 常見問題

| 遇到的情況 | 處理方式 |
| --- | --- |
| 找不到「永不」，或自動鎖定不能改 | 確認是否開啟省電模式，或受公司／學校管理；Android 可試插電保持喚醒。不要移除不明管理描述檔 |
| 加了圖示，仍看到網址列 | iPad 要從主畫面圖示開；新版確認已打開為網頁 App。Android 捷徑本來就不保證獨立視窗 |
| 配對過，從圖示開又要求六碼 | 在最終要使用的圖示／瀏覽器內重新加入。保持同一網址、協定、連接埠與瀏覽器設定檔，不用私密／無痕模式，也不要定期清除網站資料 |
| 舊 iPad 無法建立安全連線 | 先確認日期時間正確，再請 Server 管理者確認完整憑證鏈與舊 Safari 的 TLS 相容性。managed 必須維持 HTTPS，不能用忽略憑證錯誤代替 |
| 畫面還亮，但時間不走或內容不更新 | 確認時鐘在前景、未進入系統鎖定；重新整理並檢查網路與 Server。只關閉睡眠不能修復網頁載入問題 |
| 想用網頁鬧鐘叫醒鎖定中的裝置 | 網頁不能保證背景或鎖定狀態響鈴；需保持前景、亮屏，並先依[鬧鐘指南](guide.md#在-ipad-使用網頁鬧鐘)測試音訊 |
| 加入主畫面後，希望斷網也能重新開啟 | 主畫面圖示不是離線安裝。離線能力取決於瀏覽器、安全連線與快取；iOS 9 不支援目前的 Service Worker 離線機制 |
| 重新開機後沒有自動顯示時鐘 | 本頁設定的是「點圖示即開啟」。裝置重開機後通常仍要解鎖並點開圖示；自動開機展示需另做裝置的 kiosk／啟動設定 |

<a id="check"></a>
## 設好後，做一次實際檢查

1. 回到主畫面／桌面，點圖示，確認直接進入時鐘而非管理頁，時間與日期可讀。
2. 進入全螢幕，接上電源，至少放置 **15–30 分鐘**且不要觸碰；超過原先的休眠時間後，畫面仍亮、時間仍持續前進。
3. managed／HA 裝置再關閉並從同一圖示重開，確認群組與顯示內容仍正確；順便練習退出全螢幕。
4. 若要長期當時鐘，另外做跨午夜、網路斷線後恢復與裝置重開機檢查。降低不必要的亮度、保持散熱；OLED 裝置避免長期高亮度固定畫面。

這是使用者的基本確認，不等於專案完整實機驗收。iPad mini 1／iOS 9 的正式紀錄還需保留系統版本、網址／HTTPS 環境、程式版本、測試時段與結果，見[實機驗收清單](phase-b-acceptance.md)。
