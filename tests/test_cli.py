import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make the repo root (for `cli`) and the source tree importable without installing
if (_root := str(Path(__file__).resolve().parent.parent)) not in sys.path:
    sys.path.insert(0, _root)
if (_src := str(Path(__file__).resolve().parent.parent / "src")) not in sys.path:
    sys.path.insert(0, _src)

from gemini_webapi.cli import build_parser


@unittest.skipUnless(
    os.getenv("SECURE_1PSID"),
    "Skipped: SECURE_1PSID not set (live credential required)",
)
class TestCLITool(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls._cookie_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        cookies = {
            "__Secure-1PSID": os.getenv("SECURE_1PSID", ""),
            "__Secure-1PSIDTS": os.getenv("SECURE_1PSIDTS", ""),
        }
        Path(cls._cookie_path).write_text(json.dumps(cookies), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        with contextlib.suppress(OSError):
            os.unlink(cls._cookie_path)

    def _parse(self, *argv):
        parser = build_parser()
        return parser.parse_args(
            [
                "--cookies-json",
                self._cookie_path,
                "--no-persist",
                "--skip-verify",
                *argv,
            ]
        )

    async def test_cli_ask_stream(self):
        from gemini_webapi.cli import cmd_ask

        args = self._parse("ask", "Give me a inspiring idea for web development")
        result = await cmd_ask(args)
        assert result == 0

    async def test_cli_models(self):
        from gemini_webapi.cli import cmd_models

        args = self._parse("models")
        result = await cmd_models(args)
        assert result == 0

    async def test_cli_list_chats(self):
        from gemini_webapi.cli import cmd_list

        args = self._parse("list")
        result = await cmd_list(args)
        assert result == 0

    async def test_cli_inspect(self):
        from gemini_webapi.cli import cmd_inspect

        args = self._parse("inspect")
        result = await cmd_inspect(args)
        assert result == 0


if __name__ == "__main__":
    unittest.main()
