"""Version-format regressions for Android 15/16 OEM module auditing."""

from pathlib import Path
import struct
import unittest
from unittest.mock import patch

import module_abi


class ModuleVersionsTest(unittest.TestCase):
    def test_nobits_does_not_require_file_payload(self):
        # A large .bss is legal even when sh_offset + sh_size is beyond EOF.
        data = bytearray(64 + 3 * 64 + 32)
        data[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<Q", data, 0x28, 64)
        struct.pack_into("<HHH", data, 0x3a, 64, 3, 1)
        names = b"\0.shstrtab\0.bss\0"
        data[256:256 + len(names)] = names
        struct.pack_into("<IIQQQQIIQQ", data, 128, 1, 3, 0, 0, 256, len(names), 0, 0, 1, 0)
        struct.pack_into("<IIQQQQIIQQ", data, 192, 11, 8, 0, 0, 288, 8192, 0, 0, 8, 0)
        self.assertEqual(dict(module_abi.sections(bytes(data)))[".bss"], b"")

    def parse(self, entries):
        with patch.object(Path, "read_bytes", return_value=b"fixture"), \
                patch.object(module_abi, "sections", return_value=entries.items()):
            return module_abi.module_versions(Path("fixture.ko"))

    def test_legacy_android15(self):
        data = struct.pack("<Q56s", 0x12345678, b"module_layout")
        self.assertEqual(self.parse({"__versions": data}), {"module_layout": 0x12345678})

    def test_extended_long_rust_name_and_c_terminator(self):
        name = "_RNv" + "long_rust_symbol" * 8
        self.assertEqual(self.parse({
            "__version_ext_crcs": struct.pack("<II", 0x12345678, 0x90abcdef),
            "__version_ext_names": name.encode() + b"\0module_layout\0\0",
        }), {name: 0x12345678, "module_layout": 0x90abcdef})

    def test_extended_takes_precedence_like_kernel(self):
        self.assertEqual(self.parse({
            "__versions": struct.pack("<Q56s", 1, b"symbol"),
            "__version_ext_crcs": struct.pack("<I", 2),
            "__version_ext_names": b"symbol\0",
        }), {"symbol": 2})

    def test_reject_malformed_extended(self):
        cases = [
            {"__version_ext_crcs": b"1234"},
            {"__version_ext_names": b"symbol\0"},
            {"__version_ext_crcs": b"123", "__version_ext_names": b"symbol\0"},
            {"__version_ext_crcs": b"1234", "__version_ext_names": b"symbol"},
            {"__version_ext_crcs": b"12345678", "__version_ext_names": b"symbol\0\0"},
            {"__version_ext_crcs": b"1234", "__version_ext_names": b"one\0two\0"},
            {"__version_ext_crcs": b"12345678", "__version_ext_names": b"one\0one\0"},
        ]
        for entries in cases:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.parse(entries)


if __name__ == "__main__":
    unittest.main()
