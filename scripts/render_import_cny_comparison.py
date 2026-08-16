#!/usr/bin/env python3
"""Render original vs CNY-gated import forecasts without replacing either series."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "outputs" / "trade-model-research" / "model-race.csv"
JSON_PATH = ROOT / "outputs" / "trade-model-research" / "model-race.json"
OUTPUT = ROOT / "outputs" / "trade-model-research" / "import-cny-comparison.svg"
WIDTH, HEIGHT, LEFT, RIGHT, TOP, PLOT_HEIGHT = 1200, 440, 76, 30, 82, 285


def number(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None


def path_for(rows, field, x, y):
    parts, drawing = [], False
    for index, row in enumerate(rows):
        value = row[field]
        if value is None:
            drawing = False
            continue
        parts.append(f"{'L' if drawing else 'M'} {x(index):.1f} {y(value):.1f}")
        drawing = True
    return " ".join(parts)


def main() -> int:
    rows = []
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw["target"] != "imports":
                continue
            rows.append({
                "date": raw["date"][:7], "actual": number(raw["actual"]),
                "original": number(raw["anchored_factor"]),
                "cny": number(raw["import_fixed_cny_gated"]), "consensus": number(raw["consensus"]),
            })
    result = json.loads(JSON_PATH.read_text(encoding="utf-8"))["targets"]["imports"]["current_forecast"]
    if result["forecast"] is not None:
        rows.append({
            "date": result["month"], "actual": None,
            "original": number(result.get("ungated_model_forecast")),
            "cny": float(result["forecast"]), "consensus": None,
        })
    values = [row[field] for row in rows for field in ("actual", "original", "cny", "consensus") if row[field] is not None]
    low, high = min(values) - 4, max(values) + 4
    plot_width = WIDTH - LEFT - RIGHT
    x = lambda i: LEFT + plot_width * i / (len(rows) - 1)
    y = lambda value: TOP + PLOT_HEIGHT * (high - value) / (high - low)
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img">',
        '<title>进口同比原模型与春节门控模型比较</title>',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<style>text{font-family:Arial,"Microsoft YaHei",sans-serif;fill:#202124}.title{font-size:21px;font-weight:600}.sub{font-size:13px;fill:#5f6368}.axis{font-size:12px;fill:#5f6368}.grid{stroke:#e3e6ea;stroke-width:1}.actual{stroke:#202124;stroke-width:2.5;fill:none}.original{stroke:#7b61a8;stroke-width:2.1;stroke-dasharray:6 4;fill:none}.cny{stroke:#2474d2;stroke-width:2.6;fill:none}.consensus{stroke:#e68a00;stroke-width:2;stroke-dasharray:3 4;fill:none}</style>',
        '<text x="76" y="30" class="title">进口同比：原模型与春节门控模型</text>',
        '<text x="76" y="52" class="sub">单位：%；固定韩国出口因子，滚动估计系数；春节门控仅在1—3月调整。</text>',
        '<g transform="translate(610,28)"><line x1="0" y1="0" x2="25" y2="0" class="actual"/><text x="31" y="4" class="axis">实际</text><line x1="85" y1="0" x2="110" y2="0" class="original"/><text x="116" y="4" class="axis">原模型</text><line x1="190" y1="0" x2="215" y2="0" class="cny"/><text x="221" y="4" class="axis">春节门控</text><line x1="315" y1="0" x2="340" y2="0" class="consensus"/><text x="346" y="4" class="axis">一致预期</text></g>',
    ]
    for tick in range(6):
        value = high - tick * (high - low) / 5
        yy = y(value)
        svg.append(f'<line x1="{LEFT}" y1="{yy:.1f}" x2="{WIDTH-RIGHT}" y2="{yy:.1f}" class="grid"/>')
        svg.append(f'<text x="{LEFT-9}" y="{yy+4:.1f}" text-anchor="end" class="axis">{value:.0f}</text>')
    for index in range(0, len(rows), 4):
        svg.append(f'<text x="{x(index):.1f}" y="{TOP+PLOT_HEIGHT+23}" text-anchor="middle" class="axis">{html.escape(rows[index]["date"])}</text>')
    for field in ("actual", "original", "cny", "consensus"):
        svg.append(f'<path d="{path_for(rows, field, x, y)}" class="{field}"/>')
    svg.append('</svg>')
    OUTPUT.write_text("\n".join(svg), encoding="utf-8")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
