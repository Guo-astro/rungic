// SPDX-License-Identifier: GPL-2.0-or-later
// rungic-design-gallery: the design system's controls in every state (docs/87).
//   --theme light|dark|system   --section NAME (one section, for screenshots)
//   --shot FILE   save the window as an image and quit (works offscreen:
//                 QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software, e.g. with the phone locked)
#include <QCommandLineParser>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QTimer>

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    QGuiApplication::setApplicationName(QStringLiteral("rungic-design-gallery"));
    QGuiApplication::setDesktopFileName(QStringLiteral("com.rungic.DesignGallery"));
    if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_STYLE")) {
        QQuickStyle::setStyle(QStringLiteral("org.kde.desktop"));
    }
    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addOption({QStringLiteral("theme"), QStringLiteral("light, dark or system"), QStringLiteral("theme"), QStringLiteral("system")});
    parser.addOption({QStringLiteral("section"), QStringLiteral("show one section"), QStringLiteral("name")});
    parser.addOption({QStringLiteral("shot"), QStringLiteral("save the window to this image and quit"), QStringLiteral("file")});
    parser.process(app);
    QQmlApplicationEngine engine;
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.setInitialProperties({{QStringLiteral("initialTheme"), parser.value(QStringLiteral("theme"))},
                                 {QStringLiteral("section"), parser.value(QStringLiteral("section"))}});
    engine.loadFromModule("com.rungic.design", "Gallery");
    const QString shot = parser.value(QStringLiteral("shot"));
    if (!shot.isEmpty()) {
        // After the pictures and animations have had a moment.
        QTimer::singleShot(1500, &app, [&engine, shot] {
            auto *window = engine.rootObjects().isEmpty() ? nullptr : qobject_cast<QQuickWindow *>(engine.rootObjects().first());
            const bool saved = window && window->grabWindow().save(shot);
            QCoreApplication::exit(saved ? 0 : 2);
        });
    }
    return app.exec();
}
