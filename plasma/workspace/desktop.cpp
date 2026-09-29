// rungic-workspace-desktop [IMAGE]: the background of an agent workspace (docs/research/91).
//
// A workspace runs KWin alone, without Plasma's shell: where no window is, its output is
// transparent (alpha 0). The floating window then showed nothing at all, and a TV would show
// whatever lies beneath. This fills the workspace's output with a wallpaper in the background
// layer, under every window: IMAGE, else the user's own Plasma wallpaper (the phone's), else
// Plasma's default (Next); from a wallpaper package the landscape picture nearest the screen's
// shape. Without any, a quiet gradient. Started by rungic-workspace with the workspace's KWin;
// it ends with it.
#include <LayerShellQt/Window>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QImageReader>
#include <QLinearGradient>
#include <QPainter>
#include <QRasterWindow>
#include <QRegularExpression>
#include <QTextStream>
#include <QUrl>
#include <cmath>

namespace
{
// The wallpaper the user's Plasma shows: the first Image= of the mobile shell's (or the
// desktop's) containments, a file or a wallpaper package.
QString userWallpaper()
{
    // The workspace's KWin has settings of its own (rungic-workspace): the user's are elsewhere.
    const QString config = qEnvironmentVariable("RUNGIC_USER_CONFIG_HOME", QDir::homePath() + QStringLiteral("/.config"));
    for (const QString name : {QStringLiteral("plasma-org.kde.plasma.mobileshell-appletsrc"),
                               QStringLiteral("plasma-org.kde.plasma.desktop-appletsrc")}) {
        QFile file(config + QLatin1Char('/') + name);
        if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
            continue;
        QTextStream stream(&file);
        while (!stream.atEnd()) {
            const QString line = stream.readLine().trimmed();
            if (line.startsWith(QLatin1String("Image="))) {
                const QString value = line.mid(6);
                return value.startsWith(QLatin1String("file:")) ? QUrl(value).toLocalFile() : value;
            }
        }
    }
    return QStringLiteral("/usr/share/wallpapers/Next");
}

// From a wallpaper package (contents/images/<W>x<H>.<ext>): the picture whose shape is nearest
// `screen`'s, the smallest of those at least as large.
QString packagePicture(const QString &package, const QSize &screen)
{
    const QDir images(package + QStringLiteral("/contents/images"));
    const QRegularExpression size(QStringLiteral("^(\\d+)x(\\d+)\\."));
    const double want = double(screen.width()) / screen.height();
    QString best;
    double bestShape = 1e9;
    qint64 bestArea = 0;
    for (const QString &name : images.entryList(QDir::Files)) {
        const auto match = size.match(name);
        if (!match.hasMatch())
            continue;
        const int w = match.captured(1).toInt(), h = match.captured(2).toInt();
        const double shape = std::abs(std::log((double(w) / h) / want));
        const qint64 area = qint64(w) * h;
        const bool bigEnough = w >= screen.width() && h >= screen.height();
        const bool better = shape < bestShape - 0.01
            || (std::abs(shape - bestShape) <= 0.01 && bigEnough && (bestArea == 0 || area < bestArea));
        if (better) {
            best = images.filePath(name);
            bestShape = shape;
            bestArea = area;
        }
    }
    return best;
}
}

class Desktop : public QRasterWindow
{
public:
    explicit Desktop(const QString &source)
        : m_source(source)
    {
    }

protected:
    void resizeEvent(QResizeEvent *) override
    {
        m_picture = QImage();
        QString path = m_source;
        if (QFileInfo(path).isDir())
            path = packagePicture(path, size());
        if (path.isEmpty())
            return;
        // Only this size is kept: a 5120x2880 picture is decoded once and dropped.
        QImage image = QImageReader(path).read();
        if (image.isNull())
            return;
        image = image.scaled(size(), Qt::KeepAspectRatioByExpanding, Qt::SmoothTransformation);
        m_picture = image.copy((image.width() - width()) / 2, (image.height() - height()) / 2, width(), height());
    }

    void paintEvent(QPaintEvent *) override
    {
        QPainter painter(this);
        if (!m_picture.isNull()) {
            painter.drawImage(0, 0, m_picture);
            return;
        }
        // Breeze dark, a little lighter at the top, like a quiet desktop.
        QLinearGradient gradient(0, 0, 0, height());
        gradient.setColorAt(0, QColor(0x2a, 0x2e, 0x32));
        gradient.setColorAt(1, QColor(0x14, 0x16, 0x18));
        painter.fillRect(QRect(QPoint(0, 0), size()), gradient);
    }

private:
    QString m_source;
    QImage m_picture;
};

int main(int argc, char *argv[])
{
    qputenv("QT_QPA_PLATFORM", "wayland");
    QGuiApplication app(argc, argv);
    QGuiApplication::setDesktopFileName(QStringLiteral("com.rungic.WorkspaceDesktop"));
    Desktop desktop(argc > 1 ? QString::fromLocal8Bit(argv[1]) : userWallpaper());
    auto layer = LayerShellQt::Window::get(&desktop);
    layer->setScope(QStringLiteral("desktop"));
    layer->setLayer(LayerShellQt::Window::LayerBackground);
    layer->setAnchors(LayerShellQt::Window::Anchors(LayerShellQt::Window::AnchorTop | LayerShellQt::Window::AnchorBottom
                                                    | LayerShellQt::Window::AnchorLeft | LayerShellQt::Window::AnchorRight));
    layer->setExclusiveZone(-1);
    layer->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
    desktop.show();
    return app.exec();
}
