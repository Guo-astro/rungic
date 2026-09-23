# Firefox mobile configuration

Runtime JS/CSS/configuration used by the Plasma Firefox integration, based on
mobile-config-firefox 5.4.1. This is application configuration, not a browser
user profile: no cookies, passwords, history or user extensions are included.

Source project: https://gitlab.postmarketos.org/postmarketOS/mobile-config-firefox

The original per-file copyright and license headers are preserved. The local
`UserAgentManager.sys.mjs` uses Android 16 / Mobile as its default UA while
retaining site-specific compatibility rules. See the historical codec/browser
integration report in `docs/research/35-hardware-codec-integration.md`.

The `usr/` hierarchy is installed into the Linux rootfs, alongside the Firefox
launcher, `plasma/firefox-policies.json`, and `plasma/firefox-codec-prefs.js`.
It is independent of the retired Phosh desktop. The tree was moved unchanged
from local working materials after the remote-development audit found that the
first repository import omitted it.
