---
name: samsung-tv-ops
description: Inspect, deploy, verify, and recover Samsung TV Minimal Hub on the project's S90D and QN90A targets. Use for UI releases or device setup; use samsung-tv-ui for browser design work.
---

# Samsung TV Hub operations

Use the active `samsung-tv-hub` checkout. When loaded through a personal skill
symlink, resolve this skill's directory; the repository is three levels above it.
Choose the narrowest workflow matching the user's request:

- **UI update:** [UI deployment](../../../docs/guides/ui-deployment.md), `bin/deploy-ui`.
- **Setup or other device components:** [setup guide](../../../docs/guides/tv-setup.md),
  `bin/tv-setup`. Read model-specific notes only for the component being changed.
- **Browser-only work:** [UI skill](../samsung-tv-ui/SKILL.md).

## UI release

`bin/deploy-ui plan --device DEVICE` inspects the TV. After review, an authorized
update uses `bin/deploy-ui apply --device DEVICE --yes`; add `--launch` only when
opening Hub now is wanted. It closes/reopens the app and checks foreground without
restarting a native helper. `bin/deploy-ui verify --device DEVICE` checks readback.
Use `--dry-run` to inspect the workflow without contacting a device.

The entry point runs UI tests, signs current source with a forward version, and
uses the shared journal. It preserves full-setup choices and limits changes to
the Hub package. Do not replace it with ad hoc signing/install commands or expand
to a full recommended setup for a UI-only request.

Targets and signing trust come from private site configuration. S90D and QN90A
have different profiles and native integration; never substitute one for the
other. Keep credentials, signed packages, journals and raw evidence outside Git.

## Telemetry

Both TVs use Hub → no-window relay → `MiniTelemetry.Service`. Use `bin/tv-setup`
with `--components hub,telemetry`; read [telemetry operations](../../../docs/guides/telemetry.md).
Keep per-TV runtime/signing and receiver identities. S90D migration retires the
legacy collector marker and drains its lock while preserving splash/saver helper
bytes. Never re-enable the old marker alongside the signed service. Use privileged
inspection for private pairing paths; SDK absence alone can mean an unreadable parent.
Validate cold reboot separately from manual Hub entry: early API failures need the
shared adapter’s bounded startup retries, not a second model-specific boot hook.

## Changes and recovery

Inspect first. Honor existing authorization for the requested device and scope;
do not ask again for the same approved action. If live changes are not yet
authorized, prepare the exact proposal and recovery path before asking. Writing
a script or changing source does not authorize running it against a TV.

Retain the original checkout and run ID for recovery. UI deployment uses the same
locks and pending-run checks as full setup. Resume or roll back incomplete runs
before starting another update; never blindly repeat an uncertain install.
`--retry-unchanged` requires inspecting the log and confirming installer inactivity.

A file backup is not a signed reinstall package. Enroll a matching prior WGT via
`TV_SETUP_RECOVERY_DIR` when automatic package rollback is needed. Report missing
recovery material and manual-recovery exit status accurately. Do not uninstall
the app to force an update or reset preferences to resolve a version problem.

## Ad-hoc live scripts

For one-off live operations, install the toolkit once in the active checkout
(`python3 -m venv .venv && .venv/bin/pip install -e .`) and run scripts with that
interpreter. Import from the installed package —
`from tvsetup.research import Run, Checks, STATE, PRIVATE` — instead of copying a
`common.py`/`live_common.py` helper or inserting a sibling checkout onto
`sys.path`; those path hacks are the main cause of past import failures. `Run`
journals each request's intent and result and refuses replays. Build
preflight/verify checks with `Checks` (collect-and-report, one failure list) rather
than bare `assert`, which aborts on the first mismatch and forces edit-rerun loops.
On the Mac host use `host_stat`/`mtime_iso` rather than `stat -f`/`date -r`;
device-side GNU `stat -c` stays as is. Keep evidence, credentials and journals
outside Git.

Report local tests, installed-content verification, and actual on-TV observations
separately. Never describe a submitted launch or desktop preview as proof of
playback, physical Home routing, standby or reboot behavior.
