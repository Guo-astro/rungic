// SPDX-License-Identifier: GPL-2.0-or-later
// The design system's own translations: the catalog rungic-design (po/), in the language of
// the Plasma session. A context of its own (KI18nContext, KF 6.23), so the controls translate
// whether or not the app loading them has set up KI18n, and never from the app's catalog.
// For the library's controls and gallery only: apps use their own domain.
pragma Singleton
import QtQml
import org.kde.ki18n

KI18nContext {
    translationDomain: "rungic-design"
}
