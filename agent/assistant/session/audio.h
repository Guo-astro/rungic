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
    std::function<void(QString)> failed;           // cannot work at all here (a missing GStreamer element)
    std::function<void(QString)> interrupted;      // the call's audio broke; it is opened again (recover)
    std::function<void()> hungUp;     // the platform hung the call up (on Android: its call notification, a headset)
    std::function<void(quint64,quint64)> flushed;
    QLocalSocket backend;
    QString session,captureToken;
    GstElement *recorder=nullptr,*player=nullptr,*src=nullptr;
    quint64 epoch=1,played=0,written=0,samples=0;
    bool opened=false,muted=false,flushing=false,sourceReady=false,captureReady=false,reopening=false,captureRetrying=false;
    int requestId=0,flushId=0,retries=0;
    qint64 stalledSince=-1;
    explicit Audio(QObject *parent=nullptr);
    ~Audio();
    void start(const QString &id);
    void close();
    void capture();
    void mute(bool value);
    void stopPlayback();
    void play(const QByteArray &pcm);
    void recover(const QString &why);
private:
    void send(QJsonObject object);
    void message(QJsonObject object);
    void dropPlayer();
};
