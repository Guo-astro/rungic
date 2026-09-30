// SPDX-License-Identifier: GPL-2.0-or-later
#include "model.h"
#include "layout.h"
#include "usage.h"
#include "claude_code.h"
#include <KConfig>
#include <KConfigGroup>
#include <QFile>
#include <QTemporaryDir>
#include <QtTest>
#include <QDir>
#include <QFileInfo>
#include <QJsonDocument>
#include <QSet>
#include <time.h>

class CareTests : public QObject {
    Q_OBJECT
    static QJsonObject item(QString key = "crash:1", QString source = "crashes") {
        auto o = Care::observation(key, "应用退出", "原因待核实", "fault", 1, {{"signature", "abc"}});
        o["source"] = source; return o;
    }
    // ---- Agent usage (docs/research/95) ----
    static Care::UsageProvider provider(const QString &id, int order = 100, bool optional = false) {
        Care::UsageProvider p; p.id = id; p.name = id.toUpper(); p.vendor = "V"; p.order = order; p.optional = optional;
        p.service = "com.example." + id; p.path = "/usage"; p.interface = "com.example.Usage"; p.method = "Usage";
        return p;
    }
    static QJsonObject token(const QString &account, const QString &session, qint64 total, qint64 last) {
        return {{"accountKey", account}, {"session", session}, {"turn", "turn"}, {"total", total}, {"last", last}};
    }
    static QJsonObject shown(const QJsonObject &view, const QString &id) {
        for (const auto &v : view["providers"].toArray()) if (v.toObject()["id"] == id) return v.toObject();
        return {};
    }
    static void write(const QString &path, const QByteArray &bytes) {
        QDir().mkpath(QFileInfo(path).absolutePath());
        QFile f(path); QVERIFY(f.open(QIODevice::WriteOnly)); f.write(bytes);
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
    // ---- Agent usage (docs/research/95) ----
    void initTestCase() { qputenv("TZ", "UTC"); tzset(); }
    void usageDeduplicatesRequestsRestartsAndAccounts() {
        QTemporaryDir d; const auto path = d.path() + "/usage.json";
        Care::Usage u(path); u.setProviders({provider("codex")});
        const QJsonObject snapshot{{"accountKey", "account-a"}, {"account", QJsonObject{{"kind", "api-key"}}}};
        u.snapshot("codex", snapshot, 100);
        auto event = token("account-a", "thread", 1200, 200);
        u.record("codex", event, 101); u.record("codex", event, 102);
        auto device = [](const QJsonObject &view) { return shown(view, "codex")["tokens"].toObject()["device"]; };
        QCOMPARE(device(u.view(102)).toInteger(), 200); // resumed history is not counted
        event = token("account-a", "thread", 1700, 500);
        u.record("codex", event, 103); QCOMPARE(device(u.view(103)).toInteger(), 700); // same turn, second model request
        Care::Usage restarted(path); restarted.setProviders({provider("codex")});
        QVERIFY(device(restarted.view(104)).isNull()); // not shown before the account is confirmed again
        restarted.snapshot("codex", snapshot, 105); restarted.record("codex", event, 106);
        QCOMPARE(device(restarted.view(106)).toInteger(), 700);
        QCOMPARE(shown(restarted.view(106), "codex")["tokens"].toObject()["today"].toInteger(), 700);
        restarted.snapshot("codex", {{"accountKey", "account-b"}}, 107);
        QVERIFY(device(restarted.view(107)).isNull());
        restarted.record("codex", token("account-b", "thread", 1700, 500), 108);
        QCOMPARE(device(restarted.view(108)).toInteger(), 500);
        restarted.snapshot("codex", snapshot, 109); QCOMPARE(device(restarted.view(109)).toInteger(), 700);
        QCOMPARE(Care::readObject(path)["schema"].toInt(), 2);
    }
    void usageLedgerMigratesSchemaOneAndLegacyEvents() {
        QTemporaryDir d; const auto path = d.path() + "/usage.json";
        const QJsonObject account{{"turns", QJsonObject{{Care::fingerprint("thread"), QJsonObject{{"tokens", 1000}}}}}, {"total", 400}, {"days", QJsonObject{}}};
        QVERIFY(Care::writeObject(path, {{"schema", 1}, {"accounts", QJsonObject{{"a", account}}}}));
        Care::Usage u(path); u.setProviders({provider("codex")});
        u.snapshot("codex", {{"accountKey", "a"}}, 100);
        const QJsonObject legacy{{"type", "token-usage"}, {"accountKey", "a"}, {"threadId", "thread"}, {"turnId", "t"},
            {"tokenUsage", QJsonObject{{"total", QJsonObject{{"totalTokens", 1100}}}, {"last", QJsonObject{{"totalTokens", 100}}}}}};
        QVERIFY(u.record("codex", Care::codexTokenEvent(legacy), 101));
        QCOMPARE(shown(u.view(101), "codex")["tokens"].toObject()["device"].toInteger(), 500);
        QVERIFY(!u.record("codex", Care::codexTokenEvent(legacy), 102));
        QVERIFY(!u.record("undeclared", token("a", "s", 10, 0), 103)); // no descriptor, no record
    }
    void usageQuotaIsNullableAndResetDoesNotInventFreshData() {
        Care::Usage u(""); u.setProviders({provider("codex")});
        const QJsonArray limits{QJsonObject{{"id", "codex.primary"}, {"label", "codex"}, {"usedPercent", 75}, {"windowMinutes", 300}, {"resetsAt", 200}}};
        u.snapshot("codex", {{"accountKey", "a"}, {"account", QJsonObject{{"kind", "subscription"}, {"label", "ChatGPT"}}}, {"limits", limits}}, 100);
        auto p = shown(u.view(101), "codex"); QCOMPARE(p["limits"].toArray().size(), 1);
        QVERIFY(!p["limits"].toArray()[0].toObject()["expired"].toBool());
        QCOMPARE(p["limits"].toArray()[0].toObject()["windowMinutes"].toInt(), 300);
        QVERIFY(shown(u.view(201), "codex")["limits"].toArray()[0].toObject()["expired"].toBool());
        QVERIFY(shown(u.view(301), "codex")["stale"].toBool());
        // A partial read keeps the last limits and says so.
        u.snapshot("codex", {{"accountKey", "a"}, {"error", "not updated"}}, 302);
        p = shown(u.view(302), "codex");
        QCOMPARE(p["limits"].toArray().size(), 1); QVERIFY(p["stale"].toBool()); QCOMPARE(p["error"].toString(), "not updated");
        u.snapshot("codex", {{"accountKey", "a"}, {"account", QJsonObject{{"kind", "api-key"}}}}, 303);
        QVERIFY(shown(u.view(303), "codex")["limits"].toArray().isEmpty());
        u.snapshot("codex", {{"status", "signed-out"}}, 304);
        p = shown(u.view(304), "codex");
        QVERIFY(p["tokens"].toObject()["device"].isNull()); QCOMPARE(p["status"].toString(), "signed-out");
        QCOMPARE(p["account"].toObject()["kind"].toString(), "none");
    }
    void usageDescriptorsLoadFromSystemAndUserDirectories() {
        QTemporaryDir d; const auto system = d.path() + "/system", user = d.path() + "/user";
        write(system + "/codex.json", R"({"schema":1,"id":"codex","name":"Codex","vendor":"OpenAI","order":10,
            "dbus":{"service":"com.rungic.VoiceAgent","path":"/com/rungic/VoiceAgent","interface":"com.rungic.VoiceAgent","method":"Usage"}})");
        write(system + "/reader.json", R"({"schema":1,"id":"reader","name":"Reader","command":["/usr/libexec/reader","--json"],"optional":true})");
        write(system + "/broken.json", "{not json");
        write(system + "/both.json", R"({"schema":1,"id":"both","name":"B","command":["/bin/x"],"dbus":{"service":"a.b","path":"/","interface":"a.b"}})");
        write(system + "/relative.json", R"({"schema":1,"id":"relative","name":"R","command":["reader"]})");
        write(system + "/misnamed.json", R"({"schema":1,"id":"other","name":"M","command":["/bin/x"]})");
        write(system + "/Bad-Id.json", R"({"schema":1,"id":"Bad-Id","name":"M","command":["/bin/x"]})");
        write(system + "/nosource.json", R"({"schema":1,"id":"nosource","name":"N"})");
        write(system + "/badpath.json", R"({"schema":1,"id":"badpath","name":"N","dbus":{"service":"a.b","path":"relative","interface":"a.b"}})");
        write(user + "/reader.json", R"({"schema":1,"id":"reader","name":"My reader","command":["/home/u/bin/reader"],"order":5})");
        write(user + "/mine.json", R"({"schema":1,"id":"mine","name":"Mine","command":["/home/u/bin/mine"],"future":"ignored"})");
        QStringList errors;
        const auto list = Care::usageProviders({system, user, d.path() + "/missing"}, &errors);
        QStringList ids; for (const auto &p : list) ids.append(p.id);
        QCOMPARE(ids, (QStringList{"reader", "codex", "mine"})); // by order, then id
        QCOMPARE(errors.size(), 7);
        QCOMPARE(list[0].name, "My reader"); QVERIFY(list[0].file.startsWith(user)); QVERIFY(!list[0].optional);
        QCOMPARE(list[0].timeout, 10000); QCOMPARE(list[0].command, (QStringList{"/home/u/bin/reader"}));
        QVERIFY(list[1].dbus()); QCOMPARE(list[1].timeout, 35000); QCOMPARE(list[1].service, "com.rungic.VoiceAgent");
        // The descriptors this repository ships load.
        for (const auto *file : {"/../agent-usage/claude-code.json", "/../../voice-agent/agent-usage/codex.json"}) {
            const QString path = QStringLiteral(CARE_TESTDATA) + file;
            if (!QFile::exists(path)) continue; // the voice agent's tree is not part of this package's build
            QCOMPARE(Care::validateUsageProvider(Care::readObject(path), QFileInfo(path).fileName()), QString());
        }
    }
    void usageViewOrdersProvidersAndChoosesPrimary() {
        Care::Usage u(""); u.setProviders({provider("a", 10), provider("b", 20), provider("c", 30, true)});
        auto v = u.view(100);
        QCOMPARE(v["schema"].toInt(), 2); QCOMPARE(v["providers"].toArray().size(), 2); // optional c not seen yet
        QCOMPARE(v["primary"].toString(), "a"); // nothing active: the first
        QCOMPARE(shown(v, "a")["status"].toString(), "connecting"); QVERIFY(shown(v, "a")["stale"].toBool());
        QCOMPARE(shown(v, "a")["name"].toString(), "A"); QCOMPARE(shown(v, "a")["vendor"].toString(), "V");
        u.snapshot("a", {{"accountKey", "k"}}, 101); u.snapshot("b", {{"accountKey", "k"}}, 101);
        u.record("b", token("k", "s", 50, 50), 102);
        QCOMPARE(u.view(103)["primary"].toString(), "b"); // most recently active
        u.snapshot("a", {{"accountKey", "k"}, {"status", "working"}}, 90);
        QCOMPARE(u.view(104)["primary"].toString(), "a"); // working wins
        u.snapshot("c", {{"status", "ready"}, {"lastActive", 500}}, 105);
        v = u.view(106);
        QCOMPARE(v["providers"].toArray().size(), 3); QCOMPARE(v["providers"].toArray()[2].toObject()["id"].toString(), "c");
        QCOMPARE(v["primary"].toString(), "a");
        u.snapshot("a", {{"accountKey", "k"}, {"status", "ready"}}, 107);
        QCOMPARE(u.view(108)["primary"].toString(), "c");
        QCOMPARE(u.view(108)["updatedAt"].toInteger(), 107);
        u.snapshot("c", {{"available", false}}, 109);
        QCOMPARE(u.view(110)["providers"].toArray().size(), 2); // its agent isn't used here
        Care::Usage none(""); QCOMPARE(none.view(1)["primary"].toString(), QString());
    }
    void usageAccountsAreIsolatedPerProvider() {
        Care::Usage u(""); u.setProviders({provider("a"), provider("b")});
        u.snapshot("a", {{"accountKey", "same"}}, 100); u.snapshot("b", {{"accountKey", "same"}}, 100);
        u.record("a", token("same", "s", 300, 300), 101);
        auto v = u.view(102);
        QCOMPARE(shown(v, "a")["tokens"].toObject()["device"].toInteger(), 300);
        QVERIFY(shown(v, "b")["tokens"].toObject()["device"].isNull()); // the same key under another agent is not shared
        u.record("b", token("same", "s", 300, 300), 103); // the same session id under another agent counts separately
        QCOMPARE(shown(u.view(104), "b")["tokens"].toObject()["device"].toInteger(), 300);
        QCOMPARE(shown(u.view(104), "a")["tokens"].toObject()["device"].toInteger(), 300);
    }
    void usageStaleAndErrorArePerProvider() {
        Care::Usage u(""); u.setProviders({provider("a"), provider("b")});
        u.snapshot("a", {{"accountKey", "k"}}, 100); u.snapshot("b", {{"accountKey", "k"}}, 100);
        u.failure("b", "B is unavailable");
        auto v = u.view(101);
        QVERIFY(!shown(v, "a")["stale"].toBool()); QCOMPARE(shown(v, "a")["error"].toString(), QString());
        QVERIFY(shown(v, "b")["stale"].toBool()); QCOMPARE(shown(v, "b")["status"].toString(), "error");
        QCOMPARE(shown(v, "b")["error"].toString(), "B is unavailable");
        u.failure("a", {}, true);
        QCOMPARE(shown(u.view(102), "a")["status"].toString(), "offline"); QVERIFY(shown(u.view(102), "a")["stale"].toBool());
        u.snapshot("b", {{"accountKey", "k"}}, 103);
        QVERIFY(!shown(u.view(104), "b")["stale"].toBool()); QCOMPARE(shown(u.view(104), "b")["status"].toString(), "ready");
    }
    void usageDropsUnknownFields() {
        Care::Usage u(""); u.setProviders({provider("a")});
        u.snapshot("a", {{"accountKey", "secret-key"}, {"email", "someone@example.com"}, {"name", "Spoofed"}, {"id", "other"},
            {"status", "dancing"}, {"model", "m"}, {"tokenEvents", QJsonArray{}},
            {"account", QJsonObject{{"kind", "subscription"}, {"label", "L"}, {"plan", "p"}, {"token", "sk-secret"}}},
            {"tokens", QJsonObject{{"account", 12}, {"device", -3}, {"cost", 5}}},
            {"limits", QJsonArray{QJsonObject{{"id", "x"}, {"usedPercent", 5}, {"secret", "y"}}, QJsonObject{{"id", "no-percent"}}}}}, 100);
        const auto p = shown(u.view(101), "a");
        const auto text = QJsonDocument(p).toJson();
        for (const auto *leak : {"secret", "someone", "Spoofed", "cost", "dancing", "tokenEvents"}) QVERIFY2(!text.contains(leak), leak);
        const auto keys = p.keys();
        QCOMPARE(QSet<QString>(keys.begin(), keys.end()), (QSet<QString>{"id", "name", "vendor", "status", "account", "model", "tokens", "limits", "updatedAt", "stale", "error"}));
        QCOMPARE(p["name"].toString(), "A"); QCOMPARE(p["status"].toString(), "ready");
        QCOMPARE(p["account"].toObject().keys(), (QStringList{"kind", "label", "plan"}));
        QCOMPARE(p["tokens"].toObject()["account"].toInteger(), 12); QVERIFY(p["tokens"].toObject()["device"].isNull());
        QCOMPARE(p["limits"].toArray().size(), 1);
        QCOMPARE(p["limits"].toArray()[0].toObject().keys(), (QStringList{"expired", "id", "label", "resetsAt", "usedPercent", "windowMinutes"}));
    }
    void usageAdapterLedgerTokensPassThrough() {
        Care::Usage u(""); u.setProviders({provider("reader")});
        u.snapshot("reader", {{"tokens", QJsonObject{{"device", 1375}, {"today", 1322}}}}, 100);
        const auto t = shown(u.view(101), "reader")["tokens"].toObject();
        QCOMPARE(t["device"].toInteger(), 1375); QCOMPARE(t["today"].toInteger(), 1322); QVERIFY(t["account"].isNull());
    }
    void claudeCodeTranscriptsCountEachMessageOnce() {
        QTemporaryDir d; const auto root = d.path() + "/claude";
        const QString fixture = QStringLiteral(CARE_TESTDATA) + "/claude-code/projects/-home-u-proj";
        for (const auto *file : {"/s1.jsonl", "/s2.jsonl", "/s1/subagents/agent-x.jsonl"}) {
            QFile f(fixture + file); QVERIFY(f.open(QIODevice::ReadOnly));
            write(root + "/projects/-home-u-proj" + file, f.readAll());
        }
        const Care::ClaudeCode::Paths paths{{root}, d.path() + "/ledger.json", d.path() + "/statusline.json"};
        const auto now = QDateTime::fromString("2026-09-30T12:00:00Z", Qt::ISODate).toSecsSinceEpoch();
        auto r = Care::ClaudeCode::read(paths, now);
        // msg_A (1115, in two files) + msg_B (53, yesterday) + msg_C (7) + subagent msg_D (200)
        QCOMPARE(r["tokens"].toObject()["device"].toInteger(), 1375);
        QCOMPARE(r["tokens"].toObject()["today"].toInteger(), 1322);
        QCOMPARE(r["model"].toString(), "claude-sonnet-5"); QCOMPARE(r["status"].toString(), "ready");
        QCOMPARE(r["lastActive"].toInteger(), QDateTime::fromString("2026-09-30T02:00:00Z", Qt::ISODate).toSecsSinceEpoch());
        QVERIFY(!r.contains("limits")); QVERIFY(!r.contains("error")); QVERIFY(!r.contains("account"));
        QCOMPARE(Care::ClaudeCode::read(paths, now)["tokens"].toObject()["device"].toInteger(), 1375); // no recount
        QFile s1(root + "/projects/-home-u-proj/s1.jsonl"); QVERIFY(s1.open(QIODevice::Append));
        s1.write(R"({"type":"assistant","message":{"id":"msg_E","usage":{"input_tokens":400,"output_tokens)"); s1.flush();
        QCOMPARE(Care::ClaudeCode::read(paths, now)["tokens"].toObject()["device"].toInteger(), 1375); // half a line waits
        s1.write(R"(":600}},"requestId":"req_E","timestamp":"2026-09-30T11:00:00.000Z","sessionId":"s1","uuid":"a9"})" "\n"); s1.close();
        QCOMPARE(Care::ClaudeCode::read(paths, now)["tokens"].toObject()["device"].toInteger(), 2375);
        const auto during = QDateTime::fromString("2026-09-30T11:01:00Z", Qt::ISODate).toSecsSinceEpoch();
        QCOMPARE(Care::ClaudeCode::read(paths, during)["status"].toString(), "working"); // a response a minute ago
        QVERIFY(QFile::remove(root + "/projects/-home-u-proj/s2.jsonl")); // Claude Code's cleanup
        r = Care::ClaudeCode::read(paths, now + 86400);
        QCOMPARE(r["tokens"].toObject()["device"].toInteger(), 2375); QCOMPARE(r["tokens"].toObject()["today"].toInteger(), 0);
        QCOMPARE(r["status"].toString(), "ready");
        QVERIFY(!(QFileInfo(paths.ledger).permissions() & (QFile::ReadGroup | QFile::ReadOther)));
        // A first read cut short by its time budget continues next time instead of starting over.
        const Care::ClaudeCode::Paths fresh{{root}, d.path() + "/fresh.json", d.path() + "/statusline.json"};
        r = Care::ClaudeCode::read(fresh, now, 0);
        QVERIFY(!r["error"].toString().isEmpty());
        QCOMPARE(Care::ClaudeCode::read(fresh, now)["tokens"].toObject()["device"].toInteger(), 2368); // s2 (msg_C) is gone
        QCOMPARE(Care::ClaudeCode::lineTokens(QJsonObject{{"message", QJsonObject{{"usage", QJsonObject{{"input_tokens", 1},
            {"cache_creation_input_tokens", 9}, {"cache_creation", QJsonObject{{"ephemeral_5m_input_tokens", 2}, {"ephemeral_1h_input_tokens", 3}}}}}}}}), 6);
        const Care::ClaudeCode::Paths nothing{{d.path() + "/none"}, d.path() + "/n.json", d.path() + "/ns.json"};
        QCOMPARE(Care::ClaudeCode::read(nothing, now), (QJsonObject{{"available", false}}));
    }
    void claudeCodeLimitsOnlyFromTheDocumentedStatusline() {
        QTemporaryDir d;
        const Care::ClaudeCode::Paths paths{{d.path() + "/none"}, d.path() + "/ledger.json", d.path() + "/statusline.json"};
        QFile f(QStringLiteral(CARE_TESTDATA) + "/claude-code/statusline.json"); QVERIFY(f.open(QIODevice::ReadOnly));
        const auto input = f.readAll();
        const qint64 now = 1738420000;
        QCOMPARE(Care::ClaudeCode::statusline(input, paths, now), "Opus · 5h 24% · 7d 41%");
        const auto kept = QString::fromUtf8(QJsonDocument(Care::readObject(paths.statusline)).toJson());
        QVERIFY(!kept.contains("transcript_path") && !kept.contains("cost") && !kept.contains("/home/u"));
        auto r = Care::ClaudeCode::read(paths, now + 60);
        QVERIFY(!r.contains("tokens")); QCOMPARE(r["model"].toString(), "claude-opus-5-5");
        QCOMPARE(r["account"].toObject()["kind"].toString(), "subscription");
        const auto limits = r["limits"].toArray(); QCOMPARE(limits.size(), 2);
        QCOMPARE(limits[0].toObject()["windowMinutes"].toInt(), 300); QCOMPARE(limits[0].toObject()["usedPercent"].toDouble(), 23.5);
        QCOMPARE(limits[0].toObject()["resetsAt"].toInteger(), 1738425600); QCOMPARE(limits[1].toObject()["windowMinutes"].toInt(), 10080);
        // A new session's input before its first response has no rate_limits: the last ones stay.
        auto next = QJsonDocument::fromJson(input).object(); next.remove("rate_limits");
        Care::ClaudeCode::statusline(QJsonDocument(next).toJson(), paths, now + 120);
        QCOMPARE(Care::ClaudeCode::read(paths, now + 180)["limits"].toArray().size(), 2);
        QVERIFY(!Care::ClaudeCode::read(paths, now + 3721).contains("limits")); // an hour without a new reading
        // A window Claude Code dropped (reset) goes; a malformed percentage (claude-code#52326) is not kept.
        next["rate_limits"] = QJsonObject{{"seven_day", QJsonObject{{"used_percentage", 1738857600}, {"resets_at", 1738857600}}}};
        Care::ClaudeCode::statusline(QJsonDocument(next).toJson(), paths, now + 4000);
        QVERIFY(Care::ClaudeCode::read(paths, now + 4001)["limits"].toArray().isEmpty());
        QCOMPARE(Care::ClaudeCode::statusline("not json", paths, now), QString());
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
