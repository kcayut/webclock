"""USB handshake and native group invitation against a disposable WebClock."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests'), str(HERE.parent/'setup')]
import app as clock
import pair
import test_managed_display as managed


class PairingTest(unittest.TestCase):
    def test_service_addresses_and_usb_ack(self):
        self.assertEqual(pair.server_url(" https://clock.example/proxy/ "), "https://clock.example/proxy")
        self.assertEqual(pair.server_url("http://192.168.2.1:8080"), "http://192.168.2.1:8080")
        for url in ("http://example.com", "http://8.8.8.8", "https://name@host", "https://host/?x", "ftp://host"):
            with self.assertRaises(ValueError):
                pair.server_url(url)

        class Port:
            def write(self, msg):
                self.sent = msg
            def readline(self, limit):
                return b"WCD1 READY 001122334455\n"
        port = Port()
        self.assertEqual(pair.command(port,b"WCD1 HELLO","READY"),"READY 001122334455")
        self.assertEqual(port.sent,b"WCD1 HELLO\n")

    def test_group_join_survives_lost_response_without_spending_second_seat(self):
        server=managed.ManagedDisplayTest()
        self.addCleanup(server.doCleanups)
        server.setUp()
        group=server.group("桌鐘")
        invite=server.service().create_invite(server.owner,group["id"],1)["code"]
        browser=clock.app.test_client(use_cookies=False)
        joins=[]
        def call(url,path,token="",body=None):
            headers={"X-WebClock-Client":"native-v1"}
            if token:
                headers["Authorization"]="Bearer "+token
            res=browser.open(path,base_url=url,headers=headers,method="GET" if body is None else "POST",json=body)
            self.assertLess(res.status_code,300,(res.status_code,res.json))
            if path.endswith("/join"):
                joins.append(1)
                raise TimeoutError("lost confirmation")
            return res.json
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"group.json"
            with self.assertRaises(TimeoutError):
                pair.group_token("https://localhost",server.owner,path,lambda:invite,call)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            token=pair.group_token("https://localhost",server.owner,path,lambda:self.fail("second invitation"),call)
            self.assertTrue(token)
            self.assertEqual(len(joins),1)
            with self.assertRaises(ValueError):
                pair.group_token("https://localhost","other-owner",path,lambda:"",call)
            self.assertFalse(path.exists())

    def test_pending_bearer_reuses_existing_attempt_after_wrong_code(self):
        server = managed.ManagedDisplayTest()
        self.addCleanup(server.doCleanups)
        server.setUp()
        group = server.group("重試")
        invite = server.service().create_invite(server.owner, group["id"], 1)["code"]
        browser = clock.app.test_client(use_cookies=False)
        attempts = []
        def call(url, path, token="", body=None):
            headers = {"X-WebClock-Client": "native-v1"}
            if token:
                headers["Authorization"] = "Bearer " + token
            res = browser.open(path, base_url=url, headers=headers, json=body,
                               method="POST" if body is not None else "GET")
            if res.status_code >= 400:
                raise pair.HTTPError(url, res.status_code, "test", {}, BytesIO())
            if path.endswith("/prepare"):
                attempts.append(res.json["attempt_id"])
            return res.json
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "group.json"
            with self.assertRaises(pair.HTTPError) as failure:
                pair.group_token("https://localhost", server.owner, path, lambda: "000000", call)
            failure.exception.close()
            self.assertTrue(pair.group_token("https://localhost", server.owner, path, lambda: invite, call))
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0], attempts[1])


if __name__ == "__main__":
    unittest.main()
