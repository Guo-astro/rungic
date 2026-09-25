// SPDX-License-Identifier: GPL-2.0-or-later
// A conversation's entries, built from the voice agent's events (docs/59): shared by
// the chat page and the Home button's overlay (docs/67).
import QtQuick

QtObject {
    id: root
    readonly property ListModel entries: ListModel {}
    property string title: "新对话"
    // Session state (the "state" events).
    property string phase: "connecting"
    property bool agentBusy: false
    property bool handsFree: false

    // The chat groups what happens in a turn, like ChatGPT/Codex (docs/59):
    // - all transcript pieces of one push-to-talk press form one user message;
    // - an agent turn is one collapsible "work" entry holding what the assistant
    //   said meanwhile, the agent's notes, commands and file changes;
    // - replies outside agent work are bubbles: the acknowledgement before it and
    //   the answer afterwards. Entries never disappear once shown.
    property int workAt: -1          // the work entry receiving agent activity
    property bool workOpen: false    // an agent turn is running
    property real lastTime: 0        // of the latest event (a turn the history left open ends there)
    property int callAt: -1          // the proxied call entry (docs/63)
    property bool inCall: false      // talking goes to the call agent
    property string callPhase: ""    // "agent": the assistant talks; "user": the user talks, assistant paused
    property bool callMonitor: false

    function entry(fields) {
        return Object.assign({ kind: "", role: "", text: "", itemId: "", command: "", output: "",
                               status: "", exitCode: "", press: 0, started: 0, finished: 0,
                               expanded: false, steps: [] }, fields)
    }
    function step(fields) {
        return Object.assign({ kind: "", text: "", itemId: "", command: "", output: "", status: "", exitCode: "" }, fields)
    }
    function lastOf(kind, role) {
        for (let i = entries.count - 1; i >= 0; i--) {
            const e = entries.get(i)
            if (e.kind === kind && (role === undefined || e.role === role)) return i
        }
        return -1
    }
    // Chinese needs no space between pieces; Latin words do.
    function join(a, b) {
        return /[A-Za-z0-9,.!?]$/.test(a) && /^[A-Za-z0-9]/.test(b) ? a + " " + b : a + b
    }
    function addStep(fields) {
        if (root.workAt < 0) return
        entries.get(root.workAt).steps.append(step(fields))
        if (fields.kind !== "command" || !fields.status || fields.status === "running")
            entries.setProperty(root.workAt, "text", fields.kind === "command" ? fields.command : fields.text)
    }
    // The streaming bubble of transcript segment `id`, or -1.
    function liveAt(id) {
        if (!id) return -1
        for (let i = entries.count - 1; i >= 0; i--) {
            const e = entries.get(i)
            if (e.itemId === id && (e.kind === "live-user" || e.kind === "live-assistant")) return i
        }
        return -1
    }
    function removeAt(i) {
        entries.remove(i)
        if (root.workAt > i) root.workAt--
        else if (root.workAt === i) root.workAt = -1
    }
    function insertAt(i, fields) {
        entries.insert(i, entry(fields))
        if (root.workAt >= i) root.workAt++
    }

    function apply(e, live) {
        if (e.time && e.type !== "state") root.lastTime = e.time
        switch (e.type) {
        // Transcripts stream per segment (e.id): the user's transcription often ends
        // after the reply has begun, so a delta finds its own bubble by id, and the
        // finished text replaces that bubble where it stands (docs/59).
        case "delta": {
            if (!live || !e.text) return
            const at = liveAt(e.id)
            if (at >= 0) entries.setProperty(at, "text", entries.get(at).text + e.text)
            else if (e.role === "user")
                entries.append(entry({ kind: "live-user", role: "user", text: e.text, itemId: e.id || "", press: e.press || 0 }))
            else if (root.workOpen && root.workAt >= 0) {
                // Spoken progress streams into the work entry's status line.
                const w = entries.get(root.workAt)
                entries.setProperty(root.workAt, "text", w.status === "live" ? w.text + e.text : e.text)
                entries.setProperty(root.workAt, "status", "live")
            } else entries.append(entry({ kind: "live-assistant", role: "assistant", text: e.text, itemId: e.id || "" }))
            break
        }
        case "message": {
            const liveIndex = liveAt(e.id)
            if (e.role === "user") {
                const at = lastOf("message", "user")
                if (e.press && at >= 0 && entries.get(at).press === e.press) {
                    // Another segment of the same press joins its message.
                    entries.setProperty(at, "text", root.join(entries.get(at).text, e.text))
                    if (liveIndex >= 0) root.removeAt(liveIndex)
                } else {
                    // A new request: earlier turns' work folds away again.
                    for (let i = 0; i < entries.count; i++) {
                        if (entries.get(i).kind === "work" && entries.get(i).expanded) entries.setProperty(i, "expanded", false)
                    }
                    if (liveIndex >= 0) {
                        entries.setProperty(liveIndex, "kind", "message")
                        entries.setProperty(liveIndex, "text", e.text)
                    } else if (root.workAt >= 0 && root.workAt === entries.count - 1 && live
                               && entries.get(root.workAt).steps.count <= 1 && e.time - entries.get(root.workAt).started < 8) {
                        // The agent can start before the transcript of what started it arrives.
                        root.insertAt(root.workAt, { kind: "message", role: "user", text: e.text, itemId: e.id || "", press: e.press || 0 })
                    } else {
                        entries.append(entry({ kind: "message", role: "user", text: e.text, itemId: e.id || "", press: e.press || 0 }))
                    }
                }
                if (root.title === "新对话") root.title = e.text.slice(0, 20)
            } else if (liveIndex >= 0) {
                // Streamed as a bubble (before any agent work began): it stays one.
                entries.setProperty(liveIndex, "kind", "message")
                entries.setProperty(liveIndex, "text", e.text)
            } else if (root.workOpen && root.workAt >= 0 && e.started && e.started < entries.get(root.workAt).started) {
                // Begun before the work (a history replay has no stream): above the work, as it was shown.
                root.insertAt(root.workAt, { kind: "message", role: "assistant", text: e.text, itemId: e.id || "" })
            } else if (root.workOpen && root.workAt >= 0) {
                if (entries.get(root.workAt).status === "live") entries.setProperty(root.workAt, "status", "running")
                root.addStep({ kind: "said", text: e.text })
            } else {
                entries.append(entry({ kind: "message", role: "assistant", text: e.text, itemId: e.id || "" }))
            }
            break
        }
        case "agent-started": {
            // The acknowledgement before it ("好的，我来…") stays a bubble: it was shown
            // before anyone knew work would follow, and nothing on screen should vanish.
            entries.append(entry({ kind: "work", status: "running", started: e.time || Date.now() / 1000 }))
            root.workAt = entries.count - 1
            root.workOpen = true
            break
        }
        case "agent-finished":
            if (root.workAt >= 0) {
                if (entries.get(root.workAt).status !== "stopped") entries.setProperty(root.workAt, "status", "done")
                entries.setProperty(root.workAt, "finished", e.time || Date.now() / 1000)
            }
            root.workOpen = false
            break
        case "task-stopped":
            if (root.workAt >= 0 && root.workOpen) entries.setProperty(root.workAt, "status", "stopped")
            else entries.append(entry({ kind: "marker", text: "已停止" }))
            break
        case "agent-message":
            if (root.workAt < 0) {
                entries.append(entry({ kind: "work", status: "done", started: e.time || 0, finished: e.time || 0 }))
                root.workAt = entries.count - 1
            }
            root.addStep({ kind: e.final ? "answer" : "note", text: e.text, itemId: e.id || "" })
            break
        case "command": {
            if (root.workAt < 0) return
            const fields = { status: e.status, exitCode: e.exitCode === null || e.exitCode === undefined ? "" : String(e.exitCode),
                             output: e.output || "" }
            const steps = entries.get(root.workAt).steps
            let at = -1
            for (let i = steps.count - 1; i >= 0; i--) if (steps.get(i).kind === "command" && steps.get(i).itemId === e.id) { at = i; break }
            if (at >= 0) { for (const k in fields) steps.setProperty(at, k, fields[k]) }
            else root.addStep(Object.assign({ kind: "command", itemId: e.id, command: e.command }, fields))
            break
        }
        case "files": root.addStep({ kind: "files", text: (e.paths || []).join("\n") }); break
        case "approval": {
            const pending = e.status === "pending" && live
            entries.append(entry({ kind: "approval", itemId: e.id, text: e.reason || "",
                                command: e.kind === "command" ? e.text : "", status: pending ? "pending" : "expired" }))
            break
        }
        case "approval-result": {
            for (let i = entries.count - 1; i >= 0; i--) {
                if (entries.get(i).kind === "approval" && entries.get(i).itemId === e.id) {
                    entries.setProperty(i, "status", e.decision === "decline" ? "decline" : "accept")
                    break
                }
            }
            break
        }
        case "call-started":
            entries.append(entry({ kind: "call", status: "running", started: e.time || Date.now() / 1000,
                                role: e.contact || "", text: e.goal || "", expanded: true }))
            root.callAt = entries.count - 1
            root.callMonitor = !!e.monitor
            break
        case "call-transcript": case "call-owner": case "call-ask": case "call-note": {
            if (root.callAt < 0) return
            const who = e.type === "call-owner" ? "owner" : e.type === "call-ask" ? "ask"
                      : e.type === "call-note" ? "note" : e.role
            entries.get(root.callAt).steps.append(root.step({ kind: who, text: e.text }))
            break
        }
        case "call-monitor": root.callMonitor = !!e.on; break
        case "call-state":   // dialing -> ringing -> connected (or dial-failed)
            if (root.callAt >= 0) entries.setProperty(root.callAt, "command", e.state)
            break
        case "call-phase":
            if (root.callAt >= 0 && e.phase === "user") entries.setProperty(root.callAt, "status", "user")
            root.callMonitor = false
            break
        case "call-ended":
            if (root.callAt >= 0) {
                entries.setProperty(root.callAt, "status", e.reason === "handover" ? "handover" : "done")
                entries.setProperty(root.callAt, "finished", e.time || Date.now() / 1000)
                entries.setProperty(root.callAt, "output", e.summary || "")
            }
            root.callAt = -1
            root.callMonitor = false
            break
        case "error": case "call-error": entries.append(entry({ kind: "error", text: e.text })); break
        case "state":
            root.phase = e.phase; root.agentBusy = !!e.agentBusy; root.inCall = !!e.call
            root.handsFree = !!e.handsFree
            root.callPhase = e.callPhase || ""
            break
        }
    }

    // A conversation opened (history replayed, nothing running any more).
    function load(opened) {
        root.title = opened.title
        entries.clear()
        root.workAt = -1
        root.workOpen = false
        root.callAt = -1
        for (const e of opened.history) root.apply(e, false)
        // A turn that was running when the history was saved is not running now.
        if (root.workOpen && root.workAt >= 0) {
            entries.setProperty(root.workAt, "status", "done")
            entries.setProperty(root.workAt, "finished", root.lastTime)
            root.workOpen = false
        }
    }
}
