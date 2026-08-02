#!/usr/bin/env python3
"""Generate static HTML dashboard from dashboard.json data."""

import json
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "public" / "data" / "dashboard.json"
OUTPUT_DIR = ROOT / "docs"


def generate_html() -> str:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    
    categories = data.get("categories", [])
    indicators = data.get("indicators", [])
    
    # Group indicators by category
    by_category = {}
    for ind in indicators:
        cat_id = ind.get("category", "")
        by_category.setdefault(cat_id, []).append(ind)
    
    # Build category cards HTML
    category_cards = []
    for cat in categories:
        cat_id = cat["id"]
        cat_name = cat["name"]
        cat_code = cat.get("code", "")
        cat_signal = cat.get("signal", "neutral")
        cat_score = cat.get("score", 0)
        cat_bullish = cat.get("bullishCount", 0)
        cat_bearish = cat.get("bearishCount", 0)
        cat_neutral = cat.get("neutralCount", 0)
        
        sig_label = {"bullish": "债市利多", "bearish": "债市利空", "neutral": "信号中性"}
        sig_color = {"bullish": "#d54b48", "bearish": "#008f66", "neutral": "#6f787e"}
        
        sig_text = sig_label.get(cat_signal, "信号中性")
        sig_color_val = sig_color.get(cat_signal, "#6f787e")
        
        # Get family groups
        families = {}
        for ind in by_category.get(cat_id, []):
            fam = ind.get("family", "")
            families.setdefault(fam, []).append(ind)
        
        families_html = ""
        for fam_name, fam_inds in families.items():
            fam_rows = ""
            for ind in fam_inds:
                ind_signal = ind.get("signal", "neutral")
                ind_score = ind.get("score", 0)
                ind_name = ind.get("name", "")
                ind_latest = ind.get("latest", 0)
                ind_change = ind.get("change", 0)
                ind_unit = ind.get("unit", "")
                ind_freq = ind.get("frequency", "")
                ind_pctile = ind.get("percentile", 50)
                ind_fresh = ind.get("fresh", True)
                ind_hist = ind.get("history", [])
                
                # Score color
                if ind_score >= 15:
                    score_color = "#d54b48"
                elif ind_score <= -15:
                    score_color = "#008f66"
                else:
                    score_color = "#6f787e"
                
                # Change sign
                change_sign = "+" if ind_change >= 0 else ""
                change_color = "#d54b48" if ind_change > 0 else ("#008f66" if ind_change < 0 else "#6f787e")
                
                # Freshness
                fresh_badge = "" if ind_fresh else '<span class="stale-badge">滞后</span>'
                
                # Mini trend bars (last 13 weeks)
                trend_bars = ""
                if ind_hist:
                    for val in ind_hist[-13:]:
                        abs_val = abs(val)
                        h = max(4, min(40, abs_val * 0.4))
                        if val >= 15:
                            c = "#d54b48"
                        elif val <= -15:
                            c = "#008f66"
                        else:
                            c = "#6f787e44"
                        trend_bars += f'<span class="trend-bar" style="height:{h}px;background:{c}"></span>'
                
                fam_rows += f"""
                <tr class="indicator-row" data-indicator="{ind['id']}">
                    <td>
                        <div class="ind-name">{ind_name}</div>
                        <div class="ind-meta">{ind_freq} · {ind_unit} · P{ind_pctile:.0f}</div>
                    </td>
                    <td class="ind-latest">{ind_latest:,.2f}</td>
                    <td class="ind-change" style="color:{change_color}">{change_sign}{ind_change:,.2f}</td>
                    <td class="ind-score" style="color:{score_color};font-weight:600">{ind_score:+.1f}</td>
                    <td class="ind-trend">{trend_bars}</td>
                    <td>{fresh_badge}</td>
                </tr>"""
            
            families_html += f"""
            <details class="family-group open-by-default">
                <summary class="family-header">
                    <span class="family-name">{fam_name}</span>
                    <span class="family-count">({len(fam_inds)})</span>
                </summary>
                <table class="indicator-table">
                    <thead>
                        <tr>
                            <th>指标</th>
                            <th>最新值</th>
                            <th>周变化</th>
                            <th>信号</th>
                            <th>趋势</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>{fam_rows}</tbody>
                </table>
            </details>"""
        
        category_cards.append(f"""
        <div class="category-card" id="cat-{cat_id}">
            <div class="category-header">
                <div class="cat-title">
                    <span class="cat-code">{cat_code}</span>
                    <span class="cat-name">{cat_name}</span>
                </div>
                <div class="cat-signal" style="background:{sig_color_val}22;color:{sig_color_val}">
                    {sig_text}
                </div>
            </div>
            <div class="cat-stats">
                <span class="stat bullish" title="利多">{cat_bullish}</span>
                <span class="stat neutral" title="中性">{cat_neutral}</span>
                <span class="stat bearish" title="利空">{cat_bearish}</span>
                <span class="stat score" title="综合得分">{cat_score:+.1f}</span>
            </div>
            <div class="cat-body">{families_html}</div>
        </div>""")
    
    # Composite score
    composite = data.get("composite", {})
    composite_score = composite.get("score", 0)
    composite_signal = composite.get("signal", "neutral")
    composite_updated = composite.get("updatedAt", "")
    
    comp_sig_text = {"bullish": "债市利多", "bearish": "债市利空", "neutral": "信号中性"}.get(composite_signal, "中性")
    comp_sig_color = {"bullish": "#d54b48", "bearish": "#008f66", "neutral": "#6f787e"}.get(composite_signal, "#6f787e")
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>创金固收投资部 · 宏观脉搏观测面板</title>
    <style>
        :root {{
            --bull: #d54b48;
            --bear: #008f66;
            --neutral: #6f787e;
            --bg: #0a0e17;
            --card-bg: #111827;
            --border: #1f2937;
            --text: #e5e7eb;
            --text-dim: #9ca3af;
            --text-muted: #6b7280;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            padding: 20px;
        }}
        .header {{
            text-align: center;
            padding: 30px 20px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
        }}
        .header h1 {{
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
        }}
        .header .subtitle {{
            color: var(--text-dim);
            font-size: 14px;
        }}
        .composite-banner {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px 32px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }}
        .composite-banner .left h2 {{
            font-size: 16px;
            color: var(--text-dim);
            margin-bottom: 4px;
        }}
        .composite-banner .score-display {{
            font-size: 48px;
            font-weight: 700;
            color: {comp_sig_color};
        }}
        .composite-banner .signal-badge {{
            display: inline-block;
            padding: 6px 16px;
            border-radius: 20px;
            background: {comp_sig_color}22;
            color: {comp_sig_color};
            font-weight: 600;
            font-size: 14px;
        }}
        .composite-banner .right {{
            text-align: right;
        }}
        .composite-banner .right .updated {{
            color: var(--text-muted);
            font-size: 12px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
            gap: 16px;
        }}
        @media (max-width: 600px) {{
            .grid {{ grid-template-columns: 1fr; }}
        }}
        .category-card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
        }}
        .category-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid var(--border);
        }}
        .cat-title {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .cat-code {{
            background: var(--border);
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-dim);
        }}
        .cat-name {{
            font-size: 16px;
            font-weight: 600;
        }}
        .cat-signal {{
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .cat-stats {{
            display: flex;
            gap: 12px;
            padding: 10px 20px;
            border-bottom: 1px solid var(--border);
        }}
        .stat {{
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 12px;
            font-weight: 600;
        }}
        .stat.bullish {{ background: var(--bull)22; color: var(--bull); }}
        .stat.bearish {{ background: var(--bear)22; color: var(--bear); }}
        .stat.neutral {{ background: var(--neutral)22; color: var(--neutral); }}
        .stat.score {{ background: #374151; color: var(--text); }}
        .cat-body {{ padding: 4px 0; }}
        .family-group {{ border-bottom: 1px solid var(--border); }}
        .family-group:last-child {{ border-bottom: none; }}
        .family-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 20px;
            cursor: pointer;
            list-style: none;
            user-select: none;
        }}
        .family-header::-webkit-details-marker {{ display: none; }}
        .family-name {{ font-size: 13px; font-weight: 600; color: var(--text-dim); }}
        .family-count {{ font-size: 11px; color: var(--text-muted); }}
        .indicator-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }}
        .indicator-table th {{
            text-align: left;
            padding: 6px 20px 6px 20px;
            color: var(--text-muted);
            font-weight: 500;
            font-size: 11px;
            border-bottom: 1px solid var(--border);
        }}
        .indicator-table td {{
            padding: 8px 20px;
            border-bottom: none;
            vertical-align: middle;
        }}
        .indicator-row:hover {{ background: rgba(255,255,255,0.02); }}
        .ind-name {{ font-weight: 500; font-size: 13px; }}
        .ind-meta {{ font-size: 11px; color: var(--text-muted); }}
        .ind-latest {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
        .ind-change {{ font-variant-numeric: tabular-nums; font-size: 12px; }}
        .ind-score {{ font-variant-numeric: tabular-nums; }}
        .ind-trend {{
            display: flex;
            align-items: flex-end;
            gap: 1px;
            height: 40px;
        }}
        .trend-bar {{
            display: inline-block;
            width: 3px;
            border-radius: 1px;
            min-height: 4px;
        }}
        .stale-badge {{
            display: inline-block;
            padding: 1px 6px;
            border-radius: 4px;
            background: #f59e0b22;
            color: #f59e0b;
            font-size: 10px;
        }}
        .open-by-default {{ open: open; }}
        footer {{
            text-align: center;
            padding: 24px;
            color: var(--text-muted);
            font-size: 12px;
            border-top: 1px solid var(--border);
            margin-top: 24px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 创金固收投资部 · 宏观脉搏观测面板</h1>
        <p class="subtitle">中国宏观高频指标观测 · 去重评分 · 债市信号研究</p>
    </div>
    
    <div class="composite-banner">
        <div class="left">
            <h2>综合宏观观点</h2>
            <div class="score-display">{composite_score:+.1f}</div>
        </div>
        <div class="right">
            <div class="signal-badge">{comp_sig_text}</div>
            <div class="updated">数据更新: {composite_updated} · {len(indicators)} 个指标 · {len(categories)} 大类 · {len(data.get("dates", []))} 周历史</div>
        </div>
    </div>
    
    <div class="grid">
        {''.join(category_cards)}
    </div>
    
    <footer>
        <p>数据源: 创金合信内部数据 / iFinD · 更新时间: {composite_updated} · 宏观脉搏 v1.0</p>
    </footer>
</body>
</html>"""
    return html


def main():
    html = generate_html()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "index.html"
    output_file.write_text(html, encoding="utf-8")
    print(f"已生成静态页面: {output_file} ({len(html):,} 字节)")
    print(f"浏览器打开: file://{output_file.resolve()}")


if __name__ == "__main__":
    main()
