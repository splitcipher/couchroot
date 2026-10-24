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
