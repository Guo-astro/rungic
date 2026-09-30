// SPDX-License-Identifier: GPL-2.0-or-later
#include "model.h"
#include "briefing.h"
#include "layout.h"
#include "usage.h"
#include <KConfig>
#include <KConfigGroup>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QTemporaryDir>
#include <QtTest>

class CareTests : public QObject {
    Q_OBJECT
    static QJsonObject item(QString key = "crash:1", QString source = "crashes") {
        auto o = Care::observation(key, "应用退出", "原因待核实", "fault", 1, {{"signature", "abc"}});
        o["source"] = source; return o;
    }
private Q_SLOTS:
    void groupedCrashesKeepIndependentRecordsAndReceipts() {
        Care::Model m(""); auto a = item("a"), b = item("b"), c = item("other");
        const auto first = a["id"].toString(), second = b["id"].toString();
        for (auto *o : {&a, &b}) (*o)["evidence"] = QJsonObject{{"package", "desktop"}, {"version", "1"}, {"reports", 2}};
        c["evidence"] = QJsonObject{{"package", "player"}, {"version", "1"}};
        m.observe(a, 100); m.observe(b, 101); m.observe(c, 102);
        m.updatePlan(second, {{"result", "Missing evidence, cause unconfirmed.\n\nDetails"}});
        const auto groups = m.groups(); QCOMPARE(groups.size(), 2);
        QJsonObject group;
        for (const auto &v : groups) if (v.toObject()["count"].toInt() == 2) group = v.toObject();
        QCOMPARE(group["reports"].toInt(), 4); QCOMPARE(group["summary"].toString(), "Missing evidence, cause unconfirmed.");
        QCOMPARE(group["representativeId"].toString(), second);
        m.present(second, 1, false, 200); QVERIFY(!m.get(first).contains("displayedRevision"));
        m.act(second, "dismiss", {}, 201);
        QCOMPARE(m.groups(true).size(), 1); QCOMPARE(m.groups().size(), 2);
        QCOMPARE(m.list().size(), 3);
    }
    void structuredSummaryDoesNotMakeAPlanExecutable() {
        Care::Model m(""); const auto o = item(); const auto id = o["id"].toString(); m.observe(o, 100);
        auto r = m.updatePlan(id, {{"conclusion", "Possibly a known bug, not confirmed"}, {"confidence", "suspected"}, {"nextStep", "Observe"}});
        QCOMPARE(r["summary"].toString(), "Possibly a known bug, not confirmed"); QVERIFY(!r["canApply"].toBool());
        QVERIFY(m.updatePlan(id, {{"confidence", "guaranteed"}}).contains("error"));
        r = m.updatePlan(id, {{"result", "New investigation"}}); QCOMPARE(r["summary"].toString(), "New investigation");
    }
    void usageDeduplicatesRequestsRestartsAndAccounts() {
        QTemporaryDir d; const auto path = d.path() + "/usage.json";
        Care::Usage u(path);
        const auto snapshot = QJsonObject{{"accountKey", "account-a"}, {"authMode", "apiKey"}};
        u.snapshot(snapshot, 100);
        auto event = QJsonObject{{"accountKey", "account-a"}, {"threadId", "thread"}, {"turnId", "turn"},
            {"tokenUsage", QJsonObject{{"total", QJsonObject{{"totalTokens", 1200}}}, {"last", QJsonObject{{"totalTokens", 200}}}}}};
        u.token(event, 101); u.token(event, 102);
        QCOMPARE(u.view(102)["recordedTokens"].toInteger(), 200); // resumed history is not counted
        event["tokenUsage"] = QJsonObject{{"total", QJsonObject{{"totalTokens", 1700}}}, {"last", QJsonObject{{"totalTokens", 500}}}};
        u.token(event, 103); QCOMPARE(u.view(103)["recordedTokens"].toInteger(), 700); // same turn, second model request
        Care::Usage restarted(path); QVERIFY(restarted.view(104)["recordedTokens"].isNull());
        restarted.snapshot(snapshot, 105); restarted.token(event, 106); QCOMPARE(restarted.view(106)["recordedTokens"].toInteger(), 700);
        restarted.snapshot({{"accountKey", "account-b"}, {"authMode", "apiKey"}}, 107);
        QVERIFY(restarted.view(107)["recordedTokens"].isNull());
        event["accountKey"] = "account-b"; restarted.token(event, 108);
        QCOMPARE(restarted.view(108)["recordedTokens"].toInteger(), 500);
        restarted.snapshot(snapshot, 109); QCOMPARE(restarted.view(109)["recordedTokens"].toInteger(), 700);
    }
    void usageQuotaIsNullableAndResetDoesNotInventFreshData() {
        Care::Usage u("");
        const QJsonObject limits{{"rateLimits", QJsonObject{{"primary", QJsonObject{{"usedPercent", 75}, {"windowDurationMins", 300}, {"resetsAt", 200}}}}}};
        u.snapshot({{"accountKey", "a"}, {"authMode", "chatgpt"}, {"rateLimits", limits}}, 100);
        auto v = u.view(101); QCOMPARE(v["windows"].toArray().size(), 1);
        QVERIFY(!v["windows"].toArray()[0].toObject()["expired"].toBool());
        QVERIFY(u.view(201)["windows"].toArray()[0].toObject()["expired"].toBool());
        QVERIFY(u.view(301)["stale"].toBool());
        u.snapshot({{"authMode", "apiKey"}, {"rateLimits", limits}}, 302);
        QVERIFY(u.view(302)["windows"].toArray().isEmpty());
        u.snapshot({{"authMode", "none"}}, 303); QVERIFY(u.view(303)["recordedTokens"].isNull());
    }
    void staleReferencesNeverCreateRecords() {
        QTemporaryDir d; const auto path = d.path() + "/state.json";
        QVERIFY(Care::writeObject(path, {{"schema", 2}, {"items", QJsonObject{{"stale", QJsonValue::Null}}}}));
        Care::Model m(path); QVERIFY(m.load()); QVERIFY(m.list().isEmpty());
        QVERIFY(!m.present("missing", 1, false, 100));
        QVERIFY(!m.update("missing", {{"result", "late"}}));
        QVERIFY(m.updatePlan("missing", {}).contains("error"));
        QVERIFY(m.act("missing", "dismiss", {}, 100).contains("error"));
        QVERIFY(!m.taskEvent("missing", "old-task", {{"type", "finished"}}, 100));
        m.notifiedReceipts({QJsonObject{{"id", "missing"}, {"revision", 1}}}, 100);
        QVERIFY(m.list().isEmpty()); QVERIFY(m.save());
        Care::Model restarted(path); QVERIFY(restarted.load()); QVERIFY(restarted.list().isEmpty());
    }
    void widgetLayoutPreservesUserChoicesAndRemoval() {
        QTemporaryDir d; const auto path = d.path() + "/layout";
        {
            KConfig c(path, KConfig::SimpleConfig);
            auto desktop = c.group("Containments").group("1");
            desktop.writeEntry("plugin", QStringLiteral("org.kde.plasma.mobile.homescreen.folio"));
            auto folio = desktop.group("Folio");
            folio.writeEntry("favorites", QStringLiteral("[]")); // Explicitly empty is a choice.
            folio.writeEntry("pages", QStringLiteral("[[{\"type\":\"application\",\"storageId\":\"existing.desktop\",\"row\":0,\"column\":0}]]"));
            c.group("Containments").group("2").group("Applets").group("99").writeEntry("plugin", QStringLiteral("other.widget"));
            QVERIFY(c.sync());
        }
        QVERIFY(Care::setupWidget(path, {"new.desktop"}));
        {
            KConfig c(path, KConfig::SimpleConfig); auto desktop = c.group("Containments").group("1");
            auto folio = desktop.group("Folio");
            QCOMPARE(folio.readEntry("favorites", QString()), QStringLiteral("[]"));
            auto pages = QJsonDocument::fromJson(folio.readEntry("pages", QString()).toUtf8()).array();
            auto items = pages[0].toArray(); QCOMPARE(items.size(), 3);
            QCOMPARE(items[0].toObject()["storageId"].toString(), QStringLiteral("existing.desktop"));
            QCOMPARE(items[1].toObject()["row"].toInt(), 1);
            QCOMPARE(items[1].toObject()["id"].toInt(), 100);
            QVERIFY(QFile::exists(path + ".before-rungic-suggestions-widget"));
            desktop.group("Applets").group("100").deleteGroup();
            items.removeAt(1); pages[0] = items;
            folio.writeEntry("pages", QString::fromUtf8(QJsonDocument(pages).toJson(QJsonDocument::Compact)));
            QVERIFY(c.sync());
        }
        QVERIFY(Care::setupWidget(path, {"new.desktop"}));
        KConfig c(path, KConfig::SimpleConfig);
        QVERIFY(!c.group("Containments").group("1").group("Applets").hasGroup("100"));
    }
    void widgetLayoutNeverOverwritesOccupiedPage() {
        QTemporaryDir d; const auto path = d.path() + "/layout";
        {
            KConfig c(path, KConfig::SimpleConfig); auto desktop = c.group("Containments").group("1");
            desktop.writeEntry("plugin", QStringLiteral("org.kde.plasma.mobile.homescreen.folio"));
            desktop.group("Folio").writeEntry("pages", QStringLiteral("[[{\"type\":\"widget\",\"id\":12,\"row\":0,\"column\":0,\"gridWidth\":4,\"gridHeight\":5}]]"));
            QVERIFY(c.sync());
        }
        QVERIFY(Care::setupWidget(path, {"known.desktop"}));
        KConfig c(path, KConfig::SimpleConfig); const auto folio = c.group("Containments").group("1").group("Folio");
        const auto pages = QJsonDocument::fromJson(folio.readEntry("pages", QString()).toUtf8()).array();
        QCOMPARE(pages.size(), 2); QCOMPARE(pages[0].toArray()[0].toObject()["id"].toInt(), 12);
        QVERIFY(folio.readEntry("favorites", QString()).contains("known.desktop"));
    }
    void persistentSnoozeAndDeduplication() {
        QTemporaryDir d; const auto path = d.path() + "/state.json";
        Care::Model m(path); auto o = item(); const auto id = o["id"].toString();
        QVERIFY(m.load()); QVERIFY(m.observe(o, 100));
        QVERIFY(!m.observe(o, 101)); QCOMPARE(m.list().size(), 1);
        QVERIFY(!m.act(id, "snooze", {{"at", 300}}, 110).contains("error")); QVERIFY(m.save());
        Care::Model restarted(path); QVERIFY(restarted.load());
        restarted.observe(o, 200); QCOMPARE(restarted.get(id)["state"].toString(), "snoozed");
        QVERIFY(restarted.due(299).isEmpty()); QCOMPARE(restarted.due(300).size(), 1);
        QVERIFY(restarted.due(301).isEmpty()); QVERIFY(!restarted.notification(301, false, false).isEmpty());
        restarted.notified({id}, 301); QVERIFY(restarted.notification(302, true, false).isEmpty());
    }
    void resolvedBeforeReminder() {
        Care::Model m(""); const auto o = item(); const auto id = o["id"].toString();
        m.observe(o, 100); m.act(id, "snooze", {{"at", 300}}, 110);
        m.reconcile("crashes", {}, 200);
        QVERIFY(m.due(301).isEmpty()); QCOMPARE(m.get(id)["state"].toString(), "resolved");
        m.observe(o, 400); QCOMPARE(m.get(id)["state"].toString(), "new");
    }
    void dismissPersistsThroughRepeatedObservations() {
        Care::Model m(""); auto o = item(); const auto id = o["id"].toString();
        m.observe(o, 100); m.act(id, "dismiss", {}, 101); o["body"] = "次数增加";
        m.observe(o, 200); QCOMPARE(m.get(id)["state"].toString(), "dismissed");
        QVERIFY(m.notification(100000, true, false).isEmpty());
        m.act(id, "restore", {}, 300); QCOMPARE(m.get(id)["state"].toString(), "new");
    }
    void closedConditionAndNoImplicitExecution() {
        Care::Model m(""); auto o = item(); const auto id = o["id"].toString();
        m.observe(o, 100); QVERIFY(m.act(id, "closed", {}, 101).contains("error"));
        o["process"] = "player"; m.observe(o, 102);
        QVERIFY(m.act(id, "closed", {}, 103).contains("error"));
        QVERIFY(m.due(105, {}).isEmpty()); // A process name is not an application instance.
        QCOMPARE(m.get(id)["state"].toString(), "new");
    }
    void ordinaryHintsQuietOutsideFeedAndRespectInhibition() {
        Care::Model m(""); auto o = item(); m.observe(o, 100000);
        QVERIFY(m.notification(100001, false, false).isEmpty());
        QVERIFY(m.notification(100001, true, true).isEmpty());
        QVERIFY(!m.notification(100001, true, false).isEmpty());
        m.notified({o["id"].toString()}, 100001);
        m.observe(item("crash:2"), 100002);
        QVERIFY(m.notification(100002, true, false).isEmpty());
        QVERIFY(m.notification(200002, true, false).isEmpty()); // stale evidence never delivers
        m.observe(item("crash:2"), 200002);
        QVERIFY(!m.notification(200002, true, false).isEmpty());
    }
    void upstreamAndTaskCompletionDoNotResolveFaults() {
        Care::Model m(""); auto o = item(); const auto id = o["id"].toString();
        m.observe(o, 100); m.update(id, {{"upstream", QJsonObject{{"state", "merged"}}}});
        m.beginTask(id, "investigate", {}, 101);
        m.recoverTasks(); QCOMPARE(m.get(id)["state"].toString(), "working");
        QCOMPARE(m.get(id)["upstream"].toObject()["state"].toString(), "merged");
    }
    void absenceDoesNotLoseTaskOrLateResult() {
        Care::Model m(""); const auto o = item(); const auto id = o["id"].toString();
        m.observe(o, 100);
        const auto task = m.beginTask(id, "investigate", {}, 101)["task"].toObject()["id"].toString();
        m.reconcile("crashes", {}, 102);
        QCOMPARE(m.get(id)["issueState"].toString(), "absent");
        QCOMPARE(m.get(id)["state"].toString(), "working");
        m.recoverTasks(); QCOMPARE(m.get(id)["task"].toObject()["state"].toString(), "recovering");
        QVERIFY(m.taskEvent(id, task, {{"type", "result"}, {"text", "调查结果"}}, 103));
        QVERIFY(m.taskEvent(id, task, {{"type", "finished"}}, 104));
        QCOMPARE(m.get(id)["result"].toString(), "调查结果");
        QCOMPARE(m.get(id)["state"].toString(), "attention");
        QVERIFY(!m.notification(10000, false, false).isEmpty()); // task result does not need a live fault
        m.present(id, m.get(id)["deliveryRevision"].toInteger(), true, 105);
        QCOMPARE(m.get(id)["state"].toString(), "attention"); // viewing does not make a card disappear
        m.act(id, "reviewed", {}, 106);
        QCOMPARE(m.get(id)["state"].toString(), "resolved");
    }
    void confirmationBindsExactPlanAndEvidence() {
        Care::Model m(""); auto o = item(); const auto id = o["id"].toString(); m.observe(o, 100);
        m.updatePlan(id, {{"plan", "证据不足，暂不修改"}, {"verification", "未知"}, {"rollback", "无变更"}});
        QVERIFY(!m.get(id)["canApply"].toBool());
        QVERIFY(m.beginTask(id, "apply", m.get(id)["planRevision"].toString(), 101).contains("error"));
        m.updatePlan(id, {{"planStatus", "ready"}, {"plan", "配置 A"}, {"verification", "功能检查"}, {"rollback", "恢复 A"}});
        const auto a = m.get(id)["planRevision"].toString();
        m.updatePlan(id, {{"planStatus", "ready"}, {"plan", "配置 B"}});
        QVERIFY(m.beginTask(id, "apply", a, 102).contains("error"));
        const auto b = m.get(id)["planRevision"].toString();
        auto begun = m.beginTask(id, "apply", b, 103); QVERIFY(!begun.contains("error"));
        m.updatePlan(id, {{"plan", "配置 C"}, {"planStatus", "ready"}});
        QCOMPARE(m.get(id)["task"].toObject()["approvedPlan"].toObject()["plan"].toString(), "配置 B");
        const auto taskId = begun["task"].toObject()["id"].toString();
        m.taskEvent(id, taskId, {{"type", "finished"}}, 104);
        o["evidence"] = QJsonObject{{"version", "new"}}; m.observe(o, 105);
        QVERIFY(!m.get(id)["canApply"].toBool());
        QVERIFY(m.beginTask(id, "apply", m.get(id)["planRevision"].toString(), 106).contains("error"));
    }
    void presentationAndNotificationsArePerRevision() {
        Care::Model m(""); const auto a = item("a"), b = item("b");
        m.observe(a, 100000); m.observe(b, 100000);
        const auto id = a["id"].toString();
        QVERIFY(m.present(id, 1, false, 100001));
        QCOMPARE(m.notification(100002, true, false)["ids"].toArray(), QJsonArray{b["id"]});
        const auto receipt = m.notification(100002, true, false)["receipts"].toArray();
        const auto task = m.beginTask(b["id"].toString(), "investigate", {}, 100003)["task"].toObject()["id"].toString();
        m.taskEvent(b["id"].toString(), task, {{"type", "finished"}}, 100004);
        m.notifiedReceipts(receipt, 100005); // notification reply for old revision must not hide the result
        QVERIFY(!m.notification(100006, false, false).isEmpty());
        QVERIFY(!m.present(b["id"].toString(), 1, true, 100007));
        QVERIFY(m.present(b["id"].toString(), 2, true, 100007));
        QVERIFY(m.notification(100008, false, false).isEmpty());
    }
    void restartAndReplacedTasksPreserveCorrelation() {
        QTemporaryDir d; const auto path = d.path() + "/state.json";
        Care::Model m(path); const auto o = item(); const auto id = o["id"].toString(); m.observe(o, 100);
        const auto first = m.beginTask(id, "investigate", {}, 101)["task"].toObject()["id"].toString();
        QVERIFY(m.save()); Care::Model restarted(path); QVERIFY(restarted.load()); restarted.recoverTasks();
        QCOMPARE(restarted.get(id)["state"].toString(), "working");
        QVERIFY(restarted.taskEvent(id, first, {{"type", "finished"}}, 102));
        const auto second = restarted.beginTask(id, "investigate", {}, 103)["task"].toObject()["id"].toString();
        QVERIFY(first != second);
        QVERIFY(!restarted.taskEvent(id, first, {{"type", "failed"}, {"text", "late old error"}}, 104));
        QCOMPARE(restarted.get(id)["state"].toString(), "working");
    }
    void oldLedgerMigrationKeepsChoicesAndInvalidatesLegacyPlan() {
        QTemporaryDir d; const auto path = d.path() + "/state.json"; auto o = item(); const auto id = o["id"].toString();
        o["state"] = "snoozed"; o["condition"] = "old-process"; o["plan"] = "旧文字";
        o["notified"] = true; o["upstream"] = QJsonObject{{"state", "prepared"}};
        QVERIFY(Care::writeObject(path, {{"schema", 1}, {"items", QJsonObject{{id, o}}}}));
        Care::Model m(path); QVERIFY(m.load()); QVERIFY(QFile::exists(path + ".schema1-backup"));
        QCOMPARE(m.get(id)["reminderState"].toString(), "snoozed");
        QVERIFY(!m.get(id).contains("condition")); QVERIFY(!m.get(id)["canApply"].toBool());
        QCOMPARE(m.get(id)["upstream"].toObject()["state"].toString(), "prepared"); QVERIFY(m.save());
        QCOMPARE(Care::readObject(path)["schema"].toInt(), 2);
    }
    void sourceFailureCannotTriggerScheduledReminder() {
        Care::Model m(""); const auto o = item(); const auto id = o["id"].toString(); m.observe(o, 100);
        m.act(id, "snooze", {{"at", 500}}, 101);
        QVERIFY(m.due(501).isEmpty()); // some other source being fresh does not validate this issue
        m.observe(o, 502); QCOMPARE(m.due(503).size(), 1);
        m.act(id, "dismiss", {}, 504); m.reconcile("crashes", {}, 505); m.observe(o, 506);
        QCOMPARE(m.get(id)["state"].toString(), "dismissed");
    }
    void completedResultReminderSurvivesIssueAbsence() {
        Care::Model m(""); const auto o = item(); const auto id = o["id"].toString(); m.observe(o, 100);
        const auto task = m.beginTask(id, "investigate", {}, 101)["task"].toObject()["id"].toString();
        m.taskEvent(id, task, {{"type", "finished"}}, 102);
        m.act(id, "snooze", {{"at", 1000}}, 103);
        m.reconcile("crashes", {}, 104);
        QCOMPARE(m.due(1000).size(), 1);
        QVERIFY(!m.notification(1001, false, false).isEmpty());
    }
    void corruptedStateIsNotOverwritten() {
        QTemporaryDir d; QFile f(d.path() + "/state.json"); QVERIFY(f.open(QIODevice::WriteOnly)); f.write("broken"); f.close();
        Care::Model m(f.fileName()); QString error; QVERIFY(!m.load(&error)); QVERIFY(!error.isEmpty());
        QVERIFY(f.open(QIODevice::ReadOnly)); QCOMPARE(f.readAll(), QByteArray("broken"));
    }
    // ---- briefing (docs/research/96) ----
    static QJsonObject card(const QString &ref, const QString &title = "Crashes to go through", const QString &kind = "issues") {
        return {{"title", title}, {"body", "Several apps quit unexpectedly this week."}, {"kind", kind}, {"priority", 50},
                {"refs", QJsonArray{ref}}, {"action", QJsonObject{{"label", "Go through them"}, {"prompt", "List them"}}}, {"notify", false}};
    }
    void curatedOutputIsValidatedStrictly() {
        Care::Model m(""); const auto a = item("a"), b = item("b");
        m.observe(a, 100); m.observe(b, 100);
        const auto ia = a["id"].toString(), ib = b["id"].toString();
        auto extra = card(ia); extra["exec"] = "rm -rf /"; extra["id"] = "chosen-by-model";
        auto multi = card(ia, "Two"); multi["refs"] = QJsonArray{ia, ib, ia};
        QJsonArray cards{extra, multi, card("missing"), card(ib, QString(61, 'x')), card(ib, "Unknown kind", "advert"), card(ia, "Duplicate")};
        auto longBody = card(ib, "Long body"); longBody["body"] = QString(161, 'y'); cards.append(longBody);
        auto noAction = card(ib, "No action"); noAction.remove("action"); cards.append(noAction);
        auto badPriority = card(ib, "Priority"); badPriority["priority"] = 101; cards.append(badPriority);
        auto fraction = card(ib, "Fraction"); fraction["priority"] = 1.5; cards.append(fraction);
        auto mixed = card(ib, "Mixed"); mixed["refs"] = QJsonArray{ib, "missing"}; cards.append(mixed);
        auto control = card(ib, QStringLiteral("Line break‮eht")); cards.append(control);
        QStringList dropped;
        const auto valid = Care::Briefing::validate(QJsonObject{{"cards", cards}}, m.list(), &dropped);
        QCOMPARE(valid.size(), 3);
        QVERIFY(!valid[0].toObject().contains("exec"));
        QVERIFY(valid[0].toObject()["id"].toString().startsWith("agent:"));
        QCOMPARE(valid[1].toObject()["refs"].toArray().size(), 2); // duplicates within refs removed
        QCOMPARE(valid[2].toObject()["title"].toString(), QStringLiteral("Line break eht")); // no bidi/line controls
        QVERIFY(dropped.contains("refs") && dropped.contains("text") && dropped.contains("kind") && dropped.contains("duplicate")
                && dropped.contains("action") && dropped.contains("priority"));
        QJsonArray many;
        const QStringList kinds{"attention", "issues", "improvement", "result", "followup", "issues", "attention"};
        for (int i = 0; i < 7; ++i) many.append(card(i % 2 ? ia : ib, QString("Card %1").arg(i), kinds[i]));
        dropped.clear();
        QCOMPARE(Care::Briefing::validate(QJsonObject{{"cards", many}}, m.list(), &dropped).size(), 5);
        QVERIFY(dropped.contains("count"));
        QVERIFY(Care::Briefing::validate(QJsonArray{card(ia)}, m.list()).isEmpty()); // not an object
        Care::Briefing br("");
        QVERIFY(!br.applyAgent(QJsonObject{{"cards", QJsonArray{card("missing")}}}, m.list(), 200));
        QVERIFY(br.applyAgent(QJsonObject{{"cards", QJsonArray{}}}, m.list(), 200)); // nothing needs the user: allowed
        QCOMPARE(br.source(), "agent");
    }
    void curationTriggersOnlyOnMaterialChanges() {
        using namespace Care::BriefingLimits;
        Care::Model m(""); Care::Briefing br(""); auto a = item("a");
        a["evidence"] = QJsonObject{{"package", "app"}, {"reports", 1}};
        QVERIFY(!br.observe(m.list(), 50)); QCOMPARE(br.nextRun(50), 0); // nothing at all: no curation
        m.observe(a, 100);
        QVERIFY(br.observe(m.list(), 100)); QCOMPARE(br.nextRun(100), 100 + Debounce);
        m.observe(a, 160); QVERIFY(!br.observe(m.list(), 160)); // seen again: not material
        a["body"] = "reworded"; m.observe(a, 170); QVERIFY(!br.observe(m.list(), 170));
        a["evidence"] = QJsonObject{{"package", "app"}, {"reports", 2}}; m.observe(a, 180); QVERIFY(!br.observe(m.list(), 180));
        a["evidence"] = QJsonObject{{"package", "app"}, {"reports", 3}}; m.observe(a, 190); QVERIFY(br.observe(m.list(), 190)); // threshold
        QCOMPARE(br.nextRun(190), 190 + Debounce); // debounce restarts with each change
        br.begin(m.list(), 400); QCOMPARE(br.nextRun(400), 0);
        m.observe(item("b"), 410); QVERIFY(br.observe(m.list(), 410));
        QCOMPARE(br.nextRun(410), 400 + MinInterval);
        // A task result that waits for the user shortens the interval.
        const auto id = a["id"].toString();
        m.observe(a, 415); QVERIFY(!br.observe(m.list(), 415));
        const auto task = m.beginTask(id, "investigate", {}, 420)["task"].toObject()["id"].toString();
        QVERIFY(!task.isEmpty());
        m.taskEvent(id, task, {{"type", "finished"}}, 430);
        QVERIFY(br.observe(m.list(), 430)); QCOMPARE(br.nextRun(430), 400 + MinIntervalUrgent);
        br.begin(m.list(), 1000);
        m.reconcile("crashes", {}, 1100); QVERIFY(br.observe(m.list(), 1100)); // resolved is material
        // Daily cap: the 13th curation waits until the first one of the window is 24 h old.
        Care::Briefing capped(""); qint64 t = 10000;
        for (int i = 0; i < DailyCap; ++i, t += 60) capped.begin(m.list(), t);
        QVERIFY(capped.capped(t));
        m.observe(item("c"), t); QVERIFY(capped.observe(m.list(), t));
        QCOMPARE(capped.nextRun(t), 10000 + 86400);
        QVERIFY(!capped.capped(10000 + 86400));
    }
    void fallbackSummarisesFindingsAndResults() {
        Care::Model m(""); QStringList ids;
        for (const auto key : {"a", "b", "c", "d"}) { const auto o = item(key); m.observe(o, 100); ids.append(o["id"].toString()); }
        const auto task = m.beginTask(ids[3], "investigate", {}, 101)["task"].toObject()["id"].toString();
        m.updatePlan(ids[3], {{"conclusion", "Caused by an outdated driver, not confirmed"}});
        m.taskEvent(ids[3], task, {{"type", "finished"}}, 102);
        Care::Briefing br(""); br.applyFallback(m.list(), 103, "unavailable");
        const auto cards = br.cards(m.list());
        QCOMPARE(cards.size(), 2);
        const auto result = cards[0].toObject(), summary = cards[1].toObject();
        QCOMPARE(result["kind"].toString(), "result"); QCOMPARE(result["refs"].toArray(), QJsonArray{ids[3]});
        QCOMPARE(result["body"].toString(), "Caused by an outdated driver, not confirmed");
        QCOMPARE(summary["kind"].toString(), "issues"); QCOMPARE(summary["count"].toInt(), 3);
        QVERIFY(summary["title"].toString().contains("3"));
        QVERIFY(summary["body"].toString().size() <= Care::BriefingLimits::BodyMax);
        const auto view = br.view(m.list(), true, 104);
        QCOMPARE(view["source"].toString(), "fallback"); QCOMPARE(view["error"].toString(), "unavailable");
        QVERIFY(!view["cards"].toArray()[0].toObject()["action"].toObject().contains("prompt"));
    }
    void agentCardsStayAndUnseenFindingsGetServiceCards() {
        Care::Model m(""); const auto a = item("a"), b = item("b"), c = item("c");
        m.observe(a, 100); m.observe(b, 100);
        Care::Briefing br(""); br.observe(m.list(), 100); br.begin(m.list(), 300);
        QVERIFY(br.applyAgent(QJsonObject{{"cards", QJsonArray{card(a["id"].toString())}}}, m.list(), 310));
        QCOMPARE(br.cards(m.list()).size(), 1); // b was seen and left out by the Agent: it stays out
        m.observe(c, 320); br.observe(m.list(), 320);
        const auto cards = br.cards(m.list());
        QCOMPARE(cards.size(), 2);
        QJsonObject service;
        for (const auto &v : cards) if (v.toObject()["origin"] == "service") service = v.toObject();
        QCOMPARE(service["refs"].toArray(), QJsonArray{c["id"]});
    }
    void dismissedCardStaysHiddenUntilMaterialChange() {
        Care::Model m(""); auto a = item("a"); m.observe(a, 100);
        Care::Briefing br(""); br.observe(m.list(), 100);
        const auto id = br.cards(m.list())[0].toObject()["id"].toString();
        QVERIFY(br.dismiss(id, m.list(), 110));
        QVERIFY(br.cards(m.list()).isEmpty());
        a["body"] = "seen again"; m.observe(a, 200); br.observe(m.list(), 200);
        QVERIFY(br.cards(m.list()).isEmpty());
        m.reconcile("crashes", {}, 300); br.observe(m.list(), 300);
        m.observe(a, 400); br.observe(m.list(), 400); // it came back: a material change
        QCOMPARE(br.cards(m.list()).size(), 1);
        QVERIFY(!br.dismiss("fallback:none", m.list(), 410));
    }
    void feedbackReachesTheNextCurationInput() {
        Care::Model m(""); const auto a = item("a"), b = item("b"); m.observe(a, 100); m.observe(b, 100);
        Care::Briefing br(""); br.begin(m.list(), 100);
        br.applyAgent(QJsonObject{{"cards", QJsonArray{card(a["id"].toString(), "Crash A"), card(b["id"].toString(), "Crash B", "attention")}}}, m.list(), 110);
        const auto cards = br.cards(m.list());
        QVERIFY(br.dismiss(cards[0].toObject()["id"].toString(), m.list(), 120));
        QVERIFY(br.opened(cards[1].toObject()["id"].toString(), m.list(), 130));
        const auto input = br.input(m.list(), 140);
        const auto feedback = input["feedback"].toArray();
        QCOMPARE(feedback.size(), 2);
        QCOMPARE(feedback[0].toObject()["action"].toString(), "dismissed");
        QCOMPARE(feedback[1].toObject()["action"].toString(), "opened");
        QCOMPARE(input["currentCards"].toArray().size(), 2);
        bool flagged = false;
        for (const auto &v : input["items"].toArray()) if (v.toObject()["dismissedByUser"].toBool()) flagged = true;
        QVERIFY(flagged);
        QVERIFY(br.input(m.list(), 140 + 15 * 86400)["feedback"].toArray().isEmpty()); // bounded in time
    }
    void curationInputIsRedacted() {
        Care::Model m(""); const auto home = QDir::homePath();
        auto o = Care::observation("svc", "Failed: " + home + "/Documents/tax-2026.pdf", "raw body with details", "fault", 1,
            {{"unit", "sync@jane.doe@example.com.service"}, {"report", "/var/lib/crash/123"}, {"log", "Sep 30 raw log line secret-token"},
             {"package", "app"}, {"reports", 4}});
        o["source"] = "user-services"; m.observe(o, 100);
        m.updatePlan(o["id"].toString(), {{"result", "full report with raw log line"}, {"conclusion", "Config at /home/other/.config/app broke"}});
        Care::Briefing br("");
        const auto text = QString::fromUtf8(QJsonDocument(br.input(m.list(), 200)).toJson());
        QVERIFY(!text.contains(home + "/")); QVERIFY(!text.contains("tax-2026")); QVERIFY(!text.contains("/home/other"));
        QVERIFY(!text.contains("example.com")); QVERIFY(!text.contains("raw log line")); QVERIFY(!text.contains("secret-token"));
        QVERIFY(!text.contains("/var/lib/crash")); QVERIFY(!text.contains("raw body"));
        QVERIFY(text.contains("\"evidence_reports\": 4")); QVERIFY(text.contains("<private path>"));
    }
    void knowledgeRequiresEvidenceAndCannotExecute() {
        QJsonObject e{{"schema", 1}, {"id", "test"}, {"title", "test"}, {"kind", "policy"}, {"status", "verified"},
            {"explanation", "intentional"}, {"reviewed", "2026-09-29"}, {"match", QJsonObject{{"package", "app"}, {"versions", QJsonArray{"1"}}}},
            {"evidence", QJsonArray{"docs/test"}}};
        QVERIFY(Care::validateKnowledge(e).isEmpty()); e["exec"] = "false";
        QVERIFY(!Care::validateKnowledge(e).isEmpty()); e.remove("exec"); e["evidence"] = QJsonArray{};
        QVERIFY(!Care::validateKnowledge(e).isEmpty());
    }
};
QTEST_GUILESS_MAIN(CareTests)
#include "tests.moc"
