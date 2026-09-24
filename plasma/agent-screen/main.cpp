// moto-agent-screen-window (docs/65): the floating window of the assistant's screen on the phone.
// Started by moto-agent-screen once the screen is on; quits when it is turned off.
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>

#include "agentscreen.h"
#include "floater.h"

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("moto-agent-screen"));
    app.setDesktopFileName(QStringLiteral("dev.moto.AgentScreen"));
    app.setQuitOnLastWindowClosed(false);

    AgentScreen agent;
    Floater floater;
    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("agent"), &agent);
    engine.rootContext()->setContextProperty(QStringLiteral("floater"), &floater);
    engine.loadFromModule("dev.moto.agentscreen", "Main");
    if (engine.rootObjects().isEmpty())
        return 1;
    auto window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
    floater.attach(window);
    window->setProperty("ready", true);
    return app.exec();
}
