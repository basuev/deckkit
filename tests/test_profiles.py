"""Profiles, scoped Steam settings and adoption of personal installations."""

import base64
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from support import fixture

from deckkit import __main__ as commands
from deckkit import cyberpunk, launcher, profiles, steam
from deckkit.steam_api import SteamAPI, decode_fields


class Profiles(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = fixture(Path(temporary.name))
        self.installer = self.fixture["installer"]

        for name in ("steam_running", "game_running"):
            context = patch.object(steam, name, return_value=False)
            context.start()
            self.addCleanup(context.stop)

    def command(self, *arguments):
        output = io.StringIO()
        with (
            patch.object(commands, "Installer", return_value=self.installer),
            patch("sys.argv", ["deckkit", *arguments]),
            redirect_stdout(output),
        ):
            self.assertEqual(commands.main(), 0)

        return json.loads(output.getvalue())

    def test_cli_profile_changes_persist_without_touching_steam_display(self):
        self.installer.install("cyberpunk2077")
        before = self.fixture["steam_api"].snapshot()

        result = self.command("profile", "--fps", "45", "--ui-scale", "175")
        self.assertEqual(result, {"fps_limit": 45, "ui_scale": 175})
        self.assertEqual(self.command("status")["ui_scale"], 175)

        self.command("profile", "--fps", "uncapped")
        self.assertEqual(self.command("status")["fps_limit"], None)
        self.assertEqual(self.command("status")["ui_scale"], 175)
        self.assertEqual(self.fixture["steam_api"].snapshot(), before)

    def test_noninteractive_launch_uses_shared_operation_and_original_command(
        self,
    ):
        self.installer.install("cyberpunk2077")
        profiles.apply(self.installer, "cyberpunk2077", 45, 175)

        command = ["proton", "game.exe", "argument with spaces"]
        with (
            patch.object(launcher, "execute") as execute,
            patch.object(commands, "Installer", return_value=self.installer),
            patch(
                "sys.argv",
                [
                    "deckkit",
                    "launch",
                    "--no-ui",
                    "cyberpunk2077",
                    "--",
                    *command,
                ],
            ),
        ):
            self.assertEqual(commands.main(), 0)

        execute.assert_called_once_with(command)
        self.assertEqual(
            self.fixture["steam_api"].values["gamescope_display_refresh_rate"],
            90,
        )
        self.assertFalse(
            self.fixture["steam_api"].values["steamos_tdp_limit_enabled"]
        )

    def test_restore_display_preserves_later_steam_edits(self):
        steam_api = self.fixture["steam_api"]
        before = steam_api.snapshot()
        after = steam_api.apply_display_settings()
        steam_api.set_settings(
            {"gamescope_display_refresh_rate": 60, "steamos_tdp_limit": 13}
        )

        profiles.restore_display(
            self.installer, {"before": before, "after": after}
        )

        self.assertEqual(
            steam_api.values["gamescope_display_refresh_rate"], 60
        )
        self.assertEqual(steam_api.values["steamos_tdp_limit"], 13)
        self.assertEqual(
            steam_api.values["gamescope_disable_framelimit"],
            before["gamescope_disable_framelimit"],
        )

    def test_missing_app_context_preserves_files(self):
        self.installer.install("cyberpunk2077")
        settings = self.fixture["settings"].read_bytes()

        with patch.object(
            self.fixture["steam_api"],
            "wait_for_game",
            side_effect=RuntimeError("No Cyberpunk app context"),
        ):
            with self.assertRaises(RuntimeError):
                profiles.apply(
                    self.installer, "cyberpunk2077", 45, 175, steam=True
                )

        self.assertEqual(self.fixture["settings"].read_bytes(), settings)

    def personal_files(self):
        package = self.fixture["bundle"] / "assets/packages/cyberpunk2077"
        game = self.fixture["game"]
        old_ui = game / "archive/pc/mod/codex-deck-ui.archive"
        old_config = game / "engine/config/platform/pc/codex-performance.ini"
        for path in (old_ui, old_config):
            path.parent.mkdir(parents=True, exist_ok=True)
        old_ui.write_bytes((package / "profiles/175.archive").read_bytes())
        old_config.write_bytes(
            (package / "deckkit-performance.ini").read_bytes()
        )

        data = json.loads(self.fixture["settings"].read_text())
        options = data["data"][0]["options"]
        next(o for o in options if o["name"] == "MaximumFPS_OnOff")[
            "value"
        ] = True
        next(o for o in options if o["name"] == "MaximumFPS_Value")[
            "value"
        ] = 45
        self.fixture["settings"].write_text(json.dumps(data))

        return old_ui, old_config

    def test_personal_migration_adopts_files_and_preserves_selection(self):
        old_ui, old_config = self.personal_files()
        legacy = str(Path.home() / ".local/share/codex-deck-ui/launcher.py")
        steam.write_launch_options(
            self.fixture["root"],
            self.fixture["account"],
            f"FOO=bar {legacy} -- %command% --existing",
        )

        self.installer.install("cyberpunk2077")
        receipt = self.installer.load_receipt("cyberpunk2077")
        self.assertEqual(cyberpunk.selected(receipt), (45, 175))
        self.assertFalse(old_ui.exists())
        self.assertFalse(old_config.exists())

        self.installer.remove("cyberpunk2077")
        self.assertFalse(cyberpunk.ui_target(receipt).exists())
        self.assertFalse(old_ui.exists())
        self.assertFalse(old_config.exists())
        self.assertEqual(
            steam.launch_options(
                self.fixture["root"], self.fixture["account"]
            ),
            "FOO=bar %command% --existing",
        )

    def test_failed_migration_restores_exact_previous_files(self):
        old_ui, old_config = self.personal_files()
        before = {
            p: p.read_bytes()
            for p in (old_ui, old_config, self.fixture["settings"])
        }
        original = cyberpunk.install

        def fail_after_changes(receipt, package):
            original(receipt, package)
            raise RuntimeError("Failure after changing game files")

        with patch.object(
            cyberpunk, "install", side_effect=fail_after_changes
        ):
            with self.assertRaises(RuntimeError):
                self.installer.install("cyberpunk2077")

        self.assertEqual({p: p.read_bytes() for p in before}, before)
        target = self.fixture["game"] / "archive/pc/mod/deckkit-ui.archive"
        self.assertFalse(target.exists())
        self.assertIsNone(self.installer.load_receipt("cyberpunk2077"))

    def test_modified_legacy_files_are_preserved(self):
        old_ui, old_config = self.personal_files()
        old_ui.write_bytes(b"user-modified UI")
        old_config.write_bytes(b"user-modified config")

        self.installer.install("cyberpunk2077")
        self.installer.remove("cyberpunk2077")

        self.assertEqual(old_ui.read_bytes(), b"user-modified UI")
        self.assertEqual(old_config.read_bytes(), b"user-modified config")

    def test_display_adapter_sends_native_qam_fields(self):
        with patch("deckkit.steam_api.SteamClient") as client:
            connection = client.return_value.__enter__.return_value
            connection.evaluate.return_value = True
            SteamAPI().apply_display_settings()

        expression = (
            client.return_value.__enter__.return_value.evaluate.call_args.args[
                0
            ]
        )
        encoded = json.loads(
            expression[len("SteamClient.Settings.SetSetting(") : -1]
        )
        fields = decode_fields(base64.b64decode(encoded))
        self.assertEqual(fields[21005], 90)
        self.assertEqual(fields[21004], 1)
        self.assertEqual(fields[22001], 0)
        self.assertNotIn(22002, fields)
