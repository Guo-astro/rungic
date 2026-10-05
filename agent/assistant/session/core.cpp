// SPDX-License-Identifier: GPL-2.0-or-later
#include "core.h"
#include <QUuid>
QJsonObject Task::json() const {
    return {{"question",question},{"input",input},{"taskId",id},{"conversation",conversation},{"threadId",thread},{"turnId",turn},{"text",text},{"status",status},{"result",result},{"readOnly",readOnly},{"created",double(created)},{"requestKey",requestKey},{"shared",shared}};
}
bool Task::terminal() const{return status=="completed"||status=="stopped"||status=="failed"||status=="interrupted";}
bool Task::active() const{return status=="starting"||status=="running"||status=="stopping"||status=="waiting_input";}
QString Tasks::add(QString text,bool readOnly,QString conversation,QString requestKey) {
    for(const auto &t:rows)if(t.requestKey==requestKey&&!requestKey.isEmpty())return t.id;
    // Keep the live registry bounded; full conversation history remains in the store.
    while(rows.size()>=128){int old=-1;for(int i=0;i<rows.size();++i)if(rows[i].terminal()){old=i;break;}if(old<0)return {};rows.removeAt(old);}
    Task t;t.id="task_"+QUuid::createUuid().toString(QUuid::Id128);t.text=text;t.readOnly=readOnly;t.conversation=conversation;t.requestKey=requestKey;
    t.shared=!readOnly;      // acting work goes to the conversation's thread (the adapter says otherwise if not)
    rows.append(t);focused=t.id;return t.id;
}
Task *Tasks::find(const QString &id){for(auto &t:rows)if(t.id==id)return &t;return nullptr;}
Task *Tasks::byThread(const QString &thread){if(thread.isEmpty())return nullptr;for(auto &t:rows)if(t.thread==thread)return &t;return nullptr;}
Task *Tasks::target(const QString &id){
    if(!id.isEmpty())return find(id);
    if(auto *t=find(focused);t&&!t->terminal())return t;
    Task *only=nullptr;for(auto &t:rows)if(!t.terminal()){if(only)return nullptr;only=&t;}return only;
}
// A task that may act goes to the conversation's own thread, push-to-talk's (phone_session.py):
// there it starts a turn or joins the one running, so it never waits for another (a cast waited
// behind a Krita drawing, 2026-10-05). Read-only tasks run beside it, two at most.
QList<QString> Tasks::schedule(){
    int reading=0;
    for(const auto &t:rows)if(t.active()&&t.readOnly)++reading;
    QList<QString> admitted;
    for(auto &t:rows)if(t.status=="queued"){
        if(t.readOnly){if(reading>=2)continue;++reading;}
        t.status="starting";admitted.append(t.id);
    }
    return admitted;
}
QList<Task *> Tasks::onThread(const QString &thread){
    QList<Task *> found;if(thread.isEmpty())return found;
    for(auto &t:rows)if(t.thread==thread&&!t.terminal())found.append(&t);
    return found;
}
bool Tasks::stop(const QString &id){
    auto *t=target(id);if(!t)return false;if(t->terminal())return true;
    t->cancelRequested=true;
    if(t->status=="queued"){t->status="stopped";t->backendStopped=true;}
    else t->status="stopping";
    return true;
}
QJsonArray Tasks::snapshot(const QString &conversation) const{QJsonArray a;for(const auto &t:rows)if(conversation.isEmpty()||t.conversation==conversation)a.append(t.json());return a;}
void Tasks::restore(QJsonArray saved){
    rows.clear();focused.clear();for(auto v:saved){auto o=v.toObject();Task t;t.id=o["taskId"].toString();if(t.id.isEmpty()||t.id.contains('/'))continue;
        t.input=o["input"].toArray();t.conversation=o["conversation"].toString();t.thread=o["threadId"].toString();t.turn=o["turnId"].toString();t.text=o["text"].toString();t.result=o["result"].toString();t.readOnly=o["readOnly"].toBool();t.status=o["status"].toString();t.created=qint64(o["created"].toDouble());t.requestKey=o["requestKey"].toString();t.shared=o["shared"].toBool();
        // Never replay work after a restart. The bridge reconciles loaded thread status.
        if(!t.terminal())t.status="interrupted";rows.append(t);
    }
}
bool ReplyBuffer::append(QString responseId,QString itemId,const QByteArray &data){
    if(retired.contains(responseId)||(cancelled&&responseId==response))return true;
    if(responseId!=response){if(!response.isEmpty())retired.insert(response);response=responseId;item=itemId;pending.clear();cancelled=false;full=false;++generation;}
    if(full)return true;
    // The model streams a spoken reply faster than it plays, so a long one (a story, a game's turn)
    // runs ahead of playback by minutes. Half an hour ahead (about 86 MB) bounds memory; past it the
    // reply is cut where the buffered audio ends (false, once), never the conversation: a 30 s bound
    // that stopped the session ended Kevin's game ("Reply audio exceeded the buffer limit", 2026-10-05).
    if(pending.size()+data.size()>MaxPendingBytes){full=true;return false;}
    pending+=data;return true;
}
void ReplyBuffer::clear(){pending.clear();if(!response.isEmpty())retired.insert(response);cancelled=true;++generation;}
