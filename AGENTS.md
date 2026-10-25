# Couchroot project guidance

Use the current repository checkout. Keep UI development, UI deployment, and full
device setup distinct; the user's requested scope determines which workflow runs.

| Task | Entry point |
| --- | --- |
| Design or change the UI | [UI skill](.agents/skills/samsung-tv-ui/SKILL.md) |
| Deploy, inspect, or recover a TV | [Operations skill](.agents/skills/samsung-tv-ops/SKILL.md) |
| Local preview and browser checks | [UI development](docs/guides/ui-development.md) |
| Update just the Hub package | [UI deployment](docs/guides/ui-deployment.md), `bin/deploy-ui` |
| Full device setup/recovery | [Setup guide](docs/guides/tv-setup.md), `bin/tv-setup` |

`web/` is the shipped interface; `preview/` serves that same source with simulated
APIs. Keep browser tooling out of signed packages. Preserve remote navigation,
saved preference keys, the Samsung Home fallback, and QN90A's older browser support.

Use the shared setup engine for signing, identity checks, backups and journals.
Device targets and signing trust live in private site configuration. Keep signed
packages, credentials, raw logs and device identities outside Git. Source changes
alone do not authorize device deployment.

Validate changes at the affected boundary: `npm test` for UI/preview,
`python3 -m unittest discover -s tests -p '*_test.py'` for setup/deployment,
and skill validation when editing skills. Report local tests separately from
actual device verification. See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for release work.

For fast local iteration, the same Python tests also run under pytest in parallel,
about 5x faster — `pytest -n auto` is ~21s vs ~107s serial (install the dev extras:
`pip install -e '.[dev]'`; worksteal distribution is preconfigured). Inner loop while
editing a module: `pytest tests/<name>_test.py` (sub-second). Broad check skipping
the one slow suite: `pytest -n auto --ignore=tests/s90d_recovery_test.py` (a few
seconds). These are convenience runners only — the `unittest` command above remains
the authoritative gate, and device/sandbox validation should use the Python tests,
not `npm test` (its UI suite launches a browser).

`tests/s90d_recovery_test.py` is the slow outlier (~110s cumulative): each test runs
the real generated recovery shell against a temp filesystem — ~385 utility
subprocesses per test — which is the fidelity the recovery-safety suite exists for,
not waste. Run it on demand or in CI; keep it out of the rapid inner loop.
