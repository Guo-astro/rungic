// rungic-agent-screen-window --desktop | --workspace N (docs/65, docs/research/91): the floating
// window on the phone of desktop mode (the user's second desktop screen) or of the assistant's
// screen (the agent's workspace N). Started by rungic-desktop-mode or rungic-agent-screen once its
// screen is on; quits when it is turned off. Each has a desktop file of its own (its grants).
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>

#include "agentscreen.h"
#include "floater.h"

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    int workspace = 0;
    const QStringList args = app.arguments();
    const int at = args.indexOf(QStringLiteral("--workspace"));
    if (at >= 0 && at + 1 < args.size())
        workspace = qMax(1, args.at(at + 1).toInt());
    app.setApplicationName(QStringLiteral("rungic-agent-screen"));
    app.setDesktopFileName(workspace > 0 ? QStringLiteral("com.rungic.AgentScreen") : QStringLiteral("com.rungic.DesktopMode"));
    app.setQuitOnLastWindowClosed(false);

    AgentScreen agent(workspace);
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
