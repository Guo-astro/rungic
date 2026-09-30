// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <QJsonObject>
namespace Care {
QJsonObject collectSystem(const QString &knowledgeDirectory, const QString &cores = "/var/lib/rungic-cores");
QJsonObject collectUser();
QStringList runningProcesses();
}
