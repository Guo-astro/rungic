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
    QQmlApplicationEngine engine;
    bool failed = false;
    QObject::connect(&engine, &QQmlApplicationEngine::warnings, &app, [&failed](const QList<QQmlError> &errors) {
        for (const auto &error : errors) qWarning().noquote() << error.toString();
        failed = true;
    });
    engine.loadData(R"(
import QtQuick
import QtQuick.Controls
import com.rungic.suggestions
ApplicationWindow {
    width: 360; height: 740; visible: true
    SuggestionsFeed { anchors.fill: parent; home: true }
}
)");
    if (engine.rootObjects().isEmpty()) return 1;
    QTimer::singleShot(1800, &app, [&] {
        auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        if (app.arguments().size() > 1 && !window->grabWindow().save(app.arguments().at(1))) failed = true;
        auto *list = window->findChild<QQuickItem *>("suggestionsFeed");
        if (!list || !list->property("atYBeginning").toBool()) failed = true;
        if (list && list->property("count").toInt() > 10) {
            QMetaObject::invokeMethod(list, "positionViewAtEnd");
            QTimer::singleShot(300, &app, [&, list, window] {
                if (list->property("contentY").toDouble() < 1000) failed = true;
                if (app.arguments().size() > 1) window->grabWindow().save(app.arguments().at(1) + ".end.png");
                app.exit(failed ? 1 : 0);
            });
        } else app.exit(failed ? 1 : 0);
    });
    return app.exec();
}
