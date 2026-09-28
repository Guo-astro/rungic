// SPDX-License-Identifier: MIT
#pragma once
#include "handset-scale.h"
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
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
    p.androidSizeMultiplier = checked("AndroidSizeMultiplier", p.androidSizeMultiplier, 1, 2);
    p.minimumDefaultLogicalEdge = checked("MinimumDefaultLogicalEdge", p.minimumDefaultLogicalEdge, 360, 600);
    p.minimumLogicalEdge = checked("MinimumLogicalEdge", p.minimumLogicalEdge, 280, 480);
    p.fallbackLogicalEdge = checked("FallbackLogicalEdge", p.fallbackLogicalEdge, p.minimumLogicalEdge, 600);
    return p;
}
// Read-only additive host metadata; settings requests still use standard libkscreen.
// Missing/old APK metadata falls back to physical dimensions, never to densityDpi=160.
inline AndroidReference androidReference()
{
    QFile file(QStringLiteral("/mnt/android-wayland/android-display.json"));
    if (!file.open(QIODevice::ReadOnly)) return {};
    const auto info = QJsonDocument::fromJson(file.readAll()).object();
    if (info.value(QStringLiteral("version")).toInt() != 1) return {};
    return {info.value(QStringLiteral("densityDpi")).toDouble(),
            shortEdge(info.value(QStringLiteral("densityWidthPixels")).toDouble(),
                      info.value(QStringLiteral("densityHeightPixels")).toDouble())};
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
