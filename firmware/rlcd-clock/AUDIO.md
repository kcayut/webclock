# RLCD 桌鐘自訂鬧鈴

使用 FAT32 microSD。把 `alarm.wav` 放在卡片根目錄，關機後插卡，再開機。每日鬧鐘和遠端有聲鬧鐘共用這個檔案。之後只需替換卡上的檔案，無須重刷。

例如在電腦上用 FFmpeg 將音樂轉成 16 kHz、16 位元、單聲道 PCM WAV。一般長度的歌曲可整首放在卡上。

```sh
ffmpeg -i "music.mp3" -map 0:a:0 -map_metadata -1 -ac 1 -ar 16000 -c:a pcm_s16le alarm.wav
```

macOS 也可用內建的 `afconvert` 轉換，例如把立體聲 WAV 轉成桌鐘可讀的檔案。

```sh
afconvert -f WAVE -d LEI16@16000 -c 1 "music.wav" alarm.wav
```

每次有聲鬧鐘開始時，韌體會比對 WAV 標頭與檔案實際大小，最多預讀前 60 秒到 PSRAM（1.92 MB）。短曲會在響鈴期間循環播放。確認停鈴或核心的 60 秒時限到達時，會關閉喇叭放大器並停止播放。核心的時限包含讀卡時間。無卡、缺檔、格式錯誤、檔案截斷或 3 秒內讀取未完成時，該次改播內建雙音提示。聽到內建提示時，可在序列日誌找 `rlcd_alarm`。遠端設為 `silent` 或音量為 0 時維持靜音。每日鬧鐘可離線運作，已同步到裝置的遠端排程也可離線播放。

## 板級整合

- `clock.yaml` 在 `packages` 載入 `audio: !include audio.yaml`。共用核心提供 `ringing` 與 `service_clock.ring_volume()`，後者在遠端鬧鐘停止或靜音時回傳 0。核心在每日鬧鐘狀態改變、遠端狀態／輸出改變及確認停鈴時呼叫 `mix_audio`。
- 使用 ESPHome 2026.9.1、ESP-IDF、八線 PSRAM、啟用電源管理。I²C 由板級 YAML 設定 SDA GPIO13、SCL GPIO14，ES8311 位址為 `0x18`。I²S 輸出至 ES8311 的 DIN 為 GPIO8，BCLK GPIO9、MCLK GPIO16、LRCLK GPIO45。GPIO46 高電位啟用喇叭放大器，開機預設關閉。GPIO45 和 GPIO46 使用原板線路，避免加裝改變開機電位的上拉或下拉。 [微雪 ESPHome 板級設定](https://docs.waveshare.com/ESP32-ESPHome-Tutorials/Example-RLCD-Voice#61-speaker-button-triggered-ringtone)
- 原板 microSD 使用一位元 SDMMC，CLK GPIO38、CMD GPIO21、D0 GPIO39。卡片以讀取方式開檔，掛載失敗時不會格式化卡片。 [微雪 microSD 範例](https://github.com/waveshareteam/ESP32-S3-RLCD-4.2/blob/main/examples/esp-idf/06_SD_Card/components/port_bsp/sdcard_bsp.h)

## 驗證

在專案根目錄編譯並執行主機端測試。測試涵蓋短曲、60 秒界線、三分鐘長曲、前 60 秒完整但尾端截斷的長曲、奇數長度中繼資料區塊及錯誤取樣格式。

```sh
c++ -std=c++17 -Wall -Wextra -Werror firmware/rlcd-clock/test_alarm_wav.cpp -o /tmp/rlcd-alarm-wav-test
/tmp/rlcd-alarm-wav-test
```

實板驗收時，依序放入短曲、三分鐘長曲和截斷的 WAV，再測無卡與空卡。確認斷網時每日鬧鐘會循環播放短曲，長曲會在 60 秒內截停，確認停鈴可立即關閉喇叭。先同步一組有聲與一組 `silent` 的遠端排程，再離線測試兩者。最後更換卡上音樂，確認重新開機後可直接播放新檔。
