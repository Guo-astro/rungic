#!/usr/bin/env python3
"""Fetch an APT --print-uris plan using the SHA256 from apt-cache metadata.

The metadata must come from APT after a successful authenticated update in the
target container. This downloader does not select versions or bypass APT.
"""
import argparse
import concurrent.futures
import hashlib
from pathlib import Path
import shlex
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("uris", type=Path)
parser.add_argument("metadata", type=Path)
parser.add_argument("destination", type=Path)
parser.add_argument("--proxy", default="http://192.168.5.45:6152")
args = parser.parse_args()
hashes = {}
for block in args.metadata.read_text().split("\n\n"):
    fields = dict(line.split(": ", 1) for line in block.splitlines()
                  if ": " in line and not line.startswith(" "))
    if "Filename" in fields and "SHA256" in fields:
        hashes[fields["Filename"]] = fields["SHA256"]
requests = []
for line in args.uris.read_text().splitlines():
    if not line.startswith(("'http://", "'https://")):
        continue
    url, filename, size, _ = shlex.split(line)
    if Path(filename).name != filename:
        raise ValueError("Invalid archive name")
    parsed = urllib.parse.urlsplit(url)
    archive_path = "pool/" + urllib.parse.unquote(parsed.path).split("/pool/", 1)[1]
    expected = hashes[archive_path]
    # Keep the origin and path chosen by APT; use TLS for transport too.
    url = urllib.parse.urlunsplit(parsed._replace(scheme="https"))
    requests.append((url, filename, int(size), expected))
args.destination.mkdir(parents=True, exist_ok=True)


def fetch(item):
    url, filename, size, expected = item
    target = args.destination / filename
    if target.exists() and target.stat().st_size == size and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return filename
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({
        "http": args.proxy, "https": args.proxy,
    }))
    partial = target.with_name(target.name + ".part")
    for attempt in range(3):
        try:
            digest = hashlib.sha256()
            received = 0
            with opener.open(url, timeout=40) as response, partial.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
            if received != size or digest.hexdigest() != expected:
                raise ValueError("Archive checksum/size mismatch: " + filename)
            partial.replace(target)
            return filename
        except Exception:
            partial.unlink(missing_ok=True)
            if attempt == 2:
                raise


with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
    pending = [pool.submit(fetch, item) for item in requests]
    for count, future in enumerate(concurrent.futures.as_completed(pending), 1):
        future.result()
        if count % 50 == 0 or count == len(requests):
            print(f"Verified {count}/{len(requests)} archives", flush=True)
