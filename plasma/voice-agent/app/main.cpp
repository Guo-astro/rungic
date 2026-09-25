// SPDX-License-Identifier: GPL-2.0-or-later
// Voice assistant: chat list with push-to-talk for the Codex voice agent (docs/59).
//   --overlay            the resident overlay the Home button brings up (docs/67)
//   --conversation ID    open that conversation (in the running app, if there is one)
#include <KColorScheme>
#include <KSharedConfig>

#include <QDBusConnection>
#include <QDBusMessage>
#include <QGuiApplication>
#include <QIcon>
#include <QQmlApplicationEngine>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QStandardPaths>

#include "overlay.h"

// One app: a second start hands its conversation to the first (dev.moto.VoiceAssistantApp).
class AppInstance : public QObject
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "dev.moto.VoiceAssistantApp")
public:
    explicit AppInstance(QQmlApplicationEngine *engine)
        : QObject(engine)
        , m_engine(engine)
    {
    }

public Q_SLOTS:
    Q_SCRIPTABLE void Open(const QString &conversation)
    {
        const auto roots = m_engine->rootObjects();
        auto *window = roots.isEmpty() ? nullptr : qobject_cast<QQuickWindow *>(roots.constFirst());
        if (!window) {
            return;
        }
        if (!conversation.isEmpty()) {
            QMetaObject::invokeMethod(window, "openConversation", Q_ARG(QVariant, conversation));
        }
        window->showNormal();
        window->raise();
        window->requestActivate();
    }

private:
    QQmlApplicationEngine *m_engine;
};

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
    const QStringList args = app.arguments();
    const bool overlay = args.contains(QStringLiteral("--overlay"));
    const qsizetype at = args.indexOf(QStringLiteral("--conversation"));
    const QString conversation = at >= 0 && at + 1 < args.size() ? args.at(at + 1) : QString();
    auto bus = QDBusConnection::sessionBus();

    QQmlApplicationEngine engine;
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(1); },
                     Qt::QueuedConnection);
    if (overlay) {
        Overlay *object = Overlay::instance();
        engine.loadFromModule("dev.moto.voiceassistant", "AssistantOverlay");
        if (engine.rootObjects().isEmpty()) {
            return 1;
        }
        object->setWindow(qobject_cast<QQuickWindow *>(engine.rootObjects().constFirst()));
        if (!bus.registerService(QStringLiteral("dev.moto.VoiceAssistant"))
            || !bus.registerObject(QStringLiteral("/Assistant"), object, QDBusConnection::ExportScriptableSlots)) {
            qWarning("dev.moto.VoiceAssistant: already running or no session bus");
            return 1;
        }
        return app.exec();
    }
    if (!bus.registerService(QStringLiteral("dev.moto.VoiceAssistantApp"))) {
        QDBusMessage open = QDBusMessage::createMethodCall(QStringLiteral("dev.moto.VoiceAssistantApp"), QStringLiteral("/App"),
                                                           QStringLiteral("dev.moto.VoiceAssistantApp"), QStringLiteral("Open"));
        open.setArguments({conversation});
        bus.call(open);
        return 0;
    }
    // The app's own colours (docs/59). Declared through KDE_COLOR_SCHEME_PATH before any window
    // exists: the platform theme hands it to KWin (the KDE palette protocol) and Kirigami reads
    // it, so the shell's status bar and navigation panel take the same colours.
    const QString scheme = QStandardPaths::locate(QStandardPaths::GenericDataLocation,
                                                  QStringLiteral("moto-voice-assistant/MotoVoiceAssistant.colors"));
    if (!scheme.isEmpty()) {
        app.setProperty("KDE_COLOR_SCHEME_PATH", scheme);
        QGuiApplication::setPalette(KColorScheme::createApplicationPalette(KSharedConfig::openConfig(scheme)));
    }
    engine.setInitialProperties({{QStringLiteral("initialConversation"), conversation}});
    engine.loadFromModule("dev.moto.voiceassistant", "Main");
    bus.registerObject(QStringLiteral("/App"), new AppInstance(&engine), QDBusConnection::ExportScriptableSlots);
    return app.exec();
}

#include "main.moc"
