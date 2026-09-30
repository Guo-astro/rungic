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
        if (widget && list && app.arguments().contains("--swipe-test")) {
            auto findStack = [&]() -> QQuickItem * {
                auto *content = qvariant_cast<QQuickItem *>(list->property("contentItem"));
                if (content) for (auto *child : content->childItems())
                    if (child->objectName() == "desktopSuggestionStack" && child->property("count").toInt() > 1) return child;
                return nullptr;
            };
            auto *stack = findStack();
            auto require = [&](bool ok, const char *label) {
                if (!ok) { qWarning() << "swipe test:" << label; failed = true; }
            };
            require(stack && stack->property("count").toInt() > 1, "fixture stack");
            if (stack) {
                const auto offset = list->property("contentY").toDouble();
                auto swipe = [&](int distance, int duration = 180, int settle = 250) {
                    stack = findStack();
                    Q_ASSERT(stack);
                    const QPoint from = stack->mapToScene(QPointF(stack->width() / 2, stack->height() / 2)).toPoint();
                    QTest::mousePress(window, Qt::LeftButton, Qt::NoModifier, from);
                    for (int n = 1; n <= 6; ++n) {
                        QTest::qWait(duration / 6);
                        QTest::mouseMove(window, from + QPoint(0, distance * n / 6));
                    }
                    QTest::mouseRelease(window, Qt::LeftButton, Qt::NoModifier, from + QPoint(0, distance));
                    QTest::qWait(settle);
                    stack = findStack();
                    Q_ASSERT(stack);
                };
                swipe(90); // First-card boundary: keep the pointer, spring back.
                require(stack->property("currentIndex").toInt() == 0, "first boundary");
                swipe(-22, 360);
                require(stack->property("currentIndex").toInt() == 0, "short drag snaps back");
                swipe(-100);
                require(stack->property("currentIndex").toInt() == 1, "up selects second");
                require(qFuzzyIsNull(stack->property("dragOffset").toDouble()), "animation settles");
                require(list->property("contentY").toDouble() == offset, "stack does not scroll list");
                QTest::qWait(1600); // Only the now-visible member may receive a receipt.
                swipe(-100);
                require(stack->property("currentIndex").toInt() == 1, "last boundary");
                swipe(100);
                require(stack->property("currentIndex").toInt() == 0, "down selects previous");
                // A header drag scrolls the groups rather than changing the stack.
                auto *pointer = window->findChild<QQuickItem *>("suggestionsWidgetPointer");
                const QPoint from = pointer->mapToScene(QPointF(80, 22)).toPoint();
                QTest::mousePress(window, Qt::LeftButton, Qt::NoModifier, from);
                QTest::mouseMove(window, from - QPoint(0, 100), 180);
                QTest::mouseRelease(window, Qt::LeftButton, Qt::NoModifier, from - QPoint(0, 100));
                QTest::qWait(250);
                require(list->property("contentY").toDouble() > offset + 50, "header scrolls groups");
                if (!failed) qInfo() << "PASS actual pointer stack switching, bounds, snap-back, header scrolling";
            }
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
