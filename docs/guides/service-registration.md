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

## Verification and recovery

Agent package installation/update and signed forward recovery now require schema-1
`expected` registration evidence in addition to existing file, identity, protection
and preservation checks. Shared signature verification also requires the exact
single service manifest with both startup flags true. A changed manifest policy
requires review; it cannot silently redefine a repair target.

Correct package bytes with reset or unknown flags leave the Engine run partial
(or rollback-partial). Resume observes again and never reinstalls just to fix
registration. Keep the prior signed recovery package and original journal and
checkout. Engine journal schema 2 and its source-revision pin remain unchanged:
older runs must use their original checkout; they are not silently migrated to a
new verifier. Missing registration evidence is unknown, never grandfathered as
successful. Rollback that actually reinstalls an agent must pass the same fresh
check before completing. A no-op return to an already-original package is not a
new installation or a boot-readiness claim.

There is deliberately no repair command. Stop on blocked verification, inspect the
private journal and obtain exact schema/privilege/disable-policy evidence before
proposing a targeted repair. Do not clear pending markers, blindly replay an
installer, restore a whole package DB, or manually open an app to claim boot success.
