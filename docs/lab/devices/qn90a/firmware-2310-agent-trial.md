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
