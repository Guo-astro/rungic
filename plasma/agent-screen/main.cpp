// rungic-agent-screen-window (docs/65): the floating window of the assistant's screen on the phone.
// Started by rungic-agent-screen once the screen is on; quits when it is turned off.
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>

#include "agentscreen.h"
#include "floater.h"

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("rungic-agent-screen"));
    app.setDesktopFileName(QStringLiteral("com.rungic.AgentScreen"));
    app.setQuitOnLastWindowClosed(false);

    AgentScreen agent;
    Floater floater;
    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("agent"), &agent);
    engine.rootContext()->setContextProperty(QStringLiteral("floater"), &floater);
    engine.loadFromModule("com.rungic.agentscreen", "Main");
    if (engine.rootObjects().isEmpty())
        return 1;
    auto window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
    floater.attach(window);
    window->setProperty("ready", true);
    return app.exec();
}
