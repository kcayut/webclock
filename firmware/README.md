# WebClock 桌鐘韌體

| 目錄 | 內容 |
|---|---|
| [ee04-clock/](ee04-clock/README.md) | [ESPHome 韌體入口](ee04-clock/clock.yaml)、板型與分割表、USB 刷機及 OTA、[使用手冊](ee04-clock/使用手冊.md) |
| [core/](core/) | 按鍵、鬧鐘、RTC、裝置配對等共用邏輯 |
| [views/](views/) | 電子紙畫面、字型與行事曆跑馬燈 |
| [components/webclock/](components/webclock/) | WebClock 服務的 ESPHome 同步元件 |
| [setup/](setup/pair.py) | 電腦端 USB 配對工具 |
| [tests/](tests/) | 核心、同步與配對測試 |

## 準備編譯環境

在專案根目錄使用 Python 3.12 執行：

```sh
python3.12 -m venv firmware/.venv
firmware/.venv/bin/python -m pip install -r firmware/requirements.txt
```

接著依[桌鐘刷機說明](ee04-clock/README.md#刷入韌體)建立每台自己的設定、編譯並刷入。

## 共用元件測試

完成一次 EE04 編譯後，使用已安裝專案根目錄 `requirements.txt` 依賴的 Python，從專案根目錄執行 `python3 firmware/tests/run_tests.py`，驗證鬧鐘排程與同步資料解析。裝置端選單、配對與服務整合測試見[桌鐘驗證](ee04-clock/README.md#驗證)。
