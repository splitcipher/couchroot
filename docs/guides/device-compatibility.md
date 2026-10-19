# Device compatibility

These targets come from the repository's recorded device inspections, not a
fresh hardware probe.

| Target | Recorded environment | UI implications |
| --- | --- | --- |
| S90D | Firmware 2130.0, Tizen 9, ARMv7 | Preserve the verified launch bridge and explicit Samsung Home fallback. |
| QN90A | Firmware 2301.1, Tizen 6, Chromium 76, ARMv7 | Treat this as the older browser baseline; maintain existing CSS and API fallbacks. |

S89C (`QN77S89CBFXZA`, firmware 2220.4) passed a
[scoped launcher installation and physical Home-button test](../devices/s89c/README.md)
on 2026-10-18. The owner confirmed app navigation and Home return from another
app. Native Home setters and recovery also passed on its Tizen 9.0.0 / ARMv7 /
.NET 6.0.9 environment. Cold reboot and standby checks remain pending. General
setup/deployment commands continue to refuse this model while its full profile
is developed.

Keep shipped JavaScript compatible with the existing older-browser style.
Avoid introducing unsupported syntax or browser APIs without a fallback. The
Node-based workbench and tests may use modern syntax; they do not run on the TV.

The app measures flex-gap support because grid-gap support alone is insufficient.
Keep the `.no-flex-gap` rules and explicit sizing fallbacks. Chromium 76 also lacks
`inset`, `aspect-ratio`, `min()`/`max()` and rounded `outline`; use four offsets,
vw-based heights and `box-shadow` focus rings. Size dialogs in vw/vh, not px. The UI test that
removes `clamp()` declarations checks a specific fallback; it does not emulate
all of Chromium 76.

QN90A can spend seconds rasterizing full-screen gradients when focus invalidates
their paint surface, even with mostly idle aggregate CPU. Preserve the isolated
Home backdrop/footer layers and run the cached-paint browser regression. Validate
performance with native input and raster-thread CPU on the TV; synthetic handler
timing or animation-frame callbacks alone do not measure completed presentation.
See [the performance record](../devices/qn90a/performance.md).

Desktop mocks cover discovery, launching and monitoring preference storage.
They do not reproduce the TV's app inventory, security policy, sound output,
launch spinner, Home-key routing, startup, standby or firmware behavior.
Changes touching those boundaries need a model-specific on-TV check.

The TVs use separate signing profiles and integration procedures. Do not infer
that S90D startup/root helpers work on QN90A. Consult the relevant record:

- [S90D integration](../devices/s90d/README.md)
- [QN90A integration and browser compatibility](../devices/qn90a/README.md)
- [QN90A Home routing](../devices/qn90a/home.md)
- [Owner operations and release procedure](owner-operations.md)
