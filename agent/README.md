# Couchroot administration agent

## Support

The agent provides enrolled, authenticated administration for the pinned QN90A
and S90D firmware profiles. It reacquires a temporary namespace root context;
it does not patch firmware or bypass SMACK. Native is the only packaged worker and
acquisition path. The small `agent/native-acquisition/ServiceEntry.cs` .NET bridge still invokes the
native acquisition library; it contains no worker, EXEC or file-transfer engine.
The signed web Hub, native worker and telemetry settings adapter are unchanged.
S90D agent 0.7.54 passed native handoff and unattended reboot acceptance on
2026-10-21. The latest QN90A upgrade remains pending; see the
[current acceptance record](../docs/project/release-readiness.md).

The package deliberately requires an existing, settled native selection and its
committed activation/state records. It refuses managed selections, missing
selection and unfinished legacy migrations. Keep the previous signed package,
checkout and immutable journals to finish those recoveries before upgrading.
It does not invent a new selection or migrate retained jobs during installation.

Native startup retains its fenced launch, job recovery and readiness checks.
An interrupted bootstrap is sealed and cleaned by a fresh bounded native
acquisition operation; only its exact success and unchanged durable receipt clear
the pending marker. A lost reply leaves the marker for convergent cleanup. Public
requests stay closed until the selected native worker is independently ready and
the bootstrap has retired. No managed fallback is attempted.

The old managed worker and archive-root assemblies, embedded launcher wrapper,
C# protocol/file/EXEC/job/helper implementations and their managed harness are
removed. Historical migration/rollback validators remain in source for recovery tests but
are excluded from new packages; records remain readable;
the running agent no longer exposes managed migration/return methods. Existing
legacy API routes reject unavailable operations. See [release gates](../docs/project/release-readiness.md).

## MQTT integration

The outbound [Home Assistant bridge](../docs/guides/mqtt.md) is implemented through
the existing native worker and coordinator readiness lease. It requires a private
root-owned configuration; without one it remains dormant. Feature 1 provides
discovery and strict command refusal, with hardware controls/state adapters still
unavailable. It has not been deployed or hardware-qualified.

## Enrolment

Use `python3 -m tvsetup.autonomous_root --help` and the shared setup engine to
prepare per-device artifacts with the private site configuration and enrolled
signing trust. Preparation is local; it does not install or change SDK admission.
Keep the generated keys, pinned certificates and client configuration private.
Install disabled only during an owner-approved, journaled acceptance session.
Verify mutual TLS, rejection of foreign certificates and independent SDK recovery
before enabling loopback acquisition. Certificates expire; renew through explicit
enrolment, never by disabling verification.

After device acceptance, query the enrolled agent with:

```sh
python3 agent/client.py --config PRIVATE_RUN/client.json status
```

## Recovery

Keep the original checkout, immutable journal, signed recovery packages and exact
former Developer Mode Host PC IP available. Use the shared engine's pending-run
checks and device lock; restore the journal's captured state rather than installing
a newer tree over an unfinished run. See [setup recovery](../docs/guides/tv-setup.md).

If the authenticated endpoint works, `client.py --config PRIVATE_RUN/client.json
disable` stops reacquisition. It does not restore SDK admission or undo previous
administrative commands. If loopback admission prevents computer access and the
agent cannot acquire root, use Samsung Apps → Developer Mode to restore the
computer's former Host PC IP and restart. Verify ordinary SDK access before
canceling a timed rescue. Do not assume a disabled or restarted service has restored
settings. The [maintenance procedure](../docs/lab/autonomous-root/README.md#service-restart-during-maintenance)
and the full [required device acceptance, in order](../docs/lab/autonomous-root/README.md#required-device-acceptance-in-order)
require an independent rescue and, on S90D, confirmation that the original host
has exited before relaunching.

## Trust boundary

The HTTPS API requires a pinned client certificate; the client verifies and pins
the server. The loopback worker uses authenticated frames and bounded requests.
An enrolled administrator can execute privileged commands, so possession of the
private credentials is administrative access. Request IDs and durable intent
journals prevent automatic replay; a lost reply remains uncertain until reconciled.
Namespace root is still subject to firmware and SMACK policy. Never expose the
endpoint as an unauthenticated LAN service or treat successful signing as proof of
boot entitlement, recovery or hardware acceptance.

See the [protocol](PROTOCOL.md), [source provenance](UPSTREAM.json), and
[historical capabilities](../docs/lab/autonomous-root/CAPABILITIES.md).
Vendor MIT and payload licenses remain beside their sources.

Native worker changes use the explicit [upgrade and recovery workflow](../docs/guides/native-worker-upgrades.md). Package installation alone preserves the committed worker.
