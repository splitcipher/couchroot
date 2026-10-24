# Disconnected review experiments

These original 0BSD models are executable hypotheses, outside shipping paths.
They have no device transport, installer, signing or profile admission. Production
must not import them. Synthetic IDs, schemas, values and bytes are intentionally
incompatible with actual firmware artifacts. Run their tests via the normal
Python/Node offline suites. A passing model is not a hardware contract.

## Registration repair

`registration_repair.py` exercises real SQLite CAS and a private scratch intent
using the shared atomic JSON helper. It has its own deliberately synthetic table,
not the TV package database. Forward/inverse comparisons bind version, author,
component, disabled state and both startup flags; unrelated rows/columns survive.
Intent survives interruption before/after commit; a lost reply is inspected before
replay. Another pending run or any native transition blocks it; its own pending
run can reconcile. It never edits a disabled service or restores an entire DB.

Live integration is deferred until exact per-firmware schema and privilege evidence,
package/signature binding, intentional-disable policy and Engine action admission
are reviewed. Use the existing setup lock, Engine journal and native transition
interlocks for a future action; this scratch journal is not a parallel installer.
Need owner-authorized repair and inverse on both firmwares, update and new boot
readback, worker authentication, retained jobs and SDK rescue. An inverse must
refuse drift. Keep full backups as evidence, not routine DB restoration.

## Delayed startup cancellation

`startup.py` makes source, owner, selection generation and boot generation separate
from foreground app ID. It admits a known default viewer, cancels permanently on
changed/unknown evidence, rechecks before submitting, fences old callbacks and
claims once per boot across service restarts. It provides no Samsung adapter:
`viewer`, `tv`, `hdmi1`, owner and generation are synthetic contract values.

Production QN90A relay Tick and optional agent policy already cancel on other apps,
power and deadlines; the WebView host already checks source/owner during handoff.
The compiled production relay tests remain useful for these real predicates but
cannot establish input choice from the same `org.tizen.tv-viewer` ID. No blanket
viewer suppression, new source setter, S90D boot route or replacement launcher is
introduced. The firmware source/owner generation adapter and live 3B fix are gated
on authoritative semantics. Capture normal/background boots with a powered source,
select input/app early/mid/late, observe the whole launch deadline, and repeat
standby and explicit Home. Require zero delayed takeover after selection.
Rollback would disable the optional agent boot launch or restore the exact prior
signed helper/package with the existing Home route; retain its prior image first.

## Saver backend ownership

`saver.py` builds an explicitly experimental synthetic plan and exercises the real
Engine intent/backup/apply/reconcile/rollback journal with a fake mount driver.
It models exactly one stock/native/web backend, hash-bound 209-byte cache-prefix
replacement with unchanged suffix, a synthetic XML selector and a signed-app
presence prerequisite. It preserves splash/telemetry state. Wrong namespace,
missing app, malformed selector and foreign/dual overlays refuse admission.
Partial remount and failed unmount retain recovery state; rollback only accepts
exact owned intermediate states. No real profile or helper hashes are admitted.

For the future web backend the explicit proposed policy is: diagnostic failure
suppresses custom rendering. This does not change the current native helper,
which still attempts Apply after a diagnostic exception. Keep the existing native
backend as default. Integrate any eventual renderer into the combined helper
built by `native/s90d-splash/build-helper.py`, retaining Splash.Start/Finish and
original diagnostics; do not install a second Boot.dll, enabled marker or AT-HUB
hook. Use the existing S90D checkpoint and shared Engine recovery machinery.

5B live helper/package work remains blocked on exact enrolled-region selector,
cache/table and namespace evidence, underlying stock hashes captured without
unmounting unknown overlays, signed app identity/availability, and a reviewed
backend policy. Brazilian cache bytes and layout similarity are not admission.
The existing QN90A web renderer is a source candidate, not an S90D idle contract.
Before support, test idle entry from Hub/streaming/powered input, key dismissal to
the correct prior owner, audio, standby/new boot, missing app/signature/update,
and measured startup/RSS/CPU versus the native baseline. A black animation deadline
must be tested separately from application exit and panel power; it is not an OLED
panel-care guarantee. Roll back the owned selector before removing the saver app,
restore prior helper/backend and verify restoration on a new boot. Retain SDK
rescue and offline checkpoints. No vendor bytes or character artwork are included.

## Display and source evidence

`capabilities.py` projects supplied introspection XML into firmware/interface/method
and exact input/output signature strings. It does not validate signature semantics,
units, range, source applicability or restore behavior. Every control admission
is false. No D-Bus call, setter, panel-care or service-menu operation exists.
A future write requires explicit per-control admission and read/compare/write/read
with exact prior source/value recovery, plus physical image/source-mode acceptance.
Do not copy an upstream predicate that gates only some controls.

The source parser covers bounded public-API-shaped connector records, disconnected
and multiple sources, and refuses unknown/duplicate entries. Native source IDs are
a different contract. Empty inventories do not prove HDMI unsupported; connected
connectors do not prove video or native full-screen handoff. HDMI shortcut work
remains deferred until a powered source establishes connector identity, focus,
audio/HDR/game-mode, Home and standby recovery. Retain Samsung Home for inputs.
Rollback would restore the prior source and remove only owned shortcut preferences.
Removing either offline report has no TV rollback cost. This original code copies
no Vetro parser or settings data.
