// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QDir>
#include <QFile>
#include <QStandardPaths>
#include <rime_api.h>

// librime is process-global; each input method instance owns a separate session.
class RimeRuntime {
public:
    RimeApi *api = rime_get_api();
    QByteArray user;
    static RimeRuntime &instance() { static RimeRuntime r; return r; }
private:
    RimeRuntime() {
        QString path = qEnvironmentVariable("MOTO_RIME_USER_DIR");
        if (path.isEmpty()) path = QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation) + "/plasma-rime";
        QDir().mkpath(path);
        QFile::setPermissions(path, QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner);
        user = QFile::encodeName(path);
        QFile defaults(path + "/default.custom.yaml");
        if (!defaults.exists() && defaults.open(QIODevice::WriteOnly)) {
            defaults.write("patch:\n  schema_list:\n    - schema: luna_pinyin_simp\n  menu/page_size: 9\n");
            defaults.close();
        }
        RIME_STRUCT(RimeTraits, traits);
        traits.shared_data_dir = "/usr/share/rime-data";
        traits.user_data_dir = user.constData();
        traits.distribution_name = "Plasma Rime";
        traits.distribution_code_name = "moto-plasma-rime";
        traits.distribution_version = "1.0";
        traits.app_name = "rime.plasma";
        traits.min_log_level = 2;
        traits.log_dir = "";
        api->setup(&traits);
        api->initialize(&traits);
        if (api->start_maintenance(false)) api->join_maintenance_thread();
    }
    ~RimeRuntime() { api->finalize(); }
};
