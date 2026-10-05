// SPDX-License-Identifier: GPL-2.0-or-later
// The phone mode session's communication audio client (agent/assistant/session/audio.cpp) driven as the
// session drives it, muted (no PulseAudio needed), for tools/system/tests/communication_audio.py: open,
// then an interrupted playback (flush), then mute; one JSON line per thing it learns on stdout.
//   communication_client SESSION_ID      ($XDG_RUNTIME_DIR/rungic-communication.sock: the service)
#include "audio.h"
#include <QCoreApplication>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTimer>
#include <cstdio>

static void say(const QJsonObject &o) {
    std::printf("%s\n", QJsonDocument(o).toJson(QJsonDocument::Compact).constData());
    std::fflush(stdout);
}

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    gst_init(&argc, &argv);
    Audio audio;
    auto state = [&](const char *event) {
        say({{"event", event}, {"opened", audio.opened}, {"epoch", double(audio.epoch)},
             {"played", double(audio.played)}, {"written", double(audio.written)}, {"flushing", audio.flushing}});
    };
    audio.ready = [&] {
        state("ready");
        QTimer::singleShot(400, &app, [&] { state("playing"); audio.stopPlayback(); });
    };
    audio.flushed = [&](quint64 played, quint64 epoch) {
        say({{"event", "flushed"}, {"played", double(played)}, {"epoch", double(epoch)}});
        QTimer::singleShot(400, &app, [&] { state("after-flush"); audio.mute(true); });
    };
    audio.failed = [&](const QString &error) {
        say({{"event", "failed"}, {"error", error}});
        QTimer::singleShot(100, &app, &QCoreApplication::quit);
    };
    // The service's error: the client opens the call's audio again (Audio::recover); reported here
    // and then the test ends.
    audio.interrupted = [&](const QString &error) {
        say({{"event", "interrupted"}, {"error", error}, {"opened", audio.opened}, {"reopening", audio.reopening}});
        QTimer::singleShot(100, &app, &QCoreApplication::quit);
    };
    // Audio::start() muted: what start() does (it always opens unmuted, and a local socket connects at
    // once, sending open before start() returns), with the session muted before the connection, so that
    // no microphone pipeline (PulseAudio's pulsesrc, webrtcdsp) is needed here.
    audio.close();
    audio.session = QString::fromLocal8Bit(argc > 1 ? argv[1] : "session-1");
    audio.epoch = 1;
    audio.muted = true;
    audio.backend.connectToServer(QString::fromLocal8Bit(qgetenv("XDG_RUNTIME_DIR")) + "/rungic-communication.sock");
    QTimer::singleShot(10000, &app, [&] { state("timeout"); app.quit(); });
    return app.exec();
}
