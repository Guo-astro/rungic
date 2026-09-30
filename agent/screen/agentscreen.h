// A screen beside the phone's own, as seen from the Linux side (docs/65, docs/research/91): one
// floating window each.
//
// - Desktop mode (workspace 0): the Android host keeps a second output of the user's desktop
//   (KWin names it CAST-n). This object records it through KWin's zkde_screencast (a PipeWire node
//   the floating window shows) while no TV or fullscreen presents it, and forwards the window's
//   touches into it with KWin's fake input. Both protocols are restricted: KWin grants them to
//   this executable through its desktop file (X-KDE-Wayland-Interfaces).
// - The assistant's screen (workspace n): the agent's own KWin; rungic-workspace-stream records it.
// The platform bridge says whether the screen is on and whether a TV or fullscreen shows it.
#pragma once

#include <QFileSystemWatcher>
#include <QProcess>
#include <QObject>
#include <QPointer>
#include <QRect>
#include <QTimer>
#include <memory>

class QScreen;
class Screencasting;
class ScreencastStream;
class FakeInput;

class AgentScreen : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString status READ status NOTIFY statusChanged)
    Q_PROPERTY(uint nodeId READ nodeId NOTIFY nodeIdChanged)
    Q_PROPERTY(bool onTv READ onTv NOTIFY statusChanged)
    // 0: desktop mode's window; n: the assistant's screen of workspace n.
    Q_PROPERTY(int workspace READ workspace CONSTANT)
    // What the assistant is doing on this screen (rungic_cua.activity, docs/88): "" when nothing,
    // "working" with a caption, or how it ended (done, question, failed, stopped).
    Q_PROPERTY(QString activityState READ activityState NOTIFY activityChanged)
    Q_PROPERTY(QString activityText READ activityText NOTIFY activityChanged)

public:
    // `workspace`: 0 desktop mode, n the assistant's screen of workspace n.
    explicit AgentScreen(int workspace, QObject *parent = nullptr);
    ~AgentScreen() override;

    QString status() const { return m_status; }
    uint nodeId() const { return m_nodeId; }
    bool onTv() const { return m_onTv; }
    int workspace() const { return m_workspace; }
    QString activityState() const { return m_activityState; }
    QString activityText() const { return m_activityText; }

    // Input at a fraction (0..1) of the assistant's screen.
    Q_INVOKABLE void pointerMove(double fx, double fy);
    Q_INVOKABLE void pointerButton(int button, bool pressed);
    Q_INVOKABLE void scroll(double dx, double dy);
    // Hand the screen to the TV last cast to (the host keeps the output; only its frames move).
    Q_INVOKABLE void castToTv();
    // Fullscreen on the phone: the Android host presents the output itself (zero-copy), and this
    // window hides and stops recording until it leaves fullscreen.
    Q_INVOKABLE void fullscreen();
    // Turn the assistant's screen off and quit.
    Q_INVOKABLE void close();
    // Whether the window shows the picture (false: tucked into the edge). The host renders the
    // screen at a low rate while nobody looks at it (docs/65).
    Q_INVOKABLE void setWatched(bool watched);

Q_SIGNALS:
    void statusChanged();
    void nodeIdChanged();
    void activityChanged();

private:
    void poll();
    void update();
    void startStream();
    void stopStream();
    void setStatus(const QString &status);
    QString op() const;     // the platform bridge's request for this screen
    QScreen *agentOutput() const;
    void keepApart();
    void reportWatched();
    void readActivity();
    void startWorkspaceStream();
    void stopWorkspaceStream();

    std::unique_ptr<Screencasting> m_screencasting;
    std::unique_ptr<FakeInput> m_input;
    std::unique_ptr<ScreencastStream> m_stream;
    QPointer<QScreen> m_streamed;
    QTimer m_poll;
    QString m_status = QStringLiteral("starting");
    uint m_nodeId = 0;
    bool m_enabled = true;
    bool m_onTv = false;
    bool m_fullscreen = false;
    bool m_authenticated = false;
    bool m_pointerPlaced = false;
    bool m_watched = true;
    QFileSystemWatcher m_activityWatcher;
    QString m_activityPath;
    QString m_activityState;
    QString m_activityText;
    double m_activityTime = 0;
    // The assistant's screen shows workspace n (docs/research/91): its picture comes from
    // rungic-workspace-stream, which records that workspace's KWin. 0: desktop mode.
    int m_workspace = 0;
    QProcess *m_workspaceStream = nullptr;
    int m_streamedWorkspace = 0;
};
