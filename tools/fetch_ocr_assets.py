#!/usr/bin/env python3
"""Fetch the APK's OCR runtime and models (docs/64) into .work/cache/ocr and stage them.

Downloads the files pinned in provenance/ocr-20260925/sources.json (verifying SHA-256), then
writes OUT/lib/arm64-v8a/libLiteRt*.so and OUT/assets/ocr/{det,rec_*}.tflite, classes.txt.
Uses $https_proxy if set; retries through http://192.168.5.45:6152 otherwise.

  tools/fetch_ocr_assets.py OUT
"""
import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "provenance/ocr-20260925/sources.json"
CACHE = ROOT / ".work/cache/ocr"
PROXY = "http://192.168.5.45:6152"


def download(url: str, path: Path) -> None:
    for proxy in ([os.environ["https_proxy"]] if os.environ.get("https_proxy") else []) + [None, PROXY]:
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})]
        try:
            with urllib.request.build_opener(*handlers).open(url, timeout=600) as response:
                path.write_bytes(response.read())
            return
        except OSError as error:
            print(f"{url}: {error} (proxy {proxy})", file=sys.stderr)
    raise SystemExit(f"could not download {url}")


def fetch() -> dict[str, Path]:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, entry in json.loads(SOURCES.read_text())["files"].items():
        path = CACHE / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            download(entry["url"], path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                path.unlink()
                raise SystemExit(f"{name}: SHA-256 mismatch")
        out[name] = path
    return out


def main() -> None:
    out = Path(sys.argv[1])
    files = fetch()
    lib = out / "lib/arm64-v8a"
    assets = out / "assets/ocr"
    lib.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(files["litert-2.2.0.aar"]) as aar:
        for so in ("libLiteRt.so", "libLiteRtClGlAccelerator.so"):
            (lib / so).write_bytes(aar.read(f"jni/arm64-v8a/{so}"))
    for name in ("det.tflite", "rec_320.tflite", "rec_640.tflite", "rec_960.tflite"):
        shutil.copyfile(files[name], assets / name)
    classes = json.loads(files["characters.json"].read_text(encoding="utf-8"))
    assert all("\n" not in c for c in classes)
    (assets / "classes.txt").write_text("\n".join(classes) + "\n", encoding="utf-8")
    shutil.copyfile(files["LICENSE-PP-OCRv6-Small-LiteRT"], assets / "LICENSE")
    print(f"staged {lib} and {assets}")


if __name__ == "__main__":
    main()
