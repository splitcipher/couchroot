# Optional installed players

An independently installed TizenTube Cobalt app can use Hub's existing **Edit apps
→ Add apps** flow. Select it, retain stock YouTube, and reorder it as desired.
No dedicated launcher or preference migration is needed. If it is absent, refresh
discovery and inspect the installation separately; Hub does not install it.
A discovery error must not erase saved favorites. Remove only the added favorite
to undo this Hub change. Samsung Home remains the input and recovery route.

The offline workbench's **Installed player · simulation** scenario uses original
text artwork and the exact application identity. It proves UI behavior only.

| Candidate | Pinned source/release | Identity / dependency |
| --- | --- | --- |
| TizenTube Cobalt | [v2.1.1](https://github.com/reisxd/TizenTube/tree/893b663d35efa558d8bdf9f54f0c4f9a31ab6a07) | Package `xvvl3S1TT1`, app `xvvl3S1TT1.TizenTubeStandalone`, service `xvvl3S1TT1.StandaloneService` |
| tizen-youtube comparison arm | [v1.5.1](https://github.com/SushyDev/tizen-youtube/tree/02c4d8b4bacfa6f0f0efb518fbb588d6fcd60e0e) | Inspect the chosen artifact's identity, service, signing and content before any installation decision |

TizenTube's published Cobalt floor is Tizen 6, not its manifest's web-runtime
minimum. Meeting that floor does not establish QN90A or S90D compatibility. The
reviewed v2.1.1 artifact digest was
`d5ebcf5b61e907912d5200b033f0d366717cb952c9f543a6332d36bef771b3b5`;
this is historical byte evidence, not signature trust or installation approval.
Its service source binds a proxy on `0.0.0.0:8101`, uses copied Samsung Cobalt
content and a generated CA/key, and fetches an unversioned userscript. A pinned
WGT therefore does not pin subsequent injected code. LAN reachability is untested.
The alternate DNS build adds a separate network dependency and is not a default.

The other player documents a move away from proxy/MITM design in v1.3.1 and has
bundled mod/build boundaries. Its v1.5.1 release body supplies no improvement claim.
Treat README performance claims as upstream assertions and use equal measurements.
Neither player is certified here; no Homebrew installation is a prerequisite.

## Separate installation and acceptance decision

Before installation: review immutable artifact digest, package/app/version,
manifest privileges, author/signature continuity, target trust and compatibility,
copied-content ownership, service listeners and recovery. Retain the prior signed
package. Record Developer Mode Host PC IP and preserve the enrolled TV-local
acquisition and independent SDK rescue arrangements. Do not follow a generic guide
that changes Host IP or DNS without reviewing those dependencies. Use existing
setup/signing/journal machinery if external-package admission is later designed.
There is no downloader, signer, catalog or installer in this integration.

For each candidate/version on each exact firmware, use the same media/network and
stock-player baseline. Choose latency and resource budgets from the baseline
before trials; record actual observed format, not the requested quality label.

| Gate | Evidence to record (all currently untested here) |
| --- | --- |
| Discovery and repeated launch | Actual visibility, exact ID, callback versus foreground, failures and time-to-video |
| Cold launch and new boot | Service flags/readiness, proxy/listener reachability, new boot ID, no manual service rescue |
| Media | 1080p and supported 4K/HDR/60 fps, audio sync, seek/resume, account flow, defined endurance of at least 60 minutes |
| Remote and phone | Physical Back/Home, casting from intended phone, standby/wake and return to previous app |
| Isolation and recovery | Other apps, SDK rescue, Host IP, resource baseline and signed rollback |

Re-run relevant acceptance after package, remote script or upstream playback
changes. Installation, callback success and mocked behavior do not prove playback.
Rollback preserves stock YouTube, Samsung Home, prior signed app and author trust;
verify registration, ports and Host IP again. Shared copied content/CA/key may
survive uninstall: remove only separately identified owned files, never shared
Samsung files. No automatic shared-content cleanup is provided.

Both projects have GPL boundaries (TizenTube's nested service also declares ISC).
Linking/launching is not a code transplant. No upstream scripts, artwork, Samsung
binaries, credentials or signing material are included in Couchroot.
