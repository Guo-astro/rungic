#!/usr/bin/env python3
"""Compile and exercise the shared production policy, including resolution roundtrip drift."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DisplayPolicy(unittest.TestCase):
    def test_shared_policy(self):
        source = r'''
#include "shared/display-policy/handset-scale.h"
#include <cassert>
#include <limits>
#include <iostream>
using namespace Rungic::Display;
int main() {
    const double nativeDpi = renderDpi(1264, 2780, 72, 157);
    const double lowDpi = renderDpi(720, 1584, 72, 157);
    const auto native = range(1264, nativeDpi);
    assert(sameScale(native.recommended, 3.5));
    assert(sameScale(native.minimum, 3.0));
    assert(sameScale(native.maximum, 3.95));
    assert(1264 / native.maximum >= 320);
    assert(sameScale(range(720, lowDpi).recommended, 2.0));
    assert(renderDpi(2780, 1264, 157, 72) == nativeDpi);
    assert(sameScale(range(1080, renderDpi(1080, 2400, 72, 157)).recommended, 3.0));
    // Same physical panel: same logical density produces the same physical size at either mode.
    assert(std::abs(1264 / effectiveScale(nativeDpi, 128) - 720 / effectiveScale(lowDpi, 128)) < 1.5);
    for (double mm : {0., -1., 10000., std::numeric_limits<double>::quiet_NaN()}) {
        const double dpi = renderDpi(1264, 2780, mm, mm);
        assert(validDensity(dpi));
        assert(std::abs(1264 / range(1264, dpi).recommended - 360) < 2);
    }
    assert(!validScale(std::numeric_limits<double>::quiet_NaN()));
    assert(!validScale(std::numeric_limits<double>::infinity()));
    assert(!validScale(0)); assert(!validScale(-1)); assert(!validScale(5.01));
    assert(validScale(0.5)); assert(validScale(5)); assert(!validDensity(0));
    // Preserve custom settings too, not just the new recommended value.
    for (int step = 120; step <= 600; ++step) {
        const double original = step / 120.;
        const double density = nativeDpi / original;
        double saved = density, scale = original;
        for (int cycle = 0; cycle < 100; ++cycle) {
            const double low = effectiveScale(lowDpi, saved);
            saved = requestedDensity(nativeDpi, lowDpi, scale, low, saved, true);
            scale = low;
            const double high = effectiveScale(nativeDpi, saved);
            saved = requestedDensity(lowDpi, nativeDpi, scale, high, saved, true);
            scale = high;
        }
        assert(saved == density);
        assert(sameScale(scale, original));
    }
    // Mode-only requests from standard clients need the same compensation as the GUI.
    const double old = nativeDpi / 3.0;
    assert(requestedDensity(nativeDpi, lowDpi, 3, 3, old, true) == old);
    // User size change at the same mode must not be mistaken for a default or overwritten.
    assert(requestedDensity(nativeDpi, nativeDpi, 3, 3.75, old, false) == nativeDpi / 3.75);
    assert(requestedDensity(nativeDpi, nativeDpi, 3, 3, 0, false) == old);
    // Reapplying a rounded low-resolution scale must retain the exact saved intent.
    const double low = effectiveScale(lowDpi, old);
    assert(requestedDensity(lowDpi, lowDpi, low, low, old, false) == old);
    std::cout << "policy: native/720, rotation, fallback, custom values, 48100 roundtrips passed\n";
}
'''
        parent = ROOT / '.work/tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='display-policy-', dir=parent) as directory:
            directory = pathlib.Path(directory)
            cpp = directory / 'test.cpp'
            exe = directory / 'test'
            cpp.write_text(source)
            subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT), str(cpp), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
