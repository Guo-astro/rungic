// SPDX-License-Identifier: GPL-3.0-or-later
// Public Qt Virtual Keyboard input-method API; no KWin or Qt private ABI.
#include <QQmlExtensionPlugin>
#include <QVirtualKeyboardAbstractInputMethod>
#include <QVirtualKeyboardInputContext>
#include <QVirtualKeyboardInputEngine>
#include <QVirtualKeyboardSelectionListModel>
#include "runtime.h"

class RimeInputMethod : public QVirtualKeyboardAbstractInputMethod {
    Q_OBJECT
    using Engine = QVirtualKeyboardInputEngine;
    using Model = QVirtualKeyboardSelectionListModel;
    RimeApi *api = nullptr;
    RimeSessionId session = 0;
    Engine::InputMode mode = Engine::InputMode::Pinyin;
    QStringList candidates;
    bool composing = false;

    void clearCandidates() {
        composing = false;
        candidates.clear();
        emit selectionListChanged(Model::Type::WordCandidateList);
        emit selectionListActiveItemChanged(Model::Type::WordCandidateList, -1);
    }

    void refresh() {
        auto context = inputContext();
        if (!context || !session) return;
        // Read commits before notifying Qt: commit() can synchronously reset us.
        RIME_STRUCT(RimeCommit, commit);
        QString text;
        if (api->get_commit(session, &commit)) {
            text = QString::fromUtf8(commit.text);
            api->free_commit(&commit);
        }
        if (!text.isEmpty()) context->commit(text);

        QString preedit;
        RIME_STRUCT(RimeContext, state);
        if (api->get_context(session, &state)) {
            preedit = QString::fromUtf8(state.composition.preedit);
            api->free_context(&state);
        }
        candidates.clear();
        RimeCandidateListIterator iterator{};
        if (api->candidate_list_begin(session, &iterator)) {
            while (candidates.size() < 200 && api->candidate_list_next(&iterator))
                candidates.append(QString::fromUtf8(iterator.candidate.text));
            api->candidate_list_end(&iterator);
        }
        composing = !preedit.isEmpty();
        context->setPreeditText(preedit);
        emit selectionListChanged(Model::Type::WordCandidateList);
        emit selectionListActiveItemChanged(Model::Type::WordCandidateList, candidates.isEmpty() ? -1 : 0);
    }

public:
    explicit RimeInputMethod(QObject *parent = nullptr) : QVirtualKeyboardAbstractInputMethod(parent) {
        api = RimeRuntime::instance().api;
        session = api->create_session();
        if (session) {
            api->select_schema(session, "luna_pinyin_simp");
            api->set_option(session, "ascii_mode", false);
            api->set_option(session, "simplification", true);
        }
    }
    ~RimeInputMethod() override { if (session) api->destroy_session(session); }
    QList<Engine::InputMode> inputModes(const QString &) override {
        return session ? QList<Engine::InputMode>{Engine::InputMode::Pinyin, Engine::InputMode::Latin}
                       : QList<Engine::InputMode>{Engine::InputMode::Latin};
    }
    bool setInputMode(const QString &, Engine::InputMode next) override {
        if (next != mode) reset();
        mode = next;
        return mode == Engine::InputMode::Latin || session;
    }
    bool setTextCase(Engine::TextCase) override { return true; }
    bool keyEvent(Qt::Key key, const QString &text, Qt::KeyboardModifiers modifiers) override {
        if (!session || !inputContext() || mode != Engine::InputMode::Pinyin) return false;
        const auto hints = inputContext()->inputMethodHints();
        if (hints.testFlag(Qt::ImhHiddenText)) { reset(); return false; }
        api->set_option(session, "_no_learning", hints.testFlag(Qt::ImhSensitiveData));
        if (modifiers & (Qt::ControlModifier | Qt::AltModifier | Qt::MetaModifier)) return false;

        int symbol = 0;
        if (key == Qt::Key_Backspace) symbol = 0xff08;
        else if (key == Qt::Key_Return || key == Qt::Key_Enter) symbol = 0xff0d;
        else if (key == Qt::Key_Escape) symbol = 0xff1b;
        else if (key == Qt::Key_Space) symbol = 0x20;
        else if (text.size() == 1 && text.front().unicode() < 128) symbol = text.front().unicode();

        // Non-ASCII punctuation belongs to the layout. Finish composing first.
        if (!symbol) {
            if (!text.isEmpty() && composing) { api->commit_composition(session); refresh(); }
            return false;
        }
        const bool handled = api->process_key(session, symbol, 0);
        refresh();
        return handled;
    }
    QList<Model::Type> selectionLists() override { return {Model::Type::WordCandidateList}; }
    int selectionListItemCount(Model::Type type) override {
        return type == Model::Type::WordCandidateList ? candidates.size() : 0;
    }
    QVariant selectionListData(Model::Type type, int index, Model::Role role) override {
        if (type != Model::Type::WordCandidateList || index < 0 || index >= candidates.size()) return {};
        if (role == Model::Role::Display) return candidates.at(index);
        if (role == Model::Role::WordCompletionLength) return 0;
        return {};
    }
    void selectionListItemSelected(Model::Type type, int index) override {
        if (type == Model::Type::WordCandidateList && session && index >= 0 && index < candidates.size()) {
            api->select_candidate(session, index);
            refresh();
        }
    }
    // Qt contract: reset must not write to the input context.
    void reset() override {
        if (session) api->clear_composition(session);
        clearCandidates();
    }
    void update() override {
        if (session && composing) { api->commit_composition(session); refresh(); }
    }
};

class MotoRimePlugin : public QQmlExtensionPlugin {
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QQmlExtensionInterface_iid)
public:
    void registerTypes(const char *uri) override {
        qmlRegisterType<RimeInputMethod>(uri, 1, 0, "RimeInputMethod");
    }
};
#include "plugin.moc"
