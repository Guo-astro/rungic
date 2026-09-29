// SPDX-License-Identifier: GPL-2.0-or-later
// rungic-design-gallery: the design system's controls in every state (docs/87).
//   --theme light|dark|system   --section NAME (one section, for screenshots)
#include <QCommandLineParser>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQuickStyle>

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
    parser.process(app);
    QQmlApplicationEngine engine;
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.setInitialProperties({{QStringLiteral("initialTheme"), parser.value(QStringLiteral("theme"))},
                                 {QStringLiteral("section"), parser.value(QStringLiteral("section"))}});
    engine.loadFromModule("com.rungic.design", "Gallery");
    return app.exec();
}
