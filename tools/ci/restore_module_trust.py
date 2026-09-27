#!/usr/bin/env python3
"""Replace an equal-size generated GKI X.509 trust anchor with the OEM anchor."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def x509(data):
    return subprocess.run(["openssl", "x509", "-inform", "DER", "-noout", "-subject"],
                          input=data, capture_output=True, check=True).stdout.decode().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_image", type=Path)
    parser.add_argument("candidate_image", type=Path)
    parser.add_argument("stock_certificate", type=Path)
    parser.add_argument("--certificate-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    stock = args.stock_image.read_bytes()
    image = args.candidate_image.read_bytes()
    cert = args.stock_certificate.read_bytes()
    length = len(cert)
    require(sha256(cert) == args.certificate_sha256, "OEM certificate hash mismatch")
    require(length >= 256 and cert[:2] == b"\x30\x82" and
            int.from_bytes(cert[2:4], "big") + 4 == length, "unsupported OEM DER certificate")
    subject = x509(cert)
    require(stock.count(cert) == 1, "OEM certificate is not unique in stock Image")
    marker = cert[:4]
    require(image.count(marker) == 1, "candidate has no unique equal-length DER certificate")
    offset = image.find(marker)
    previous = image[offset:offset + length]
    require(len(previous) == length and x509(previous) == subject,
            "candidate trust anchor differs in size or subject")
    require(previous != cert, "candidate already contains the OEM certificate")
    output = image[:offset] + cert + image[offset + length:]
    require(len(output) == len(image) and output[:offset] == image[:offset] and
            output[offset + length:] == image[offset + length:], "bytes changed outside certificate")
    require(not args.output.exists(), "refusing to overwrite output")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    report = {"schema_version": 1, "stock_image_sha256": sha256(stock),
              "candidate_image_sha256": sha256(image), "output_image_sha256": sha256(output),
              "stock_certificate_sha256": sha256(cert),
              "replaced_certificate_sha256": sha256(previous),
              "certificate_length": length, "certificate_offset": offset,
              "changed_bytes": sum(a != b for a, b in zip(previous, cert)),
              "certificate_subject": subject,
              "changed_outside_certificate": False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"trust-anchor replacement failed: {error}", file=sys.stderr)
        sys.exit(1)
