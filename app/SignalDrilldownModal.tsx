"use client";

import { useEffect, useMemo, useState } from "react";
import type { DashboardData, Indicator, Signal } from "./types";

export interface SignalDrilldownSelection {
  date: string;
  historyIndex: number;
  categoryId?: string;
}

const signalMeta: Record<Signal, { label: string; className: string }> = {
  bullish: { label: "债市利多", className: "is-bullish" },
  bearish: { label: "债市利空", className: "is-bearish" },
  neutral: { label: "信号中性", className: "is-neutral" },
};

function signalForScore(score: number): Signal {
  const displayedScore = Math.round(score);
  if (displayedScore >= 15) return "bullish";
  if (displayedScore <= -15) return "bearish";
  return "neutral";
}

function scoreTone(score: number) {
  const signal = signalForScore(score);
  if (signal === "bullish") return "var(--bull)";
  if (signal === "bearish") return "var(--bear)";
  return "var(--neutral)";
}

function formatValue(value: number | null, unit: string) {
  if (value === null || !Number.isFinite(value)) return "—";
  const digits = Math.abs(value) >= 1000 ? 0 : Math.abs(value) >= 100 ? 1 : 2;
  const number = value.toLocaleString("zh-CN", { maximumFractionDigits: digits });
  return unit === "指数" || !unit ? number : `${number} ${unit}`;
}

function valueAtOrBefore(indicator: Indicator, date: string) {
  for (let index = indicator.series.length - 1; index >= 0; index -= 1) {
    if (indicator.series[index].date <= date) return indicator.series[index].value;
  }
  return null;
}

type SignalCounts = Record<Signal, number>;

function countSignals(indicators: Indicator[], historyIndex: number): SignalCounts {
  return indicators.reduce<SignalCounts>(
    (counts, indicator) => {
      counts[signalForScore(indicator.history[historyIndex] ?? 0)] += 1;
      return counts;
    },
    { bullish: 0, bearish: 0, neutral: 0 },
  );
}

