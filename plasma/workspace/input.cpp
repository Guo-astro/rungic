// rungic-workspace-input: the agent's pointer and keyboard in its own workspace (docs/research/91).
//
// An agent workspace is a KWin of its own; nobody is there to allow a RemoteDesktop portal
// session, so the agent's input goes straight to that KWin through its fake-input protocol
// (org_kde_kwin_fake_input, granted to this executable by its desktop file, as to the
// assistant screen's window). Connects to $WAYLAND_DISPLAY and reads one command a line on
// stdin, answering "ok" (or "error ...") when the compositor has it:
//   move X Y          pointer to X Y (global logical coordinates)
//   rel DX DY         pointer by DX DY
//   button CODE 0|1   Linux button code (BTN_LEFT 0x110 = 272), released or pressed
//   axis 0|1 VALUE    vertical or horizontal scroll, in pointer axis units (15 a notch)
//   key KEYSYM 0|1    a key by X keysym (the us layout's key for it)
#include <QCoreApplication>
#include <QGuiApplication>
#include <QHash>
#include <QSocketNotifier>
#include <QWaylandClientExtensionTemplate>
#include <cstdio>
#include <iostream>
#include <string>
#include <unistd.h>
#include <xkbcommon/xkbcommon.h>

#include "qwayland-fake-input.h"

class FakeInput : public QWaylandClientExtensionTemplate<FakeInput>, public QtWayland::org_kde_kwin_fake_input
{
public:
    FakeInput()
        : QWaylandClientExtensionTemplate<FakeInput>(4)
    {
        initialize();
    }
};

// X keysym -> evdev key code, from the us layout (levels 0 and 1).
static QHash<uint32_t, uint32_t> keycodes()
{
    QHash<uint32_t, uint32_t> map;
    xkb_context *context = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    const xkb_rule_names names{nullptr, nullptr, "us", nullptr, nullptr};
    xkb_keymap *keymap = context ? xkb_keymap_new_from_names(context, &names, XKB_KEYMAP_COMPILE_NO_FLAGS) : nullptr;
    if (keymap) {
        for (xkb_keycode_t code = xkb_keymap_min_keycode(keymap); code <= xkb_keymap_max_keycode(keymap); ++code) {
            for (xkb_level_index_t level = 0; level < 2; ++level) {
                const xkb_keysym_t *syms = nullptr;
                const int count = xkb_keymap_key_get_syms_by_level(keymap, code, 0, level, &syms);
                for (int i = 0; i < count; ++i) {
                    if (!map.contains(syms[i])) {
                        map.insert(syms[i], code - 8);
                    }
                }
            }
        }
        xkb_keymap_unref(keymap);
    }
    if (context) {
        xkb_context_unref(context);
    }
    return map;
}

int main(int argc, char *argv[])
{
    qputenv("QT_QPA_PLATFORM", "wayland");
    QGuiApplication app(argc, argv);
    QGuiApplication::setDesktopFileName(QStringLiteral("com.rungic.WorkspaceInput"));
    FakeInput input;
    const QHash<uint32_t, uint32_t> keys = keycodes();
    auto *display = qApp->nativeInterface<QNativeInterface::QWaylandApplication>()->display();
    bool authenticated = false;

    auto reply = [](const std::string &text) {
        std::cout << text << std::endl;
    };
    QSocketNotifier notifier(STDIN_FILENO, QSocketNotifier::Read);
    QObject::connect(&notifier, &QSocketNotifier::activated, &app, [&]() {
        std::string line;
        if (!std::getline(std::cin, line)) {
            QCoreApplication::quit();
            return;
        }
        if (!input.isActive()) {
            reply("error the compositor offers no fake input");
            return;
        }
        if (!authenticated) {
            input.authenticate(QStringLiteral("Rungic workspace"), QStringLiteral("The agent's pointer and keyboard"));
            authenticated = true;
        }
        char command[16] = {};
        double a = 0, b = 0;
        const int fields = std::sscanf(line.c_str(), "%15s %lf %lf", command, &a, &b);
        const std::string name = fields > 0 ? command : "";
        if (name == "move" && fields == 3) {
            input.pointer_motion_absolute(wl_fixed_from_double(a), wl_fixed_from_double(b));
        } else if (name == "rel" && fields == 3) {
            input.pointer_motion(wl_fixed_from_double(a), wl_fixed_from_double(b));
        } else if (name == "button" && fields == 3) {
            input.button(uint32_t(a), uint32_t(b));
        } else if (name == "axis" && fields == 3) {
            input.axis(uint32_t(a), wl_fixed_from_double(b));
        } else if (name == "key" && fields == 3) {
            const auto code = keys.constFind(uint32_t(a));
            if (code == keys.constEnd()) {
                reply("error no key for keysym " + std::to_string(uint32_t(a)));
                return;
            }
            input.keyboard_key(*code, uint32_t(b));
        } else {
            reply("error unknown command: " + line);
            return;
        }
        wl_display_roundtrip(display);
        reply("ok");
    });
    return app.exec();
}
