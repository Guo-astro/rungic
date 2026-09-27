#!/usr/bin/env python3
"""Compare a GKI Module.symvers with every OEM module's version references."""

import argparse
import json
from pathlib import Path
import struct
import sys


def sections(data):
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("expected little-endian ELF64 module")
    offset = struct.unpack_from("<Q", data, 0x28)[0]
    size, count, strings = struct.unpack_from("<HHH", data, 0x3A)
    if size < 64 or offset + size * count > len(data) or strings >= count:
        raise ValueError("invalid ELF section table")
    headers = [struct.unpack_from("<IIQQQQIIQQ", data, offset + size * i)
               for i in range(count)]
    names = data[headers[strings][4]:headers[strings][4] + headers[strings][5]]
    for header in headers:
        name_end = names.find(b"\0", header[0])
        if name_end < 0:
            raise ValueError("invalid ELF section name")
        name = names[header[0]:name_end].decode("ascii")
        start, length = header[4:6]
        if start + length > len(data):
            raise ValueError(f"invalid {name} section bounds")
        yield name, data[start:start + length]


def module_versions(path):
    entries = dict(sections(path.read_bytes()))
    version_data = entries.get("__versions")
    if version_data is None:
        raise ValueError(f"{path}: missing __versions")
    if len(version_data) % 64:
        raise ValueError(f"{path}: invalid __versions length")
    result = {}
    for start in range(0, len(version_data), 64):
        entry = version_data[start:start + 64]
        crc = struct.unpack_from("<I", entry)[0]
        symbol = entry[8:].split(b"\0", 1)[0].decode("ascii")
        if symbol in result:
            raise ValueError(f"{path}: duplicate version for {symbol}")
        result[symbol] = crc
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symvers", type=Path)
    parser.add_argument("modules", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = {}
    for line in args.symvers.read_text().splitlines():
        fields = line.split()
        if len(fields) < 3:
            raise ValueError(f"invalid Module.symvers line: {line}")
        expected[fields[1]] = int(fields[0], 16)
    modules = sorted(args.modules.rglob("*.ko"))
    if not modules:
        raise ValueError("no OEM modules found")
    reports = []
    for module in modules:
        versions = module_versions(module)
        mismatch = {name: {"oem_crc": f"0x{crc:08x}",
                           "built_crc": f"0x{expected[name]:08x}"}
                    for name, crc in versions.items()
                    if name in expected and crc != expected[name]}
        reports.append({"module": str(module.relative_to(args.modules)),
                        "references": len(versions),
                        "matched": sum(name in expected and crc == expected[name]
                                       for name, crc in versions.items()),
                        "unresolved_by_gki": sorted(set(versions) - set(expected)),
                        "mismatch": mismatch})
    report = {"schema_version": 1, "module_count": len(reports),
              "references": sum(item["references"] for item in reports),
              "matched": sum(item["matched"] for item in reports),
              "mismatch_count": sum(len(item["mismatch"]) for item in reports),
              "unresolved_count": sum(len(item["unresolved_by_gki"]) for item in reports),
              "modules": reports}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "modules"}, indent=2))
    if report["mismatch_count"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, struct.error) as error:
        print(f"module ABI check failed: {error}", file=sys.stderr)
        sys.exit(2)
