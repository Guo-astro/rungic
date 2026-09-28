#!/usr/bin/env python3
"""Verify and unpack a pinned Motorola factory archive (G100 by default).

This only creates host-side files. It never connects to or flashes a phone.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib


MODEL = "portov_cn"
BUILD = "W1VT36H.1-51-8"
FINGERPRINT = f"motorola/portov_cn/portov:16/{BUILD}/e9ec8-e96731:user/release-keys"
INFO_NAME = "PORTOV_CN_W1VT36H.1-51-8_subsidy-DEFAULT_regulatory-DEFAULT_CFC.info.txt"
SUPER_COUNT = 32
BLOCK = 8 * 1024 * 1024


def digest(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(BLOCK), b""):
            h.update(chunk)
    return h.hexdigest()


def xml_metadata(data: bytes) -> tuple[str, str, dict[str, str]]:
    root = ET.fromstring(data)
    model = root.find("./header/phone_model")
    software = root.find("./header/software_version")
    if model is None or software is None:
        raise ValueError("Missing firmware identity in XML")
    checksums = {}
    for step in root.findall("./steps/step"):
        name = step.get("filename")
        md5 = step.get("MD5")
        if name:
            if not md5 or not re.fullmatch(r"[0-9a-fA-F]{32}", md5):
                raise ValueError(f"Missing or invalid XML MD5 for {name}")
            old = checksums.setdefault(name, md5.lower())
            if old != md5.lower():
                raise ValueError(f"Conflicting XML MD5 for {name}")
    return model.get("model", ""), software.get("version", ""), checksums


def sparse_size(path: Path) -> int:
    with path.open("rb") as stream:
        header = stream.read(28)
    if len(header) != 28:
        raise ValueError(f"Truncated sparse header: {path.name}")
    magic, major, _minor, file_header, chunk_header, block_size, blocks, _chunks, _checksum = struct.unpack(
        "<I4H4I", header
    )
    if magic != 0xED26FF3A or major != 1 or file_header < 28 or chunk_header < 12 or block_size != 4096:
        raise ValueError(f"Unexpected sparse format: {path.name}")
    return block_size * blocks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--simg2img", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="Recheck files in an existing .partial directory")
    parser.add_argument("--identity", type=Path,
                        help="Audited JSON: model, device, build, fingerprint, info_name, super_count")
    args = parser.parse_args()

    identity = {"model": "XT2533-4", "device": MODEL, "build": BUILD,
                "fingerprint": FINGERPRINT, "info_name": INFO_NAME, "super_count": SUPER_COUNT}
    if args.identity:
        identity = json.loads(args.identity.read_text())
    for key in ("model", "device", "build", "fingerprint", "info_name"):
        if not isinstance(identity.get(key), str) or not identity[key].strip():
            raise ValueError(f"Missing pinned identity field: {key}")
    count = identity.get("super_count")
    if type(count) is not int or count < 1:
        raise ValueError("super_count must be a positive integer")
    fingerprint = identity["fingerprint"]
    match = re.fullmatch(r"motorola/([^/]+)/([^:]+):([^/]+)/([^/]+)/([^:]+):user/release-keys", fingerprint)
    if not match or match[1] != identity["device"] or match[4] != identity["build"]:
        raise ValueError("Pinned fingerprint does not match device/build")
    software_prefix = f"{identity['device']}-user {match[3]} {identity['build']} {match[5]} release-keys"

    archive = args.archive.resolve(strict=True)
    output = args.output.resolve()
    staging = output.with_name(output.name + ".partial")
    if output.exists() or (staging.exists() and not args.resume):
        raise SystemExit(f"Refusing to overwrite {output} or {staging}")
    if not args.simg2img.is_file():
        raise SystemExit(f"Missing simg2img: {args.simg2img}")

    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        if len(names) != len(set(names)) or not names or any(
            name in ("", ".", "..") or "/" in name or "\\" in name for name in names
        ):
            raise ValueError("Archive contains duplicate or unsafe entry names")
        if identity["info_name"] not in names or "flashfile.xml" not in names or "servicefile.xml" not in names:
            raise ValueError("Missing required firmware metadata")
        info = zipped.read(identity["info_name"]).decode("utf-8")
        if (f"Build Fingerprint: {fingerprint}" not in info.splitlines() or
                f"Model Number: {identity['model']}" not in info.splitlines()):
            raise ValueError("Firmware info does not match the pinned identity")
        flash_model, flash_software, flash_md5 = xml_metadata(zipped.read("flashfile.xml"))
        service_model, service_software, service_md5 = xml_metadata(zipped.read("servicefile.xml"))
        for model, software in ((flash_model, flash_software), (service_model, service_software)):
            if model != identity["device"] or not (software == software_prefix or software.startswith(software_prefix + " ")):
                raise ValueError("XML firmware identity does not match the pinned identity")
        if flash_md5 != service_md5 or not set(flash_md5).issubset(names):
            raise ValueError("Flash/service file lists or archive members differ")
        expected_chunks = {f"super.img_sparsechunk.{i}" for i in range(count)}
        if {n for n in names if n.startswith("super.img_sparsechunk.")} != expected_chunks:
            raise ValueError("Super chunk set differs from pinned count")
        for index in range(count):
            if f"super.img_sparsechunk.{index}" not in flash_md5:
                raise ValueError(f"Missing super chunk {index}")

        staging.mkdir(parents=True, exist_ok=args.resume)
        manifest = {
            "model": identity["model"],
            "device": identity["device"],
            "build": identity["build"],
            "fingerprint": fingerprint,
            "archive_identity": identity,
            "source_archive": str(archive),
            "archive_bytes": archive.stat().st_size,
            "files": {},
            "flashed": False,
            "device_tested": False,
        }
        for position, member in enumerate(zipped.infolist(), 1):
            name = member.filename
            destination = staging / name
            sha = hashlib.sha256()
            md5 = hashlib.md5()
            size = 0
            crc = 0
            if args.resume and destination.is_file() and destination.stat().st_size == member.file_size:
                source = destination.open("rb")
                target = None
            else:
                source = zipped.open(member)
                target = destination.open("wb")
            try:
                for chunk in iter(lambda: source.read(BLOCK), b""):
                    if target is not None:
                        target.write(chunk)
                    sha.update(chunk)
                    md5.update(chunk)
                    crc = zlib.crc32(chunk, crc)
                    size += len(chunk)
            finally:
                source.close()
                if target is not None:
                    target.close()
            if (size != member.file_size or crc != member.CRC or
                    (name in flash_md5 and md5.hexdigest() != flash_md5[name])):
                raise ValueError(f"Size, ZIP CRC, or XML MD5 mismatch: {name}")
            manifest["files"][name] = {"bytes": size, "md5": md5.hexdigest(), "sha256": sha.hexdigest()}
            print(f"[{position}/{len(names)}] verified {name}", flush=True)

    manifest["archive_sha256"] = digest(archive)
    chunks = [staging / f"super.img_sparsechunk.{index}" for index in range(count)]
    super_sizes = {sparse_size(chunk) for chunk in chunks}
    if len(super_sizes) != 1:
        raise ValueError("Super chunks declare different logical partition sizes")
    expected_super_size = super_sizes.pop()
    super_raw = staging / "super.raw.img"
    if not (args.resume and super_raw.is_file() and super_raw.stat().st_size == expected_super_size):
        subprocess.run([str(args.simg2img.resolve(strict=True)), *(str(chunk) for chunk in chunks), str(super_raw)], check=True)
    if super_raw.stat().st_size != expected_super_size:
        raise ValueError("Assembled super size differs from sparse headers")
    manifest["files"][super_raw.name] = {
        "bytes": expected_super_size,
        "sha256": digest(super_raw),
        "derived_from": [chunk.name for chunk in chunks],
    }
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(output)
    print(f"Verified stock image set: {output}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
