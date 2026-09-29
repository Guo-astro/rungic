// SPDX-License-Identifier: GPL-2.0-or-later
// The composer (docs/87). Voice first: the whole bar can be held to talk, a tap listens
// hands-free. While held, sliding up onto × drops what was said and onto 文 turns it into
// text to edit. The keyboard button switches to typing; + adds photos or files.
//
// It is always in exactly one state (`phase`), and each state says, in one place (`states`),
// which parts show, what the bar says and whether the keyboard is up:
//   voice         idle: + · 按住说话 · keyboard
//   busy          the agent works or speaks: + · 按住补充说明 · stop
//   unavailable   the user is on a call themselves
//   hold          held: the wave, the time, the two targets above
//   cancel        held over ×
//   toText        held over 文
//   transcribing  released over 文, the text is on its way
//   handsFree     listening without a hold: the wave · 说完自动发送 · stop
//   keyboard      typing (attachments above the text)
//   attach        the + panel in the keyboard's place (the bar the user came from; keyboard down)
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import QtCore
import Qt.labs.folderlistmodel
import com.rungic.design

Item {
    id: composer
    property var chat
    property bool busy: false
    property bool speaking: false
    property bool canTalk: true
    property real micLevel: -90
    property var attachments: []              // [{path, name, kind}]
    signal talkPressed()
    signal talkReleased(string zone)
    signal handsFreeStopped()
    signal sendRequested(string text, var attachments)
    signal stopRequested()

    // What the user is doing (inputs to the state).
    property bool holding: false
    property string zone: ""                  // while held: "" send, "cancel", "text"
    property bool keyboard: false             // typing rather than talking
    property bool attachOpen: false
    property bool dictation: false            // the field holds what was said, to edit
    property bool transcribing: false
    readonly property bool inCall: chat ? chat.inCall : false

    // The one state it is in.
    property string forcedState: ""
    readonly property string phase: forcedState !== "" ? forcedState
        : holding ? (zone === "cancel" ? "cancel" : zone === "text" ? "toText" : "hold")
        : transcribing ? "transcribing"
        : chat && chat.handsFree ? "handsFree"
        : attachOpen ? "attach"
        : keyboard ? "keyboard"
        : !canTalk ? "unavailable"
        : busy || speaking ? "busy" : "voice"
    state: phase

    // What each state shows (the defaults are the idle voice bar's).
    property string barMode: "idle"
    property string label: inCall ? "按住回答助理" : "按住说话"
    property string foot: inCall ? "对方听不到你对助理说的话" : "按住说话 · 轻点免提"
    property bool showVoice: true
    property bool showText: false
    property bool showPanel: false
    property bool showTargets: false
    property bool showWave: false
    property bool showTimer: false
    property bool showHandsFree: false
    property bool showStop: false
    property bool showKeyboardButton: true
    property bool showPlus: true
    property bool canHold: true
    states: [
        State { name: "voice" },
        State {
            name: "busy"
            PropertyChanges { composer.label: "按住补充说明"; composer.foot: "轻点右边停止"; composer.showKeyboardButton: false; composer.showStop: true }
        },
        State {
            name: "unavailable"
            PropertyChanges { composer.barMode: "disabled"; composer.label: "你正在通话中"; composer.foot: ""; composer.canHold: false; composer.showKeyboardButton: false; composer.showPlus: false }
        },
        State {
            name: "hold"
            PropertyChanges { composer.barMode: "hot"; composer.foot: "上滑到 × 取消 · 上滑到“文”改成文字"; composer.showTargets: true; composer.showWave: true; composer.showTimer: true; composer.showKeyboardButton: false; composer.showPlus: false }
        },
        State {
            name: "cancel"; extend: "hold"
            PropertyChanges { composer.barMode: "cancel" }
        },
        State {
            name: "toText"; extend: "hold"
        },
        State {
            name: "transcribing"
            PropertyChanges { composer.barMode: "disabled"; composer.label: "正在转成文字…"; composer.foot: ""; composer.canHold: false; composer.showKeyboardButton: false; composer.showPlus: false }
        },
        State {
            name: "handsFree"
            PropertyChanges { composer.barMode: "handsFree"; composer.foot: "免提中 · 停顿约 1 秒后自动发送"; composer.canHold: false; composer.showWave: true; composer.showHandsFree: true; composer.showKeyboardButton: false; composer.showPlus: false }
        },
        State {
            name: "keyboard"
            PropertyChanges {
                composer.showVoice: false; composer.showText: true; composer.canHold: false
                composer.foot: composer.dictation ? "刚才说的话已转成文字，改好再发"
                             : composer.attachments.length > 0 ? "可以再加一句说明，或直接发送" : ""
            }
            StateChangeScript { script: field.forceActiveFocus() }
        },
        State {
            name: "attach"
            PropertyChanges {
                composer.showVoice: !composer.keyboard; composer.showText: composer.keyboard; composer.showPanel: true
                composer.foot: ""; composer.canHold: false; composer.showKeyboardButton: !composer.keyboard
            }
            // The panel takes the keyboard's place: the keyboard goes down first.
            StateChangeScript { script: { field.focus = false; Qt.inputMethod.hide() } }
        }
    ]

    implicitHeight: column.implicitHeight

    function reset() {
        holding = false; zone = ""; keyboard = false; attachOpen = false
        dictation = false; transcribing = false; attachments = []; field.text = ""
    }
    // What was said, back as text (TalkToText).
    function dictated(text) {
        transcribing = false
        if (!text) return
        dictation = true
        field.text = text
        keyboard = true
        field.cursorPosition = text.length
    }
    function submit() {
        const text = field.text.trim()
        if (!text && attachments.length === 0) return
        sendRequested(text, attachments)
        field.text = ""
        attachments = []
        dictation = false
    }
    function addAttachment(url) {
        const path = decodeURIComponent(url.toString().replace(/^file:\/\//, ""))
        if (attachments.some(a => a.path === path)) return
        const name = path.split("/").pop()
        const kind = /\.(png|jpe?g|webp|gif)$/i.test(name) ? "image" : "file"
        attachments = attachments.concat([{ path: path, name: name, kind: kind }])
    }
    function removeAttachment(path) { attachments = attachments.filter(a => a.path !== path) }
    // Attachments chosen: back to the text with them.
    function attached() { attachOpen = false; keyboard = true }

    readonly property real level: Math.max(0, Math.min(1, (micLevel + 55) / 35))
    property real heldSeconds: 0
    Timer { interval: 250; repeat: true; running: composer.holding; onTriggered: composer.heldSeconds += 0.25 }

    // ---- while held: what to slide onto, above the bar --------------------------------
    Item {
        id: holdLayer
        anchors { left: parent.left; right: parent.right; bottom: parent.top }
        height: targets.implicitHeight + 18 + 48
        visible: composer.showTargets
        // Fades in over the thread's bottom so the conversation stays visible.
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0; color: Theme.alpha(Theme.background, 0) }
                GradientStop { position: 48 / holdLayer.height; color: Theme.background }
            }
        }
        RowLayout {
            id: targets
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: 28; rightMargin: 28; bottomMargin: 18 }
            HoldTarget { id: cancelTarget; iconName: "close"; text: "取消"; on: composer.phase === "cancel" }
            Text {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
                text: composer.phase === "cancel" ? "松开取消" : composer.phase === "toText" ? "松开后改成文字编辑" : "松开发送"
                font.family: Theme.fontFamily
                font.pixelSize: 15
                font.weight: Font.DemiBold
                color: Theme.text
                wrapMode: Text.Wrap
            }
            HoldTarget { id: textTarget; iconName: "text"; text: "转文字"; edit: true; on: composer.phase === "toText" }
        }
    }

    ColumnLayout {
        id: column
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        spacing: 0

        Item {
            Layout.fillWidth: true
            implicitHeight: bars.implicitHeight + 8 + (composer.showPanel ? 8 : 20)
            // The talk gesture: the whole bar can be held; its buttons, above this, take their own taps.
            MouseArea {
                id: talkArea
                x: bars.x + voice.x
                y: bars.y + voice.y
                width: voice.width
                height: voice.height
                // A hold in progress keeps its gesture whatever the state says.
                enabled: composer.canHold || composer.holding
                visible: composer.showVoice
                preventStealing: true
                function zoneAt(mouse) {
                    const p = mapToItem(composer, mouse.x, mouse.y)
                    const near = (target) => {
                        const c = target.mapToItem(composer, target.width / 2, 30)
                        return Math.hypot(p.x - c.x, p.y - c.y) < 70
                    }
                    if (near(cancelTarget)) return "cancel"
                    if (near(textTarget)) return "text"
                    return ""
                }
                onPressed: {
                    composer.heldSeconds = 0
                    composer.zone = ""
                    composer.holding = true
                    composer.talkPressed()
                }
                onPositionChanged: mouse => { if (composer.holding) composer.zone = zoneAt(mouse) }
                onReleased: {
                    const zone = composer.zone
                    composer.holding = false
                    composer.zone = ""
                    if (zone === "text") composer.transcribing = true
                    composer.talkReleased(zone)
                }
                onCanceled: {
                    composer.holding = false
                    composer.zone = ""
                    composer.talkReleased("cancel")
                }
            }
            ColumnLayout {
                id: bars
                anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 8; leftMargin: 12; rightMargin: 12 }
                spacing: 8

                // ---- voice -------------------------------------------------------------
                VoiceBar {
                    id: voice
                    Layout.fillWidth: true
                    Layout.maximumWidth: Theme.readingWidth + 24
                    Layout.alignment: Qt.AlignHCenter
                    visible: composer.showVoice
                    mode: composer.barMode
                    Accessible.role: Accessible.Button
                    Accessible.name: composer.showWave ? "正在听" : composer.label

                    IconButton {
                        visible: composer.showPlus
                        iconName: composer.showPanel ? "close" : "plus"
                        text: composer.showPanel ? "收起" : "添加照片或文件"
                        tint: voice.ink
                        onClicked: composer.attachOpen = !composer.attachOpen
                    }
                    Wave {
                        visible: composer.showWave
                        Layout.fillWidth: true
                        Layout.leftMargin: composer.showTimer ? 14 : 8
                        Layout.rightMargin: 8
                        bars: Math.max(8, Math.floor((voice.width - 120) / 6))
                        barHeight: composer.showTimer ? 32 : 28
                        level: composer.level
                        active: composer.phase !== "cancel"
                        color: voice.ink
                        clip: true
                    }
                    Text {
                        visible: composer.showTimer
                        rightPadding: 14
                        leftPadding: 4
                        text: Math.floor(composer.heldSeconds / 60) + ":" + String(Math.floor(composer.heldSeconds) % 60).padStart(2, "0")
                        font.family: Theme.monoFamily
                        font.pixelSize: 13
                        color: voice.ink
                        opacity: 0.75
                    }
                    Text {
                        visible: composer.showHandsFree
                        rightPadding: 8
                        text: "说完自动发送"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.metaSize
                        color: Theme.dim
                    }
                    CircleButton {
                        visible: composer.showHandsFree
                        iconName: "stop"
                        text: "停止聆听"
                        onClicked: composer.handsFreeStopped()
                    }
                    // The bar's middle says what holding it does.
                    Text {
                        visible: !composer.showWave
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: composer.label
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySize
                        font.weight: Font.DemiBold
                        color: voice.ink
                    }
                    IconButton {
                        visible: composer.showKeyboardButton && !composer.showWave
                        iconName: "keyboard"
                        text: "用键盘输入"
                        tint: voice.ink
                        onClicked: { composer.attachOpen = false; composer.keyboard = true }
                    }
                    CircleButton {
                        visible: composer.showStop
                        iconName: "stop"
                        text: "停止"
                        onClicked: composer.stopRequested()
                    }
                }

                // ---- keyboard --------------------------------------------------------------
                TextBar {
                    Layout.fillWidth: true
                    Layout.maximumWidth: Theme.readingWidth + 24
                    Layout.alignment: Qt.AlignHCenter
                    visible: composer.showText
                    // Attachments waiting to go with the message.
                    Flickable {
                        Layout.fillWidth: true
                        visible: composer.attachments.length > 0
                        implicitHeight: 72
                        contentWidth: tray.implicitWidth
                        clip: true
                        Row {
                            id: tray
                            topPadding: 8
                            leftPadding: 6
                            spacing: 8
                            Repeater {
                                model: composer.attachments
                                Item {
                                    required property var modelData
                                    width: modelData.kind === "image" ? 64 : Math.min(200, fileLabel.implicitWidth + 50)
                                    height: 64
                                    Rectangle {
                                        anchors.fill: parent
                                        radius: Theme.radiusInput
                                        color: modelData.kind === "image" ? Theme.fill2 : Theme.background
                                        border.width: modelData.kind === "image" ? 0 : 1
                                        border.color: Theme.line
                                        clip: true
                                        Image {
                                            anchors.fill: parent
                                            visible: modelData.kind === "image"
                                            source: modelData.kind === "image" ? "file://" + modelData.path : ""
                                            sourceSize: Qt.size(128, 128)
                                            fillMode: Image.PreserveAspectCrop
                                            asynchronous: true
                                        }
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 10
                                            anchors.rightMargin: 14
                                            visible: modelData.kind !== "image"
                                            spacing: 10
                                            Icon { name: "file"; color: Theme.dim }
                                            ColumnLayout {
                                                spacing: 0
                                                Text { id: fileLabel; Layout.maximumWidth: 140; text: modelData.name; elide: Text.ElideMiddle; font.family: Theme.fontFamily; font.pixelSize: Theme.metaSize; color: Theme.text }
                                                Text { text: (modelData.name.split(".").pop() || "").toUpperCase(); font.family: Theme.fontFamily; font.pixelSize: Theme.labelSize; color: Theme.dim }
                                            }
                                        }
                                    }
                                    QQC2.AbstractButton {
                                        x: parent.width - 18
                                        y: -6
                                        width: 24
                                        height: 24
                                        Accessible.name: "移除" + modelData.name
                                        onClicked: composer.removeAttachment(modelData.path)
                                        background: Rectangle { radius: 12; color: Theme.strong; border.width: 2; border.color: Theme.fill }
                                        contentItem: Item { Icon { anchors.centerIn: parent; name: "close"; color: Theme.strongInk; implicitWidth: 12; implicitHeight: 12 } }
                                    }
                                }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        IconButton {
                            Layout.alignment: Qt.AlignBottom
                            iconName: composer.showPanel ? "close" : "plus"
                            text: composer.showPanel ? "收起" : "添加照片或文件"
                            onClicked: composer.attachOpen = !composer.attachOpen
                        }
                        QQC2.TextArea {
                            id: field
                            Layout.fillWidth: true
                            Layout.maximumHeight: 26 * 5 + 18
                            background: null
                            topPadding: 9
                            bottomPadding: 9
                            leftPadding: 6
                            rightPadding: 6
                            wrapMode: TextEdit.Wrap
                            placeholderText: "输入消息"
                            placeholderTextColor: Theme.dim
                            color: Theme.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.bodySize
                            Accessible.name: "输入消息"
                            // Touching the text while the panel is open: back to typing.
                            onActiveFocusChanged: if (activeFocus) composer.attachOpen = false
                            Keys.onReturnPressed: event => {
                                // Enter sends; Shift+Enter starts a new line (a hardware keyboard).
                                if (event.modifiers & Qt.ShiftModifier) event.accepted = false
                                else composer.submit()
                            }
                        }
                        CircleButton {
                            Layout.alignment: Qt.AlignBottom
                            visible: field.text.trim().length > 0 || composer.attachments.length > 0
                            iconName: "send"
                            text: "发送"
                            onClicked: composer.submit()
                        }
                        IconButton {
                            Layout.alignment: Qt.AlignBottom
                            visible: field.text.trim().length === 0 && composer.attachments.length === 0
                            iconName: "voice"
                            text: "改用语音"
                            onClicked: { composer.keyboard = false; composer.attachOpen = false; composer.dictation = false; field.focus = false; Qt.inputMethod.hide() }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: text.length > 0
                    horizontalAlignment: Text.AlignHCenter
                    text: composer.foot
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.footSize
                    lineHeight: 16
                    lineHeightMode: Text.FixedHeight
                    color: Theme.dim
                }
            }
        }

        // ---- + : photos and files ---------------------------------------------------------
        Rectangle {
            Layout.fillWidth: true
            visible: composer.showPanel
            implicitHeight: panel.implicitHeight + 34
            color: Theme.side
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            ColumnLayout {
                id: panel
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16; topMargin: 14 }
                spacing: 14
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 10
                    Tile { Layout.fillWidth: true; iconName: "image"; text: "照片"; onClicked: { dialog.images = true; dialog.open() } }
                    Tile { Layout.fillWidth: true; iconName: "file"; text: "文件"; onClicked: { dialog.images = false; dialog.open() } }
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: recent.count > 0
                    Text { Layout.fillWidth: true; text: "最近照片"; font.family: Theme.fontFamily; font.pixelSize: Theme.labelSize; color: Theme.dim }
                    PillButton {
                        visible: photos.picked.length > 0
                        text: "添加 " + photos.picked.length + " 张"
                        onClicked: {
                            for (const url of photos.picked) composer.addAttachment(url)
                            photos.picked = []
                            composer.attached()
                        }
                    }
                }
                // Four across, whatever the count.
                Grid {
                    id: photos
                    property var picked: []
                    readonly property real cell: (width - 3 * spacing) / 4
                    Layout.fillWidth: true
                    visible: recent.count > 0
                    columns: 4
                    spacing: 4
                    Repeater {
                        model: FolderListModel {
                            id: recent
                            folder: StandardPaths.writableLocation(StandardPaths.PicturesLocation)
                            nameFilters: ["*.png", "*.jpg", "*.jpeg", "*.webp"]
                            showDirs: false
                            sortField: FolderListModel.Time
                        }
                        delegate: QQC2.AbstractButton {
                            id: photo
                            required property int index
                            required property url fileUrl
                            readonly property int order: photos.picked.indexOf(fileUrl.toString())
                            visible: index < 8
                            width: photos.cell
                            height: photos.cell
                            Accessible.name: "照片 " + (index + 1) + (order >= 0 ? "，已选" : "")
                            onClicked: {
                                const url = fileUrl.toString()
                                photos.picked = order >= 0 ? photos.picked.filter(u => u !== url) : photos.picked.concat([url])
                            }
                            background: Rectangle {
                                radius: 8
                                color: Theme.fill2
                                clip: true
                                Image {
                                    anchors.fill: parent
                                    source: photo.fileUrl
                                    sourceSize: Qt.size(160, 160)
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                }
                                Rectangle {
                                    anchors.fill: parent
                                    radius: 8
                                    color: photo.down ? Theme.alpha(Theme.strong, 0.18) : "transparent"
                                    border.width: photo.order >= 0 ? 3 : 0
                                    border.color: Theme.strong
                                }
                                Rectangle {
                                    anchors { right: parent.right; top: parent.top; margins: 6 }
                                    width: 22
                                    height: 22
                                    radius: 11
                                    border.width: 1.5
                                    border.color: photo.order >= 0 ? Theme.strong : "#ffffff"
                                    color: photo.order >= 0 ? Theme.strong : Qt.rgba(0, 0, 0, 0.25)
                                    Text {
                                        anchors.centerIn: parent
                                        visible: photo.order >= 0
                                        text: photo.order + 1
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                        color: Theme.strongInk
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    FileDialog {
        id: dialog
        property bool images: true
        fileMode: FileDialog.OpenFiles
        currentFolder: StandardPaths.writableLocation(images ? StandardPaths.PicturesLocation : StandardPaths.DocumentsLocation)
        nameFilters: images ? ["图片 (*.png *.jpg *.jpeg *.webp *.gif)"] : ["所有文件 (*)"]
        onAccepted: {
            for (const url of selectedFiles) composer.addAttachment(url)
            composer.attached()
        }
    }
}
