// SPDX-License-Identifier: MIT
#pragma once
#include <algorithm>
#include <array>
#include <cmath>

namespace Rungic::Display
{
// A logical density describes the user's physical UI size, independently of render resolution.
// Keep this value unrounded; only the effective Wayland scale is quantized to 1/120.
struct Policy {
    double targetDpi = 128;
    double compactDpi = 150;
    double minimumLogicalEdge = 320;
    double fallbackLogicalEdge = 360;
};
constexpr double minimumScale = 0.5;
constexpr double maximumScale = 5.0; // also accepted by KWin's persisted configuration reader
inline bool validScale(double value) { return std::isfinite(value) && value >= minimumScale && value <= maximumScale; }
inline bool validDensity(double value) { return std::isfinite(value) && value > 0 && value < 10000; }
inline double quantize(double value) { return std::round(value * 120.0) / 120.0; }
inline bool sameScale(double a, double b) { return std::abs(a - b) < 1.0 / 240.0; }
inline double shortEdge(double width, double height) { return std::min(width, height); }
inline double renderDpi(double width, double height, double mmWidth, double mmHeight, const Policy &p = {})
{
    const double edge = shortEdge(width, height);
    const double mm = shortEdge(mmWidth, mmHeight);
    // Reject implausible handset metadata. Fallback preserves a usable handset layout.
    if (edge <= 0 || !std::isfinite(edge)) return 0;
    if (!std::isfinite(mm) || mm < 35 || mm > 200) return edge * p.targetDpi / p.fallbackLogicalEdge;
    return edge * 25.4 / mm;
}
inline double effectiveScale(double dpi, double logicalDpi)
{
    return validDensity(dpi) && validDensity(logicalDpi) ? quantize(dpi / logicalDpi) : 0;
}
struct Range { double recommended; double minimum; double maximum; };
inline Range range(double edge, double dpi, const Policy &p = {})
{
    const double hi = std::clamp(std::floor(edge / p.minimumLogicalEdge * 20.0) / 20.0, minimumScale, maximumScale);
    const double lo = std::clamp(std::ceil(dpi / p.compactDpi * 20.0) / 20.0, minimumScale, hi);
    const double preferred = std::clamp(std::round(dpi / p.targetDpi * 20.0) / 20.0, lo, hi);
    return {preferred, lo, hi};
}
inline std::array<double, 5> presets(double edge, double dpi, double nativeEdge, const Policy &p = {})
{
    if (!(edge > 0) || !validDensity(dpi) || !std::isfinite(nativeEdge)) return {1, 1, 1, 1, 1};
    nativeEdge = std::max(edge, nativeEdge);
    const auto native = range(nativeEdge, dpi * nativeEdge / edge, p);
    const auto half = [](double a, double b) { return std::round((a + b) * 10) / 20; };
    std::array<double, 5> values{native.minimum, half(native.minimum, native.recommended), native.recommended,
                                 half(native.recommended, native.maximum), native.maximum};
    for (auto &value : values) value = quantize(value * edge / nativeEdge);
    return values;
}
// Explicit scale changes set a new preference. A mode-only request, or a client's rounded
// compensation of the old preference, keeps its original unrounded density (no roundtrip drift).
inline double requestedDensity(double oldDpi, double newDpi, double currentScale, double requestedScale,
                               double savedDensity, bool modeChanged)
{
    const double previous = validDensity(savedDensity) ? savedDensity : oldDpi / currentScale;
    if (sameScale(requestedScale, effectiveScale(newDpi, previous))
        || (modeChanged && sameScale(requestedScale, currentScale))) return previous;
    return newDpi / requestedScale;
}
}
