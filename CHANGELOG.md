# Changelog

Notable changes to Couchroot, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
There are no published release entries here. Dates below identify source-history
milestones, not releases or blanket hardware acceptance. The former `dev0` and
`dev1` drafts are consolidated into one development section.

## [Unreleased]

### Added

- Profile-backed device registry, read-only TV survey and field-specific
  identity refusal codes for onboarding and untested-firmware feedback
  (2026-10-22). The registry continues to accept only the reviewed QN90A and
  S90D profiles; survey matches do not add model or firmware support.
- Redacted issue-ready TV reports, read-only TV doctor checks, local device
  configuration initialization and certificate pin generation (2026-10-22).
- Portable firmware profiles, private site configuration, independently enrolled
  signing trust, and a shared installation/recovery journal (2026-10-11).
- Experimental QN90A native and WebView launchers, preference import, Home/source
  handling, startup diagnostics and first-boot recovery (2026-10-12).
- Authenticated root-agent file transfers, retained jobs, app execution and a
  signed native launcher used by the managed worker (2026-10-13).
- Journaled native-worker transitions and SDK rescue alongside the managed
  fallback and small entry bridge (2026-10-14 through 2026-10-19).
- Model-aware package inventory shared by packaging, signing, setup and WebView,
  with unsigned reproducibility checks for both TVs (2026-10-19).

### Changed

- Make the Home Assistant MQTT bridge explicitly opt-in. Missing `enabled` and
  optional feature flags now default off, and unconfigured or disabled leases are
  not retried until the worker restarts (2026-10-25).
- Use launcher-only recommendations on a device's first setup, leaving cleanup
  and telemetry opt-in; only a completed full-setup run (`scope: setup`) enables
  the previous defaults. UI, launcher-only, recovery and trial runs do not
  qualify (2026-10-22).
- Interactive `doctor --tv` shows this computer's routed IPv4 when available;
  survey and shared report output continue to omit all IP addresses. Unknown
  devices can now receive an unverified skeleton without a nearest-profile diff
  (2026-10-22).
- Tidy the repository root (2026-10-22). Command-line entry points move to
  `bin/` (`bin/couchroot-install`, `bin/deploy-ui`, `bin/tv-setup`); examples and
  sanitized device evidence move under `docs/`; contributing and security
  guidance move to `.github/`; licensing and credits move to `docs/project/`; the
  QN90A Home-route and app-cleanup helpers move from `setup/` to `native/`.
  Component revisions and managed build output are unchanged. Resume or roll back
  runs started before this change from their original checkout.
- Consolidate development names under Couchroot and require Node.js 22 or newer
  for the workbench. The installed TV app remains Minimal Hub; identifiers,
  saved preferences and on-TV paths are unchanged.
- Add direct shortcut rearrangement, removal undo, optional hold-OK editing,
  remembered selection and remote-operated launch recovery (published in the
  2026-10-11 source snapshot).
- Buffer root-agent protocol input and use authenticated binary transfer chunks
  with bounded, pinned HTTPS reuse (2026-10-13).
- Narrow QN90A home use to basic telemetry with the existing settings adapter;
  retire continuous QN90A inspection while retaining S90D inspection and history.
  Separate SDK-free checks from managed builds (2026-10-19).

### Fixed

- Present saved WebView content only after rendering, preserve foreground apps,
  and restore the launcher after standby on Live TV (2026-10-12).
- Load libpthread at WebView startup to avoid the QN90A Chromium initialization
  crash (2026-10-13).
- Preserve interrupted-operation recovery, original-host exit checks on S90D
  restart, and durable journals through local finalization (2026-10-19).
- Preserve timeout errors on macOS while still killing helpers after a supervised
  leader exits; bound managed EXEC pipe draining and background work (2026-10-19).
- Clear stale move-mode tiles, ignore stale telemetry-save callbacks and preserve
  valid favorites when saved entries are malformed (2026-10-19).

### Security

- Keep device credentials, signing containers, backups and raw evidence outside
  Git; bind journals and rollback to the enrolled target and trust (2026-10-11).
- Preserve digest checks, conditional replacement, allowlisted paths and
  no-automatic-replay behavior for privileged transfers (2026-10-13).
- Use architecture-correct no-follow flags for managed file access, private
  launcher logs, and bounded unauthenticated peers/lines (2026-10-19).

## Validation and versioning

Historical measurements and their limits remain in the [documentation index](docs/README.md),
[WebView record](native/webview/README.md) and [agent capabilities](docs/lab/autonomous-root/CAPABILITIES.md).
See [release readiness](docs/project/release-readiness.md) for current acceptance gates.
Old device results do not qualify every later source revision.

The milestone dates above come from Git: initial publication `e19f623` (2026-10-11),
native/WebView work `63ae846`, `7bc5278` and `c3b47a2` (2026-10-12), startup and
transfer fixes `ec13079`, `44b711f` and `54f2182` (2026-10-13), native parity
`5b60f71` (2026-10-14), and the release/Phase 1/manifest changes through `59de764`
(2026-10-19). This rewrite does not create tags or claim a release.

CLI versions, TV package versions and journal schemas are separate. Package
versions must increase for in-place installation; recover unfinished journals
with their original checkout. Journal migration and new firmware support require
explicit review.
