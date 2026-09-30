// SPDX-License-Identifier: GPL-3.0-or-later
#include <QCoreApplication>
#include <QTextStream>
#include "runtime.h"
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    auto api = RimeRuntime::instance().api;
    auto session = api->create_session();
    if (!session || !api->select_schema(session, "luna_pinyin_simp")) return 1;
    api->set_option(session, "ascii_mode", false);
    api->set_option(session, "simplification", true);
    const QList<QPair<QByteArray, QString>> examples{{"nihao", "你好"}, {"zhongguo", "中国"}, {"ceshi", "测试"}};
    for (int repeat = 0; repeat < 100; ++repeat) {
        for (const auto &example : examples) {
            api->clear_composition(session);
            for (char c : example.first) if (!api->process_key(session, c, 0)) return 2;
            RIME_STRUCT(RimeContext, context);
            if (!api->get_context(session, &context)) return 3;
            const bool valid = context.menu.num_candidates > 0 && QString::fromUtf8(context.menu.candidates[0].text) == example.second;
            api->free_context(&context);
            if (!valid || !api->select_candidate(session, 0)) return 4;
            RIME_STRUCT(RimeCommit, commit);
            if (!api->get_commit(session, &commit)) return 5;
            const bool committed = QString::fromUtf8(commit.text) == example.second;
            api->free_commit(&commit);
            if (!committed) return 6;
        }
    }
    api->destroy_session(session);
    QTextStream(stdout) << "PASS: 300 rapid compositions, Chinese first candidate, selection and commit\n";
}
