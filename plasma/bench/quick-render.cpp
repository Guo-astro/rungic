// SPDX-License-Identifier: MIT
// Diagnostic workload only. Backend chosen by QSG_RHI_BACKEND, no global changes.
#include <QGuiApplication>
#include <QQuickView>
#include <QQuickItem>
#include <QSGRendererInterface>
#include <QSurfaceFormat>
#include <QTimer>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QFile>
#include <QMutex>
#include <QMutexLocker>
#include <QElapsedTimer>
#include <sys/resource.h>

static double cpuMs() {
    rusage r{}; getrusage(RUSAGE_SELF, &r);
    return (r.ru_utime.tv_sec+r.ru_stime.tv_sec)*1000.0
        + (r.ru_utime.tv_usec+r.ru_stime.tv_usec)/1000.0;
}
int main(int argc, char **argv) {
    QSurfaceFormat format; format.setRenderableType(QSurfaceFormat::OpenGLES);
    format.setVersion(3,2); format.setSwapInterval(1);
    QSurfaceFormat::setDefaultFormat(format);
    QGuiApplication app(argc,argv);
    if (argc != 3) return 2;
    QQuickView view; view.setTitle("Moto GPU benchmark");
    view.setResizeMode(QQuickView::SizeRootObjectToView);
    view.setSource(QUrl::fromLocalFile(argv[1]));
    if (view.status() == QQuickView::Error) return 3;
    QElapsedTimer timer; timer.start();
    QMutex mutex; bool active=false;
    double cpuStart=0, startMs=0, renderStart=0;
    QJsonArray frames, renderDurations, displays;
    QTimer displayTimer;
    QObject::connect(&displayTimer,&QTimer::timeout,&view,[&]{
        QMutexLocker lock(&mutex);
        if(!active) return;
        QFile input("/mnt/android-wayland/android-display.json");
        if(input.open(QIODevice::ReadOnly)) {
            auto value=QJsonDocument::fromJson(input.readAll()).object();
            value.insert("sample_ms",timer.nsecsElapsed()/1e6);
            displays.append(value);
        }
    });
    displayTimer.start(500);
    QObject::connect(&view,&QQuickWindow::beforeRendering,&view,[&]{
        QMutexLocker lock(&mutex); renderStart=timer.nsecsElapsed()/1e6;
    },Qt::DirectConnection);
    QObject::connect(&view,&QQuickWindow::afterRendering,&view,[&]{
        QMutexLocker lock(&mutex);
        if(active) renderDurations.append(timer.nsecsElapsed()/1e6-renderStart);
    },Qt::DirectConnection);
    QObject::connect(&view,&QQuickWindow::frameSwapped,&view,[&]{
        QMutexLocker lock(&mutex);
        if(active) frames.append(timer.nsecsElapsed()/1e6);
    },Qt::DirectConnection);
    view.showMaximized();
    QTimer::singleShot(4000,Qt::PreciseTimer,&view,[&]{
        QMutexLocker lock(&mutex); cpuStart=cpuMs();
        startMs=timer.nsecsElapsed()/1e6; active=true;
    });
    QTimer::singleShot(16000,Qt::PreciseTimer,&view,[&]{
        QJsonObject result;
        {
            QMutexLocker lock(&mutex); active=false;
            result={{"requested_backend",qEnvironmentVariable("QSG_RHI_BACKEND")},
                {"graphics_api",int(view.rendererInterface()->graphicsApi())},
                {"width",view.width()},{"height",view.height()},
                {"dpr",view.devicePixelRatio()},
                {"elapsed_ms",timer.nsecsElapsed()/1e6-startMs},
                {"cpu_ms",cpuMs()-cpuStart},{"swapped_ms",frames},
                {"render_command_ms",renderDurations},{"display_samples",displays}};
        }
        QFile output(argv[2]);
        if(!output.open(QIODevice::WriteOnly)) app.exit(4);
        else {output.write(QJsonDocument(result).toJson()); app.quit();}
    });
    return app.exec();
}
