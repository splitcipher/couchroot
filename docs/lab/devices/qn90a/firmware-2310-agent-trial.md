# QN90A 2310.0 agent recovery qualification

This is an explicit owner-authorized agent/recovery trial for QN85QN90AAFXZA,
21_NIKEM2_QTV, ARMv7, exact firmware `T-NKM2AKUC-2310.0`. It is outside the
ordinary setup registry; its 2301.1 profile, cleanup allowlist and capability
claims remain unchanged. No other model, firmware or full-setup capability is
admitted by this trial.

Read-only inspection on 2026-10-24 found build
`TIZEN-TRUNK2021-NikeM2-HOTFIX-RELEASE_20260721.1`, .NET Core 3.1.3, the same
three pinned host/archive-launcher executable hashes, SDK UID/GID 901 with
SMACK System and the expected inherited capabilities, and the unchanged owner
UID/GID 5001/100. The version file is a regular file on the read-only root
filesystem. Earlier captures contain 2301.1 and an earlier build. The mechanism
behind these differing observations has not been established.

`tvsetup.qn90a_firmware_trial.configured_trial` constructs the explicit transport
contract from source-controlled constants and the existing physical/trust binding.
It additionally pins the complete version-file SHA-256. Runtime, architecture,
host/launcher, disposable signature, original-resource and cleanup checks remain
mandatory. `native_rescue.plan(..., firmware="T-NKM2AKUC-2310.0")` binds the same
exact version-file digest; omission retains the original firmware contract.
This is not a private-site override or automatic fallback after refusal.

Qualification order:

1. Verify identity, SDK admission, exact file/hash/runtime/capability evidence,
   no pending operation, signed recovery packages and retained enrollment.
2. Use the existing bounded temporary-root transport for an identity/read-only
   operation. Require baseline/root receipts, unchanged system originals,
   clean staging and no leftover probe processes before any persistent change.
3. Disable acquisition through the enrolled authenticated API. Preserve disabled
   configuration and credentials; journal only the exact firmware-field change
   using the existing file backup/compare/readback machinery. Keep service
   registration, selection, jobs, Hub data and signed package bytes intact.
4. Restart only the coordinator to read the disabled configuration. Verify the
   retained native SDK recovery helper, arm an independently guarded SDK rescue
   before restoring loopback, then enable the existing worker. Retire the rescue
   only after root identity, exact executable digest, stable lifecycle state,
   a bounded job, preserved data and loopback readback pass.

On failure, keep external SDK access, the disabled configuration, exact backups
and original source checkout. Reconcile uncertain results before another submit.
Restoring the previous 2301.1 enrollment is a safe disabled rollback, not a way
to make a worker run on 2310.0. Old signed packages also retain the old firmware
pin. Do not force a downgrade or change trust to recover. If loopback return
fails, the timed rescue must restore the independently verified external host.

Hardware results are recorded separately after execution. A working manually
restarted worker does not qualify unattended boot, standby, package installation,
full setup, cleanup or Samsung Home behavior. Reboot acceptance requires its own
owner-authorized observation with a new boot ID and independent Hub confirmation.

## Owner-authorized result, 2026-10-24

The bounded temporary-root acquisition passed, including original-resource and
cleanup checks. The shared engine backed up and changed only the disabled agent
configuration's firmware field; existing credential bytes and signed 0.7.54
package content remained unchanged. No package was signed or installed.

The coordinator was stopped once through the guarded root transport. QN90A's
existing auto-restart produced a new authenticated host. The manual restart
script conservatively withheld its own start when process identity became
unreadable during exit; later inspection proved the old host absent and the new
host running the expected executable with the disabled configuration. SDK-only
inspection cannot read that executable link. A transient-service invocation also
required literal script transport to avoid systemd expanding shell variables;
the failed guard-only attempts were inspected and were not blindly replayed.

The retained native recovery helper restored loopback under exact firmware,
version-file, boot, ownership and executable guards, with an independent timed
external-SDK rescue armed. The enrolled service then reacquired the selected
native worker. Its actual running executable was verified as
`c82a7f37497a69a407e0fa5c99b09c454bb3e0dcc31a45a1c2994fcb68532ca5`.
A bounded root job completed successfully; two earlier durable job records,
selection, credential pins, protected Hub assets and inspected routing settings
were unchanged. Service startup registration remained expected. The previous
worker review and retained backup/helper hashes passed. The rescue was retired
unfired, all owned maintenance units were retired, and the same worker remained
ready with no pending native lifecycle operation or setup run.

This qualifies the existing agent's same-boot recovery on this exact 2310.0 TV.
No reboot was submitted during qualification. Unattended worker startup after
reboot, standby, full setup and physical Home/fallback acceptance remain separate
gates. The original 2301.1 registry profile deliberately still refuses 2310.0;
future maintenance must use the explicit trial contract and retained recovery
records rather than changing private site safety fields.

Offline validation: 614 Python tests passed, 237 platform/opt-in tests skipped;
the separate Linux service-restart suite passed all 11 tests. This includes
firmware/profile drift refusal, immutable baseline guard checks, rescue binding
and lost-reply/no-replay coverage, and real delayed-exit process tests. Mocked
failure and recovery coverage is not a physical interruption or reboot test.
