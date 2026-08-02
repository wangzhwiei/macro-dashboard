#!/usr/bin/env python3
"""
CJHX 宏观指标原始时间序列提取脚本。

职责：
- 读取数据源优先级清单（recommended_source=CJHX）和合成指标底层数据清单（source=cjhx）
- 按 CJHX catalog 编码查询 cais_dc_macroeconomic_indicators 接口
- 输出符合 raw-data.schema.json 的 JSON 文件
- 不处理 iFinD EDB、不计算合成指标、不做任何数据转换

用法：
  python scripts/fetch_cjhx_raw.py --mode bootstrap   # 首次全量（800天）
  python scripts/fetch_cjhx_raw.py --mode incremental  # 每日增量（90天）
"""
import argparse
import json
import os
import re
import socket
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# ── DNS patch for CJHX ────────────────────────────────────────────────────
_ORIG_GETADDRINFO = socket.getaddrinfo
def _patched_getaddrinfo(host, port, family=0, type_=0, proto=0, flags=0):
    if host == "ai.cjhxfund.com":
        host = "10.202.9.103"
    return _ORIG_GETADDRINFO(host, port, family, type_, proto, flags)
socket.getaddrinfo = _patched_getaddrinfo

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT.parent / "media"
CJHX_SKILL = ROOT.parent / "skills" / "cjhx-cais-bis-skill" / "scripts"

# Input files
PRIORITY_CSV = MEDIA / "118c5390edf94c37b7a427981b090985_数据源优先级清单.csv"
COMPOSITE_CSV = MEDIA / "2126feff0b784977b48b1f665aa79d9c_合成指标底层数据清单.csv"
CATALOG_JSON = ROOT / "outputs" / "cjhx_code_catalog.json"

# ── Credentials ───────────────────────────────────────────────────────────

def load_cjhx_api_key() -> str:
    from cryptography.fernet import Fernet
    key_path = CJHX_SKILL / ".cred_key"
    enc_path = CJHX_SKILL / ".cred_encrypted"
    if not key_path.exists() or not enc_path.exists():
        raise RuntimeError("CJHX API key files not found")
    key = key_path.read_bytes()
    encrypted = enc_path.read_bytes()
    return Fernet(key).decrypt(encrypted).decode()

# ── CJHX API client ───────────────────────────────────────────────────────

BASE_URL = "https://ai.cjhxfund.com/ai-gateway"

