// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QDir>
#include <QFile>
#include <QList>
#include <QStandardPaths>
#include <QString>
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#include <rime_api.h>

// librime is process-global; each input method instance owns at most one session at a time.
//
// The user dictionary (luna_pinyin.userdb, LevelDB) is shared by every process running this
// plugin: plasma-keyboard and the fullscreen keyboard (docs/41, 2026-10-03). LevelDB lets one
// process open it at a time, and librime 1.16.1 answers a failed open by scheduling a recovery
// (UserDictionary::Load -> UserDbRecoveryTask::Run) that runs leveldb::RepairDB, which takes no
// lock, and may rename the directory away: under the process that has it open. So no session
// here may even try to open it unless this process holds the directory lock below. Sessions
// holding it are "shared"; while another process holds it, a "guest" session is built with
// enable_user_dict off: Chinese input without learning, retried on the next session.
class RimeRuntime {
public:
    struct Session {
        RimeSessionId id = 0;
        bool shared = false;   // uses the user dictionary
    };
    static constexpr const char *schema = "luna_pinyin_simp";
    RimeApi *api = rime_get_api();
    QByteArray user;
    bool ready = false;    // the schema is deployed
    bool guests = false;   // schema edits reach new sessions (probed below)
    static RimeRuntime &instance() { static RimeRuntime r; return r; }

    // A shared session when this process can hold the user dictionary, otherwise a guest one
    // (unless sharedOnly). False when neither is possible.
    bool open(Session &s, bool sharedOnly = false) {
        if (!ready) return false;
        if (retainUserDb()) {
            s = {api->create_session(), true};
            if (s.id && prepare(s.id)) return true;
            close(s);
            return false;
        }
        if (sharedOnly || !guests) return false;
        const auto saved = disableUserDict();
        s = {api->create_session(), false};
        const bool ok = s.id && prepare(s.id);
        restore(saved);
        if (!ok) close(s);
        return ok;
    }
    void close(Session &s) {
        if (s.id) api->destroy_session(s.id);   // the last one closes the LevelDB synchronously
        if (s.shared) releaseUserDb();
        s = {};
    }

private:
    RimeConfig config{};   // keeps the parsed schema cached between sessions (most of a cold start)
    int lockFd = -1;
    int users = 0;         // shared sessions in this process

    struct Edit { RimeConfig config; QByteArray key; Bool value; };

    bool prepare(RimeSessionId id) {
        char current[100] = {};
        // create_session builds the schema_list default; select only if that is another one.
        if (!api->get_current_schema(id, current, sizeof current) || qstrcmp(current, schema) != 0)
            if (!api->select_schema(id, schema)) return false;
        api->set_option(id, "ascii_mode", false);
        api->set_option(id, "simplification", true);
        return true;
    }

    bool retainUserDb() {
        if (users) { ++users; return true; }
        const int fd = ::open(QByteArray(user + "/rungic-userdb.lock").constData(), O_RDWR | O_CREAT | O_CLOEXEC, 0600);
        if (fd < 0) return false;
        if (::flock(fd, LOCK_EX | LOCK_NB) != 0 || foreignHolder()) { ::close(fd); return false; }
        lockFd = fd;
        users = 1;
        return true;
    }
    void releaseUserDb() {
        if (users == 0 || --users > 0) return;
        api->join_maintenance_thread();   // a recovery task may still hold the database
        ::close(lockFd);
        lockFd = -1;
    }
    // A LevelDB lock (fcntl) without our directory lock: a process that does not take it, such
    // as plasma-keyboard still running a plugin from before 2026-10-03. Only called while this
    // process holds no user dictionary: closing a probe fd drops the caller's own fcntl locks.
    bool foreignHolder() const {
        const auto dbs = QDir(QFile::decodeName(user)).entryInfoList({QStringLiteral("*.userdb")}, QDir::Dirs);
        for (const QFileInfo &db : dbs) {
            const int fd = ::open(QFile::encodeName(db.filePath() + QStringLiteral("/LOCK")).constData(), O_RDONLY | O_CLOEXEC);
            if (fd < 0) continue;
            struct flock probe {};
            probe.l_type = F_WRLCK;
            probe.l_whence = SEEK_SET;
            const bool held = ::fcntl(fd, F_GETLK, &probe) == 0 && probe.l_type != F_UNLCK;
            ::close(fd);
            if (held) return true;
        }
        return false;
    }

