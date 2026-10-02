// A screen beside the phone's own, as seen from the Linux side (docs/65, docs/research/91): one
// floating window each.
//
// - Desktop mode (workspace 0): the user's independent desktop, a KWin of its own (docs/research/97
//   §19), on while it runs; its picture without the pointer (the touches are the pointer), and a
//   second one with it while fullscreen's touchpad mode asks.
// - The assistant's screen (workspace n): the agent's own KWin, the agent's pointer drawn in.
// rungic-workspace-stream records each and takes the window's touches and typing into it. The
// platform bridge says whether a TV shows the screen, and whether the assistant's screen is on.
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


class AgentScreen : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString status READ status NOTIFY statusChanged)
    Q_PROPERTY(uint nodeId READ nodeId NOTIFY nodeIdChanged)
    // Desktop mode's picture with the system's pointer drawn in, while asked for (setPointerShown):
    // fullscreen's touchpad mode. 0 when there is none (yet).
    Q_PROPERTY(uint pointerNodeId READ pointerNodeId NOTIFY pointerNodeIdChanged)
    // Desktop mode on a TV: a picture of its own for the TV's view (setTvShown), 0 until it starts.
    Q_PROPERTY(uint tvNodeId READ tvNodeId NOTIFY tvNodeIdChanged)
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
    uint pointerNodeId() const { return m_pointerNodeId; }
    uint tvNodeId() const { return m_tvNodeId; }
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
    // The blurred wallpaper under the director's fullscreen (rungic-agent-screen background).
    Q_INVOKABLE QString backgroundFile() const;
    // The size of the output it shows, in the pixels of its pointer and scroll: every workspace's
    // KWin is 1920x1080 (rungic-workspace).
    Q_INVOKABLE QSize outputSize() const { return QSize(1920, 1080); }
    // Fullscreen's touchpad mode shows the system's pointer (docs/research/97 §17.4): desktop mode
    // records a second picture with the pointer drawn in (pointerNodeId), the first one left as it
    // is. An assistant's screen's picture has the pointer already: nothing to do.
    Q_INVOKABLE void setPointerShown(bool shown);
    // The TV's view of desktop mode wants a picture: a fresh stream, which starts with a frame (a
    // second consumer of the running one waited for the screen to change, up to a minute).
    Q_INVOKABLE void setTvShown(bool shown);
    // Typing on the phone into the focused field: text as an input method commits it, and keys
    // (Linux key codes: Enter, Backspace, arrows...) pressed or released.
    Q_INVOKABLE void typeText(const QString &text);
    Q_INVOKABLE void key(int code, bool pressed);
    // Fullscreen on the phone: the Android host presents the output itself (zero-copy), and this
    // window hides and stops recording until it leaves fullscreen.
    Q_INVOKABLE void fullscreen();
    // Turn the screen off and quit.
    Q_INVOKABLE void close();

Q_SIGNALS:
    void statusChanged();
    void nodeIdChanged();
    void pointerNodeIdChanged();
    void tvNodeIdChanged();
    void activityChanged();

private:
    void poll();
    void update();
    void setStatus(const QString &status);
    QString op() const;     // the platform bridge's request for this screen
    void readActivity();
    void startWorkspaceStream();
    void stopWorkspaceStream();
    void send(const QString &line);   // a command to rungic-workspace-stream

    uint m_pointerNodeId = 0;
    uint m_tvNodeId = 0;
    bool m_tvShown = false;
    bool m_pointerShown = false;
    QTimer m_poll;
    QString m_status = QStringLiteral("starting");
    uint m_nodeId = 0;
    bool m_enabled = true;
    bool m_onTv = false;
    bool m_fullscreen = false;
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
