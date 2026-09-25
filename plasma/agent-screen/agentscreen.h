// The assistant's screen as seen from the Linux side (docs/65).
//
// The Android host keeps a second output (KWin names it CAST-n) while the assistant's screen is on:
// a TV presents it when one is connected, else nothing does. This object watches the platform
// bridge for which of the two holds, records the output through KWin's zkde_screencast (a PipeWire
// node the floating window shows) while no TV presents it, and forwards the window's touches into
// that output with KWin's fake input. Both protocols are restricted: KWin grants them to this
// executable through its desktop file (X-KDE-Wayland-Interfaces).
#pragma once

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

public:
    explicit AgentScreen(QObject *parent = nullptr);
    ~AgentScreen() override;

    QString status() const { return m_status; }
    uint nodeId() const { return m_nodeId; }
    bool onTv() const { return m_onTv; }

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

Q_SIGNALS:
    void statusChanged();
    void nodeIdChanged();

private:
    void poll();
    void update();
    void startStream();
    void stopStream();
    void setStatus(const QString &status);
    QScreen *agentOutput() const;
    void keepApart();

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
};
