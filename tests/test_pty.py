"""Test de bout en bout dans un vrai pseudo-terminal (Linux)."""
import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def drive(keys, env_extra, cols=100, rows=30):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor",
           "PYTHONPATH": str(ROOT / "src"), **env_extra}
    proc = subprocess.Popen([sys.executable, "-m", "yhelp_tui"], stdin=slave, stdout=slave,
                            stderr=slave, env=env, close_fds=True)
    os.close(slave)
    out = b""

    def pump(t):
        nonlocal out
        end = time.time() + t
        while time.time() < end:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    return
                if not data:
                    return
                out += data

    pump(0.8)
    for k in keys:
        os.write(master, k)
        pump(0.4)
    deadline = time.time() + 5
    while proc.poll() is None and time.time() < deadline:
        pump(0.1)
    if proc.poll() is None:
        proc.kill()
    os.close(master)
    return proc.returncode, out.decode("utf-8", "replace")


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux requis")
class PtyTests(unittest.TestCase):
    def test_quit(self):
        home = tempfile.mkdtemp()
        rc, out = drive([b"q"], {"YHELP_HOME": home})
        self.assertEqual(rc, 0)
        self.assertIn("\x1b[?1049h", out)
        self.assertIn("\x1b[?1049l", out)
        self.assertIn("System Info", out)

    def test_run_command_and_cd(self):
        home = tempfile.mkdtemp()
        Path(home, "commands.json").write_text(json.dumps(
            [{"id": "hi", "name": "Hi", "command": "echo hello-from-hub", "category": "outils"}]))
        rc, out = drive([b"\r", b"\r", b"q"], {"YHELP_HOME": home})
        self.assertEqual(rc, 0)
        self.assertIn("hello-from-hub", out)
        self.assertEqual(json.loads(Path(home, "commands.json").read_text())[0]["use_count"], 1)
        self.assertEqual(len(json.loads(Path(home, "history.json").read_text())), 1)

        cdfile = os.path.join(tempfile.mkdtemp(), "cd")
        Path(home, "shortcuts.json").write_text(json.dumps([{"id": "h", "name": "Home", "path": "~"}]))
        rc, _ = drive([b"\x1b[D", b"\x1b[B", b"\x1b[B", b"\x1b[C", b"\r"],
                      {"YHELP_HOME": home, "YHELP_CD_FILE": cdfile, "HOME": home})
        self.assertEqual(rc, 0)
        self.assertEqual(Path(cdfile).read_text(), home)


if __name__ == "__main__":
    unittest.main()
