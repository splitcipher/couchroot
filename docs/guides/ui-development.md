# UI development

Minimal Hub has one UI source: `web/`. The browser workbench serves those files
with simulated Tizen APIs. The unsigned TV package includes only the explicit
model-aware manifest in `tvsetup/planner.py::hub_sources`; it contains no preview tooling.

## Start

Requires Node 20+; packaging also requires Python 3.

```sh
npm ci
npx playwright install chromium
npm run dev
```

Open <http://127.0.0.1:8766>. The server binds only to loopback. Use
`PORT=8767 npm run dev` if the default port is occupied. Stop with Ctrl+C.
Saving files under `web/` or `preview/` reloads the embedded app; refresh the
outer page after changing the workbench itself.

The embedded app has a 1920×1080 viewport scaled to fit the window. Choose
**Open full viewport** to inspect the app at your browser's actual viewport size.
Click inside it, then use arrows to navigate, Enter for OK, and Escape for Back.

## Scenarios

The selector covers default Home, a full catalog, the compact layout with the
clock, empty Home, an unavailable app, Edit apps, move-or-remove, moving in the
Home grid, undo removal, opening an app, hold-OK settings, the app picker,
settings, reset confirmation, monitoring preferences,
launch/discovery failures, unreadable saved shortcuts, and missing artwork.

Scenario definitions live in `preview/scenarios.js`. `preview/fixtures.js`
provides catalogs and simulated app discovery, launch, audio API, and private
filesystem access. UI tests use the same mock installer with a numbered catalog
for stable assertions. Sound starts off in the workbench; enabling it can play
the app's normal local Web Audio tones.

- Edits to favorites/settings survive reloads within a scenario.
- Switching scenarios or selecting **Reset scenario** reseeds preview preferences.
- The scenarios share one preview origin; use separate browser contexts for
  independent sessions. Do not edit two scenarios concurrently in same-origin tabs.
- Monitoring preferences are stored in browser storage. No receiver is contacted.
- Simulated app launches appear in the workbench footer; no real app opens.
  Successful mocks simulate a hide/return cycle. The Opening scenario delays
  the callback for five seconds so launch progress can be inspected.

Direct links are useful for browser automation:

```text
/hub?scenario=many
/hub?scenario=settings&reset=1
/hub?scenario=monitoring&reset=1&static=1
```

`reset=1` reseeds once and is removed from the URL. `static=1` disables reload
polling for captures. `/web/index.html` serves the original, uninjected app for
checking its basic desktop fallback.

The injected preview permits same-origin connections for reload polling. The
shipped HTML retains its offline content policy (`connect-src 'none'`).

## Validate and package

```sh
npm run check:web-es5
npm run test:ui
npm test
npm run screenshots
npm run screenshots -- --small  # 960×540 captures in test-results/screenshots-960/
npm run package
```

Screenshot capture starts its own temporary server and writes 1920×1080 PNGs
for every scenario to `test-results/screenshots/`. It uses fresh browser contexts,
a fixed clock and reduced motion. Inspect the images; these are not golden-image
tests. `npm run check:web-es5` parses every raw `web/*.js` file as an ES5 script and
runs in the web/offline CI job. It checks syntax only, not runtime APIs or CSS.
The older-browser checks exercise selected fallbacks in modern Chromium,
not a Tizen emulator.

Packaging writes `dist/MinimalHub-<device>-unsigned.wgt` and `dist/manifest-<device>.json`.
For an authorized update to an already configured TV, follow
[UI deployment](ui-deployment.md). It signs current source through the setup
engine; the unsigned WGT is a local build check, not its deployment input.
Use [the setup guide](tv-setup.md) for first-time installation.

## Selection and launch recovery

Settings → Start on defaults to **Last selected**. The last highlighted Home app
is saved as `minimal-hub.selection.v1`; `minimal-hub.start.v1` stores `last` or
`first`. First favorite affects a fresh Hub start, while returning from an app
still restores the in-session selection. Missing shortcuts fall back to the first
favorite; an empty Home continues to offer Add apps. Neither preference reorders
shortcuts, and Reset shortcuts preserves the startup preference.

Selection writes wait 250 ms after navigation settles, with a flush on visibility
change or pagehide. Abrupt power loss before a write can retain the previous
selection. A failed write keeps navigation usable and reports a Home status
message when no other message is active.

Failed launches and the ten-second timeout open a remote-operated dialog with
Back to apps, Retry and Samsung Home. Back restores the failed shortcut. If
Samsung Home itself fails, its redundant fallback action is omitted. Leaving
Home for a utility page cancels pending feedback; stale callbacks cannot open a
dialog over that page. Accepted launches keep an on-tile progress badge and
duplicate-launch guard until Hub hides. If Hub stays visible for ten seconds,
the recovery dialog distinguishes an accepted request from no response. Back
dismisses feedback; it cannot revoke a request already sent to the TV. Preview
API success still does not prove a real TV app has reached the foreground.
Samsung Home is an exception to the visibility wait: on QN90A it opens as a
partial overlay while Hub remains visible. Its accepted callback clears launch
feedback; errors and a missing callback still open recovery.

