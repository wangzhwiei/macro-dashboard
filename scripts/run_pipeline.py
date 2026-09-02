#!/usr/bin/env python3
"""One-command data update, strict validation and optional page build."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_step(label: str, command: list[str]) -> None:
    print(f"\n[{label}] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def run_optional_step(label: str, command: list[str]) -> bool:
    try:
        run_step(label, command)
        return True
    except subprocess.CalledProcessError as error:
        print(
            f"\n{label}未通过严格来源校验，保留上一版已验证数据并继续：{error}",
            file=sys.stderr,
            flush=True,
        )
        return False


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
        "--forecast-target-month",
        help="Optional month-end override passed to the fast CPI/PPI/PMI refresh.",
    )
    parser.add_argument("--full-forecast", action="store_true", help="手动重跑完整历史无前视回测；每日计划任务默认快速刷新")
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
            "导出频率与新鲜度审计",
            [python, "scripts/audit_freshness.py"],
        )
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
        forecast_inputs = ROOT / "data" / "forecast-model" / "ifind_latest_inputs.json"
        refresh_end = date.fromisoformat(args.end_date) if args.end_date else date.today()
        refresh_start = (refresh_end - timedelta(days=95)).isoformat()
        fetch_command = [
            python, "scripts/fetch_forecast_inputs_ifind.py",
            "--start", refresh_start, "--end", refresh_end.isoformat(),
        ]
        if forecast_inputs.exists():
            fetch_command.append("--merge-existing")
        run_step("增量刷新 CPI/PPI/PMI 固定 iFinD 输入", fetch_command)
        consensus_command = [python, "scripts/fetch_forecast_consensus.py"]
        if args.forecast_target_month:
            consensus_command.extend(["--target-month", args.forecast_target_month])
        run_step("抓取公开市场一致预期", consensus_command)
        forecast_command = [python, "scripts/generate_forecasts.py"] if args.full_forecast else [python, "scripts/refresh_forecasts_fast.py"]
        if args.forecast_target_month and not args.full_forecast:
            forecast_command.extend(["--target-month", args.forecast_target_month])
        run_step(
            "生成月频每日预测" if args.full_forecast else "快速刷新月频预测",
            forecast_command,
        )
        run_step(
            "写入网页社零V7定稿模型",
            [python, "scripts/publish_retail_v7_forecasts.py", "--output", "public/data/forecasts.json"],
        )
        run_optional_step("刷新进出口真实值", [python, "scripts/fetch_trade_actuals.py"])
        run_step("刷新进出口一致预期", [python, "scripts/fetch_baseline.py"])
        run_step("刷新进出口固定因子", [python, "scripts/fetch_trade_fixed_factors.py"])
        trade_model_command = [python, "scripts/research_trade_model_race.py"]
        if args.forecast_target_month:
            trade_model_command.extend(["--target-month", args.forecast_target_month])
        run_step("滚动估计进出口固定模型", trade_model_command)
        run_step("写入网页进出口预测", [python, "scripts/publish_fixed_trade_forecasts.py"])
        run_step("刷新工业增加值固定ID数据", [python, "scripts/fetch_industrial_value_data.py"])
        run_step("运行工业增加值月频模型", [python, "scripts/industrial_value_forecast_model.py"])
        run_step(
            "写入网页工业增加值定稿模型",
            [python, "scripts/publish_industrial_value_forecasts.py", "--base", "public/data/forecasts.json"],
        )
        run_step("刷新信用预测固定ID数据", [python, "scripts/fetch_credit_forecast_data.py"])
        run_step("运行固定版M2、贷款与社融模型", [python, "scripts/credit_forecast_model.py"])
        run_step(
            "写入网页信用预测",
            [python, "scripts/publish_credit_forecasts.py", "--base", "public/data/forecasts.json"],
        )
        run_step(
            "刷新固定资产投资固定ID数据",
            [python, "scripts/fetch_investment_forecast_data.py", "--resume"],
        )
        run_step(
            "运行冻结版固定资产投资固定额模型",
            [python, "scripts/investment_level_forecast_model.py"],
        )
        run_step(
            "写入网页固定资产投资预测",
            [python, "scripts/publish_investment_forecasts.py", "--base", "public/data/forecasts.json"],
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
