# /// script
# requires-python = ">=3.10"
# dependencies = ["pyserial>=3.5,<4"]
# ///
"""Pair an already-flashed desk clock over its physical USB port."""
from getpass import getpass
from hashlib import sha256
from ipaddress import IPv4Address, IPv4Network
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request



class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def server_url(raw):
    url = raw.strip().rstrip("/")
    parts = urlsplit(url)
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment or parts.port == 0
            or any(ord(c) <= 32 or ord(c) == 127 or c in "@?#\\" for c in url)
            or len(url.encode()) > 320):
        raise ValueError("請輸入桌鐘可連到的 WebClock 服務根網址，可包含反向代理路徑。")
    if parts.scheme == "http":
        ip = IPv4Address(parts.hostname)
        if not any(ip in IPv4Network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
            raise ValueError("個人區網 HTTP 請用路由器分配的私人 IPv4；其他位址請用 HTTPS。")
    return url


def api(url, path, token="", body=None):
    headers = {"Accept": "application/json", "X-WebClock-Client": "native-v1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = Request(url + path, data=data, headers=headers)
    with build_opener(NoRedirect()).open(req, timeout=12) as response:
        if response.headers.get_content_type() != "application/json":
            raise ValueError("此網址未回傳 WebClock API，請確認服務根網址。")
        return json.load(response)


def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as tmp:
        try:
            json.dump(data, tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
        except BaseException:
            os.unlink(tmp.name)
            raise
    os.replace(tmp.name, path)


def group_token(url, owner, statefile, invite, call=api):
    base = "/api/v2/device"
    saved = json.loads(statefile.read_text()) if statefile.exists() else {}
    token = saved.get("token", "")
    status = {}
    if token:
        try:
            status = call(url, base + "/identity", token)
        except HTTPError as err:
            if err.code not in (401, 403):
                raise
            err.close()
            # A revoked or expired credential can only be replaced with a new invitation.
    if status.get("status") != "active":
        code = invite().strip().upper()
        if not re.fullmatch("[A-Z0-9]{6}", code):
            raise ValueError("群組邀請碼應為六位英數字元。")
        if status.get("status") != "pending":
            # Pending bearer tokens cannot read /identity; prepare reuses their attempt.
            try:
                prepared = call(url, base + "/token/prepare", token, {})
            except HTTPError as error:
                if not token or error.code not in (401, 403):
                    raise
                error.close()
                prepared = call(url, base + "/token/prepare", body={})
            token, attempt = prepared["token"], prepared["attempt_id"]
            write_private(statefile, {"token": token})
        else:
            attempt = status["attempt_id"]
        call(url, base + "/token/join", token, {"attempt_id": attempt, "code": code})
        status = call(url, base + "/identity", token)
    if status.get("status") != "active":
        raise ValueError("群組尚未授權，請再執行配對。")
    if status.get("identity", {}).get("owner_id") != owner:
        # Release only the seat acquired by this credential, then allow a clean retry.
        call(url, base + "/token/leave", token, {})
        statefile.unlink(missing_ok=True)
        raise ValueError("群組與程式憑證屬於不同管理者，請使用正確的邀請碼重試。")
    print("顯示群組已確認：", status.get("group", {}).get("name", ""))
    return token


def command(port, message, expected):
    port.write(message + b"\n")
    end = monotonic() + 6
    while monotonic() < end:
        line = port.readline(4096).strip()
        if line.startswith(b"WCD1 "):
            value = line[5:].decode("ascii", errors="replace")
            if value == expected or value.startswith(expected + " "):
                return value
            raise ValueError("桌鐘未接受設定：" + value)
    raise ValueError("桌鐘未回應。請關閉其他序列工具，按 ● 進入選單、用 ＋ 選「USB 配對」後重試。")


def run():
    import serial
    from serial.tools.list_ports import comports

    ports = [p for p in comports() if p.vid is not None]
    for i, p in enumerate(ports, 1):
        print(f"{i}. {p.device}　{p.description}")
    choice = input("輸入桌鐘埠的號碼或完整路徑：").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(ports):
        choice = ports[int(choice)-1].device
    if not choice:
        raise ValueError("請選擇 USB 資料線所連接的桌鐘。")
    with serial.Serial(port=None, baudrate=115200, timeout=.3, write_timeout=5) as port:
        port.port = choice
        port.dtr = port.rts = False
        port.open()
        input("回到桌鐘主畫面，按 ● 進入選單，用 ＋ 選「USB 配對」，看到「USB 配對」後按 Enter。")
        ready = command(port, b"WCD1 HELLO", "READY")
        mac = ready.removeprefix("READY ")
        if not re.fullmatch("[0-9a-fA-F]{12}",mac):
            raise ValueError("請確認選到 WebClock 桌鐘。")
        url = server_url(input("WebClock 根網址："))
        local = url.startswith("http://")
        if local and input("此私人區網會以明文傳送個人模式權杖，確認信任網路請輸入 YES：") != "YES":
            raise ValueError("設定已取消。")
        token = getpass("貼上「程式存取」的桌鐘憑證（輸入不顯示）：").strip()
        identity = api(url, "/api/v1/control/identity", token)
        client = identity["client"]
        if not {"schedules:read","schedules:write"} <= set(client["scopes"]):
            raise ValueError("請建立同時具有讀、寫鬧鐘權限的程式憑證。")
        managed = identity["mode"] == "managed"
        display = ""
        grouped = managed or input("個人模式使用群組行事曆？輸入 y，其餘直接 Enter：").lower() == "y"
        if grouped:
            if local:
                raise ValueError("群組配對請使用 HTTPS 服務網址。")
            owner = client["owner_id"]
            key = sha256((url+"\n"+owner+"\n"+mac.lower()).encode()).hexdigest()
            statefile = Path.home()/".webclock-desk"/(key+".json")
            display = group_token(url, owner, statefile, lambda: getpass("輸入管理者提供的群組邀請碼："))
        profile = dict(url=url, control=token, display=display, local_http=local)
        command(port, b"WCD1 SET "+json.dumps(profile,separators=(",",":")).encode(), "SAVED")
        print("桌鐘已儲存服務設定並重新開機。請設定一次本機鬧鐘，到 WebClock「排程」確認同步。")


if __name__ == "__main__":
    try:
        run()
    except HTTPError as err:
        err.close()
        sys.exit(f"WebClock 回應 HTTP {err.code}。請確認網址、憑證權限及邀請碼，再重跑配對。")
    except (URLError,OSError,ValueError,KeyError,EOFError,KeyboardInterrupt) as err:
        sys.exit(f"配對未完成。{err}")
