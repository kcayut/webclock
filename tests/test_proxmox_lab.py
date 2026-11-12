"""Exercise the host script with fake infrastructure; never contacts Proxmox."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "tools/create_proxmox_lab.sh"
MOCK = r'''
import hashlib, json, lzma, os, pathlib, sys, tempfile
cmd = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ["LAB_TEST_ROOT"])
scenario = os.environ.get("LAB_TEST_SCENARIO", "")
with (root / "calls").open("a") as f:
    f.write(json.dumps([cmd] + args) + "\n")
payload = b"test-image"
archive = lzma.compress(payload)
if cmd == "id": print(0)
elif cmd == "uname": print("x86_64")
elif cmd in ("ip", "ssh-keygen"): pass
elif cmd == "pvesm": print("Name Type Status Total Used Available %\nlocal-lvm lvmthin active 100 0 100 0")
elif cmd == "pvesh":
    print(json.dumps([{"vmid": 982, "type": "lxc"}] if scenario == "collision" else []))
elif cmd == "mktemp": print(tempfile.mkdtemp(dir=root))
elif cmd == "curl":
    url = args[args.index("-o") - 1]
    target = pathlib.Path(args[args.index("-o") + 1])
    if "api.github.com" in url:
        digest = "sha256:" + hashlib.sha256(archive).hexdigest()
        if scenario == "missing_digest": digest = None
        data = json.dumps({"tag_name": "test", "assets": [{
            "name": "haos_ova-test.qcow2.xz", "digest": digest,
            "browser_download_url": "https://github.com/home-assistant/operating-system/releases/download/test/haos_ova-test.qcow2.xz"
        }]}).encode()
    elif url.endswith(".xz"): data = archive
    elif url.endswith("SHA256SUMS"):
        digest = "0" * 64 if scenario == "bad_hash" else hashlib.sha256(payload).hexdigest()
        data = (digest + " *ubuntu-24.04-server-cloudimg-amd64.img\n").encode()
    elif url.endswith("/ubuntu-24.04-server-cloudimg-amd64.img"): data = payload
    else: sys.exit("unexpected download URL: " + url)
    target.write_bytes(data)
elif cmd == "sha256sum":
    digest, filename = sys.stdin.read().strip().split(None, 1)
    sys.exit(0 if hashlib.sha256(pathlib.Path(filename).read_bytes()).hexdigest() == digest else 1)
elif cmd == "xz":
    p = pathlib.Path(args[-1]); p.with_suffix("").write_bytes(lzma.decompress(p.read_bytes())); p.unlink()
elif cmd == "qemu-img": print(json.dumps({"format": "qcow2", "virtual-size": 1024**3}))
elif cmd == "qm":
    if scenario == "import_failure" and args[:2] == ["importdisk", "982"]: sys.exit(1)
    if args[0] == "config": print("unused0: local-lvm:vm-" + args[1] + "-disk-0")
else: sys.exit("unexpected mock: " + cmd)
'''


class ProxmoxLabTests(unittest.TestCase):
    def run_lab(self, scenario="", extra=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock = root / "mock"
            mock.write_text(f"#!{sys.executable}\n" + MOCK)
            mock.chmod(0o755)
            for name in ("id", "uname", "qm", "pvesh", "pvesm", "ip", "curl",
                         "xz", "sha256sum", "ssh-keygen", "qemu-img", "mktemp"):
                (root / name).symlink_to(mock)
            # The key parser is mocked; no actual identity or infrastructure is used.
            key = root / "key.pub"
            key.write_text("fixture-public-key\n")
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                       LAB_TEST_ROOT=str(root), LAB_TEST_SCENARIO=scenario)
            result = subprocess.run(["bash", str(SCRIPT), "--ssh-key", str(key), *extra],
                                    env=env, text=True, errors="backslashreplace", capture_output=True)
            log = root / "calls"
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_three_hosts_configured_before_any_start(self):
        result, calls = self.run_lab()
        self.assertEqual(result.returncode, 0, result.stderr)
        creates = [c for c in calls if c[:2] == ["qm", "create"]]
        self.assertEqual([c[2] for c in creates], ["981", "982", "983"])
        starts = [c for c in calls if c[:2] == ["qm", "start"]]
        self.assertEqual(starts, [["qm", "start", str(i)] for i in range(981, 984)])
        first_start = next(i for i, c in enumerate(calls) if c[:2] == ["qm", "start"])
        self.assertTrue(all(i < first_start for i, c in enumerate(calls) if c[:2] == ["qm", "set"]))
        self.assertTrue(any("local-lvm:1,efitype=4m,pre-enrolled-keys=0" in c for c in calls))
        self.assertEqual(sum("--sshkeys" in c and "ip=dhcp" in c for c in calls), 2)

    def test_existing_lxc_id_stops_before_download_or_mutation(self):
        result, calls = self.run_lab("collision")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("982", result.stderr)
        self.assertFalse(any(c[0] in ("curl", "qm") for c in calls))

    def test_hash_or_digest_failure_never_creates_vm(self):
        for scenario in ("missing_digest", "bad_hash"):
            with self.subTest(scenario=scenario):
                result, calls = self.run_lab(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[0] == "qm" for c in calls))

    def test_partial_failure_keeps_vms_and_starts_none(self):
        result, calls = self.run_lab("import_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("保留 VM", result.stderr)
        self.assertFalse(any(c[:2] in (["qm", "destroy"], ["qm", "start"]) for c in calls))

    def test_invalid_id_is_rejected_before_external_commands(self):
        result, calls = self.run_lab(extra=("--base-id", "999999999"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
