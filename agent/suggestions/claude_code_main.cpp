// SPDX-License-Identifier: GPL-2.0-or-later
// rungic-agent-usage-claude-code (docs/research/95)
//   --json        the Claude Code provider object for the desktop's agent usage (its descriptor runs this)
//   --statusline  as, or from, Claude Code's statusLine command: keeps the documented rate limits
//                 from the JSON on stdin and prints a short status line
#include "claude_code.h"
#include <KLocalizedString>
#include <QCoreApplication>
#include <QDateTime>
#include <QFile>
#include <QJsonDocument>
#include <cstdio>

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    KLocalizedString::setApplicationDomain("rungic-suggestions");
    const auto args = app.arguments();
    const auto paths = Care::ClaudeCode::defaults();
    const auto now = QDateTime::currentSecsSinceEpoch();
    if (args.contains("--statusline")) {
        QFile input;
        if (!input.open(stdin, QIODevice::ReadOnly)) return 1;
        const auto line = Care::ClaudeCode::statusline(input.read(1024 * 1024), paths, now);
        printf("%s\n", qPrintable(line));
        return 0;
    }
    if (args.contains("--json")) {
        printf("%s\n", QJsonDocument(Care::ClaudeCode::read(paths, now)).toJson(QJsonDocument::Compact).constData());
        return 0;
    }
    fprintf(stderr, "Usage: rungic-agent-usage-claude-code --json | --statusline\n");
    return 2;
}
