// SPDX-License-Identifier: GPL-2.0-or-later
// Voice assistant: chat list with push-to-talk for the Codex voice agent (docs/59).
#include <QGuiApplication>
#include <QIcon>
#include <QQmlApplicationEngine>
#include <QQuickStyle>

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    QGuiApplication::setApplicationName(QStringLiteral("moto-voice-assistant"));
    QGuiApplication::setApplicationDisplayName(QStringLiteral("语音助手"));
    QGuiApplication::setDesktopFileName(QStringLiteral("dev.moto.VoiceAssistant"));
    QGuiApplication::setWindowIcon(QIcon::fromTheme(QStringLiteral("audio-input-microphone")));
    if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_STYLE")) {
        QQuickStyle::setStyle(QStringLiteral("org.kde.desktop"));
    }
    QQmlApplicationEngine engine;
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(1); },
                     Qt::QueuedConnection);
    engine.loadFromModule("dev.moto.voiceassistant", "Main");
    return app.exec();
}
