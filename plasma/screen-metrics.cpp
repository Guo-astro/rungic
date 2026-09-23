// SPDX-License-Identifier: MIT
// Report Qt's logical screen geometry, which can differ from nested KScreen.
#include <QGuiApplication>
#include <QScreen>
#include <QJsonArray>
#include <QJsonObject>
#include <QJsonDocument>
#include <cstdio>
int main(int argc, char **argv) {
    QGuiApplication app(argc, argv);
    QJsonArray screens;
    for (auto screen : app.screens()) {
        screens.append(QJsonObject{{"name", screen->name()},
            {"width", screen->geometry().width()}, {"height", screen->geometry().height()},
            {"scale", screen->devicePixelRatio()}});
    }
    const auto data = QJsonDocument(screens).toJson(QJsonDocument::Compact);
    std::puts(data.constData());
}
