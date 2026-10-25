"""Shared plumbing for ad-hoc live field and validation scripts.

Background: one-off scripts under ``.local-research/<run>/`` used to each carry
their own copy of a ``common.py`` / ``live_common.py`` helper. Those copies all
began with ``sys.path.insert(0, '/Users/james/Repos/couchroot-*')`` pointing at
whichever sibling checkout happened to be current, followed by the same block of
``tvsetup`` / ``agent`` imports and the same ``call`` / ``execute`` / ``status``
wrappers. That is the single biggest source of the ``ModuleNotFoundError`` and
wrong-repo failures in the deploy sessions.

With ``tvsetup`` installed editable (``pip install -e .``), those path hacks are
unnecessary: a run script does ::

    from tvsetup.fieldkit import Run, STATE, PRIVATE, atomic_json

    run = Run("s90d", Path(__file__).parent, client_cfg)
    run.status("preflight", expect_device="s90d")
    run.execute("uname -a\\n")

instead of copying a bespoke module and guessing a ``sys.path`` entry. The
wrappers below preserve the intent-journaling and no-replay behaviour the copies
relied on: every request writes an ``*-intent.json`` before it is sent and a
``*-result.json`` after, and an intent file that already exists refuses a replay.
"""

from __future__ import annotations

import base64
import json
import os
import stat as _stat
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Re-exported so run scripts need a single import line, not the old block.
from .common import STATE, PRIVATE, atomic_json, sha, lock, run  # noqa: F401
from .site import load_site, configured_profile, binding  # noqa: F401
from .engine import pending  # noqa: F401

# agent/ is a namespace package declared in pyproject; this resolves once
# tvsetup is installed editable, from any working directory.
from agent.client import request

# Matches the ceiling the per-run copies asserted against before sending /v1/exec.
EXEC_COMMAND_LIMIT = 16384


@dataclass
class Run:
    """A single live research run rooted at one evidence directory.

    Parameters mirror what the old per-run helpers hard-coded as module
    constants, so each script supplies its own device/root/credentials instead
    of editing a copied file.
    """

    device: str
    root: Path
    cfg: dict
    timeout: int = 30
    _seen: set = field(default_factory=set, repr=False)

    def _journal(self, prefix: str, intent: dict) -> Path:
        token = uuid.uuid4().hex
        atomic_json(self.root / f"{prefix}-{token}-intent.json", intent)
        return self.root / f"{prefix}-{token}"

    def call(self, method: str, route: str, body=None, *, timeout=None, **kw):
        """Journalled request to the device agent, preserving intent/result evidence."""
        base = self._journal("request", dict(method=method, route=route, body=body))
        result = request(self.cfg, method, route, body,
                         timeout=self.timeout if timeout is None else timeout, **kw)
        atomic_json(Path(str(base) + "-result.json"), result)
        return result

    def status(self, label: str, *, expect_device: str | None = None):
        """GET /v1/status, journal it to ``<label>.json``, optionally assert the target."""
        s = self.call("GET", "/v1/status")
        atomic_json(self.root / f"{label}.json", s)
        if expect_device is not None:
            assert s.get("device") == expect_device, "Target device drift"
        return s

    def execute(self, script: str, *, timeout_ms: int = 20000):
        """Run a shell script on the device via base64-wrapped /v1/exec.

        Fails closed: a non-zero exit or a timeout raises, so callers inspect the
        journalled evidence rather than replaying.
        """
        command = "printf %s " + base64.b64encode(script.encode()).decode() + " | base64 -d | /bin/sh"
        assert len(command) <= EXEC_COMMAND_LIMIT, "exec command exceeds transport limit"
        body = {"id": str(uuid.uuid4()), "command": command, "timeout_ms": timeout_ms}
        r = self.call("POST", "/v1/exec", body)
        assert r["exit_code"] == 0 and not r["timed_out"], \
            "Command incomplete; inspect journalled evidence without replay"
        return r["stdout"]

    def intent(self, name: str, data: dict) -> Path:
        """Record a one-shot intent; refuse a second submission of the same name."""
        p = self.root / f"{name}-intent.json"
        assert name not in self._seen and not p.exists(), \
            "Already submitted; inspect without replay"
        atomic_json(p, data)
        self._seen.add(name)
        return p

    def transport(self, label: str, client_path: Path):
        """An AgentTransport rooted under this run (imported lazily to keep imports light)."""
        from .agent_transport import AgentTransport
        profile = configured_profile(self.device, load_site())
        return AgentTransport(profile, self.root / label, client_path)


class Checks:
    """Collect-and-report preflight/verify checks.

    The deploy sessions lost many cycles to ``assert cond`` in preflight scripts:
    the first mismatch aborts, the model edits that one assertion and reruns, and
    the next mismatch aborts again. ``Checks`` records every check and reports
    them together, printing expected-vs-actual, so one run surfaces everything.
    Call :meth:`require` at the end to fail (non-zero) only if something did.

        c = Checks("qn90a preflight")
        c.equal("firmware", status["firmware"], expected_fw)
        c.equal("service", service_state, "not running")
        c.require()
    """

    def __init__(self, label: str = ""):
        self.label = label
        self.results: list[tuple[bool, str, str]] = []

    def check(self, name: str, ok, *, expected=None, actual=None) -> bool:
        ok = bool(ok)
        detail = ""
        if not ok and (expected is not None or actual is not None):
            detail = f"expected {expected!r}, got {actual!r}"
        self.results.append((ok, name, detail))
        return ok

    def equal(self, name: str, actual, expected) -> bool:
        return self.check(name, actual == expected, expected=expected, actual=actual)

    @property
    def failed(self) -> list[tuple[bool, str, str]]:
        return [r for r in self.results if not r[0]]

    def report(self) -> str:
        lines = []
        for ok, name, detail in self.results:
            mark = "ok  " if ok else "FAIL"
            lines.append(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
        passed = len(self.results) - len(self.failed)
        head = f"{self.label or 'checks'}: {passed}/{len(self.results)} passed"
        return "\n".join([head, *lines])

    def require(self) -> None:
        """Print the full report, then raise once if any check failed."""
        print(self.report())
        if self.failed:
            names = ", ".join(name for _, name, _ in self.failed)
            raise AssertionError(
                f"{len(self.failed)} check(s) failed in {self.label or 'preflight'}: {names}"
            )


def host_stat(path) -> dict:
    """Host-side file metadata via Python, not a `stat` shell-out.

    ``stat`` takes GNU (`-c`) vs BSD/macOS (`-f`) format flags that are not
    interchangeable; host scripts that used `stat -c`/`stat -f` failed on macOS.
    Device-side scripts keep using the TV's GNU ``stat`` — this is for the host.
    """
    st = os.stat(path)
    return dict(
        mode=_stat.filemode(st.st_mode),
        uid=st.st_uid,
        gid=st.st_gid,
        size=st.st_size,
        mtime=st.st_mtime,
    )


def mtime_iso(path) -> str:
    """ISO-8601 UTC mtime for a host path (replaces `date -r <epoch>`)."""
    return datetime.fromtimestamp(os.stat(path).st_mtime, timezone.utc).isoformat()
