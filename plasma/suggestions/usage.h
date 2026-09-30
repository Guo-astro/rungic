// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "model.h"
namespace Care {
class Usage {
public:
    explicit Usage(QString path);
    void snapshot(const QJsonObject &data, qint64 now);
    void token(const QJsonObject &event, qint64 now);
    QJsonObject view(qint64 now) const;
    void error(const QString &message) { problem = message; }
private:
    void save();
    QString path, accountKey, problem;
    QJsonObject accounts, current;
    qint64 refreshed = 0;
};
}
