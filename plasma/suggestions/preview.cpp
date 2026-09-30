// SPDX-License-Identifier: GPL-2.0-or-later
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQuickWindow>
#include <QQuickItem>
#include <QTimer>
#include <QImage>
#include <QDebug>

int main(int argc, char **argv) {
    QGuiApplication app(argc, argv);
    const bool agent = app.arguments().contains("--agent");
    const bool usage = app.arguments().contains("--usage");
    const bool widget = app.arguments().contains("--widget");
    QQmlApplicationEngine engine;
    bool failed = false;
    QObject::connect(&engine, &QQmlApplicationEngine::warnings, &app, [&failed](const QList<QQmlError> &errors) {
        for (const auto &error : errors) qWarning().noquote() << error.toString();
        failed = true;
    });
    engine.loadData(agent ? R"(
import QtQuick
import QtQuick.Controls
import com.rungic.suggestions
ApplicationWindow {
    width: 360; height: 740; visible: true; color: "#355d50"
    AgentWidget { x: 8; y: 30; width: 344; height: 126 }
}
)" : usage ? R"(
import QtQuick
import QtQuick.Controls
import com.rungic.suggestions
ApplicationWindow {
    width: 360; height: 740; visible: true
    AgentUsageDetails { anchors.fill: parent }
}
)" : widget ? R"(
import QtQuick
import QtQuick.Controls
import com.rungic.suggestions
ApplicationWindow {
    width: 360; height: 740; visible: true; color: "#355d50"
    SuggestionsWidget { x: 16; y: 30; width: 328; height: 340 }
}
)" : R"(
import QtQuick
import QtQuick.Controls
import com.rungic.suggestions
ApplicationWindow {
    width: 360; height: 740; visible: true
    SuggestionsFeed { anchors.fill: parent }
}
)");
    if (engine.rootObjects().isEmpty()) return 1;
    QTimer::singleShot(1800, &app, [&] {
        auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        if (app.arguments().size() > 1 && !window->grabWindow().save(app.arguments().at(1))) failed = true;
        if (agent || usage) { app.exit(failed ? 1 : 0); return; }
        auto *list = window->findChild<QQuickItem *>(widget ? "suggestionsWidgetList" : "suggestionsFeed");
        if (!list || !list->property("atYBeginning").toBool()) {
            qWarning() << "preview beginning" << (list ? list->property("contentY") : QVariant())
                       << (list ? list->property("originY") : QVariant());
            failed = true;
        }
        if (widget && list && list->height() > window->height() / 2) failed = true;
        if (list && list->property("count").toInt() > 10) {
            QMetaObject::invokeMethod(list, "positionViewAtEnd");
            QTimer::singleShot(300, &app, [&, list, window] {
                if (list->property("contentY").toDouble() < 1000) {
                    qWarning() << "preview end" << list->property("contentY") << list->property("count");
                    failed = true;
                }
                if (app.arguments().size() > 1) window->grabWindow().save(app.arguments().at(1) + ".end.png");
                app.exit(failed ? 1 : 0);
            });
        } else app.exit(failed ? 1 : 0);
    });
    return app.exec();
}
