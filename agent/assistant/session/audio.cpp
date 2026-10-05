// SPDX-License-Identifier: GPL-2.0-or-later
#include "audio.h"
#include <QDebug>
#include <QElapsedTimer>
#include <QJsonDocument>
#include <QTimer>
#include <QUuid>
#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>
struct CaptureContext {Audio *audio;QString session;};
Audio::Audio(QObject *parent):QObject(parent){
    backend.setReadBufferSize(65536);
    connect(&backend,&QLocalSocket::connected,this,[this]{send({{"op","open"},{"muted",muted}});});
    connect(&backend,&QLocalSocket::readyRead,this,[this]{while(backend.canReadLine())message(QJsonDocument::fromJson(backend.readLine()).object());});
    // The call's audio is meant to recover, not to end the call: a broken connection, a restarted
    // service, a pipeline error or an unanswered interruption open the audio again (recover), as
    // long as the call lasts. Only hanging up ends it (2026-10-05, the user).
    connect(&backend,&QLocalSocket::disconnected,this,[this]{if(!session.isEmpty())recover("Communication audio disconnected");});
    connect(&backend,&QLocalSocket::errorOccurred,this,[this](QLocalSocket::LocalSocketError){if(!session.isEmpty())recover("Communication audio backend unavailable");});
}
static QString socketPath(){return QString::fromLocal8Bit(qgetenv("XDG_RUNTIME_DIR"))+"/rungic-communication.sock";}
void Audio::recover(const QString &why){
    if(session.isEmpty()||reopening)return;
    reopening=true;const auto id=session;
    qWarning().noquote()<<"call audio interrupted:"<<why<<"- opening it again";
    opened=false;sourceReady=captureReady=false;captureToken.clear();backend.abort();
    if(recorder){gst_element_set_state(recorder,GST_STATE_NULL);gst_object_unref(recorder);recorder=nullptr;}
    dropPlayer();flushing=false;flushId=0;stalledSince=-1;
    if(interrupted)interrupted(why);
    // 0.25 s, then longer up to 5 s between tries, for as long as the call lasts.
    const int delay=std::min(5000,250<<std::min(retries,5));++retries;
    QTimer::singleShot(delay,this,[this,id]{if(session!=id)return;reopening=false;epoch=1;played=written=0;backend.connectToServer(socketPath());});
}
Audio::~Audio(){close();}
void Audio::start(const QString &id){close();session=id;epoch=1;played=written=0;muted=false;retries=0;backend.connectToServer(socketPath());}
void Audio::send(QJsonObject o){o["sessionId"]=session;if(!o.contains("id"))o["id"]=++requestId;backend.write(QJsonDocument(o).toJson(QJsonDocument::Compact)+'\n');}
void Audio::close(){
    opened=false;sourceReady=captureReady=false;reopening=false;session.clear();captureToken.clear();backend.abort();
    if(recorder){gst_element_set_state(recorder,GST_STATE_NULL);gst_object_unref(recorder);recorder=nullptr;}
    dropPlayer();flushing=false;
}
void Audio::message(QJsonObject o){
    if(o["type"]=="error"){recover(o["error"].toString());return;}
    if(o.contains("error")){
        // A request refused (a stale session, a flush already pending): an interruption that is not
        // acknowledged opens the audio again; anything else is only logged.
        if(flushId!=0&&o["id"].toInt()==flushId)recover("Playback interruption refused: "+o["error"].toString());
        else qWarning().noquote()<<"call audio request refused:"<<o["error"].toString();
        return;
    }
    if(o["type"]=="ready"){
        sourceReady=!muted&&o["microphone"].toBool(true);opened=true;retries=0;capture();if((muted||(sourceReady&&captureReady))&&ready)ready();
    } else if(o["type"]=="position"){
        if(o["hungUp"].toBool()&&opened){if(hungUp)hungUp();return;}
        if(quint64(o["epoch"].toDouble())==epoch){played=quint64(o["playedFrames"].toDouble());written=quint64(o["writtenFrames"].toDouble());}
    } else if(o["id"].toInt()==flushId && flushId!=0){
        flushId=0;flushing=false;epoch=quint64(o["newEpoch"].toDouble());played=written=0;
        if(flushed)flushed(quint64(o["playedFrames"].toDouble()),epoch);
    }
}
void Audio::capture(){
    if(muted||recorder)return;
    captureToken=QUuid::createUuid().toString();
    GError *error=nullptr;
    recorder=gst_parse_launch("pulsesrc device=android_communication_microphone buffer-time=40000 latency-time=10000 ! audio/x-raw,format=S16LE,rate=48000,channels=1,layout=interleaved ! webrtcdsp echo-cancel=false noise-suppression=false gain-control=false voice-detection=true ! audioresample ! audio/x-raw,format=S16LE,rate=24000,channels=1 ! appsink name=mic emit-signals=true sync=false max-buffers=5 drop=false",&error);
    if(error||!recorder){if(error)g_error_free(error);if(failed)failed("Local voice detection unavailable");return;}
    GstBus *bus=gst_element_get_bus(recorder);
    gst_bus_set_sync_handler(bus,+[](GstBus *,GstMessage *m,gpointer p)->GstBusSyncReply{
        auto *context=static_cast<CaptureContext *>(p);auto *self=context->audio;auto token=context->session;
        if(GST_MESSAGE_TYPE(m)==GST_MESSAGE_ELEMENT){auto *s=gst_message_get_structure(m);gboolean active=false;
            if(s&&gst_structure_has_name(s,"voice-activity")&&gst_structure_get_boolean(s,"stream-has-voice",&active))
                QMetaObject::invokeMethod(self,[self,active,token]{if(self->captureToken==token&&!self->muted&&self->opened&&self->speech)self->speech(active);},Qt::QueuedConnection);
        } else if(GST_MESSAGE_TYPE(m)==GST_MESSAGE_ASYNC_DONE){
            QMetaObject::invokeMethod(self,[self,token]{if(self->captureToken==token&&self->opened){self->captureReady=true;if(self->sourceReady&&self->ready)self->ready();}},Qt::QueuedConnection);
        } else if(GST_MESSAGE_TYPE(m)==GST_MESSAGE_ERROR){QMetaObject::invokeMethod(self,[self,token]{if(self->captureToken==token&&self->opened&&self->failed)self->recover("Communication microphone pipeline failed");},Qt::QueuedConnection);}
        gst_message_unref(m);return GST_BUS_DROP;
    },new CaptureContext{this,captureToken},+[](gpointer p){delete static_cast<CaptureContext *>(p);});gst_object_unref(bus);
    auto *sink=gst_bin_get_by_name(GST_BIN(recorder),"mic");
    g_signal_connect_data(sink,"new-sample",G_CALLBACK(+[](GstAppSink *sink,gpointer p)->GstFlowReturn{
        GstSample *sample=gst_app_sink_pull_sample(sink);if(!sample)return GST_FLOW_EOS;GstMapInfo info;
        auto *b=gst_sample_get_buffer(sample);QByteArray data;
        if(gst_buffer_map(b,&info,GST_MAP_READ)){data=QByteArray(reinterpret_cast<const char *>(info.data),info.size);gst_buffer_unmap(b,&info);}gst_sample_unref(sample);
        auto *context=static_cast<CaptureContext *>(p);auto *self=context->audio;const auto generation=context->session;
        QMetaObject::invokeMethod(self,[self,data,generation]{if(self->opened&&!self->muted&&self->captureToken==generation&&self->microphone)self->microphone(data);},Qt::QueuedConnection);
        return GST_FLOW_OK;
    }),new CaptureContext{this,captureToken},+[](gpointer p,GClosure *){delete static_cast<CaptureContext *>(p);},GConnectFlags(0));gst_object_unref(sink);
    if(gst_element_set_state(recorder,GST_STATE_PLAYING)==GST_STATE_CHANGE_FAILURE) {
        // The sound server away for a moment: the capture is tried again each second while the call
        // is open, the playback going on meanwhile.
        qWarning("call microphone could not start; trying again");
        gst_element_set_state(recorder,GST_STATE_NULL);gst_object_unref(recorder);recorder=nullptr;captureToken.clear();
        if(!captureRetrying){captureRetrying=true;const auto id=session;
            QTimer::singleShot(1000,this,[this,id]{captureRetrying=false;if(session==id&&opened)capture();});}
    }
}
void Audio::mute(bool value){
    muted=value;sourceReady=captureReady=false;if(value)captureToken.clear();
    if(value&&recorder){gst_element_set_state(recorder,GST_STATE_NULL);gst_object_unref(recorder);recorder=nullptr;}
    send({{"op","mute"},{"muted",value}});if(!value)capture();
}
void Audio::dropPlayer(){
    if(player){gst_element_set_state(player,GST_STATE_NULL);gst_object_unref(player);player=nullptr;}
    if(src){gst_object_unref(src);src=nullptr;}samples=0;
}
void Audio::stopPlayback(){
    dropPlayer();if(!opened||flushing)return;flushing=true;flushId=++requestId;send({{"op","flush"},{"id",flushId}});
    const int id=flushId;QTimer::singleShot(2000,this,[this,id]{if(flushing&&flushId==id)recover("Playback interruption was not acknowledged");});
}
void Audio::play(const QByteArray &pcm){
    if(!opened||flushing||pcm.isEmpty())return;
    if(!player){GError *error=nullptr;player=gst_parse_launch("appsrc name=audio format=time is-live=true block=false caps=audio/x-raw,format=S16LE,rate=24000,channels=1,layout=interleaved ! audioconvert ! audioresample ! audio/x-raw,format=S16LE,rate=48000,channels=1 ! pulsesink device=android_communication sync=false buffer-time=60000 latency-time=10000",&error);
        if(error||!player){if(error)g_error_free(error);if(failed)failed("Communication playback unavailable");return;}
        src=gst_bin_get_by_name(GST_BIN(player),"audio");
        auto *bus=gst_element_get_bus(player);
        gst_bus_set_sync_handler(bus,+[](GstBus *,GstMessage *m,gpointer p)->GstBusSyncReply{
            auto *c=static_cast<CaptureContext *>(p);auto *self=c->audio;auto token=c->session;
            if(GST_MESSAGE_TYPE(m)==GST_MESSAGE_ERROR)QMetaObject::invokeMethod(self,[self,token]{if(self->session==token&&self->opened&&self->failed)self->recover("Communication playback pipeline failed");},Qt::QueuedConnection);
            gst_message_unref(m);return GST_BUS_DROP;
        },new CaptureContext{this,session},+[](gpointer p){delete static_cast<CaptureContext *>(p);});gst_object_unref(bus);
        gst_element_set_state(player,GST_STATE_PLAYING);
    }
    // Playback not taken for a moment (the platform routing the call again): what does not fit is
    // dropped, as live audio already late; playback stuck for 3 s opens the audio again.
    guint64 queued=0;g_object_get(src,"current-level-bytes",&queued,nullptr);
    static QElapsedTimer clock;if(!clock.isValid())clock.start();
    if(queued>24000){
        if(stalledSince<0){stalledSince=clock.elapsed();qWarning()<<"call playback not taken; dropping audio";}
        else if(clock.elapsed()-stalledSince>3000)recover("Communication playback stalled");
        return;
    }
    stalledSince=-1;
    auto *b=gst_buffer_new_allocate(nullptr,pcm.size(),nullptr);gst_buffer_fill(b,0,pcm.data(),pcm.size());GST_BUFFER_PTS(b)=samples*GST_SECOND/24000;GST_BUFFER_DURATION(b)=quint64(pcm.size()/2)*GST_SECOND/24000;samples+=pcm.size()/2;
    gst_app_src_push_buffer(GST_APP_SRC(src),b);
}
