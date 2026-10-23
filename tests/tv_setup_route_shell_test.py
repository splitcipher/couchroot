"""Route SQL must cross the shell unchanged in apply and rollback."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from tvsetup.operations import Driver, route_sql
from tvsetup.planner import Action, HOME_DESIRED, HOME_STOCK
from tvsetup.transport import TABLES


class RouteShellTests(unittest.TestCase):
    def test_values_cannot_expand_or_terminate_sql_input(self):
        values = [
            "literal TV_SETUP_SQL with 'quotes' and 100%",
            "$(printf SHELL_EXPANDED) `printf SHELL_EXPANDED` $HOME \\text",
            "before\nTV_SETUP_SQL\nprintf HEREDOC_ESCAPED\nexit 0\nafter",
        ]
        for value in values:
            for reverse in (False, True):
                with (
                    self.subTest(value=value, reverse=reverse),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    original = list(HOME_STOCK)
                    original[-1] = value
                    action = Action(
                        "route",
                        "home",
                        "routes",
                        [original],
                        [HOME_DESIRED],
                        dict(table="key_filter", scope="home"),
                    )
                    driver = Driver.__new__(Driver)
                    driver.tv = Mock()
                    driver.control_call = Mock()
                    state = dict(key_filter=action.after if reverse else action.before)
                    if reverse:
                        driver.rollback(action, {}, state)
                    else:
                        driver.execute(action, {}, state)
                    script = driver.tv.root.call_args.args[0]
                    # Capture stdin at the sqlite boundary. No device path is opened.
                    # The real SQL transaction is exercised below in memory.
                    shim = Path(tmp) / "sqlite3"
                    shim.write_text(
                        '#!/bin/sh\nif [ "$1" = -readonly ]; then printf "ok\\n"; else cat; fi\n'
                    )
                    shim.chmod(0o700)
                    result = subprocess.run(
                        ["sh", "-c", "set -eu\n" + script],
                        cwd=tmp,
                        env=dict(
                            os.environ, PATH=tmp + os.pathsep + os.environ["PATH"]
                        ),
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, route_sql(action, reverse))
                    driver.control_call.assert_called_once_with("reload", root=True)
                    columns = TABLES["key_filter"][2]
                    with closing(sqlite3.connect(":memory:")) as db:
                        db.execute(
                            "CREATE TABLE key_filter("
                            + ",".join(c + " TEXT" for c in columns)
                            + ")"
                        )
                        db.executemany(
                            "INSERT INTO key_filter VALUES("
                            + ",".join("?" for _ in columns)
                            + ")",
                            state["key_filter"],
                        )
                        db.commit()
                        db.executescript(result.stdout)
                        expected = action.before if reverse else action.after
                        self.assertEqual(
                            list(db.execute("SELECT * FROM key_filter")),
                            [tuple(row) for row in expected],
                        )


if __name__ == "__main__":
    unittest.main()
