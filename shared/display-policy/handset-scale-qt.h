// SPDX-License-Identifier: MIT
#pragma once
#include "handset-scale.h"
#include <QSettings>
#include <QSize>
#include <QString>

namespace Rungic::Display
{
inline Policy policy()
{
    // System policy only; user size stays in KWin's output configuration.
    QSettings settings(QStringLiteral("/etc/xdg/rungic-display-policyrc"), QSettings::IniFormat);
    Policy p;
    settings.beginGroup(QStringLiteral("Handset"));
    const auto checked = [&](const char *key, double fallback, double low, double high) {
        const double value = settings.value(QString::fromLatin1(key), fallback).toDouble();
        return std::isfinite(value) && value >= low && value <= high ? value : fallback;
    };
    p.targetDpi = checked("TargetLogicalDpi", p.targetDpi, 96, 180);
    p.compactDpi = checked("CompactLogicalDpi", p.compactDpi, p.targetDpi, 220);
    p.minimumLogicalEdge = checked("MinimumLogicalEdge", p.minimumLogicalEdge, 280, 480);
    p.fallbackLogicalEdge = checked("FallbackLogicalEdge", p.fallbackLogicalEdge, p.minimumLogicalEdge, 600);
    return p;
}
inline bool isHandset(const QString &manufacturer, const QString &model)
{
    return manufacturer == QLatin1String("Rungic") && model == QLatin1String("Handset");
}
inline double dpi(const QSize &pixels, const QSize &mm, const Policy &p = policy())
{
    return renderDpi(pixels.width(), pixels.height(), mm.width(), mm.height(), p);
}
inline Range range(const QSize &pixels, const QSize &mm)
{
    const auto p = policy();
    return range(shortEdge(pixels.width(), pixels.height()), dpi(pixels, mm, p), p);
}
}