def query_cjhx_macro(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """
    查询 CJHX 宏观经济指标（全量拉取，按日期范围）。
    API 不支持按编码筛选，返回所有指标所有日期的数据。
    返回：[{f1, f2, f3, f4, f5}, ...]
    """
    api_key = load_cjhx_api_key()
    
    payload = {
        "page": 1,
        "pageSize": 10000,
        "startDate": start_date,
        "endDate": end_date,
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Host": "ai.cjhxfund.com",
    }
    
    all_records = []
    page = 1
    max_pages = 10  # Safety limit
    while page <= max_pages:
        payload["page"] = page
        try:
            resp = requests.post(
                f"{BASE_URL}/admin/dataquery/execute/cais_dc_macroeconomic_indicators",
                headers=headers, json=payload, timeout=30, verify=False
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(f"API timeout on page {page}")
        
        resp.raise_for_status()
        data = resp.json()
        
        code = data.get("code")
        if code not in (0, 200, "0", "200"):
            msg = data.get("msg", data.get("message", "unknown"))
            raise RuntimeError(f"API error: code={code} msg={msg}")
        
        body = data.get("body", [])
        if not body:
            break
        all_records.extend(body)
        sys.stderr.write(f"  Page {page}: {len(body)} records (total {len(all_records)})\n")
        sys.stderr.flush()
        
        if len(body) < 10000:
            break
        page += 1
        time.sleep(0.2)
    
    return all_records


# ── Build series list ─────────────────────────────────────────────────────

def load_catalog() -> Dict[str, str]:
    """Load CJHX catalog: {code: name}"""
    with open(CATALOG_JSON) as f:
        cat = json.load(f)
    return {code: info.get("name", "") for code, info in cat.items()}


def build_series_list() -> List[Dict[str, Any]]:
    """
    构建需要提取的序列列表。
    来源：
    1. 数据源优先级清单（recommended_source=CJHX）
    2. 合成指标底层数据清单（source=cjhx）
    
    注意：优先级清单中的某些行（如 metro_composite）的底层数据已由合成清单提供。
    对于这类行，如果合成清单有对应的 CJHX 底层序列，则优先级清单中该行
    不再单独查询（因为它的 query_name 是展示名称，不是 CJHX 接口中的指标名）。
    """
    import csv
    
    series_list = []
    # Track composite raw_series_keys that cover priority list entries
    composite_keys = set()
    
    # 2. Composite list - cjhx rows (process first)
    with open(COMPOSITE_CSV, encoding="utf-8-sig") as f:
        composite_rows = [r for r in csv.DictReader(f) 
                         if r.get("source", "").strip() == "cjhx"]
    
    for row in composite_rows:
        s = {
            "seriesKey": row["raw_series_key"].strip(),
            "queryName": row["query_name"].strip(),
            "source_file": "composite",
        }
        series_list.append(s)
        composite_keys.add(row["raw_series_key"].strip())
    
    # 1. Priority list - CJHX rows
    with open(PRIORITY_CSV, encoding="utf-8-sig") as f:
        priority_rows = [r for r in csv.DictReader(f) 
                        if r.get("recommended_source", "").strip() == "CJHX"]
    
    # Map indicator_id -> composite raw_series_key to know which to skip
    # (composite entries that cover priority entries)
    # e.g., metro_composite is covered by metro_shanghai + metro_guangzhou
    
    # Build skip set: indicator_ids that are composites covered by composite list
    skip_ids = set()
    for row in composite_rows:
        pass  # Will determine based on manual mapping below
    
    for row in priority_rows:
        indicator_id = row["indicator_id"].strip()
        qname = row["indicator_name"].strip()
        
        # Skip if this is a composite indicator whose raw data is in composite list
        # These are indicators whose CJHX name doesn't match their display name
        # and whose raw data is already handled
        if indicator_id in ("metro_composite", "boxoffice_7d", "tire_composite", "steel_inventory"):
            # Check if the queryName matches a CJHX catalog name
            # If not, the raw data is handled by composite list
            # If the priority row's queryName IS a CJHX name, keep it
            # Otherwise, skip it (it's just a display label)
            if qname in ("重点城市地铁客流指数",):
                continue  # Covered by metro_shanghai + metro_guangzhou
            # For boxoffice_7d, tire_composite, steel_inventory - keep them
            # because they have CJHX codes in the priority list
        
        series_list.append({
            "seriesKey": indicator_id,
            "semantic_code": row["semantic_code"].strip(),
            "queryName": qname,
            "source_file": "priority",
        })
    
    return series_list


# ── Match series to CJHX codes ────────────────────────────────────────────

def match_series_to_codes(series_list: List[Dict], catalog: Dict[str, str]) -> None:
    """
    将序列匹配到 CJHX 编码。
    修改 series_list 中的每个元素，添加 provider_id, matched_name, candidates 字段。
    """
    # Build reverse index: lowercase name -> [(code, original_name), ...]
    name_index: Dict[str, List[tuple]] = {}
    for code, name in catalog.items():
        lower = name.lower()
        name_index.setdefault(lower, []).append((code, name))
    
    for s in series_list:
        qname = s["queryName"].strip()
        qname_lower = qname.lower()
        
        # 1. Exact match
        if qname_lower in name_index:
            matches = name_index[qname_lower]
            if len(matches) == 1:
                s["provider_id"] = matches[0][0]
                s["matched_name"] = matches[0][1]
                s["candidates"] = []
                continue
            else:
                # Multiple exact matches - pick first
                s["provider_id"] = matches[0][0]
                s["matched_name"] = matches[0][1]
                s["candidates"] = [m[1] for m in matches[1:]]
                continue
        
        # 2. Substring match (query name in catalog name)
        substring_matches = []
        for cat_name_lower, matches in name_index.items():
            if qname_lower in cat_name_lower or cat_name_lower in qname_lower:
                for m in matches:
                    if m[1] not in [cm for cm in substring_matches]:
                        substring_matches.append(m)
        
        if len(substring_matches) == 1:
            s["provider_id"] = substring_matches[0][0]
            s["matched_name"] = substring_matches[0][1]
            s["candidates"] = []
            continue
        
        # 3. Fuzzy: check if query name contains key parts of catalog name or vice versa
        import difflib
        best_score = 0
        best_match = None
        all_matches = []
        
        for code, name in catalog.items():
            score = difflib.SequenceMatcher(None, qname, name).ratio()
            if score > 0.5:
                all_matches.append((score, code, name))
            if score > best_score:
                best_score = score
                best_match = (code, name)
        
        if best_score > 0.8 and len(all_matches) == 1:
            s["provider_id"] = best_match[0]
            s["matched_name"] = best_match[1]
            s["candidates"] = []
        elif best_score > 0.5:
            # Too ambiguous - list candidates
            s["provider_id"] = None
            s["matched_name"] = None
            s["candidates"] = [f"{m[2]} ({m[0]:.0%}) [{m[1]}]" for m in sorted(all_matches, key=lambda x: -x[0])[:5]]
        else:
            s["provider_id"] = None
            s["matched_name"] = None
            s["candidates"] = []


# ── Known manual mapping (for indicators that fuzzy matching can't resolve) ──

MANUAL_MAPPING = {
    # seriesKey -> (provider_id, queryName)
    # FR007 IRS
    "irs_1y": ("M1004036", "FR007利率互换定盘曲线_均值:1年"),
    "irs_5y": ("M1004040", "FR007利率互换定盘曲线_均值:5年"),
    
    # SHIBOR
    "shibor_3m": ("M0017142", "SHIBOR:三个月"),
    "shibor_6m": ("M0017144", "SHIBOR:6个月"),
    "shibor_1y": ("M0017145", "SHIBOR:1年"),
    # Note: shibor_6m and shibor_1y may be iFinD in priority list, but if they appear as CJHX, map them here
    
    # FX
    "usdcny": ("M0000185", "中间价:美元兑人民币"),
    "usdjpy": ("M0000199", "美元兑日元"),
    "eurusd": ("M0000200", "欧元兑美元"),
    "dxy": ("M0000271", "美元指数"),
    
    # Commodities / prices
    "brent": ("S0031525", "期货结算价(连续):布伦特原油"),
    "wti": ("M0000005", "期货结算价(连续):WTI原油"),
    "bdi": ("S0031550", "波罗的海干散货指数(BDI)"),
    "bci": ("S0031552", "好望角型运费指数(BCI)"),
    "bpi": ("S0031551", "巴拿马型运费指数(BPI)"),
    "scfi": ("S0114089", "SCFI:综合指数"),
    "ccfi": ("S0000066", "CCFI:综合指数"),
    
    # Metals
    "gold_spot": ("S0031645", "伦敦现货黄金:以美元计价"),
    "silver_spot": ("S0031648", "伦敦现货白银:以美元计价"),
    "copper_price": ("S0182161", "中国:平均价:铜(1#)有色市场"),
    "aluminum_a00": ("S0182162", "中国:平均价:铝(A00):有色市场"),
    "nickel_1": ("S0048090", "中国:平均价:镍板(1#):有色市场"),
    "lme_zinc": ("S5914464", "中国:市场价:锌锭(0#)"),
    
    # Industrial
    "crude_steel": ("S5708246", "日均产量:粗钢:重点企业(旬)"),
    "crude_steel_daily_output": ("S5708246", "日均产量:粗钢:重点企业(旬)"),
    
    # Tires
    "tire_composite": ("S6124650", "开工率:汽车轮胎:全钢胎"),  # Will handle separately
    
    # Food prices
    "pork_price": ("S5065106", "平均批发价:猪肉"),
    "agri_200": ("S0248945", "农产品批发价格200指数"),
    "vegetable_28_price": ("S5065111", "平均批发价:28种重点监测蔬菜"),
    "fruit_7_price": ("S5065112", "平均批发价:7种重点监测水果"),
    "beef_price": ("S5065107", "平均批发价:牛肉"),
    "mutton_price": ("S5065108", "平均批发价:羊肉"),
    "egg_price": ("S5065109", "平均批发价:鸡蛋"),
    "chicken_price": ("S5065110", "平均批发价:白条鸡"),
    
    # Cement
    "cement_national": ("S5914515", "水泥价格指数:全国"),
    "cement_east": ("S5914519", "水泥价格指数:华东"),
    "cement_yangtze": ("S5914516", "水泥价格指数:长江"),
    
    # Glass
    "glass_spot": ("S5456780", "玻璃现货价"),
    
    # Real estate
    "land_4w": ("S2726992", "100大中城市:成交土地占地面积:当周值"),
    "newhome_30c": ("S2707380", "30大中城市:商品房成交面积"),
    "listing_price": ("S2772559", "城市二手房出售挂牌价指数:全国"),
    "listing_price_tier1": ("S2772570", "城市二手房出售挂牌价指数:一线城市"),
    "listing_price_tier2": ("S2772571", "城市二手房出售挂牌价指数:二线城市"),
    
    # Land sub-categories
    "land_tier1": ("S2727036", "100大中城市:成交土地占地面积:一线城市:当周值"),
    "land_tier2": ("S2727037", "100大中城市:成交土地占地面积:二线城市:当周值"),
    "land_tier3": ("S2727038", "100大中城市:成交土地占地面积:三线城市:当周值"),
    "land_premium": ("S2726996", "100大中城市:成交土地溢价率:当周值"),
    
    # New home sub-categories
    "newhome_tier1": ("S2707382", "30大中城市:商品房成交面积:一线城市"),
    "newhome_tier2": ("S2707384", "30大中城市:商品房成交面积:二线城市"),
    "newhome_tier3": ("S2707386", "30大中城市:商品房成交面积:三线城市"),
    
    # Car sales
    "car_retail_yoy": ("S6126414", "乘用车厂家零售当周同比"),
    "car_wholesale_yoy": ("S6126412", "乘用车厂家批发当周同比"),
    
    # Steel indices
    "steel_plate_index": ("S0066751", "中国:钢材价格指数:板材"),
    "steel_long_index": ("S0066750", "中国:钢材价格指数:长材"),
    
    # Lithium, titanium, rare earth
    "lithium_carbonate": ("S5811336", "中国:价格:碳酸锂(99.5%电,国产)"),
    "titanium_dioxide": ("S5470446", "中国:现货价:钛白粉(金红石型)"),
    "rare_earth_index": ("S6949588", "中国:价格指数:稀土"),
    
    # Futures
    "iron_ore_futures": ("M0330386", "收盘价:铁矿石指数"),
    "coke_futures": ("S0181380", "期货结算价(活跃合约):焦炭"),
    "coking_coal_futures": ("S0181379", "期货结算价(活跃合约):焦煤"),
    "thermal_coal_futures": ("S0182141", "期货结算价(活跃合约):动力煤"),
    
    # Other
    "nanhua_industry": ("S0105897", "南华工业品指数"),
    "filament_rate": ("S5446172", "开工率:涤纶长丝:江浙地区"),
    "qhd_coal_price": ("S5101377", "秦皇岛港:平仓价:动力末煤(Q5500,山西产)"),
    "iron_ore_62": ("S5705176", "中国北方:铁矿石价格指数(62%FeCFR)"),
    "rebar_price": ("S5707798", "价格:螺纹钢:HRB400 20mm:全国"),
    "hrc_spot": ("S5707804", "价格:热轧板卷:Q235B:4.75mm:全国"),
    
    # FR007 IRS 3M / 6M
    "irs_3m": ("M1004033", "FR007利率互换定盘曲线_均值:3个月"),
    "irs_6m": ("M1004124", "FR007利率互换收盘曲线_均值:6M"),
    
    # Unmatched items from priority list
    "metro_composite": None,  # Handled by composite mapping (metro_shanghai / metro_guangzhou)
    "boxoffice_7d": ("S6637039", "当日电影票房:全国"),
    "movie_audience": ("S6637041", "当日观影人次:全国"),
    "blast_furnace": None,     # CJHX catalog does not have 高炉开工率
    "steel_inventory": ("S0181750", "库存:螺纹钢(含上海全部仓库)"),
    "listing_tier1": ("S2772570", "城市二手房出售挂牌价指数:一线城市"),
    "listing_tier2": ("S2772571", "城市二手房出售挂牌价指数:二线城市"),
    "vegetable_price": ("S5065111", "平均批发价:28种重点监测蔬菜"),
    "fruit_price": ("S5065112", "平均批发价:7种重点监测水果"),
    "aluminum_price": ("S0182162", "中国:平均价:铝(A00):有色市场"),
    "nickel_price": ("S0048090", "中国:平均价:镍板(1#):有色市场"),
    "hot_rolled_price": ("S5707804", "价格:热轧板卷:Q235B:4.75mm:全国"),
    "lithium_price": ("S5811336", "中国:价格:碳酸锂(99.5%电,国产)"),
    "titanium_price": ("S5470446", "中国:现货价:钛白粉(金红石型)"),
}

# Composite raw series mappings
COMPOSITE_MANUAL_MAPPING = {
    "metro_shanghai": ("S6444538", "地铁客运量:上海"),
    "metro_guangzhou": ("S6444539", "地铁客运量:广州"),
    "box_office_daily": ("S6637039", "当日电影票房:全国"),
    "land_100_cities_weekly": ("S2726992", "100大中城市:成交土地占地面积:当周值"),
    "new_home_30_cities_daily": ("S2707380", "30大中城市:商品房成交面积"),
    "tire_semi_steel_rate": ("S6124651", "开工率:汽车轮胎:半钢胎"),
    "tire_all_steel_rate": ("S6124650", "开工率:汽车轮胎:全钢胎"),
    "rebar_inventory": ("S0181750", "库存:螺纹钢(含上海全部仓库)"),
}


def apply_manual_mappings(series_list: List[Dict]) -> None:
    """Apply manual mappings for indicators that fuzzy matching can't resolve."""
    for s in series_list:
        key = s["seriesKey"]
        
        # Check composite mapping first
        if key in COMPOSITE_MANUAL_MAPPING:
            code, name = COMPOSITE_MANUAL_MAPPING[key]
            s["provider_id"] = code
            s["matched_name"] = name
            s["candidates"] = []
            continue
        
        # Check priority mapping
        if key in MANUAL_MAPPING:
            val = MANUAL_MAPPING[key]
            if val is None:
                # Explicitly marked as unavailable in CJHX
                s["provider_id"] = None
                s["matched_name"] = None
                s["candidates"] = ["CJHX catalog 中不存在此指标"]
            else:
                code, name = val
                s["provider_id"] = code
                s["matched_name"] = name
                s["candidates"] = []
            continue
        
        # Also try matching by semantic_code
        sc = s.get("semantic_code", "")
        # Map semantic_code to seriesKey for lookup
        sc_key_map = {}
        for row_key, (code, name) in MANUAL_MAPPING.items():
            sc_key_map[row_key] = (code, name)


# ── Main extraction ───────────────────────────────────────────────────────

def extract(mode: str = "bootstrap"):
    today = date.today()
    
    if mode == "bootstrap":
        start = today - timedelta(days=180)  # API caps at ~100k records; 180 days ensures full coverage
    else:
        start = today - timedelta(days=90)
    
    start_str = start.strftime("%Y%m%d")
    end_str = today.strftime("%Y%m%d")
    
    print(f"Date range: {start.strftime('%Y-%m-%d')} to {end_str}")
    print(f"Mode: {mode}")
    
    # Load series list
    series_list = build_series_list()
    print(f"Total series to extract: {len(series_list)}")
    
    # Load catalog
    catalog = load_catalog()
    print(f"CJHX catalog entries: {len(catalog)}")
    
    # Match series to codes
    match_series_to_codes(series_list, catalog)
    
    # Apply manual mappings (override fuzzy matches)
    apply_manual_mappings(series_list)
    
    # Remove duplicate seriesKeys (keep first occurrence)
    seen_keys = set()
    unique_series = []
    for s in series_list:
        if s["seriesKey"] not in seen_keys:
            seen_keys.add(s["seriesKey"])
            unique_series.append(s)
    series_list = unique_series
    
    # Print matching status
    matched = sum(1 for s in series_list if s.get("provider_id"))
    unmatched = sum(1 for s in series_list if not s.get("provider_id"))
    
    print(f"\nAfter dedup: {len(series_list)} series")
    print(f"  Matched: {matched}")
    print(f"  Unmatched: {unmatched}")
    
    # ── Query API (single call for all data) ───────────────────────────
    sys.stderr.write("\nQuerying CJHX API (all indicators, single call)...\n")
    sys.stderr.flush()
    
    all_records = []
    error_codes = set()
    
    try:
        all_records = query_cjhx_macro(start_str, end_str)
        sys.stderr.write(f"Total records fetched: {len(all_records)}\n")
    except Exception as e:
        sys.stderr.write(f"API query failed: {e}\n")
        # Mark all series as error
        for s in series_list:
            if s.get("provider_id"):
                s["api_error"] = str(e)
                error_codes.add(s["provider_id"])
    
    sys.stderr.flush()
    
    # Parse records into series
    sys.stderr.write("Building output...\n")
    sys.stderr.flush()
    
    # Group records by provider code (f3)
    records_by_code: Dict[str, List[Dict]] = {}
    for r in all_records:
        r_code = r.get("f3")
        if r_code:
            records_by_code.setdefault(r_code, []).append(r)
    
    output_series = []
    
    # Group series by provider_id for processing
    by_code: Dict[str, List[Dict]] = {}
    for s in series_list:
        if s.get("provider_id") and s["provider_id"] not in error_codes:
            by_code.setdefault(s["provider_id"], []).append(s)
    
    # Process successful queries
    for code, series_group in by_code.items():
        code_records = records_by_code.get(code, [])
        
        for s in series_group:
            obs = []
            for r in code_records:
                date_str = str(r.get("f2", ""))
                value = r.get("f5")
                
                if not date_str or value is None or value == "" or value == "-":
                    continue
                
                try:
                    if len(date_str) == 8 and date_str.isdigit():
                        d = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
                    elif "-" in date_str:
                        d = date.fromisoformat(date_str[:10])
                    else:
                        continue
                    
                    val = float(value)
                    obs.append({"date": d.isoformat(), "value": val})
                except (ValueError, TypeError):
                    continue
            
            # Sort by date, deduplicate (keep last)
            obs.sort(key=lambda x: x["date"])
            seen_dates = set()
            deduped = []
            for o in reversed(obs):
                if o["date"] not in seen_dates:
                    seen_dates.add(o["date"])
                    deduped.append(o)
            deduped.reverse()
            
            freq = infer_frequency(deduped)
            
            output_series.append({
                "seriesKey": s["seriesKey"],
                "source": "cjhx",
                "queryName": s.get("matched_name") or s["queryName"],
                "providerId": code,
                "providerFrequency": freq,
                "providerUnit": "",
                "timezone": "Asia/Shanghai",
                "status": "ok" if deduped else "empty",
                "observations": deduped,
                "error": None,
            })
    
    # Process error series (no code or API failed)
    for s in series_list:
        if s.get("provider_id") and s["provider_id"] not in error_codes:
            continue  # Already processed
        if s.get("provider_id") and s["provider_id"] in error_codes:
            error_msg = s.get("api_error", "API query failed")
        else:
            candidates = s.get("candidates", [])
            error_msg = candidates[0] if candidates else "No CJHX code available"
        
        output_series.append({
            "seriesKey": s["seriesKey"],
            "source": "cjhx",
            "queryName": s["queryName"],
            "providerId": None,
            "providerFrequency": None,
            "providerUnit": None,
            "timezone": "Asia/Shanghai",
            "status": "error",
            "observations": [],
            "error": str(error_msg),
        })
    
    # ── Write output ───────────────────────────────────────────────────
    out_dir = ROOT / "data" / "incoming"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    batch_date = today.isoformat()
    output = {
        "schemaVersion": "1.0.0",
        "manifestVersion": "1.0.0",
        "batchDate": batch_date,
        "generatedAt": today.isoformat() + "T00:00:00+08:00",
        "producer": "fetch_cjhx_raw.py",
        "mode": mode,
        "window": {
            "start": start.isoformat(),
            "end": today.isoformat(),
        },
        "complete": len(output_series) == len(series_list),
        "series": output_series,
        "errors": [],
    }
    
    out_path = out_dir / f"cjhx-{batch_date}.json"
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nOutput saved: {out_path}")
    
    # ── Summary report ─────────────────────────────────────────────────
    ok_count = sum(1 for s in output_series if s["status"] == "ok")
    empty_count = sum(1 for s in output_series if s["status"] == "empty")
    error_count = sum(1 for s in output_series if s["status"] == "error")
    
    print(f"\n{'='*60}")
    print(f"EXTRACTION SUMMARY")
    print(f"{'='*60}")
    print(f"Total series: {len(output_series)}")
    print(f"  OK:     {ok_count}")
    print(f"  Empty:  {empty_count}")
    print(f"  Error:  {error_count}")
    print(f"{'='*60}")
    
    # Print per-series details
    for s in output_series:
        latest = s["observations"][-1]["date"] if s["observations"] else "N/A"
        count = len(s["observations"])
        status_icon = "✓" if s["status"] == "ok" else ("⚠" if s["status"] == "empty" else "✗")
        print(f"  {status_icon} {s['seriesKey']:30s} | {s['providerId'] or 'NONE':12s} | {count:5d} obs | latest={latest} | freq={s['providerFrequency'] or 'N/A'}")
    
    # Print errors
    if error_count:
        print(f"\n{'='*60}")
        print("ERROR DETAILS")
        print(f"{'='*60}")
        for s in output_series:
            if s["status"] == "error":
                print(f"  {s['seriesKey']:30s} | {s['error']}")


def infer_frequency(observations: List[Dict]) -> Optional[str]:
    """Infer data frequency from observation dates."""
    if len(observations) < 2:
        return None
    
    dates = sorted([date.fromisoformat(o["date"]) for o in observations])
    gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
    avg_gap = sum(gaps) / len(gaps)
    
    if avg_gap <= 2:
        return "D"
    elif avg_gap <= 10:
        return "W"
    elif avg_gap <= 45:
        return "M"
    else:
        return "Q"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["bootstrap", "incremental"], default="bootstrap")
    args = parser.parse_args()
    extract(args.mode)
