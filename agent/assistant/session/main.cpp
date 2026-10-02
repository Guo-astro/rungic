// SPDX-License-Identifier: GPL-2.0-or-later
#include "session.h"
#include <QCoreApplication>
#include <QFile>
#include <QJsonDocument>
#include <QSocketNotifier>
#include <fcntl.h>
#include <unistd.h>
int main(int argc,char **argv){
    QCoreApplication app(argc,argv);gst_init(&argc,&argv);
    QFile out;out.open(STDOUT_FILENO,QIODevice::WriteOnly,QFileDevice::DontCloseHandle);
    Session session;session.output=[&out](QJsonObject o){out.write(QJsonDocument(o).toJson(QJsonDocument::Compact)+'\n');out.flush();};
    QByteArray buffer;::fcntl(STDIN_FILENO,F_SETFL,::fcntl(STDIN_FILENO,F_GETFL)|O_NONBLOCK);
    QSocketNotifier input(STDIN_FILENO,QSocketNotifier::Read);
    QObject::connect(&input,&QSocketNotifier::activated,&app,[&]{
        char bytes[16384];ssize_t n;while((n=::read(STDIN_FILENO,bytes,sizeof(bytes)))>0)buffer.append(bytes,n);
        if(n==0){session.stop();app.quit();return;}
        if(buffer.size()>8*1024*1024){session.stop("Control input overflow");app.quit();return;}
        while(buffer.contains('\n')){
            int at=buffer.indexOf('\n');auto data=buffer.left(at);buffer.remove(0,at+1);QJsonParseError error;
            auto doc=QJsonDocument::fromJson(data,&error);if(error.error==QJsonParseError::NoError)session.receive(doc.object());
        }
    });
    return app.exec();
}
