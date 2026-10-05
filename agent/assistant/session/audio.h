// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <QObject>
#include <QLocalSocket>
#include <QJsonObject>
#include <gst/gst.h>
#include <functional>
class Audio : public QObject {
public:
    std::function<void(const QByteArray &)> microphone;
    std::function<void(bool)> speech;
    std::function<void()> ready;
    std::function<void(QString)> failed;
    std::function<void()> hungUp;     // Android hung the call up (its notification, a headset)
    std::function<void(quint64,quint64)> flushed;
    QLocalSocket backend;
    QString session,captureToken;
    GstElement *recorder=nullptr,*player=nullptr,*src=nullptr;
    quint64 epoch=1,played=0,written=0,samples=0;
    bool opened=false,muted=false,flushing=false,sourceReady=false,captureReady=false;
    int requestId=0,flushId=0;
    explicit Audio(QObject *parent=nullptr);
    ~Audio();
    void start(const QString &id);
    void close();
    void capture();
    void mute(bool value);
    void stopPlayback();
    void play(const QByteArray &pcm);
private:
    void send(QJsonObject object);
    void message(QJsonObject object);
    void dropPlayer();
};
