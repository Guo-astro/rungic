// SPDX-License-Identifier: GPL-2.0-or-later
#include "model.h"
#include "layout.h"
#include <KConfig>
#include <KConfigGroup>
#include <QFile>
#include <QTemporaryDir>
#include <QtTest>

class CareTests : public QObject {
    Q_OBJECT
    static QJsonObject item(QString key = "crash:1", QString source = "crashes") {
        auto o = Care::observation(key, "应用退出", "原因待核实", "fault", 1, {{"signature", "abc"}});
        o["source"] = source; return o;
    }
private Q_SLOTS:
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
            auto items = pages[0].toArray(); QCOMPARE(items.size(), 2);
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
