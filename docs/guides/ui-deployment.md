# Deploy the Hub UI

Use `bin/deploy-ui` to update **only Minimal Hub** on an already configured S90D or
QN90A. It reuses the setup engine's model/identity checks, signing trust, forward
package version, backup, content readback and recovery journal. Use
[`tv-setup`](tv-setup.md) for first-time setup and other device components.

## Normal update

```sh
bin/deploy-ui plan --device qn90a
bin/deploy-ui apply --device qn90a --launch --yes
bin/deploy-ui verify --device qn90a
```

Substitute `s90d` for the other model. Select one TV at a time. `plan` and `verify`
inspect the TV; they are not offline commands. `apply` runs `npm test`, prepares
and signs from current source, prints one summary, then updates in place. Omit
`--yes` for an interactive confirmation. Without an interactive terminal,
explicit `--yes` is required.

`--launch` closes/reopens Hub after the update and checks its foreground app ID.
It interrupts the current screen. Omit it to let the UI load at its next normal
start. No reboot, Home routing, native helper restart, app cleanup, or NAS changes
are requested by this workflow.

Saved favorites and app settings remain in the installed app's data directory;
there is no uninstall. Full-setup choices remain unchanged, including when none
were saved before. The shared ownership ledger records the new package hashes.
Saved component selections, exclusions and old artifact overrides are ignored:
UI deployment always builds the current Hub source for the selected model.

## Prerequisites

- Install JavaScript/browser dependencies with `npm ci` and
  `npx playwright install chromium`.
- Use Python 3.12+ and the host dependencies from the [setup guide](tv-setup.md).
- Configure private `site.json` and enrolled signing trust as described there.
  Use `--site /path/to/site.json`, `TV_SETUP_SITE`, or the standard
  `~/.config/samsung-tv-hub/site.json` location.
- Use the existing toolkit and Tizen signer (`TIZEN` can select its executable).
  No credentials or target addresses belong in the repository.

To inspect command selection without tests, signing or device contact:

```sh
bin/deploy-ui apply --device qn90a --launch --dry-run
```

`--dry-run` prints the intended workflow; it does not validate prerequisites or
prove that a deployment would succeed. `--json` supports machine-readable setup
summaries; test output goes to stderr. Mutating JSON calls require `--yes`.

During a separately authorized temporary SDK-host maintenance window, Samsung's
HTTP `developerIP` field can still report the prior address. Set
`TV_SETUP_LIVE_SDK_HOST=1` for the deployment commands to require exact live
`vconftool` readback through a connected SDK session instead. This does not change
the setting, enable Developer Mode or relax model, physical identity, firmware,
hash or signing checks. Missing, mismatched, failed or incomplete SDK readback
stops the operation. Arrange and journal the host transition and restoration
separately; restore the original value on completion or abort. Omit the variable
outside that window. The default HTTP admission check remains unchanged.

## Recovery

The summary gives a run ID. Logs and signed packages stay under
`TV_SETUP_STATE` (default: the toolkit's `setup/` directory). UI and full setup
share locks, pending-run checks and the ownership ledger.

```sh
bin/deploy-ui resume --device qn90a --run RUN_ID --yes
bin/deploy-ui rollback --device qn90a --run RUN_ID --yes
```

These commands accept only UI deployment journals. Use `tv-setup` for a full-setup
run. Keep the original source checkout and site/trust configuration for recovery;
source or destination drift blocks it. Recovery does not rerun browser tests.

An uncertain installation is not retried automatically. Inspect its private log
and confirm the installer is idle before explicitly using
`resume --retry-unchanged`. An uncertain foreground launch also requires inspection;
the command does not repeat the launch or reboot the TV. In that case the command
returns an error, while the verified installation remains complete in its journal
with an uncertain activation note. Use `verify` and inspect the TV before asking
for another launch; there is no incomplete package installation to resume.

For an automatic package rollback, set `TV_SETUP_RECOVERY_DIR` to a private
directory containing the matching, previously signed WGT before applying. The
engine checks it against the installed content and enrolled signing identity.
An installed-file backup alone is **not** an installable rollback package. If a
matching WGT is absent, the summary reports that limitation; rollback can require
manual package recovery and returns exit code 3.

## Verification limits

Automated checks validate the selected model and installed package content.
On the TV, confirm the new screen, arrows/OK/Back, saved favorites, an app launch,
and the Samsung Home fallback. Browser fixtures and installer completion do not
establish visual, playback, Home-key or reboot behavior.

Direct use of `scripts/sign.py` has the same site/trust requirement: `--site` is
optional only because `TV_SETUP_SITE` or the standard site.json location can
supply it. A named SDK signing profile alone is insufficient.
