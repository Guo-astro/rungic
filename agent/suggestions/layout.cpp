// SPDX-License-Identifier: GPL-2.0-or-later
#include "layout.h"
#include <KConfig>
#include <KConfigGroup>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSet>
#include <functional>

static bool setupOne(const QString &path, const QStringList &launchers, const QString &plugin, const QString &versionKey, int height, const QString &backupSuffix) {
    // Before plasmashell starts, never while its in-memory layout is live.
    // Fresh accounts without a containment can use the widget picker; the next
    // session also has a containment to initialize here.
    if (!QFile::exists(path)) return true;
    KConfig config(path, KConfig::SimpleConfig);
    KConfigGroup containments(&config, "Containments");
    int maximumId = 0;
    std::function<void(const KConfigGroup &)> visit = [&](const KConfigGroup &group) {
        for (const auto &name : group.groupList()) {
            maximumId = qMax(maximumId, name.toInt());
            visit(group.group(name));
        }
    };
    visit(containments);
    for (const auto &name : containments.groupList()) {
        auto desktop = containments.group(name);
        if (desktop.readEntry("plugin", QString()) != "org.kde.plasma.mobile.homescreen.folio") continue;
        auto folio = desktop.group("Folio");
        auto migration = desktop.group("Rungic");
        if (migration.readEntry(versionKey, 0) >= 1) continue;
        auto applets = desktop.group("Applets");
        for (const auto &id : applets.groupList()) {
            if (applets.group(id).readEntry("plugin", QString()) == plugin) {
                migration.writeEntry(versionKey, 1);
                return config.sync(); // An existing manually placed widget wins.
            }
        }
        const int columns = folio.readEntry("homeScreenColumns", 4);
        const int rows = folio.readEntry("homeScreenRows", 5);
        if (columns < 3 || rows < height) return true;
        QJsonParseError error;
        const auto document = QJsonDocument::fromJson(folio.readEntry("pages", QStringLiteral("[[]]")).toUtf8(), &error);
        if (error.error != QJsonParseError::NoError || !document.isArray()) return false;
        auto pages = document.array();
        if (pages.isEmpty()) pages.append(QJsonArray());
        const int width = qMin(columns, 4);
        int targetPage = -1, targetRow = 0;
        for (int page = 0; page < pages.size() && targetPage < 0; ++page) {
            if (!pages[page].isArray()) return false;
            QSet<int> occupied;
            for (const auto &value : pages[page].toArray()) {
                const auto item = value.toObject();
                const bool widget = item["type"] == "widget";
                const int w = widget ? qMax(1, item["gridWidth"].toInt()) : 1;
                const int h = widget ? qMax(1, item["gridHeight"].toInt()) : 1;
                for (int y = 0; y < h; ++y) for (int x = 0; x < w; ++x)
                    occupied.insert((item["row"].toInt() + y) * columns + item["column"].toInt() + x);
            }
            for (int row = 0; row <= rows - height; ++row) {
                bool free = true;
                for (int y = row; y < row + height; ++y) for (int x = 0; x < width; ++x)
                    if (occupied.contains(y * columns + x)) free = false;
                if (free) { targetPage = page; targetRow = row; break; }
            }
        }
        if (targetPage < 0) { targetPage = pages.size(); pages.append(QJsonArray()); }
        const QString backup = path + backupSuffix;
        if (!QFile::exists(backup) && !QFile::copy(path, backup)) return false;
        const int id = ++maximumId;
        auto page = pages[targetPage].toArray();
        page.append(QJsonObject{{"type", "widget"}, {"id", id}, {"row", targetRow}, {"column", 0},
                                {"gridWidth", width}, {"gridHeight", height}});
        pages[targetPage] = page;
        auto applet = applets.group(QString::number(id));
        applet.writeEntry("plugin", plugin);
        applet.writeEntry("immutability", 1);
        folio.writeEntry("pages", QString::fromUtf8(QJsonDocument(pages).toJson(QJsonDocument::Compact)));
        // Seed an absent setting only. Explicitly empty or customized favourites
        // belong to the user and must survive migrations and upgrades.
        if (!folio.hasKey("favorites") && !launchers.isEmpty()) {
            QJsonArray favorites;
            for (const auto &launcher : launchers)
                favorites.append(QJsonObject{{"type", "application"}, {"storageId", launcher}});
            folio.writeEntry("favorites", QString::fromUtf8(QJsonDocument(favorites).toJson(QJsonDocument::Compact)));
        }
        migration.writeEntry(versionKey, 1);
        return config.sync();
    }
    return true;
}

bool Care::setupWidget(const QString &path, const QStringList &launchers) {
    return setupOne(path, launchers, "com.rungic.suggestions", "suggestionsWidgetVersion", 3, ".before-rungic-suggestions-widget")
        && setupOne(path, {}, "com.rungic.agent", "agentWidgetVersion", 1, ".before-rungic-agent-widget");
}
