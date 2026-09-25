// SPDX-License-Identifier: GPL-2.0-or-later
#include "systemtheme.h"

#include <KConfigGroup>
#include <KSharedConfig>
#include <QGuiApplication>
#include <QRgb>
#include <QJSEngine>
#include <QStyleHints>

static SystemTheme *s_instance = nullptr;

SystemTheme::SystemTheme(QObject *parent)
    : QObject(parent)
    , m_watcher(KConfigWatcher::create(KSharedConfig::openConfig(QStringLiteral("kdeglobals"))))
{
    connect(m_watcher.data(), &KConfigWatcher::configChanged, this, [this](const KConfigGroup &group) {
        if (group.name().startsWith(QLatin1String("Colors:")) || group.name() == QLatin1String("General")) {
            update();
        }
    });
    connect(QGuiApplication::styleHints(), &QStyleHints::colorSchemeChanged, this, &SystemTheme::update);
    update();
}

SystemTheme *SystemTheme::instance()
{
    if (!s_instance) {
        s_instance = new SystemTheme(qApp);
    }
    return s_instance;
}

SystemTheme *SystemTheme::create(QQmlEngine *, QJSEngine *)
{
    QJSEngine::setObjectOwnership(instance(), QJSEngine::CppOwnership);
    return instance();
}

bool SystemTheme::dark() const
{
    return m_dark;
}

void SystemTheme::update()
{
    auto config = KSharedConfig::openConfig(QStringLiteral("kdeglobals"));
    config->reparseConfiguration();
    // Breeze Light's window background when kdeglobals does not say.
    const QStringList rgb = KConfigGroup(config, QStringLiteral("Colors:Window")).readEntry("BackgroundNormal", QStringLiteral("239,240,241")).split(QLatin1Char(','));
    bool dark = false;
    if (rgb.size() >= 3) {
        dark = qGray(rgb[0].trimmed().toInt(), rgb[1].trimmed().toInt(), rgb[2].trimmed().toInt()) < 128;
    }
    if (dark != m_dark) {
        m_dark = dark;
        Q_EMIT darkChanged();
    }
}
