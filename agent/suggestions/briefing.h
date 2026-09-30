// SPDX-License-Identifier: GPL-2.0-or-later
// The briefing (docs/research/96): the few cards the user sees, chosen by the Agent from the ledger
// (Model), which stays the fact store. Everything here is pure and takes `now`, so the service's
// timers and the tests drive the same code.
#pragma once
#include <QJsonArray>
#include <QJsonObject>
#include <QSet>
#include <QString>

namespace Care {
namespace BriefingLimits {
constexpr int MaxCards = 5;
constexpr int TitleMax = 60;
constexpr int BodyMax = 160;
constexpr int LabelMax = 40;
constexpr int PromptMax = 400;
constexpr int MaxRefs = 50;
constexpr int InputItems = 40;          // ledger records sent to the curator at most
constexpr int FeedbackKept = 20;
constexpr qint64 FeedbackDays = 14;
constexpr qint64 Debounce = 120;        // quiet after the last material change
constexpr qint64 MinInterval = 3600;    // between two background curations
constexpr qint64 MinIntervalUrgent = 600; // when a task result waits or a severe fault appeared
constexpr int DailyCap = 12;            // curations (background and manual) per 24 h
constexpr qint64 ResolvedShown = 3 * 86400; // resolved records still reported to the curator
}

// Every string that leaves the device for curation goes through this: home paths, e-mail
// addresses and control characters removed, whitespace simplified, length bounded.
QString redact(const QString &text, int max = 200);

class Briefing {
public:
    explicit Briefing(QString path);
    bool load();
    bool save(QString *error = nullptr) const;

    // Per ledger record, what counts as a material change: a new record, recurrence or severity
    // increase (deliveryRevision), resolved (issueState), a reports count crossing a threshold,
    // a task result waiting for review. Last seen times, wording and receipts are not material.
    static QString material(const QJsonObject &item);
    static QJsonObject digest(const QJsonArray &items);
    // Strictly validated curator output: unknown kinds, bad refs, overlong text, missing fields
    // drop the card; unknown fields are never copied; at most MaxCards.
    static QJsonArray validate(const QJsonValue &output, const QJsonArray &items, QStringList *dropped = nullptr);
    // Deterministic cards without the Agent: one summary for the open findings and one per task
    // result waiting for the user's review.
    static QJsonArray fallbackCards(const QJsonArray &items);

    // A ledger snapshot: records a material change (and schedules curation) when the digest
    // differs from the last one seen. Returns whether it did.
    bool observe(const QJsonArray &items, qint64 now);
    // When curation may run next (0: nothing pending). Debounce, minimum interval, daily cap.
    qint64 nextRun(qint64 now) const;
    bool capped(qint64 now) const;
    // One ledger record as it may leave the device: allow-listed fields, redacted text.
    static QJsonObject redacted(const QJsonObject &item, const QJsonObject &dismissed = {});
    // The redacted input for the curator.
    QJsonObject input(const QJsonArray &items, qint64 now) const;
    void begin(const QJsonArray &items, qint64 now);
    // Adopts the curator's cards; false (nothing changed) when none of them is usable.
    bool applyAgent(const QJsonValue &output, const QJsonArray &items, qint64 now, QStringList *dropped = nullptr);
    void applyFallback(const QJsonArray &items, qint64 now, const QString &error = {});

    // What the user sees: the curated cards (still valid, not dismissed) and, for findings the
    // curator hasn't seen yet, the deterministic cards; at most MaxCards.
    QJsonArray cards(const QJsonArray &items) const;
    QJsonObject card(const QString &id, const QJsonArray &items) const;
    QJsonObject view(const QJsonArray &items, bool background, qint64 now) const;
    // "Not now": the card's records stay hidden until one of them changes materially.
    bool dismiss(const QString &id, const QJsonArray &items, qint64 now);
    bool opened(const QString &id, const QJsonArray &items, qint64 now);
    QJsonArray feedback(qint64 now) const;

    bool curating = false;
    QString source() const { return state["source"].toString(); }
    QJsonObject state;
private:
    void remember(const QJsonObject &card, const QString &action, qint64 now);
    QString path;
};
}
