# Documentation

Start with [Choosing a launcher](guides/choosing-a-launcher.md) and the
[setup guide](guides/tv-setup.md). Guides describe supported workflows; lab notes
record model-specific experiments and historical evidence, including failed approaches.
They are not deployment instructions or acceptance of the current source.

## Guides

- [Choosing a launcher](guides/choosing-a-launcher.md)
- [UI design rules](guides/design-guidelines.md)
- [Identity refusal codes](guides/refusal-codes.md)
- [Device compatibility](guides/device-compatibility.md)
- [Porting to a new TV or firmware](guides/porting-to-a-new-tv.md)
- [Edit apps in Minimal Hub](guides/edit-apps.md)
- [Owner-supervised hardware acceptance](guides/hardware-acceptance.md)
- [Native boot-hook installation and recovery](guides/native-installation.md)
- [QN90A basic telemetry: local integration candidate](guides/native-telemetry.md)
- [Couchroot owner operations](guides/owner-operations.md)
- [S90D boot checkpoints and recovery](guides/s90d-boot-recovery.md)
- [SDB connection reuse](guides/sdb-connection-reliability.md)
- [Shared Samsung TV monitoring](guides/telemetry.md)
- [TV setup and reapplication (unreleased)](guides/tv-setup.md)
- [Deploy the Hub UI](guides/ui-deployment.md)
- [UI development](guides/ui-development.md)
- [Couchroot command-line installer](guides/universal-installer.md)

## Project plans and release records

- [Couchroot .NET deprecation plan](project/dotnet-deprecation-plan.md)
- [Source publication review — 2026-10-11](project/publication-review.md)
- [QN90A cleanup tracker](project/qn90a-cleanup-plan.md)
- [Combined release candidate — 2026-10-19](project/release-readiness.md)
- [Licensing](project/licensing.md)
- [Sources & credits](project/credits.md)

Example configuration lives in [examples/](examples/site.json); sanitized device
evidence referenced by the lab notes lives in [lab/inventory/](lab/inventory/).

## Images

- [README screenshots](images/README.md)

## Lab: QN90A

- [QN90A port and rollback](lab/devices/qn90a/README.md)
- [QN90A optional-app cleanup](lab/devices/qn90a/app-cleanup.md)
- [QN90A boot performance: from ~118 s to ~10 s](lab/devices/qn90a/boot-performance.md)
- [QN90A return after AirPlay mirroring](lab/devices/qn90a/casting.md)
- [Why Minimal Hub did not replace Live TV at cold boot](lab/devices/qn90a/direct-boot.md)
- [QN90A Home key routing](lab/devices/qn90a/home.md)
- [QN90A one-time memory cleanup](lab/devices/qn90a/overhead.md)
- [QN90A package-image startup investigation](lab/devices/qn90a/package-images.md)
- [QN90A navigation performance](lab/devices/qn90a/performance.md)
- [QN90A startup audit — 2026-09-22](lab/devices/qn90a/startup-audit.md)
- [QN90A startup-disable comparisons — 2026-09-22](lab/devices/qn90a/startup-disable-tests.md)
- [QN90A startup launch diagnostics — 2026-09-22](lab/devices/qn90a/startup-launch-diagnostics.md)
- [QN90A viewer suppression trial](lab/devices/qn90a/suppression-trial.md)
- [QN90A TV-viewer background startup investigation](lab/devices/qn90a/viewer-background.md)
- [QN90A web startup profiling — 2026-09-22](lab/devices/qn90a/web-startup.md)

## Lab: S90D

- [Couchroot integration on Samsung S90D](lab/devices/s90d/README.md)
- [S90D optional-app cleanup](lab/devices/s90d/app-cleanup.md)
- [S90D boot-to-dashboard inventory design](lab/devices/s90d/boot-inventory.md)
- [S90D native Hub feasibility — 2026-10-12](lab/devices/s90d/native-boot-assessment.md)
- [Samsung S90D memory trimming](lab/devices/s90d/overhead.md)
- [Samsung S90D on-demand root after reboot](lab/devices/s90d/persistence.md)
- [S90D boot-splash acknowledgement investigation](lab/devices/s90d/splash-acknowledgement.md)
- [S90D telemetry to TrueNAS Netdata](lab/devices/s90d/telemetry.md)
- [Alternative S90D screensaver route (web app)](lab/devices/s90d/web-app-screensaver.md)

## Lab: platform research

- [Verified temporary root chain](lab/research/exploit-chain.md)
- [HDMI shortcuts investigation](lab/research/hdmi-shortcuts.md)
- [Minimal Hub hardware validation — 2026-09-22](lab/research/hub-hardware-validation-20260922.md)
- [Samsung launch spinner — native suppression in 0.3.8](lab/research/launch-spinner.md)
- [Native startup and restart](lab/research/native-autostart.md)
- [Native collector supervision](lab/research/native-service-research.md)
- [Native Netdata feasibility](lab/research/netdata-native.md)
- [Tizen 6 startup research: ranked points of interest](lab/research/tizen6-survey.md)

## Implementation references

- [Native WebView host and recovery](../native/webview/README.md)
- [Retired pure-native experiment](../research/archive/native-hub/README.md)
- [Root agent and recovery](lab/autonomous-root/README.md)

The offline `python3 scripts/check-docs.py` check validates repository-relative
Markdown/HTML links and anchors and requires every document under `docs/` in this
index. Site-root web routes and external URLs are outside its scope. The two
generated saver scripts are checked by the separate saver build/reproducibility job.

## Lab: autonomous root

- [Persistent worker capabilities](lab/autonomous-root/CAPABILITIES.md)
- [Autonomous TV administration prototype](lab/autonomous-root/README.md)
- [Agent .NET dependency inventory](lab/autonomous-root/native-worker/DOTNET-INVENTORY.md)
- [Native agent parity and .NET retirement plan](lab/autonomous-root/native-worker/MIGRATION.md)
- [Production files and retained job compatibility](lab/autonomous-root/native-worker/PARITY.md)

- [Native worker upgrades and recovery](guides/native-worker-upgrades.md)
