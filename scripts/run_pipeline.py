#!/usr/bin/env python3
"""One-command data update, strict validation and optional page build."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_step(label: str, command: list[str]) -> None:
    print(f"\n[{label}] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--adapter",
        choices=["mock", "http", "custom", "hybrid"],
        default="hybrid",
    )
    parser.add_argument("--days", type=int, default=600)
    parser.add_argument("--end-date")
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="只更新和校验数据，不执行前端测试与静态构建",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "outputs" / "data-quality-report.json",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "outputs" / "series-catalog.csv",
    )
    args = parser.parse_args()

    python = sys.executable
    update_command = [
        python,
        "scripts/update_dashboard.py",
        "--adapter",
        args.adapter,
        "--days",
        str(args.days),
    ]
    if args.end_date:
        update_command.extend(["--end-date", args.end_date])

    try:
        run_step(
            "导出接口序列目录",
            [
                python,
                "scripts/export_series_catalog.py",
                "--output",
                str(args.catalog),
            ],
        )
        run_step("调用接口并生成页面数据", update_command)
        run_step(
            "严格数据质量校验",
            [
                python,
                "scripts/validate_dashboard.py",
                "--strict",
                "--report",
                str(args.report),
            ],
        )
        run_step(
            "数据适配器单元测试",
            [
                python,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_*.py",
            ],
        )
        if not args.data_only:
            npm = shutil.which("npm")
            if not npm:
                raise RuntimeError("未找到npm，请安装Node.js 22及以上版本")
            run_step("页面测试", [npm, "test"])
            run_step("静态页面构建", [npm, "run", "build:github"])
    except (subprocess.CalledProcessError, RuntimeError) as error:
        print(f"\n流水线失败：{error}", file=sys.stderr)
        return 1

    print(
        "\n流水线完成：接口数据已生成、严格校验通过"
        + ("。" if args.data_only else "，页面测试和静态构建通过。")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
