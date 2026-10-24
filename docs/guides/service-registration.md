# Administration service registration evidence

Setup snapshots include `agent_registration` schema 1 for the exact
`MiniRoot01.Service` / `MiniRoot01` registration. The generic `apps` inventory
remains two columns. This record is freshly observed during the snapshot; a saved
journal is historical evidence, not current state.

`expected` means the service component is `svcapp`, package and app are explicitly
not disabled, and the text startup flags are both `true`, matching the signed
agent manifest. `disabled` distinguishes disabled registration from reset startup
flags. NULL, unfamiliar types/values, missing/duplicate rows, wrong components,
unreadable databases and unsupported schemas remain `unknown`. SQLite values are
typed; unfamiliar flag strings are redacted. No SQL writes or acquisition changes
are part of observation. Worker readiness and new-boot readiness are explicitly
`not_observed`; registration alone cannot establish either.

The existing telemetry inspector provides similar operational fields, but cached
telemetry is not a substitute for fresh setup verification. Exact firmware schema
and flag representation still require separately authorized readback on QN90A and
S90D. Unexpected representations require review, not permissive coercion.

Hardware acceptance must bind exact firmware, enrolled trust and signed package;
compare fresh registration with the manifest and inspector, then separately check
an authenticated worker, executable hash, selected runtime, pending maintenance,
retained jobs and SDK rescue. Confirm a new boot ID without manually opening the
agent. Physical Home, standby, app return and playback are separate observations.
Power-loss/interrupted-update acceptance is also separate.

Removing this observation field needs no TV rollback. Preserve private snapshots
outside Git. No registration repair is authorized by an `unknown` or `disabled`
result; in particular an intentionally disabled service must not be re-enabled.
