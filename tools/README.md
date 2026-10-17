# 維護者工具

這裡放開發與發佈使用的工具，不放安裝後需要執行的程式，也不包含在 Server Release 或 Docker 映像中。

在專案根目錄執行：

```bash
python3 tools/build_release.py --check
python3 tools/build_release.py --tag vX.Y.Z --output /tmp/webclock-release
```

打包讀取 **Git HEAD 已提交內容**；`--check` 檢查工作目錄的版號。先提交候選版本，再打包，才能讓產物對應到候選程式。不要改成直接打包工作目錄，以免帶入私人設定與未驗證內容。

版本規則、發行流程與驗收證據見[發行說明](../doc/ha-release.md)。HA 本機建置入口在 [`homeassistant/prepare_local_app.sh`](../homeassistant/prepare_local_app.sh)，主機演練在 [`tests/rehearsal/`](../tests/rehearsal/README.md)。
