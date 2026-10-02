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
#include <QJsonObject>
#include <QMap>
#include <QProcess>
#include <QObject>
#include <QPointer>
#include <QRect>
#include <QTimer>
#include <QVariantMap>
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
    // In a team (rungic_cua.team, docs/research/91): the member's role, and the kind of its latest
    // post (review, progress, blocked, question, done, failed, ended), "" outside a team.
    Q_PROPERTY(QString teamRole READ teamRole NOTIFY activityChanged)
    Q_PROPERTY(QString teamKind READ teamKind NOTIFY activityChanged)

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
    QString teamRole() const { return m_teamRole; }
    QString teamKind() const { return m_teamKind; }

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
    QString m_teamRole;
    QString m_teamKind;
    double m_activityTime = 0;
    // The assistant's screen shows workspace n (docs/research/91): its picture comes from
    // rungic-workspace-stream, which records that workspace's KWin. 0: desktop mode.
    int m_workspace = 0;
    QProcess *m_workspaceStream = nullptr;
    int m_streamedWorkspace = 0;
};

// The director (导播台, docs/58): the assistant's screens together in one floating window, one of
// them in focus, large, the others as thumbnails below it. Its state (members: the workspaces
// running now, the focus, how large the focus is) is the Android app's, shared with the TV
// (platform bridge op "director"); this follows it and keeps one AgentScreen per member, each
// with its own picture.
// The team's board as a tile of the director (rungic_cua.team, Director.BOARD in the app): no
// workspace and no picture, drawn by the window from `board` (brief, phase, members, decision, result).
class BoardTile : public QObject
{
    Q_OBJECT
    Q_PROPERTY(int workspace READ workspace CONSTANT)
    Q_PROPERTY(uint nodeId READ nodeId CONSTANT)
    Q_PROPERTY(QString activityState READ none CONSTANT)
    Q_PROPERTY(QString activityText READ none CONSTANT)
    Q_PROPERTY(QString teamRole READ none CONSTANT)
    Q_PROPERTY(QString teamKind READ none CONSTANT)
    Q_PROPERTY(QVariantMap board READ board NOTIFY boardChanged)

public:
    static constexpr int kSlot = 100;
    using QObject::QObject;
    int workspace() const { return kSlot; }
    uint nodeId() const { return 0; }
    QString none() const { return {}; }
    QVariantMap board() const { return m_board; }
    void setBoard(const QVariantMap &board)
    {
        if (board == m_board)
            return;
        m_board = board;
        Q_EMIT boardChanged();
    }

Q_SIGNALS:
    void boardChanged();

private:
    QVariantMap m_board;
};

class Director : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QList<QObject *> screens READ screens NOTIFY changed)
    // The tile in focus (a screen or the board), and the screen the window's controls act on: the
    // focus, or beside the board the first screen.
    Q_PROPERTY(QObject *focusTile READ focusTile NOTIFY changed)
    Q_PROPERTY(QObject *focusScreen READ focusScreen NOTIFY changed)
    Q_PROPERTY(int focus READ focus NOTIFY changed)
    // 0 standard, 1 enlarged (thumbnails a thin strip), 2 solo (the focus only).
    Q_PROPERTY(int level READ level NOTIFY changed)
    // The director is fullscreen on the phone (the Android app shows it; this window hides).
    Q_PROPERTY(bool fullscreenShown READ fullscreenShown NOTIFY changed)

public:
    explicit Director(QObject *parent = nullptr);

    QList<QObject *> screens() const;
    QObject *focusTile() const;
    QObject *focusScreen() const;
    int focus() const { return m_focus; }
    int level() const { return m_level; }
    bool empty() const { return m_screens.isEmpty(); }
    bool fullscreenShown() const { return m_fullscreen; }
    // The director fullscreen on the phone (docs/58).
    Q_INVOKABLE void fullscreen();

    Q_INVOKABLE void setFocus(int workspace);
    // Standard, enlarged, solo, standard ...
    Q_INVOKABLE void nextLevel();

Q_SIGNALS:
    void changed();

private:
    void poll();
    void apply(const QJsonObject &state);

    QMap<int, AgentScreen *> m_screens;
    BoardTile *m_board = nullptr;
    bool m_boardShown = false;
    int m_focus = 0;
    int m_level = 0;
    bool m_fullscreen = false;
    int m_version = -1;
    QTimer m_poll;
};
