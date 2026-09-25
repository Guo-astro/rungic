#include <QGuiApplication>
#include <QScreen>
#include <QDebug>
int main(int argc,char**argv){QGuiApplication a(argc,argv);for(auto s:a.screens())qInfo()<<s->name()<<s->geometry()<<s->devicePixelRatio()<<s->refreshRate();}
