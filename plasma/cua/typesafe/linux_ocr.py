"""Text recognition for the Linux adapter (docs/64).

The phone's Android side runs PP-OCRv6 Small on its GPU (LiteRT, the APK's OcrBridge) and answers
over the platform bridge; this module sends it the capture's pixels: about 0.5 s for the whole
phone screen. PP-OCRv5 mobile on the Linux CPU (RapidOCR on onnxruntime, about 2 s) is the fallback
when the bridge cannot answer.

Request (platform.sock): one JSON line {"op": "ocr", "width", "height", "format": "rgb", "bytes",
"det_scale"} followed by the raw RGB pixels, row by row. Reply: one JSON line {"lines": [{"text",
"score", "box": [x1, y1, x2, y2]}], "ms": {...}} in the image's own pixels, or {"error": ...}.
The detector reads text best at about 1.5 image pixels per screen point, hence det_scale.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time

from PIL import Image

SOCKET = os.environ.get("MOTO_PLATFORM_SOCKET", "/mnt/android-wayland/platform.sock")
TIMEOUT = 20.0
ENGINE = os.environ.get("MOTO_OCR", "android")  # android | local
DET_PIXELS_PER_POINT = 1.5

Line = tuple[str, float, tuple[float, float, float, float]]
_local = None


def recognize(image: Image.Image, scale: float = 1.0) -> list[Line]:
    """Lines of text in `image`, whose `scale` is its pixels per screen point."""
    if ENGINE == "android":
        try:
            return android(image, min(1.0, DET_PIXELS_PER_POINT / scale))
        except (OSError, ValueError, RuntimeError) as e:
            print(f"android OCR unavailable ({e}); reading on the CPU", file=sys.stderr)
    return local(image)


def android(image: Image.Image, det_scale: float) -> list[Line]:
    rgb = image.convert("RGB")
    data = rgb.tobytes()
    header = {"op": "ocr", "width": rgb.width, "height": rgb.height, "format": "rgb", "bytes": len(data),
              "det_scale": round(det_scale, 4)}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(TIMEOUT)
        conn.connect(SOCKET)
        conn.sendall(json.dumps(header).encode() + b"\n" + data)
        reply = b""
        while not reply.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            reply += chunk
    result = json.loads(reply)
    if "error" in result:
        raise RuntimeError(result["error"])
    return [(ln["text"], float(ln["score"]), tuple(float(v) for v in ln["box"])) for ln in result["lines"]]


def local(image: Image.Image) -> list[Line]:
    global _local
    if _local is None:
        from rapidocr import ModelType, OCRVersion, RapidOCR

        _local = RapidOCR(
            params={
                "Global.use_cls": False,
                "Global.log_level": "error",
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Det.model_type": ModelType.MOBILE,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
                "EngineConfig.onnxruntime.intra_op_num_threads": 4,
            }
        )
    started = time.monotonic()
    result = _local(image.convert("RGB"))
    out: list[Line] = []
    for box, text, score in zip(result.boxes if result.boxes is not None else [], result.txts or (), result.scores or (), strict=False):
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        out.append((text, float(score), (min(xs), min(ys), max(xs), max(ys))))
    print(f"local OCR {time.monotonic() - started:.2f}s, {len(out)} lines", file=sys.stderr)
    return out
