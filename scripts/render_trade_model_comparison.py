#!/usr/bin/env python3
"""Render actual, standalone forecast and consensus as a static SVG."""

from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "outputs" / "trade-model-research" / "model-race.csv"
JSON_PATH = ROOT / "outputs" / "trade-model-research" / "model-race.json"
OUTPUT = ROOT / "outputs" / "trade-model-research" / "model-comparison.svg"
WIDTH, HEIGHT = 1200, 700
LEFT, RIGHT = 78, 28
PLOT_TOP, PLOT_HEIGHT, GAP = 100, 230, 70


def number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def path_for(rows: list[dict], field: str, x, y) -> str:
    parts, drawing = [], False
    for index, row in enumerate(rows):
        value = row.get(field)
        if value is None:
            drawing = False
            continue
        parts.append(f"{'L' if drawing else 'M'} {x(index):.1f} {y(value):.1f}")
        drawing = True
    return " ".join(parts)


def main() -> int:
    groups = {"exports": [], "imports": []}
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            forecast_field = "export_fixed_cny_gated" if raw["target"] == "exports" else "import_fixed_cny_gated"
            groups[raw["target"]].append({
                "date": raw["date"][:7],
                "actual": number(raw["actual"]),
                "forecast": number(raw[forecast_field]),
                "consensus": number(raw["consensus"]),
            })
    result = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    for key in groups:
        current = result["targets"][key]["current_forecast"]
        if current["forecast"] is not None:
            groups[key].append({
                "date": current["month"], "actual": None,
                "forecast": float(current["forecast"]), "consensus": None,
            })

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img">',
        '<title>中国进出口同比：真实值、独立模型预测与一致预期</title>',
        '<desc>出口和进口固定因子滚动估计模型的时间序列回测图。</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,"Microsoft YaHei",sans-serif;fill:#202124}.title{font-size:22px;font-weight:600}.sub{font-size:13px;fill:#5f6368}.axis{font-size:12px;fill:#5f6368}.grid{stroke:#e3e6ea;stroke-width:1}.zero{stroke:#9aa0a6;stroke-width:1}.actual{stroke:#202124;stroke-width:2.6;fill:none}.forecast{stroke:#2474d2;stroke-width:2.4;fill:none}.consensus{stroke:#e68a00;stroke-width:2.2;stroke-dasharray:6 4;fill:none}.point{stroke:#fff;stroke-width:1.5}</style>',
        '<text x="78" y="34" class="title">中国进出口同比预测效果对比</text>',
        '<text x="78" y="56" class="sub">单位：%；固定因子与滞后、滚动估计系数；一致预期仅用于评价，不进入模型。</text>',
        '<g transform="translate(720,25)"><line x1="0" y1="0" x2="28" y2="0" class="actual"/><text x="36" y="4" class="axis">真实值</text><line x1="112" y1="0" x2="140" y2="0" class="forecast"/><text x="148" y="4" class="axis">模型预测</text><line x1="244" y1="0" x2="272" y2="0" class="consensus"/><text x="280" y="4" class="axis">一致预期</text></g>',
    ]
    for panel, key in enumerate(("exports", "imports")):
        rows = groups[key]
        top = PLOT_TOP + panel * (PLOT_HEIGHT + GAP)
        values = [row[field] for row in rows for field in ("actual", "forecast", "consensus") if row[field] is not None]
        low, high = min(values), max(values)
        pad = max((high - low) * 0.12, 2.0)
        low, high = low - pad, high + pad
        plot_width = WIDTH - LEFT - RIGHT
        x = lambda i: LEFT + plot_width * i / (len(rows) - 1)
        y = lambda v: top + PLOT_HEIGHT * (high - v) / (high - low)
        label = "出口金额同比" if key == "exports" else "进口金额同比"
        svg.append(f'<text x="{LEFT}" y="{top - 14}" class="title">{label}</text>')
        for tick in range(5):
            value = high - tick * (high - low) / 4
            yy = y(value)
            svg.append(f'<line x1="{LEFT}" y1="{yy:.1f}" x2="{WIDTH-RIGHT}" y2="{yy:.1f}" class="grid"/>')
            svg.append(f'<text x="{LEFT-10}" y="{yy+4:.1f}" text-anchor="end" class="axis">{value:.0f}</text>')
        if low <= 0 <= high:
            svg.append(f'<line x1="{LEFT}" y1="{y(0):.1f}" x2="{WIDTH-RIGHT}" y2="{y(0):.1f}" class="zero"/>')
        for index in range(0, len(rows), 4):
            svg.append(f'<text x="{x(index):.1f}" y="{top+PLOT_HEIGHT+22}" text-anchor="middle" class="axis">{html.escape(rows[index]["date"])}</text>')
        svg.append(f'<path d="{path_for(rows,"actual",x,y)}" class="actual"/>')
        svg.append(f'<path d="{path_for(rows,"forecast",x,y)}" class="forecast"/>')
        svg.append(f'<path d="{path_for(rows,"consensus",x,y)}" class="consensus"/>')
        forecast_indexes = [index for index, row in enumerate(rows) if row["forecast"] is not None]
        if forecast_indexes:
            last_index = forecast_indexes[-1]
            last = rows[last_index]
            svg.append(f'<circle cx="{x(last_index):.1f}" cy="{y(last["forecast"]):.1f}" r="4.5" fill="#2474d2" class="point"/>')
            svg.append(f'<text x="{x(last_index)-6:.1f}" y="{y(last["forecast"])-9:.1f}" text-anchor="end" class="axis">{last["forecast"]:.2f}</text>')
    svg.append('</svg>')
    OUTPUT.write_text("\n".join(svg), encoding="utf-8")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
