// SPDX-License-Identifier: GPL-2.0-or-later
// Explicit live-model probe: synthetic fixtures, temporary journal, simulated
// Codex RPC, real local VAD and ASR. No microphone or speaker. Never installed.
#include "session.h"
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QNetworkProxy>
#include <QNetworkRequest>
#include <QTemporaryDir>
#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>
#include <cstdio>

static void print(QJsonObject object,FILE *file=stdout){
    auto line=QJsonDocument(object).toJson(QJsonDocument::Compact)+'\n';
    std::fwrite(line.data(),1,line.size(),file);std::fflush(file);
}
int main(int argc,char **argv){
    QCoreApplication app(argc,argv);gst_init(&argc,&argv);
    if(app.arguments().size()<3||app.arguments().size()>4)return 2;
    const int holdMinutes=app.arguments().size()==4?app.arguments()[3].toInt():0;
    if(holdMinutes<0||holdMinutes>30)return 2;
    QFile fixture(app.arguments()[1]),prompt(app.arguments()[2]);
    if(!fixture.open(QIODevice::ReadOnly)||!prompt.open(QIODevice::ReadOnly))return 2;
    auto cases=QJsonDocument::fromJson(fixture.readAll()).array();
    QFile key(QDir::homePath()+"/.config/rungic-voice-agent/openai-api-key");if(!key.open(QIODevice::ReadOnly))return 2;
    QTemporaryDir temporary;Session session;session.journal=temporary.path()+"/tasks.json";session.leases=temporary.path();session.tasks.rows.clear();
    session.id="voice_probe";session.conversation="synthetic_probe";session.language=QString::fromLocal8Bit(qgetenv("RUNGIC_PROBE_LANGUAGE"));session.prompt=QString::fromUtf8(prompt.readAll());session.generation=1;session.lastVoice=-10000;
    // Audio is simulated. The production endpointing and routing logic remains active.
    session.audio.opened=session.audio.sourceReady=session.audio.captureReady=true;session.audio.flushing=true;
    auto proxy=QUrl(QString::fromLocal8Bit(qgetenv("https_proxy")));if(proxy.isEmpty())proxy=QUrl(QString::fromLocal8Bit(qgetenv("HTTPS_PROXY")));
    if(!proxy.isEmpty())session.ws.setProxy(QNetworkProxy(QNetworkProxy::HttpProxy,proxy.host(),proxy.port(8080)));
    GError *error=nullptr;
    auto *pipeline=gst_parse_launch("appsrc name=fixture format=time is-live=true caps=audio/x-raw,format=S16LE,rate=24000,channels=1,layout=interleaved ! audioresample ! audio/x-raw,rate=48000 ! webrtcdsp echo-cancel=false noise-suppression=false gain-control=false voice-detection=true ! audioresample ! audio/x-raw,rate=24000 ! appsink name=mic emit-signals=true sync=false max-buffers=5",&error);
    if(error||!pipeline)return 2;
    auto *source=gst_bin_get_by_name(GST_BIN(pipeline),"fixture"),*sink=gst_bin_get_by_name(GST_BIN(pipeline),"mic");
    auto *bus=gst_element_get_bus(pipeline);
    gst_bus_set_sync_handler(bus,+[](GstBus *,GstMessage *message,gpointer ptr)->GstBusSyncReply{
        auto *s=static_cast<Session *>(ptr);
        if(GST_MESSAGE_TYPE(message)==GST_MESSAGE_ELEMENT){
            auto *structure=gst_message_get_structure(message);gboolean active=false;
            if(structure&&gst_structure_has_name(structure,"voice-activity")&&gst_structure_get_boolean(structure,"stream-has-voice",&active))
                QMetaObject::invokeMethod(s,[s,active]{s->onSpeech(active);},Qt::QueuedConnection);
        } else if(GST_MESSAGE_TYPE(message)==GST_MESSAGE_ERROR)QMetaObject::invokeMethod(s,[]{QCoreApplication::exit(2);},Qt::QueuedConnection);
        gst_message_unref(message);return GST_BUS_DROP;
    },&session,nullptr);gst_object_unref(bus);
    // Use the same callback as the production microphone, on its owning Qt thread.
    g_signal_connect(sink,"new-sample",G_CALLBACK(+[](GstAppSink *sink,gpointer ptr)->GstFlowReturn{
        auto *s=static_cast<Session *>(ptr);auto *sample=gst_app_sink_pull_sample(sink);if(!sample)return GST_FLOW_EOS;
        GstMapInfo map;auto *buffer=gst_sample_get_buffer(sample);QByteArray data;
        if(gst_buffer_map(buffer,&map,GST_MAP_READ)){data=QByteArray(reinterpret_cast<const char *>(map.data),map.size);gst_buffer_unmap(buffer,&map);}gst_sample_unref(sample);
        QMetaObject::invokeMethod(s,[s,data]{if(s->audio.microphone)s->audio.microphone(data);},Qt::QueuedConnection);return GST_FLOW_OK;
    }),&session);gst_object_unref(sink);gst_element_set_state(pipeline,GST_STATE_PLAYING);
    int index=-1,offset=0;quint64 samples=0;bool waiting=false,advancing=false,holding=false;
    QStringList functions,spoken;QJsonArray actions;QString mainResponse,transcript;QByteArray input;
    qint64 endInput=-1,firstAudio=-1,holdStart=0;
    std::function<void()> next=[&]{
        ++index;functions.clear();spoken.clear();actions={};mainResponse.clear();transcript.clear();input.clear();offset=0;endInput=firstAudio=-1;waiting=false;advancing=false;
        if(index>=cases.size()){
            if(holdMinutes){holding=true;holdStart=session.clock.elapsed();print({{"type","hold-start"},{"minutes",holdMinutes}});}
            else {session.stop();app.quit();}return;
        }
        auto c=cases[index].toObject();
        if(!c["audio_file"].toString().isEmpty()){
            QFile f(c["audio_file"].toString());if(!f.open(QIODevice::ReadOnly)){app.exit(2);return;}input=f.readAll();
        }else session.command("SendPhoneText",{{"conversationId",session.conversation},{"text",c["text"]}},[](QJsonObject){});
        waiting=true;
    };
    QTimer feeder;feeder.setInterval(20);
    QObject::connect(&feeder,&QTimer::timeout,&app,[&]{
        QByteArray data(960,0);
        if(offset<input.size()){data=input.mid(offset,960);offset+=data.size();if(offset==input.size())endInput=session.clock.elapsed();}
        auto *buffer=gst_buffer_new_allocate(nullptr,data.size(),nullptr);gst_buffer_fill(buffer,0,data.data(),data.size());GST_BUFFER_PTS(buffer)=samples*GST_SECOND/24000;GST_BUFFER_DURATION(buffer)=quint64(data.size()/2)*GST_SECOND/24000;samples+=data.size()/2;gst_app_src_push_buffer(GST_APP_SRC(source),buffer);
        // Consume simulated playback at the production pace. No sound reaches a device.
        if(!session.playback.pending.isEmpty()&&!session.localSpeech){auto n=qMin(960,session.playback.pending.size());session.playback.pending.remove(0,n);session.lastPlaybackPush=session.clock.elapsed();}
        if(holding&&session.clock.elapsed()-holdStart>=holdMinutes*60000){print({{"type","hold-complete"},{"seconds",double(session.clock.elapsed()-holdStart)/1000},{"connected",session.connected},{"configured",session.configured}});session.stop();app.quit();}
    });feeder.start();
    QTimer heartbeat;heartbeat.setInterval(60000);QObject::connect(&heartbeat,&QTimer::timeout,&app,[&]{if(holding)print({{"type","heartbeat"},{"seconds",double(session.clock.elapsed()-holdStart)/1000},{"connected",session.connected},{"configured",session.configured}});});heartbeat.start();
    session.output=[&](QJsonObject o){
        if(o["type"]=="event"){
            auto e=o["event"].toObject();if(e["type"]=="message"&&e["role"]=="user")transcript=e["text"].toString();
            if(e["type"]=="message"&&e["role"]=="assistant")spoken.append(e["text"].toString());
            if(e["type"]=="phone-notice")print(e,stderr);
        }
        if(o["type"]=="rpc"){
            const auto method=o["method"].toString();auto p=o["params"].toObject();QJsonObject r;
            actions.append(QJsonObject{{"method",method},{"params",p},{"during_input",offset<input.size()}});
            if(method=="thread/start")r={{"thread",QJsonObject{{"id","thread_"+p["taskId"].toString()}}}};
            else if(method=="turn/start")r={{"turn",QJsonObject{{"id","turn_"+p["taskId"].toString()}}}};
            QTimer::singleShot(0,&session,[&,o,r,method,p]{session.receive({{"type","rpc-result"},{"id",o["id"]},{"result",r}});if(method=="turn/interrupt")session.notification("turn/completed",{{"threadId",p["threadId"]},{"turn",QJsonObject{{"id",p["turnId"]},{"status","interrupted"}}}});});
        }
    };
    QObject::connect(&session.ws,&QWebSocket::textMessageReceived,&app,[&](QString text){
        auto o=QJsonDocument::fromJson(text.toUtf8()).object();const auto type=o["type"].toString();
        if(type=="session.updated"&&index<0)QTimer::singleShot(0,&app,next);
        if(waiting&&type=="response.created"){auto rid=o["response"].toObject()["id"].toString();auto c=session.responses.value(rid);if(c.generation==session.generation&&!c.progress)mainResponse=rid;}
        if(waiting&&type=="response.output_audio.delta"&&firstAudio<0&&endInput>=0&&session.playback.response==o["response_id"].toString()&&!session.localSpeech)firstAudio=session.clock.elapsed();
        if(waiting&&type=="response.function_call_arguments.done")functions.append(o["name"].toString());
        if(waiting&&type=="response.done"&&o["response"].toObject()["id"].toString()==mainResponse&&!advancing){
            advancing=true;
            QTimer::singleShot(1500,&app,[&]{print({{"case",cases[index]},{"transcript",transcript},{"spoken",QJsonArray::fromStringList(spoken)},{"functions",QJsonArray::fromStringList(functions)},{"actions",actions},{"tasks",session.tasks.snapshot()},{"firstCloudAudioAfterInputMs",firstAudio>=0&&endInput>=0?double(firstAudio-endInput):-1}});next();});
        }
        if(type=="error")print(o,stderr);
    });
    QObject::connect(&session.ws,&QWebSocket::disconnected,&app,[&]{if(holding||waiting)app.exit(1);});
    QNetworkRequest request(QUrl("wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1-mini"));request.setRawHeader("Authorization","Bearer "+key.readAll().trimmed());session.ws.open(request);
    QTimer::singleShot(180000+holdMinutes*60000,&app,[&]{session.stop();app.exit(1);});int result=app.exec();gst_element_set_state(pipeline,GST_STATE_NULL);gst_object_unref(source);gst_object_unref(pipeline);return result;
}
