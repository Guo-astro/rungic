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
    const auto nativePresets = presets(1264, nativeDpi, 1264);
    const auto lowPresets = presets(720, lowDpi, 1264);
    assert(sameScale(nativePresets[2], 3.5));
    assert(sameScale(lowPresets[2], effectiveScale(lowDpi, nativeDpi / 3.5)));
    for (int i = 0; i < 5; ++i) {
        assert(std::abs(1264 / nativePresets[i] - 720 / lowPresets[i]) < 1.5);
    }
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
    // Android density is logical DPI; its reference pixels must not be the 720 render buffer.
    struct Example { double edge, density, expected; };
    for (auto test : {Example{1080,390,3}, {1264,480,3.5}, {1440,560,4},
                      {1440,480,3.75}, {720,320,2}, {1600,320,2.5}}) {
        const AndroidReference android{test.density, test.edge};
        // Deliberately inconsistent physical DPI: valid Android metadata takes precedence.
        auto sizes = presets(test.edge, 200, test.edge, {}, android);
        assert(sameScale(sizes[2], test.expected));
        assert(test.edge / sizes[2] >= 360);
        auto reduced = presets(720, 200*720/test.edge, test.edge, {}, android);
        assert(std::abs(test.edge / sizes[2] - 720 / reduced[2]) < 2);
        assert(720 / reduced[2] >= 360);
    }
    const AndroidReference x70{480,1264};
    assert(sameScale(presets(720, lowDpi, 1264, {}, x70)[2], 239.0/120));
    assert(sameScale(presets(1264, nativeDpi, 1264, {}, {320,1264})[2], 2.5));
    // wm size / system resolution uses the paired reference, not the maximum panel mode.
    assert(sameScale(presets(1440, 400, 1440, {}, {320,1080})[2], 3.35));
    for (AndroidReference invalid : {AndroidReference{}, {480,0}, {0,1264}, {-1,1264},
                                     {480,std::numeric_limits<double>::infinity()},
                                     {std::numeric_limits<double>::quiet_NaN(),1264}}) {
        assert(!invalid.valid());
        assert(sameScale(presets(1264, nativeDpi, 1264, {}, invalid)[2], 3.5));
    }
    // Density candidates at the layout boundary may round up: defaults must never do so.
    for (int edge=720; edge<=2000; ++edge) {
        const auto sizes=presets(edge,450,edge,{}, {640,double(edge)});
        const auto low=presets(720,450*720.0/edge,edge,{}, {640,double(edge)});
        assert(edge/sizes[2] >= 360-1e-8 && 720/low[2] >= 360-1e-8);
        assert(validScale(sizes[2]) && validScale(low[2]));
    }
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
