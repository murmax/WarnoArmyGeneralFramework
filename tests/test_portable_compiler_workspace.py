"""Portable official ModGen workspace staging without a game Mods project."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from warno_ag.native_toolchain import prepare_native_compiler_workspace


class PortableCompilerWorkspaceTests(unittest.TestCase):
    def test_explicit_parent_keeps_compiler_files_outside_game_mods(self):
        artifacts = Path(__file__).resolve().parents[1] / "artifacts"
        artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="portable-compiler-", dir=artifacts) as folder:
            root = Path(folder)
            game = root / "game"
            parent = root / "e-workspaces"
            (game / "Mods/ModData").mkdir(parents=True)
            parent.mkdir()
            with zipfile.ZipFile(game / "Mods/ModData/base.zip", "w") as archive:
                archive.writestr("GameData/Generated/Gameplay/test.ndf", "source")
            with patch("warno_ag.native_toolchain.subprocess.run") as run:
                run.return_value.returncode = 0
                report = prepare_native_compiler_workspace(
                    game, "WarnoAGFPortableBuild", workspace_parent=parent)
            workspace = parent / "WarnoAGFPortableBuild"
            self.assertEqual(report["workspace"], str(workspace.resolve()))
            self.assertEqual(report["workspace_parent"], str(parent.resolve()))
            self.assertFalse((game / "Mods/WarnoAGFPortableBuild").exists())
            self.assertEqual((workspace / "GameData/Generated/Gameplay/test.ndf").read_text(),
                             "source")
            self.assertEqual(json.loads((workspace / "agf-compiler-workspace.json")
                                        .read_text(encoding="utf-8"))["generation_run"], False)
            self.assertEqual(run.call_args.kwargs["cwd"], workspace.resolve())


if __name__ == "__main__":
    unittest.main()
