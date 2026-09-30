// SPDX-License-Identifier: GPL-2.0-or-later
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQuickWindow>
#include <QQuickItem>
#include <QTimer>
#include <QImage>
#include <QDebug>
#include <QTest>

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
    // Fixed cards: the pointer test must not depend on what the service holds.
    SuggestionsWidget {
        objectName: "suggestionsWidget"
        x: 10; y: 30; width: 340; height: 330
        forcedBriefing: ({ generatedAt: Date.now() / 1000 - 600, source: "agent" })
        forcedCards: [1, 2, 3].map(n => ({ id: "card" + n, kind: "issues", refs: [], title: "Card " + n,
                                           body: "Sample card for the pointer test.", action: { label: "Open" } }))
    }
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
        if (widget) {
            auto *deck = window->findChild<QQuickItem *>("suggestionsWidget");
            auto require = [&](bool ok, const char *label) {
                if (!ok) { qWarning() << "swipe test:" << label; failed = true; }
            };
            require(deck, "widget");
            if (deck && app.arguments().contains("--swipe-test")) {
                auto swipe = [&](int distance, int duration = 180, int settle = 350) {
                    const QPoint from = deck->mapToScene(QPointF(deck->width() / 2, deck->height() / 2)).toPoint();
                    QTest::mousePress(window, Qt::LeftButton, Qt::NoModifier, from);
                    for (int n = 1; n <= 6; ++n) {
                        QTest::qWait(duration / 6);
                        QTest::mouseMove(window, from + QPoint(0, distance * n / 6));
                    }
                    QTest::mouseRelease(window, Qt::LeftButton, Qt::NoModifier, from + QPoint(0, distance));
                    QTest::qWait(settle);
                };
                const auto current = [&] { return deck->property("current").toInt(); };
                swipe(90);
                require(current() == 0, "first card: a pull down springs back");
                swipe(-22, 360);
                require(current() == 0, "a short drag snaps back");
                swipe(-120);
                require(current() == 1, "swipe up shows the second card");
                require(qFuzzyIsNull(deck->property("dragOffset").toDouble()), "the animation settles");
                swipe(-120);
                swipe(-120);
                require(current() == 2, "the last card stays at the end");
                swipe(120);
                require(current() == 1, "swipe down shows the previous card");
                if (!failed) qInfo() << "PASS pager swipe, bounds, snap-back";
            }
            app.exit(failed ? 1 : 0);
            return;
        }
        auto *list = window->findChild<QQuickItem *>("suggestionsFeed");
        if (!list || !list->property("atYBeginning").toBool()) {
            qWarning() << "preview beginning" << (list ? list->property("contentY") : QVariant())
                       << (list ? list->property("originY") : QVariant());
            failed = true;
        }
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
