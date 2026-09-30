// SPDX-License-Identifier: GPL-2.0-or-later
// The agent's model and reasoning effort (docs/98): the provider's models for this account, the
// account's default first; the chosen model's efforts, its default first. Whatever the provider,
// the service hands over one shape (model_catalog.py): Models() and SetAgentModel().
// States: loading (nothing read yet), ready, unavailable (the provider couldn't be asked).
import QtQuick
import QtQuick.Layouts
import com.rungic.design
import com.rungic.voiceassistant
import "efforts.js" as Efforts

SettingsFrame {
    id: page
    // i18nc for efforts.js (a library has no context to find it in).
    readonly property var tr: (context, text, ...args) => i18nc(context, text, ...args)
    title: i18nc("@title", "Model")
    property var catalog: ({})
    property string failure: ""           // the last SetAgentModel error
    property string forcedState: ""
    readonly property var models: catalog.models || []
    readonly property var choice: catalog.choice || ({ model: "", effort: "" })
    readonly property var effective: catalog.effective || ({})
    readonly property var defaultModel: models.find(m => m.default) || models[0] || null
    readonly property var shownModel: models.find(m => m.id === effective.model) || defaultModel
    readonly property string visualState: forcedState !== "" ? forcedState
        : catalog.known ? "ready" : catalog.error ? "unavailable" : "loading"
    state: visualState
    property bool listShown: false
    property bool busyShown: true
    property bool problemShown: false
    states: [
        State { name: "loading"; PropertyChanges { page.listShown: false; page.busyShown: true; page.problemShown: false } },
        State { name: "ready"; PropertyChanges { page.listShown: true; page.busyShown: false; page.problemShown: false } },
        State { name: "unavailable"; PropertyChanges { page.listShown: false; page.busyShown: false; page.problemShown: true } }
    ]

    function load(refresh) { AgentClient.request("Models", [JSON.stringify({ provider: page.catalog.provider || "", refresh: !!refresh })]) }
    function choose(model, effort) {
        page.failure = ""
        // Optimistic: the rows move at once; the reply (or its error) settles them.
        page.catalog = Object.assign({}, page.catalog, { choice: { model: model, effort: effort } })
        AgentClient.request("SetAgentModel", [JSON.stringify({ provider: page.catalog.provider || "", model: model, effort: effort })])
    }
    function chooseModel(id) {
        const target = id ? page.models.find(m => m.id === id) : page.defaultModel
        const keep = target && (target.efforts || []).some(e => e.id === page.choice.effort)
        page.choose(id, keep ? page.choice.effort : "")
    }

    Component.onCompleted: load(true)
    Connections {
        target: AgentClient
        function onReplied(method, json) {
            if (method !== "Models" && method !== "SetAgentModel") return
            const reply = JSON.parse(json)
            if (reply.error && reply.models === undefined) {
                if (method === "SetAgentModel") { page.failure = reply.error; page.load(false) }
                else page.catalog = Object.assign({}, page.catalog, { error: reply.error })
                return
            }
            page.catalog = reply
        }
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.type === "agent-model") page.catalog = e
        }
    }

    // ---- loading and unavailable ------------------------------------------------------
    RowLayout {
        Layout.fillWidth: true
        Layout.margins: Theme.gutter
        visible: page.busyShown
        spacing: Theme.spaceM
        BusyRing {}
        Text { text: i18nc("@info", "Reading the models of your account…"); color: Theme.dim; font.family: Theme.fontFamily; font.pixelSize: Theme.bodySize }
    }
    ColumnLayout {
        Layout.fillWidth: true
        Layout.margins: Theme.gutter
        visible: page.problemShown
        spacing: Theme.spaceM
        Note {
            Layout.fillWidth: true
            tone: "negative"
            text: i18nc("@info %1 is the reason", "Couldn't read the models: %1", page.catalog.error || "")
        }
        PillButton { text: i18nc("@action:button", "Try again"); onClicked: { page.catalog = Object.assign({}, page.catalog, { error: "" }); page.load(true) } }
    }

    // ---- ready -----------------------------------------------------------------------
    ColumnLayout {
        Layout.fillWidth: true
        visible: page.listShown
        spacing: 0

        Note {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.gutter
            Layout.rightMargin: Theme.gutter
            Layout.topMargin: Theme.spaceL
            visible: !!page.catalog.override
            text: i18nc("@info %1 is a model", "A development setting (RUNGIC_AGENT_MODEL) runs every task on %1.", page.catalog.override || "")
        }
        Note {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.gutter
            Layout.rightMargin: Theme.gutter
            Layout.topMargin: Theme.spaceL
            visible: !!page.effective.fallback
            tone: "negative"
            text: i18nc("@info %1 the chosen model, %2 the model used instead", "This account no longer offers %1. Tasks use the account's default, %2.",
                        page.choice.model, page.effective.name || "")
        }
        Note {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.gutter
            Layout.rightMargin: Theme.gutter
            Layout.topMargin: Theme.spaceL
            visible: page.failure !== ""
            tone: "negative"
            text: page.failure
        }

        SectionLabel { Layout.fillWidth: true; text: page.catalog.name ? i18nc("@title:group %1 is the agent, e.g. Codex", "%1 model", page.catalog.name) : i18nc("@title:group", "Model") }
        ListGroup {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.groupMargin
            Layout.rightMargin: Theme.groupMargin
            ListRow {
                text: i18nc("@item the model", "Account default")
                subtitle: page.defaultModel ? i18nc("@info %1 is a model", "Now %1", page.defaultModel.name) : ""
                Accessible.role: Accessible.RadioButton
                leading: RadioMark { on: page.choice.model === "" }
                onClicked: page.chooseModel("")
            }
            Repeater {
                model: page.models
                ListRow {
                    required property var modelData
                    text: modelData.name
                    subtitle: modelData.upgrade
                        ? i18nc("@info %1 describes the model, %2 is the model replacing it", "%1 · Being replaced by %2", modelData.description,
                                (page.models.find(m => m.id === modelData.upgrade) || { name: modelData.upgrade }).name)
                        : modelData.description
                    Accessible.role: Accessible.RadioButton
                    leading: RadioMark { on: page.choice.model === modelData.id }
                    onClicked: page.chooseModel(modelData.id)
                }
            }
        }

        SectionLabel { Layout.fillWidth: true; text: i18nc("@title:group", "Reasoning effort") }
        ListGroup {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.groupMargin
            Layout.rightMargin: Theme.groupMargin
            ListRow {
                text: i18nc("@item reasoning effort", "Model default")
                subtitle: page.shownModel && page.shownModel.defaultEffort ? Efforts.name(page.tr, page.shownModel.defaultEffort) : ""
                Accessible.role: Accessible.RadioButton
                leading: RadioMark { on: page.choice.effort === "" }
                onClicked: page.choose(page.choice.model, "")
            }
            Repeater {
                model: page.shownModel ? page.shownModel.efforts || [] : []
                ListRow {
                    required property var modelData
                    text: Efforts.name(page.tr, modelData.id)
                    subtitle: Efforts.note(page.tr, modelData)
                    Accessible.role: Accessible.RadioButton
                    leading: RadioMark { on: page.choice.effort === modelData.id }
                    onClicked: page.choose(page.choice.model, modelData.id)
                }
            }
        }
        Note {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.gutter
            Layout.rightMargin: Theme.gutter
            Layout.topMargin: Theme.spaceM
            text: i18nc("@info", "More effort means the agent thinks longer: slower answers, more of your plan. A change applies from the next task.")
        }
        Item { implicitHeight: Theme.spaceXxl }
    }
}
