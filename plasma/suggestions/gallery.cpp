// SPDX-License-Identifier: GPL-2.0-or-later
// rungic-suggestions-gallery: the home-screen widgets in every state (WidgetGallery.qml).
//   --theme light|dark|system
//   --shot FILE   save the window as an image and quit (works offscreen:
//                 QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software, e.g. with the phone locked)
// Exits 3 when QML reported warnings, so a broken state fails the shot instead of looking fine.
#include <QCommandLineParser>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QTimer>

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    QGuiApplication::setApplicationName(QStringLiteral("rungic-suggestions-gallery"));
    if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_STYLE")) {
        QQuickStyle::setStyle(QStringLiteral("org.kde.desktop"));
    }
    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addOption({QStringLiteral("theme"), QStringLiteral("light, dark or system"), QStringLiteral("theme"), QStringLiteral("system")});
    parser.addOption({QStringLiteral("shot"), QStringLiteral("save the window to this image and quit"), QStringLiteral("file")});
    parser.process(app);
    QQmlApplicationEngine engine;
    bool warned = false;
    QObject::connect(&engine, &QQmlApplicationEngine::warnings, &app, [&warned](const QList<QQmlError> &errors) {
        for (const auto &error : errors) qWarning().noquote() << error.toString();
        warned = true;
    });
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.setInitialProperties({{QStringLiteral("initialTheme"), parser.value(QStringLiteral("theme"))}});
    engine.loadFromModule("com.rungic.suggestions", "WidgetGallery");
    const QString shot = parser.value(QStringLiteral("shot"));
    if (!shot.isEmpty()) {
        QTimer::singleShot(1500, &app, [&engine, &warned, shot] {
            auto *window = engine.rootObjects().isEmpty() ? nullptr : qobject_cast<QQuickWindow *>(engine.rootObjects().first());
            const bool saved = window && window->grabWindow().save(shot);
            QCoreApplication::exit(!saved ? 2 : warned ? 3 : 0);
        });
    }
    return app.exec();
}
