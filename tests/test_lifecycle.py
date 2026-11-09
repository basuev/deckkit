import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import fixture

from deckkit import cyberpunk, steam, vdf
from deckkit.archive import extract


class Lifecycle(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fixture = fixture(Path(tmp.name), sd=True)
        self.installer = self.fixture["installer"]
        for name in ("steam_running", "game_running"):
            context = patch.object(steam, name, return_value=False)
            context.start()
            self.addCleanup(context.stop)

    def test_library_prefix_and_current_account_discovery(self):
        self.assertEqual(
            steam.find_game(self.fixture["root"]), self.fixture["game"]
        )
        self.assertEqual(
            steam.find_settings(self.fixture["root"], self.fixture["game"]),
            self.fixture["settings"],
        )
        self.assertEqual(steam.active_account(self.fixture["root"]), "123")

    def test_install_launch_preferences_update_and_remove(self):
        original = steam.launch_options(self.fixture["root"], "123")
        save = self.fixture["saves"] / "campaign.dat"
        self.installer.install("cyberpunk2077")
        receipt = self.installer.load_receipt("cyberpunk2077")
        self.assertIn(
            " launch cyberpunk2077 -- %command%",
            steam.launch_options(self.fixture["root"], "123"),
        )
        self.assertEqual(cyberpunk.selected(receipt), (None, 150))
        cyberpunk.apply(
            receipt, self.installer.paths.packages / "cyberpunk2077", 45, 175
        )
        self.installer.save_receipt(receipt)
        self.installer.install("cyberpunk2077")
        self.assertEqual(
            cyberpunk.selected(self.installer.load_receipt("cyberpunk2077")),
            (45, 175),
        )
        self.installer.remove("cyberpunk2077")
        self.assertEqual(
            steam.launch_options(self.fixture["root"], "123"), original
        )
        self.assertEqual(
            json.loads(self.fixture["settings"].read_text()),
            self.fixture["data"],
        )
        self.assertFalse(cyberpunk.ui_target(receipt).exists())
        self.assertEqual(save.read_bytes(), b"never touch this save")

    def test_removal_preserves_later_user_changes(self):
        self.installer.install("cyberpunk2077")
        data = json.loads(self.fixture["settings"].read_text())
        data["data"][1]["options"][0].update(value="Medium", index=1)
        self.fixture["settings"].write_text(json.dumps(data))
        current = steam.launch_options(self.fixture["root"], "123")
        steam.write_launch_options(
            self.fixture["root"], "123", current + " --new-user-option"
        )
        receipt = self.installer.load_receipt("cyberpunk2077")
        cyberpunk.ui_target(receipt).write_bytes(
            b"another mod manager's replacement"
        )
        result = self.installer.remove("cyberpunk2077")
        self.assertEqual(
            json.loads(self.fixture["settings"].read_text())["data"][1][
                "options"
            ][0]["value"],
            "Medium",
        )
        self.assertIn(
            "--new-user-option",
            steam.launch_options(self.fixture["root"], "123"),
        )
        self.assertNotIn(
            "launch cyberpunk2077",
            steam.launch_options(self.fixture["root"], "123"),
        )
        self.assertTrue(result["preserved"])

    def test_corrupt_package_does_not_modify_game(self):
        before = self.fixture["settings"].read_bytes()
        profile = (
            self.fixture["bundle"]
            / "assets/packages/cyberpunk2077/profiles/150.archive"
        )
        profile.write_bytes(b"corrupt")
        with self.assertRaises(RuntimeError):
            self.installer.install("cyberpunk2077")
        self.assertEqual(self.fixture["settings"].read_bytes(), before)
        self.assertIsNone(self.installer.load_receipt("cyberpunk2077"))

    def test_running_game_blocks_file_changes(self):
        before = self.fixture["settings"].read_bytes()
        with patch.object(steam, "game_running", return_value=True):
            with self.assertRaises(RuntimeError):
                self.installer.install("cyberpunk2077")
        self.assertEqual(self.fixture["settings"].read_bytes(), before)

    def test_standard_removes_only_the_own_archive(self):
        self.installer.install("cyberpunk2077")
        receipt = self.installer.load_receipt("cyberpunk2077")
        other = cyberpunk.ui_target(receipt).with_name("other.archive")
        other.write_bytes(b"keep")
        for scale in (175, 100, 150):
            cyberpunk.apply(
                receipt,
                self.installer.paths.packages / "cyberpunk2077",
                None,
                scale,
            )
            self.assertEqual(cyberpunk.selected(receipt)[1], scale)
        self.assertEqual(other.read_bytes(), b"keep")

    def test_modes_release_old_tdp_cap_and_preserve_camera(self):
        camera = {
            "FPP_TurningX": 0.0,
            "FPP_TurningY": 0.0,
            "FPP_ADSTurningX": 0.0,
            "FPP_ADSTurningY": 0.0,
            "FPP_PadX": 18.0,
        }
        data = json.loads(self.fixture["settings"].read_text())
        data["data"].append(
            {
                "group_name": "/controls/fppcamerapad",
                "options": [
                    {"name": key, "value": value}
                    for key, value in camera.items()
                ],
            }
        )
        self.fixture["settings"].write_text(json.dumps(data))
        self.installer.install("cyberpunk2077")
        receipt = self.installer.load_receipt("cyberpunk2077")
        steam_api = self.fixture["steam_api"]
        for fps_limit in (45, None):
            with self.subTest(fps_limit=fps_limit):
                steam_api.set_settings(
                    {"steamos_tdp_limit_enabled": 1, "steamos_tdp_limit": 10}
                )
                steam_api.apply_display_settings()
                cyberpunk.apply(
                    receipt,
                    self.installer.paths.packages / "cyberpunk2077",
                    fps_limit,
                    175,
                )
                self.assertFalse(steam_api.values["steamos_tdp_limit_enabled"])
                self.assertTrue(
                    steam_api.values["gamescope_disable_framelimit"]
                )
                self.assertEqual(
                    steam_api.values["gamescope_display_refresh_rate"], 90
                )
                current = json.loads(self.fixture["settings"].read_text())
                options = {
                    o["name"]: o["value"]
                    for g in current["data"]
                    for o in g.get("options", [])
                }
                self.assertEqual(options["MaximumFPS_OnOff"], fps_limit == 45)
                self.assertEqual(options["MaximumFPS_Value"], 45)
                self.assertEqual(
                    options["VSync"], "UI-Settings-Video-QualitySetting-Off"
                )
                self.assertEqual({key: options[key] for key in camera}, camera)

    def test_remove_creates_scoped_one_shot_restore(self):
        self.installer.install("cyberpunk2077")
        receipt = self.installer.load_receipt("cyberpunk2077")
        receipt["steam_before"] = self.fixture["steam_api"].snapshot()
        receipt["steam_after"] = self.fixture[
            "steam_api"
        ].apply_display_settings()
        self.installer.save_receipt(receipt)
        self.installer.remove("cyberpunk2077")
        self.assertIn(
            "restore cyberpunk2077",
            steam.launch_options(self.fixture["root"], "123"),
        )
        job = json.loads(
            (
                self.installer.paths.state / "restore/cyberpunk2077.json"
            ).read_text()
        )
        self.assertEqual(job["before"]["gamescope_app_target_framerate"], 45)
        self.assertFalse(
            (self.installer.paths.packages / "cyberpunk2077").exists()
        )

    def test_shortcuts_roundtrip_and_duplicate_registration(self):
        file = steam.shortcut_file(self.fixture["root"], "123")
        other = [
            [
                0,
                "shortcuts",
                [
                    [
                        0,
                        "0",
                        [
                            [2, "appid", vdf.integer(42)],
                            [1, "AppName", "Other game"],
                        ],
                    ]
                ],
            ]
        ]
        file.write_bytes(vdf.encode_binary(other))
        for _ in range(2):
            steam.register_shortcut(
                self.fixture["root"],
                "123",
                self.installer.paths.command,
                Path("icon.svg"),
            )
        parsed = vdf.decode_binary(file.read_bytes())
        self.assertEqual(len(parsed[0][2]), 2)
        self.assertEqual(parsed[0][2][0], other[0][2][0])
        self.assertEqual(vdf.encode_binary(parsed), file.read_bytes())

    def test_archive_rejects_traversal_and_external_symlinks(self):
        for name, link in [("../escape", None), ("link", "../../escape")]:
            source = self.installer.paths.home.parent / "bad.tar.gz"
            with tarfile.open(source, "w:gz") as out:
                item = tarfile.TarInfo(name)
                if link:
                    item.type = tarfile.SYMTYPE
                    item.linkname = link
                else:
                    item.size = 4
                out.addfile(item, None if link else io.BytesIO(b"test"))
            with self.assertRaises(ValueError):
                extract(source, self.installer.paths.home / "unpack")


if __name__ == "__main__":
    unittest.main()
