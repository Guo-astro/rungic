// SPDX-License-Identifier: GPL-2.0-or-later
// A picture from a file, still or moving (docs/88). Image reads it off the UI thread and counts
// its frames; one with more than one (a GIF, an animated WebP) is then played by an
// AnimatedImage over it, which takes over once its first frame is up. Multi-page formats (TIFF,
// icons) stay on their first page. Playing pauses while the picture is hidden or its window is.
// `status`, the implicit size and `sourceSize` are the still picture's, as for an Image.
import QtQuick

Item {
    id: picture
    property url source
    property alias sourceSize: still.sourceSize
    property alias fillMode: still.fillMode
    property alias smooth: still.smooth
    readonly property alias status: still.status
    readonly property bool animated: still.status === Image.Ready && still.frameCount > 1
        && !/\.(tiff?|ico|icns|cur)$/i.test(String(source))
    // The frames are shown (the still picture is under them, hidden).
    readonly property bool moving: player.item !== null && player.item.shown
    readonly property bool onScreen: visible && Window.visibility !== Window.Hidden && Window.visibility !== Window.Minimized
    implicitWidth: still.implicitWidth
    implicitHeight: still.implicitHeight

    Image {
        id: still
        anchors.fill: parent
        source: picture.source
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        smooth: true
        visible: !picture.moving
    }
    Loader {
        id: player
        anchors.fill: parent
        active: picture.animated
        sourceComponent: AnimatedImage {
            // QMovie scales every frame to exactly sourceSize, with no aspect ratio of its own,
            // and a changed sourceSize reloads the file. So the frames are first read at their
            // own size, and only a larger file gets the still picture's size, never a smaller.
            property bool settled: false
            readonly property bool shown: settled && status === AnimatedImage.Ready
            source: picture.source
            fillMode: still.fillMode
            smooth: still.smooth
            // One frame in memory at a time, not all of them.
            cache: false
            paused: !picture.onScreen
            onStatusChanged: {
                if (status !== AnimatedImage.Ready || settled)
                    return
                settled = true
                if (implicitWidth > still.implicitWidth + 1)
                    sourceSize = Qt.size(still.implicitWidth, still.implicitHeight)
            }
        }
    }
}