Home, editor and settings scroll cues indicate content above/below their viewport.
Clipped items keep normal opacity, and trailing padding does not trigger a cue.
Local browser checks cover these behaviors; selection across real standby/restart,
launch handoff, remote feel and Chromium 76 presentation remain on-TV checks for
both models before claiming hardware verification.

## Grid editing and return work

Edit apps → choose a shortcut → Move now uses the Home grid. All four arrows
move the selected tile to the neighboring position, respecting the three- or
four-column layout and a shorter final row. Down at the bottom reaches Cancel;
Up returns to the moving tile. OK or Save position commits, while Back/Cancel
discards the draft. A failed save keeps the draft available for retry.

Remove from Home offers **Undo remove** in the editor toolbar and Home footer.
It restores the latest removed shortcut at its original index while preserving
later additions/reordering. It is session-only, has no timer, and clears on
successful undo, another successful removal, or Reset shortcuts. It never
uninstalls an app. Failed writes retain the saved list and undo entry.

Settings → Hold OK to edit is off by default (`minimal-hub.hold.v1`, `on`/`off`).
Enabled taps launch on release; a 650 ms hold opens Move/Remove from Home.
Repeated keydowns, Back/arrows, blur and visibility changes cannot accidentally
complete a pending hold. Edit apps remains available. Verify keydown, repeat and
keyup behavior with each physical remote before relying on this shortcut.

Home retains its tile nodes when order, layout, artwork and availability are
unchanged. App lookup uses an ID map, and return discovery starts after 150 ms
instead of during the first restored render. Browser tests check node reuse and
late-data/focus behavior. This does not establish native standby or screensaver
return latency; see [the performance record](../lab/devices/qn90a/performance.md).

The [2026-09-22 hardware record](../lab/research/hub-hardware-validation-20260922.md) tracks the
UI deployment and native-key checks on both TVs, including remaining physical
remote, playback and startup acceptance.

HDMI is not exposed until source handoff is verified on each model. See the
[HDMI investigation](../lab/research/hdmi-shortcuts.md) for evidence and the remaining checks.

## Source boundaries

```text
web/         Shipped screens, state, presentation and TV adapters
preview/     Local workbench, scenarios, shared mocks and screenshot tooling
tests/       Unit and browser behavior checks
bin/         Command-line entry points (couchroot-install, deploy-ui, tv-setup)
tvsetup/     Shared setup engine
agent/       Root agent service and native worker
native/      Native on-TV components and the experimental WebView launcher
telemetry/   Monitoring service and collectors
tools/       Guarded per-model device operation scripts
scripts/     Packaging, signing and offline checks
research/    Hardware research and retired code
docs/        Guides, lab notes, examples and sanitized device evidence
```

Keep rendering and remote navigation in `web/hub.js`; put device API calls in
the existing adapters. Preserve the separate model and presentation modules.
Add modules when a responsibility needs separation, updating script order,
package contents and tests together. Build and rollback scripts reference
research paths directly; move a path and its references together, and run
`tests/repository_paths_test.py` to catch broken repository-root expressions.

## Startup work

Saved shortcuts, handlers and navigation initialize before the initial catalog
request. Discovery is scheduled after document focus; explicitly opening the
editor can request it immediately and cancels the pending startup request.
Monitoring waits for focus and a further 1.5 seconds before reading preferences.
Tizen callback-based APIs can still block while loading their native extensions.
Hidden startup waits for a visible, focused return; existing bounded monitoring
retries and explicit discovery recovery remain available.

`HubBootTrace` hooks are inert in a normal package. The research recorder adds
bounded navigation/paint timing when explicitly included in a diagnostic build;
it is not a production asset. See the [QN90A measurements and limitations](../lab/devices/qn90a/web-startup.md).

The model-aware package manifest is `tvsetup.planner.hub_sources`. `python3
scripts/package.py --device s90d` (the default) or `--device qn90a` builds the
same unsigned runtime inputs used by the setup builder; QN90A adds its idle
script. The native WebView bundle uses the unconfigured variant to preserve its
existing adapter behavior.

Standalone `scripts/sign.py` uses `SAMSUNG_TV_TOOLKIT` and the enrolled signing
trust from `--site` / `TV_SETUP_SITE`. It verifies both package signatures before
reporting success. `--boot-trace` increments the patch version read from the
widget manifest. Signing is local; it does not install or contact a TV.
