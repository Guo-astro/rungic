// SPDX-License-Identifier: GPL-2.0-or-later
// A task-owned MCP worker. Cancelling kills only its private process group, never user apps.
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QProcessEnvironment>
#include <QRegularExpression>
#include <QSaveFile>
#include <QSocketNotifier>
#include <QTimer>
#include <fcntl.h>
#include <signal.h>
#include <sys/prctl.h>
#include <unistd.h>

static QByteArray line(const QJsonObject &o){return QJsonDocument(o).toJson(QJsonDocument::Compact)+'\n';}
// starttime is field 22; comm can contain spaces or closing parentheses.
static QByteArray startTime(qint64 pid){QFile f(QString("/proc/%1/stat").arg(pid));if(!f.open(QIODevice::ReadOnly))return {};auto data=f.readAll();return data.mid(data.lastIndexOf(')')+2).split(' ').value(19);}
class TaskTools : public QObject {
public:
    QFile input,output;QSocketNotifier *watch;QProcess child;QTimer check;
    QString task,leasePath,statusPath;QByteArray buffer,childBuffer;QHash<QString,QJsonValue> pending;
    bool stopped=false,closing=false;
    qint64 workerGroup=0;
    TaskTools(QString id,QStringList cmd):task(id) {
        leasePath=QString::fromLocal8Bit(qgetenv("XDG_RUNTIME_DIR"))+"/rungic-task-leases/"+task+".json";statusPath=leasePath+".tools";
        input.open(STDIN_FILENO,QIODevice::ReadOnly,QFileDevice::DontCloseHandle);output.open(STDOUT_FILENO,QIODevice::WriteOnly,QFileDevice::DontCloseHandle);
        ::fcntl(STDIN_FILENO,F_SETFL,::fcntl(STDIN_FILENO,F_GETFL)|O_NONBLOCK);
        watch=new QSocketNotifier(STDIN_FILENO,QSocketNotifier::Read,this);
        child.setChildProcessModifier([]{::setpgid(0,0);::prctl(PR_SET_PDEATHSIG,SIGKILL);});
        auto env=QProcessEnvironment::systemEnvironment();env.insert("RUNGIC_TASK_ID",task);child.setProcessEnvironment(env);
        connect(&child,&QProcess::started,this,[this]{workerGroup=child.processId();});
        connect(watch,&QSocketNotifier::activated,this,[this]{read();});
        connect(&child,&QProcess::readyReadStandardOutput,this,[this]{
            childBuffer+=child.readAllStandardOutput();
            while(childBuffer.contains('\n')){
                int at=childBuffer.indexOf('\n');auto data=childBuffer.left(at);childBuffer.remove(0,at+1);
                auto o=QJsonDocument::fromJson(data).object();if(o.contains("id")&&!o.contains("method"))pending.remove(key(o["id"]));
                output.write(data+'\n');output.flush();status();
            }
            if(childBuffer.size()>32*1024*1024)cancel();
        });
        connect(&child,&QProcess::readyReadStandardError,this,[this]{child.readAllStandardError();});
        connect(&child,qOverload<int,QProcess::ExitStatus>(&QProcess::finished),this,[this](int,QProcess::ExitStatus){
            if(!stopped)cancel();status();
        });
        child.setProgram(cmd.takeFirst());child.setArguments(cmd);child.start();
        check.setInterval(25);connect(&check,&QTimer::timeout,this,[this]{if(!pending.isEmpty()&&!validLease())cancel();});check.start();status();
    }
    ~TaskTools(){cancel();QFile::remove(statusPath);}
    QString key(QJsonValue id){return QString::fromUtf8(QJsonDocument(QJsonArray{id}).toJson(QJsonDocument::Compact));}
    bool validLease(){
        QFile f(leasePath);if(!f.open(QIODevice::ReadOnly))return false;auto o=QJsonDocument::fromJson(f.readAll()).object();
        qint64 pid=qint64(o["pid"].toDouble());
        return o["taskId"].toString()==task && o["exclusive"].toBool() && pid>0 && o["startTime"].toString().toLatin1()==startTime(pid);
    }
    void status(){
        QSaveFile f(statusPath);if(f.open(QIODevice::WriteOnly)){f.setPermissions(QFileDevice::ReadOwner|QFileDevice::WriteOwner);f.write(line({{"pid",double(QCoreApplication::applicationPid())},{"startTime",QString::fromLatin1(startTime(QCoreApplication::applicationPid()))},{"active",!pending.isEmpty()},{"stopped",stopped}}));f.commit();}
    }
    void error(QJsonValue id,const QString &message){
        QJsonObject result{{"isError",true},{"content",QJsonArray{QJsonObject{{"type","text"},{"text",message}}}}};
        output.write(line(QJsonObject{{"jsonrpc","2.0"},{"id",id},{"result",result}}));output.flush();
    }
    void cancel(){
        if(stopped)return;stopped=true;
        const auto pid=workerGroup?workerGroup:child.processId();if(pid>0){
            ::kill(-pid,SIGTERM);if(child.state()!=QProcess::NotRunning)child.waitForFinished(150);
            // The worker can exit before a descendant which ignores SIGTERM.
            // Finish its private group even when waitForFinished already succeeded.
            if(::kill(-pid,0)==0)::kill(-pid,SIGKILL);
            if(child.state()!=QProcess::NotRunning)child.waitForFinished(1000);
        }
        auto ids=pending;pending.clear();for(auto id:ids)error(id,"Task cancelled; no further desktop actions were performed");status();
    }
    void read(){
        char data[16384];ssize_t n;while((n=::read(STDIN_FILENO,data,sizeof(data)))>0)buffer.append(data,n);
        if(n==0){watch->setEnabled(false);cancel();QCoreApplication::quit();return;}
        if(buffer.size()>4*1024*1024){cancel();QCoreApplication::quit();return;}
        while(buffer.contains('\n')){
            int at=buffer.indexOf('\n');auto data=buffer.left(at);buffer.remove(0,at+1);auto o=QJsonDocument::fromJson(data).object();
            auto method=o["method"].toString();
            if(method=="notifications/cancelled"){
                if(pending.contains(key(o["params"].toObject()["requestId"])))cancel();continue;
            }
            if(method=="tools/call"){
                if(stopped||!validLease()){error(o["id"],"Task has no desktop operation lease");continue;}
                pending[key(o["id"])]=o["id"];status();
            }
            if(stopped){if(o.contains("id"))error(o["id"],"Task worker stopped");continue;}
            child.write(data+'\n');
        }
    }
};
int main(int argc,char **argv){
    QCoreApplication app(argc,argv);auto args=app.arguments();args.removeFirst();
    if(args.size()<4||args.takeFirst()!="--task")return 2;QString task=args.takeFirst();
    if(!QRegularExpression("^[A-Za-z0-9_-]{1,80}$").match(task).hasMatch()||args.takeFirst()!="--"||args.isEmpty())return 2;
    TaskTools tools(task,args);return app.exec();
}
