#include <QCoreApplication>
#include <QDebug>
#include <KApplicationTrader>
#include <KService>
#include <KSycoca>
int main(int argc,char**argv){QCoreApplication app(argc,argv); qInfo()<<"cache"<<KSycoca::self()->absoluteFilePath(); auto all=KApplicationTrader::query({});qInfo()<<"applications"<<all.size();for(auto s:all) qInfo()<<s->storageId()<<s->name()<<s->noDisplay()<<s->showOnCurrentPlatform();}
