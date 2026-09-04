from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


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

    def test_resume_refreshes_live_and_uses_validated_series_only_as_fallback(self) -> None:
        for script_name in ("fetch_credit_forecast_data", "fetch_investment_forecast_data"):
            module = load_script(script_name)
            config = {"target": {"providerId": "FIXED_ID", "query": "fixed query", "role": "target"}}
            previous = {
                "providerId": "FIXED_ID",
                "role": "target",
                "observations": [["2026-07-31", 1.0]],
            }
            with tempfile.TemporaryDirectory() as directory:
                checkpoint = Path(directory) / "source.json"
                checkpoint.write_text(
                    json.dumps({"series": {"target": previous}}),
                    encoding="utf-8",
                )
                live_call = Mock(return_value={})
                patches = (
                    patch.object(module, "SERIES", config),
                    patch.object(module, "load_call", return_value=live_call),
                    patch.object(module, "parse", side_effect=RuntimeError("temporary provider gap")),
                    patch.object(module.time, "sleep", return_value=None),
                )
                with patches[0], patches[1], patches[2], patches[3]:
                    if script_name == "fetch_credit_forecast_data":
                        with patch.object(module, "find_call", return_value=Path("call.py")):
                            result = module.fetch(checkpoint, resume=True)
                    else:
                        result = module.fetch(Path("call.py"), checkpoint, resume=True)
                self.assertEqual(live_call.call_count, 3)
                self.assertEqual(result["series"]["target"], previous)
                self.assertEqual(len(result["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
