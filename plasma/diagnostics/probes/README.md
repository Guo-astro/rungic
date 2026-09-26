Small probes compiled into rungic-plasma-diagnostics (docs/61). Their sources lived only in
the phone's /opt until 2026-09-26:

- apps-probe: what KSycoca/KApplicationTrader list (launcher entries).
- screen-probe: QScreen geometry, device pixel ratio and refresh rate as Qt sees them.
- rungic-input-probe: a text field for input method acceptance ("输入验收"); logs the length
  and whether Chinese was committed, never the text.
