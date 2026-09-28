"""Reject wrong-device and incomplete Motorola archives before extraction."""

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

import prepare_g100_stock as stock


class StockIdentityTest(unittest.TestCase):
    def setUp(self):
        work = Path(__file__).resolve().parents[1] / ".work/tests"
        work.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, vantage=True, extra=False, corrupt=False):
        identity = ({"model": "XT2603-1", "device": "vantage_cn", "build": "W2WV36.55-75-15",
                     "fingerprint": "motorola/vantage_cn/vantage:16/W2WV36.55-75-15/0a2efa-422586:user/release-keys",
                     "info_name": "vantage.info.txt", "super_count": 1} if vantage else
                    {"model": "XT2533-4", "device": stock.MODEL, "build": stock.BUILD,
                     "fingerprint": stock.FINGERPRINT, "info_name": stock.INFO_NAME,
                     "super_count": stock.SUPER_COUNT})
        sparse = struct.pack("<I4H4I", 0xED26FF3A, 1, 0, 28, 12, 4096, 1, 0, 0)
        files = {f"super.img_sparsechunk.{i}": sparse for i in range(identity["super_count"])}
        if extra:
            files[f"super.img_sparsechunk.{identity['super_count']}"] = sparse
        incremental = identity["fingerprint"].split("/")[4].split(":")[0]
        steps = "".join(f'<step filename="{name}" MD5="{hashlib.md5(data).hexdigest()}"/>'
                        for name, data in files.items())
        xml = (f'<flashing><header><phone_model model="{identity["device"]}"/>'
               f'<software_version version="{identity["device"]}-user 16 {identity["build"]} '
               f'{incremental} release-keys"/></header><steps>{steps}</steps></flashing>')
        with zipfile.ZipFile(self.root / "stock.zip", "w") as z:
            z.writestr(identity["info_name"], f'Build Fingerprint: {identity["fingerprint"]}\n'
                       f'Model Number: {identity["model"]}\n')
            z.writestr("flashfile.xml", xml)
            z.writestr("servicefile.xml", xml)
            for name, data in files.items():
                z.writestr(name, data + (b"corrupt" if corrupt else b""))
        (self.root / "identity.json").write_text(json.dumps(identity))
        simg = self.root / "simg2img"
        simg.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\n'
                        'Path(sys.argv[-1]).write_bytes(bytes(4096))\n')
        simg.chmod(0o755)

    def run_tool(self, override=True):
        cmd = [sys.executable, stock.__file__, str(self.root / "stock.zip"),
               str(self.root / "out"), "--simg2img", str(self.root / "simg2img")]
        if override:
            cmd += ["--identity", str(self.root / "identity.json")]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_g100_default_still_works(self):
        self.fixture(vantage=False)
        result = self.run_tool(override=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_vantage_identity(self):
        self.fixture()
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_rejects_vantage(self):
        self.fixture()
        self.assertNotEqual(self.run_tool(override=False).returncode, 0)
        self.assertFalse((self.root / "out.partial").exists())

    def test_extra_chunk_rejected_before_extraction(self):
        self.fixture(extra=True)
        self.assertNotEqual(self.run_tool().returncode, 0)
        self.assertFalse((self.root / "out.partial").exists())

    def test_xml_digest_mismatch_never_published(self):
        self.fixture(corrupt=True)
        self.assertNotEqual(self.run_tool().returncode, 0)
        self.assertFalse((self.root / "out").exists())


if __name__ == "__main__":
    unittest.main()