export default function SignalDrilldownModal({
  data,
  selection,
  onClose,
  onOpenIndicator,
}: {
  data: DashboardData;
  selection: SignalDrilldownSelection;
  onClose: () => void;
  onOpenIndicator: (indicator: Indicator) => void;
}) {
  const [categoryId, setCategoryId] = useState(selection.categoryId ?? "");

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKey);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  const categories = useMemo(
    () =>
      data.categories.map((category) => {
        const score = category.weeklyScores[selection.historyIndex] ?? 0;
        const categoryIndicators = data.indicators.filter(
          (indicator) => indicator.category === category.id,
        );
        const core = categoryIndicators.filter((indicator) => indicator.core);
        const auxiliary = categoryIndicators.filter((indicator) => !indicator.core);
        return {
          category,
          score,
          signal: signalForScore(score),
          detail: {
            core: countSignals(core, selection.historyIndex),
            auxiliary: countSignals(auxiliary, selection.historyIndex),
          },
        };
      }),
    [data, selection.historyIndex],
  );

  const selectedCategory = data.categories.find((item) => item.id === categoryId);
  const indicators = useMemo(
    () =>
      data.indicators
        .filter((indicator) => indicator.category === categoryId)
        .map((indicator) => {
          const score = indicator.history[selection.historyIndex] ?? 0;
          return {
            indicator,
            score,
            signal: signalForScore(score),
            value: valueAtOrBefore(indicator, selection.date),
          };
        })
        .sort(
          (left, right) =>
            Number(right.indicator.core) - Number(left.indicator.core) ||
            Math.abs(right.score) - Math.abs(left.score),
        ),
    [categoryId, data.indicators, selection.date, selection.historyIndex],
  );

  const indicatorGroups = [
    {
      id: "core",
      label: "核心指标",
      description: "参与指标族与大类观点计算",
      items: indicators.filter(({ indicator }) => indicator.core),
    },
    {
      id: "auxiliary",
      label: "辅助指标",
      description: "用于交叉验证，不重复计入观点",
      items: indicators.filter(({ indicator }) => !indicator.core),
    },
  ].filter((group) => group.items.length > 0);

  const overallScore = data.overall.weeklyScores[selection.historyIndex] ?? 0;

  return (
    <div className="modal-backdrop drilldown-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="signal-drilldown-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${selection.date}宏观信号明细`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="drilldown-header">
          <div>
            <span className="eyebrow">历史截面 · {selection.date}</span>
            <h2>{selectedCategory?.name ?? "综合宏观观点"}</h2>
            <p>
              {selectedCategory
                ? "以下为该大类全部高频指标在当时的债市方向；点击指标名称查看完整历史走势。"
                : "先查看当时九大类的利多利空分布；点击任一大类继续下钻到高频指标。"}
            </p>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        {!selectedCategory ? (
          <div className="historical-category-grid">
            <div className="historical-overall-card">
              <span>综合信号</span>
              <strong style={{ color: scoreTone(overallScore) }}>
                {overallScore > 0 ? "+" : ""}{Math.round(overallScore)}
              </strong>
              <span className={`signal-badge ${signalMeta[signalForScore(overallScore)].className}`}>
                {signalMeta[signalForScore(overallScore)].label}
              </span>
            </div>
            {categories.map(({ category, score, signal, detail }) => (
              <button
                key={category.id}
                className="historical-category-card"
                onClick={() => setCategoryId(category.id)}
              >
                <span>{category.code}</span>
                <strong>{category.name}</strong>
                <b style={{ color: scoreTone(score) }}>
                  {score > 0 ? "+" : ""}{Math.round(score)}
                </b>
                <small className={signalMeta[signal].className}>
                  {signalMeta[signal].label}
                </small>
                <em className="historical-category-counts">
                  <span>
                    <i className="indicator-role-badge is-core">核心</i>
                    利多 {detail.core.bullish} · 利空 {detail.core.bearish} · 中性 {detail.core.neutral}
                  </span>
                  <span>
                    <i className="indicator-role-badge is-auxiliary">辅助</i>
                    利多 {detail.auxiliary.bullish} · 利空 {detail.auxiliary.bearish} · 中性 {detail.auxiliary.neutral}
                  </span>
                </em>
              </button>
            ))}
          </div>
        ) : (
          <>
            {!selection.categoryId && (
              <button className="drilldown-back" onClick={() => setCategoryId("")}>
                ← 返回九大类
              </button>
            )}
            <div className="historical-indicator-list">
              <div className="historical-indicator-columns" aria-hidden="true">
                <span>高频指标</span><span>当时值</span><span>强度</span><span>债市方向</span>
              </div>
              {indicatorGroups.map((group) => (
                <section className={`historical-indicator-group is-${group.id}`} key={group.id}>
                  <div className="historical-indicator-group-title">
                    <span className={`indicator-role-badge is-${group.id}`}>{group.label}</span>
                    <strong>{group.items.length}项</strong>
                    <small>{group.description}</small>
                  </div>
                  {group.items.map(({ indicator, score, signal, value }) => (
                    <div
                      className={`historical-indicator-row ${indicator.core ? "is-core" : "is-auxiliary"}`}
                      key={indicator.id}
                    >
                      <button onClick={() => onOpenIndicator(indicator)}>
                        <strong>{indicator.name}</strong>
                        <small>{indicator.family} · {indicator.frequency}</small>
                      </button>
                      <span>{formatValue(value, indicator.unit)}</span>
                      <b style={{ color: scoreTone(score) }}>
                        {score > 0 ? "+" : ""}{Math.round(score)}
                      </b>
                      <span className={`signal-badge ${signalMeta[signal].className}`}>
                        {signalMeta[signal].label}
                      </span>
                    </div>
                  ))}
                </section>
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
