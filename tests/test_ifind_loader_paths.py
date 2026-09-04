from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IFindLoaderPathTests(unittest.TestCase):
    def test_loaders_resolve_config_from_skill_directory_and_restore_cwd(self) -> None:
        modules = (
            (load_script("fetch_industrial_value_data"), "load_ifind_call"),
            (load_script("fetch_credit_forecast_data"), "load_call"),
            (load_script("fetch_investment_forecast_data"), "load_call"),
        )
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory)
            (skill / "mcp_config.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            (skill / "call.py").write_text(
                "import json\n"
                "from pathlib import Path\n"
                "CONFIG = json.loads(Path('mcp_config.json').read_text(encoding='utf-8'))\n"
                "def call(*args, **kwargs):\n"
                "    return CONFIG\n",
                encoding="utf-8",
            )
            for module, loader_name in modules:
                loaded = getattr(module, loader_name)(skill / "call.py")
                self.assertEqual(loaded(), {"ok": True})
                self.assertEqual(Path.cwd(), original)


if __name__ == "__main__":
    unittest.main()