    // Schema configs are shared, in memory, with the sessions created while they are open
    // (ConfigComponentBase::GetConfigData's cache), so turning enable_user_dict off in them for
    // the duration of create_session/select_schema keeps those engines off the user dictionary.
    // The engine reads it only when building its translators, which a guest session does only
    // there. Covers the schema we select and the schema_list default that create_session builds.
    QList<Edit> disableUserDict() {
        QList<QByteArray> ids{schema};
        RimeConfig defaults{};
        if (api->config_open("default", &defaults)) {
            const size_t n = api->config_list_size(&defaults, "schema_list");
            for (size_t i = 0; i < n; ++i)
                if (const char *id = api->config_get_cstring(&defaults, QByteArray("schema_list/@" + QByteArray::number(qulonglong(i)) + "/schema").constData()))
                    if (!ids.contains(id)) ids.append(id);
            api->config_close(&defaults);
        }
        QList<Edit> edits;
        for (const QByteArray &id : ids) {
            RimeConfig c{};
            if (!api->schema_open(id.constData(), &c)) continue;
            QList<QByteArray> keys;   // translators without "@name" share the "translator" namespace
            const size_t n = api->config_list_size(&c, "engine/translators");
            for (size_t i = 0; i < n; ++i) {
                const QByteArray entry = api->config_get_cstring(&c, QByteArray("engine/translators/@" + QByteArray::number(qulonglong(i))).constData());
                const int at = entry.indexOf('@');
                const QByteArray key = (at < 0 ? QByteArray("translator") : entry.mid(at + 1)) + "/enable_user_dict";
                if (keys.contains(key)) continue;
                keys.append(key);
                Bool value = True;   // librime's default when absent
                api->config_get_bool(&c, key.constData(), &value);
                api->config_set_bool(&c, key.constData(), False);
                edits.append({c, key, value});
            }
            edits.append({c, {}, False});   // the handle, closed by restore()
        }
        return edits;
    }
    void restore(QList<Edit> edits) {
        for (Edit &e : edits) {   // values first, then the handle, as appended
            if (!e.key.isEmpty()) api->config_set_bool(&e.config, e.key.constData(), e.value);
            else api->config_close(&e.config);
        }
    }
    // Guest sessions depend on that sharing; check it once rather than assume it.
    bool probeGuests() {
        RimeConfig other{};
        if (!api->schema_open(schema, &other)) return false;
        Bool before = True, seen = True;
        api->config_get_bool(&config, "translator/enable_user_dict", &before);
        api->config_set_bool(&config, "translator/enable_user_dict", !before);
        const bool shared = api->config_get_bool(&other, "translator/enable_user_dict", &seen) && seen == !before;
        api->config_set_bool(&config, "translator/enable_user_dict", before);
        api->config_close(&other);
        return shared;
    }

    RimeRuntime() {
        QString path = qEnvironmentVariable("RUNGIC_RIME_USER_DIR");
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
        traits.distribution_code_name = "rungic-plasma-rime";
        traits.distribution_version = "1.0";
        traits.app_name = "rime.plasma";
        traits.min_log_level = 2;
        traits.log_dir = "";
        api->setup(&traits);
        api->initialize(&traits);
        if (api->start_maintenance(false)) api->join_maintenance_thread();
        ready = api->schema_open(schema, &config) && api->config_get_cstring(&config, "schema/schema_id");
        guests = ready && probeGuests();
    }
    ~RimeRuntime() {
        if (config.ptr) api->config_close(&config);
        api->finalize();
    }
};
