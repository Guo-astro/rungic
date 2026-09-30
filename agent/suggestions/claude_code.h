// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <QByteArray>
#include <QJsonObject>
#include <QStringList>
// The Claude Code usage reader (docs/research/95), a provider of the desktop's agent usage.
//  - Tokens: Claude Code's own session transcripts (<config>/projects/**/*.jsonl). Their format is
//    internal to Claude Code and changes between versions: read defensively, counted into a ledger of
//    our own (deduplicated per API message), so counts outlive Claude Code's transcript cleanup.
//  - Limits: only from the documented statusline input (`rate_limits`, Claude Code >= 2.1.80), when
//    the user runs `--statusline` as (or from) their statusLine command. Never from undocumented APIs.
namespace Care::ClaudeCode {
struct Paths {
    QStringList roots;  // Claude Code configuration directories (each with projects/)
    QString ledger;     // our counts
    QString statusline; // the last statusline input we kept
};
Paths defaults();
// The provider object for AgentUsage. Reads at most `budgetMs` of new transcript lines per run;
// the rest continues on the next run.
QJsonObject read(const Paths &paths, qint64 now, qint64 budgetMs = 8000);
// Keeps the documented statusline fields (rate limits, model); returns a one-line status to print.
QString statusline(const QByteArray &input, const Paths &paths, qint64 now);
// Tokens of one transcript line (input + output + cache writes + cache reads), 0 if it has none.
qint64 lineTokens(const QJsonObject &line);
}
