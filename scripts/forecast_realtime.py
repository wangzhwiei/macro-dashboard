"""Fixed-parameter intramonth CPI/PPI nowcasts using only data available by each day."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

SPRING = {
    2010: 2, 2011: 2, 2012: 1, 2013: 2, 2014: 1, 2015: 2,
    2016: 2, 2017: 1, 2018: 2, 2019: 2, 2020: 1, 2021: 2,
    2022: 2, 2023: 1, 2024: 2, 2025: 1, 2026: 2,
}


def records(payload: Any) -> list[list[Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    if isinstance(payload, dict) and isinstance(payload.get("series"), list):
        return payload["series"]
    return payload if isinstance(payload, list) else []


def series(payload: Any) -> pd.Series:
    rows = records(payload)
    if not rows:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(rows, columns=["date", "value"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.dropna().drop_duplicates("date", keep="last").set_index("date")["value"].sort_index()


def monthly(payload: Any, how: str = "last") -> pd.Series:
    values = series(payload)
    grouped = values.resample("ME")
    return (grouped.mean() if how == "mean" else grouped.last()).dropna()


def spring_dummy(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series([float(SPRING.get(day.year) == day.month) for day in index], index=index)


def exact_yoy(previous_yoy: float, current_mom: float, year_ago_mom: float) -> float:
    return ((1 + previous_yoy / 100) * (1 + current_mom / 100) / (1 + year_ago_mom / 100) - 1) * 100


def fit_fixed(target: pd.Series, exog: pd.DataFrame, target_month: pd.Timestamp,
              order: tuple[int, int, int], seasonal: tuple[int, int, int, int]):
    training = target[target.index < target_month].dropna()
    x_training = exog.reindex(training.index)
    valid = x_training.notna().all(axis=1)
    training, x_training = training.loc[valid], x_training.loc[valid]
    fitted = SARIMAX(
        training, exog=x_training, order=order, seasonal_order=seasonal,
        enforce_stationarity=False, enforce_invertibility=False,
    ).fit(disp=False, maxiter=500)
    return fitted, x_training.mean()


def forecast_one(fitted: Any, means: pd.Series, row: dict[str, float]) -> float:
    frame = pd.DataFrame([row], columns=means.index).fillna(means)
    return float(fitted.forecast(1, exog=frame).iloc[0])


def month_mean_to(values: pd.Series, month: pd.Timestamp, cutoff: pd.Timestamp) -> float:
    selected = values[(values.index.to_period("M") == month.to_period("M")) & (values.index <= cutoff)]
    if selected.empty:
        raise RuntimeError(f"{month:%Y-%m} 在 {cutoff:%Y-%m-%d} 前无可用高频数据")
    return float(selected.mean())


def month_last_to(values: pd.Series, month: pd.Timestamp, cutoff: pd.Timestamp) -> float:
    selected = values[(values.index.to_period("M") == month.to_period("M")) & (values.index <= cutoff)]
    if selected.empty:
        raise RuntimeError(f"{month:%Y-%m} 在 {cutoff:%Y-%m-%d} 前无可用高频数据")
    return float(selected.iloc[-1])


def points(values: list[tuple[pd.Timestamp, float]]) -> list[dict[str, Any]]:
    return [{"date": day.date().isoformat(), "value": round(float(value), 6)} for day, value in values]


def build_daily_nowcasts(source: dict[str, Any], live: dict[str, Any], locked: dict[str, Any],
                         target_month: pd.Timestamp) -> dict[str, list[dict[str, Any]]]:
    dashboard = {key: series(value) for key, value in live["dashboard"].items()}
    crb_daily = series(live["ifindCrb"])
    previous = target_month - pd.offsets.MonthEnd(1)
    cutoffs = sorted({day for values in [*dashboard.values(), crb_daily] for day in values.index
                      if day.to_period("M") == target_month.to_period("M")})
    if not cutoffs or cutoffs[-1] < target_month:
        raise RuntimeError(f"实时输入未覆盖目标月末：{target_month.date()}")

    # CPI: fit the locked component models once with information available through June.
    cpi, targets = source["cpi"], source["targets"]
    cpi_index = pd.date_range("2010-01-31", target_month, freq="ME")
    food, nonfood = monthly(cpi["cpi_food_mom"]).reindex(cpi_index), monthly(cpi["cpi_nonfood_mom"]).reindex(cpi_index)
    total_mom, cpi_yoy = monthly(cpi["cpi_mom_total"]).reindex(cpi_index), monthly(targets["cpi"]).reindex(cpi_index)
    food.loc[previous], nonfood.loc[previous], total_mom.loc[previous], cpi_yoy.loc[previous] = -.4, -.3, -.3, 1.0
    food_weight = (monthly(cpi["food_weight"]) / 100).reindex(cpi_index)
    veg_local, pork_local = monthly(cpi["veg"], "mean"), monthly(cpi["pork"], "last")
    crb_local, pmi_local = monthly(cpi["crb"], "mean"), monthly(cpi["pmi"], "last")
    for day, value in crb_daily.resample("ME").mean().items():
        crb_local.loc[day] = value
    cpi_inputs = {"veg": veg_local.reindex(cpi_index), "pork": pork_local.reindex(cpi_index),
                  "crb": crb_local.reindex(cpi_index), "pmi": pmi_local.reindex(cpi_index)}
    food_exog = pd.DataFrame({"spring": spring_dummy(cpi_index), "veg_dL0": cpi_inputs["veg"].diff(),
                              "pork_dL0": cpi_inputs["pork"].diff()}, index=cpi_index)
    nonfood_exog = pd.DataFrame({"spring": spring_dummy(cpi_index), "crb_dL0": cpi_inputs["crb"].diff(),
                                 "pmi_L1": cpi_inputs["pmi"].shift(1)}, index=cpi_index)
    food_fit, food_means = fit_fixed(food, food_exog, target_month, (2, 1, 0), (1, 0, 1, 12))
    nonfood_fit, nonfood_means = fit_fixed(nonfood, nonfood_exog, target_month, (1, 0, 1), (1, 1, 1, 12))
    weight = float((monthly(cpi["food_weight"]) / 100).rolling(12, min_periods=6).mean().shift(1).dropna().iloc[-1])
    dash_prev_mean = {key: month_mean_to(values, previous, previous) for key, values in dashboard.items()}
    dash_prev_last = month_last_to(dashboard["pork_price"], previous, previous)
    cpi_mom_path: list[tuple[pd.Timestamp, float]] = []
    cpi_yoy_path: list[tuple[pd.Timestamp, float]] = []
    for cutoff in cutoffs:
        veg_target = float(veg_local.loc[previous]) + month_mean_to(dashboard["vegetable_price"], target_month, cutoff) - dash_prev_mean["vegetable_price"]
        pork_target = float(pork_local.loc[previous]) + month_last_to(dashboard["pork_price"], target_month, cutoff) - dash_prev_last
        crb_target = month_mean_to(crb_daily, target_month, cutoff)
        food_value = forecast_one(food_fit, food_means, {
            "spring": float(SPRING.get(target_month.year) == target_month.month),
            "veg_dL0": veg_target - float(veg_local.loc[previous]),
            "pork_dL0": pork_target - float(pork_local.loc[previous]),
        })
        nonfood_value = forecast_one(nonfood_fit, nonfood_means, {
            "spring": float(SPRING.get(target_month.year) == target_month.month),
            "crb_dL0": crb_target - float(crb_local.loc[previous]),
            "pmi_L1": float(pmi_local.loc[previous]),
        })
        mom_value = food_value * weight + nonfood_value * (1 - weight)
        yoy_value = exact_yoy(float(cpi_yoy.loc[previous]), mom_value,
                              float(total_mom.loc[(target_month - pd.DateOffset(months=12)) + pd.offsets.MonthEnd(0)]))
        cpi_mom_path.append((cutoff, mom_value)); cpi_yoy_path.append((cutoff, yoy_value))

    # PPI: dashboard levels are used only for their MTD return, preserving each locked local series' scale.
    raw = source["raw"]
    ppi_index = pd.date_range("2020-01-31", target_month, freq="ME")
    ppi_mom, ppi_yoy = monthly(targets["ppi_mom"]).reindex(ppi_index), monthly(targets["ppi"]).reindex(ppi_index)
    ppi_mom.loc[previous], ppi_yoy.loc[previous] = -.3, 4.1
    mapping = {
        "nh": ("南华工业品指数", "nanhua_industry"),
        "oil": ("现货价:原油:英国布伦特Dtd", "brent"),
        "coal": ("动力煤价格", "qhd_coal_price"),
        "rebar": ("螺纹钢", "rebar_price"),
        "cu": ("铜价", "copper_price"),
    }
    local = {key: monthly(raw[name], "mean") for key, (name, _) in mapping.items()}
    crb_ppi = monthly(raw["CRB现货指数:综合"], "mean")
    for day, value in crb_daily.resample("ME").mean().items():
        crb_ppi.loc[day] = value
    history_levels = {key: values.reindex(ppi_index) for key, values in local.items()}
    history_levels["crb"] = crb_ppi.reindex(ppi_index)
    changes = {key: values.pct_change(fill_method=None) * 100 for key, values in history_levels.items()}
    ppi_exog = pd.DataFrame({"nh_pct": changes["nh"], "nh_pctL1": changes["nh"].shift(1),
                             "oil_pct": changes["oil"], "coal_pct": changes["coal"],
                             "rebar_pct": changes["rebar"], "cu_pct": changes["cu"],
                             "crb_pct": changes["crb"]}, index=ppi_index)
    ppi_fit, ppi_means = fit_fixed(ppi_mom, ppi_exog, target_month, (1, 0, 1), (1, 0, 0, 12))
    ppi_mom_path: list[tuple[pd.Timestamp, float]] = []
    ppi_yoy_path: list[tuple[pd.Timestamp, float]] = []
    for cutoff in cutoffs:
        current_changes = {}
        for key, (_, dashboard_id) in mapping.items():
            ratio = month_mean_to(dashboard[dashboard_id], target_month, cutoff) / dash_prev_mean[dashboard_id]
            current_changes[key] = (ratio - 1) * 100
        current_changes["crb"] = (month_mean_to(crb_daily, target_month, cutoff) / float(crb_ppi.loc[previous]) - 1) * 100
        mom_value = forecast_one(ppi_fit, ppi_means, {
            "nh_pct": current_changes["nh"], "nh_pctL1": float(changes["nh"].loc[previous]),
            "oil_pct": current_changes["oil"], "coal_pct": current_changes["coal"],
            "rebar_pct": current_changes["rebar"], "cu_pct": current_changes["cu"],
            "crb_pct": current_changes["crb"],
        })
        yoy_value = exact_yoy(float(ppi_yoy.loc[previous]), mom_value,
                              float(ppi_mom.loc[(target_month - pd.DateOffset(months=12)) + pd.offsets.MonthEnd(0)]))
        ppi_mom_path.append((cutoff, mom_value)); ppi_yoy_path.append((cutoff, yoy_value))

    output = {"cpi": points(cpi_yoy_path), "cpi_mom": points(cpi_mom_path),
              "ppi": points(ppi_yoy_path), "ppi_mom": points(ppi_mom_path)}
    expected = {"cpi": locked["cpi"]["forecast"], "cpi_mom": locked["cpi"]["momForecast"],
                "ppi": locked["ppi"]["forecast"], "ppi_mom": locked["ppi"]["momForecast"]}
    for key, value in expected.items():
        if abs(output[key][-1]["value"] - float(value)) > 1e-5:
            raise RuntimeError(f"{key} 月末实时值未收敛至锁定月频预测：{output[key][-1]['value']} vs {value}")
    return output
