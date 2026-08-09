#!/usr/bin/env python3
"""Run the locked forecast generator with pandas/statsmodels or local WSL."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "scripts" / "generate_forecasts_model.py"


def wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise RuntimeError(f"无法转换为 WSL 路径：{resolved}")
    relative = resolved.as_posix().split(":/", 1)[1]
    return f"/mnt/{drive}/{relative}"


def main() -> int:
    try:
        import pandas  # noqa: F401
        import statsmodels  # noqa: F401
    except ImportError:
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if not wsl:
            raise RuntimeError("预测生成需要 pandas/statsmodels；本机也未找到 WSL 运行时")
        command = [
            wsl, "-d", os.environ.get("FORECAST_WSL_DISTRO", "Ubuntu"), "--", "python3", wsl_path(CORE),
            "--input", wsl_path(ROOT / "data" / "forecast-model" / "model_inputs.json"),
            "--locked", wsl_path(ROOT / "data" / "forecast-model" / "locked_nowcasts.json"),
            "--consensus", wsl_path(ROOT / "data" / "forecast-model" / "consensus.json"),
            "--live", wsl_path(ROOT / "data" / "forecast-model" / "live_inputs.json"),
            "--official-pmi", wsl_path(ROOT / "data" / "forecast-model" / "official_pmi_subindices.json"),
            "--ifind-latest", wsl_path(ROOT / "data" / "forecast-model" / "ifind_latest_inputs.json"),
            "--output", wsl_path(ROOT / "public" / "data" / "forecasts.json"),
        ]
        return subprocess.run(command, cwd=ROOT, check=False).returncode
    return subprocess.run([sys.executable, str(CORE)], cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
