#!/usr/bin/env python3
"""Assemble the pinned Android host and its separately maintained dependencies in .work.

Edit upstream changes with pq.py prepare/export android-host or smithay. Rungic-only
modules live in plasma/android-host and enter through the android-host recipe's overlay.
This command only prepares source; it does not build, install or contact a device.
"""
import argparse
from pathlib import Path

import pq


def prepare(output=None):
    output = Path(output or pq.WORKSPACE / '.work/build/android-host/source').resolve()
    work = (pq.WORKSPACE / '.work').resolve()
    if output == work or not output.is_relative_to(work):
        raise SystemExit('Android host sources must be prepared inside .work')
    pq.source('android-host', output)
    for name in ('smithay', 'winit'):
        pq.source(name, output / 'lib' / name)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output')
    print(prepare(parser.parse_args().output))
