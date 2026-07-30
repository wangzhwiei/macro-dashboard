"use client";

import { useEffect, useMemo, useState } from "react";
import type {
  CategorySummary,
  DashboardData,
  Indicator,
  Signal,
} from "./types";

const signalMeta: Record<
  Signal,
  { label: string; short: string; className: string }
> = {
  bullish: { label: "债市利多", short: "利多", className: "is-bullish" },
  bearish: { label: "债市利空", short: "利空", className: "is-bearish" },
  neutral: { label: "信号中性", short: "中性", className: "is-neutral" },
};

function formatNumber(value: number, unit: string) {
  if (!Number.isFinite(value)) return "—";
  const absolute = Math.abs(value);
  const digits = absolute >= 1000 ? 0 : absolute >= 100 ? 1 : 2;
  return `${value.toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })}${unit === "指数" || unit === "z" ? "" : unit}`;
}

function scoreTone(score: number) {
  if (score >= 15) return "var(--bull)";
  if (score <= -15) return "var(--bear)";
  return "var(--neutral)";
}

function heatColor(score: number) {
  const strength = Math.min(1, Math.abs(score) / 100);
  if (score >= 15) return `rgba(0, 143, 102, ${0.16 + strength * 0.76})`;
  if (score <= -15) return `rgba(213, 75, 72, ${0.16 + strength * 0.76})`;
  return "rgba(111, 120, 126, .12)";
}

function SignalBadge({ signal }: { signal: Signal }) {
  const meta = signalMeta[signal];
  return <span className={`signal-badge ${meta.className}`}>{meta.label}</span>;
}

function MiniTrend({ values }: { values: number[] }) {
  const max = Math.max(...values.map((value) => Math.abs(value)), 1);
  return (
    <div className="mini-trend" aria-label="最近13周信号趋势">
      {values.slice(-13).map((value, index) => (
        <span
          key={index}
          style={{
            height: `${Math.max(12, (Math.abs(value) / max) * 100)}%`,
            background: scoreTone(value),
          }}
        />
      ))}
    </div>
  );
}

function CategoryCard({
  category,
  active,
  onSelect,
}: {
  category: CategorySummary;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      className={`category-card ${active ? "is-active" : ""}`}
      onClick={onSelect}
      aria-pressed={active}
    >
      <div className="category-card-top">
        <span className="category-code">{category.code}</span>
        <span className={`score-dot ${signalMeta[category.signal].className}`} />
      </div>
      <strong>{category.name}</strong>
      <div className="category-score">
        <span style={{ color: scoreTone(category.score) }}>
          {category.score > 0 ? "+" : ""}
          {Math.round(category.score)}
        </span>
        <small>{signalMeta[category.signal].short}</small>
      </div>
      <MiniTrend values={category.weeklyScores} />
      <div className="category-foot">
        <span>扩散度 {category.breadth}%</span>
        <span>
          {category.validCount}/{category.totalCount}
        </span>
      </div>
    </button>
  );
}

function IndicatorRow({
  indicator,
  category,
}: {
  indicator: Indicator;
  category?: CategorySummary;
}) {
  const meta = signalMeta[indicator.signal];
  return (
    <details className="indicator-row">
      <summary>
        <div className="indicator-name">
          <span className="indicator-category">{category?.code}</span>
          <span>
            <strong>{indicator.name}</strong>
            <small>
              {indicator.family} · {indicator.frequency}
            </small>
          </span>
        </div>
        <div className="indicator-value">
          <strong>{formatNumber(indicator.latest, indicator.unit)}</strong>
          <small>{indicator.changeLabel}</small>
        </div>
        <div className="strength-cell">
          <span className="strength-track">
            <span
              style={{
                width: `${Math.max(6, Math.abs(indicator.score))}%`,
                background: scoreTone(indicator.score),
              }}
            />
          </span>
          <small>
            强度 {indicator.score > 0 ? "+" : ""}
            {Math.round(indicator.score)}
          </small>
        </div>
        <SignalBadge signal={indicator.signal} />
        <div className="updated-cell">
          <strong>{indicator.updatedAt.slice(5)}</strong>
          <small>{indicator.source}</small>
        </div>
        <span className="row-chevron" aria-hidden="true">
          ＋
        </span>
      </summary>
      <div className="indicator-detail">
        <div>
          <span>信号解释</span>
          <p>{indicator.reason}</p>
        </div>
        <div className="detail-metrics">
          <span>
            历史分位 <strong>{indicator.percentile}%</strong>
          </span>
          <span>
            上期值{" "}
            <strong>{formatNumber(indicator.previous, indicator.unit)}</strong>
          </span>
          <span>
            属性 <strong>{indicator.core ? "核心指标" : "辅助指标"}</strong>
          </span>
          <span className={meta.className}>
            当前 <strong>{meta.label}</strong>
          </span>
        </div>
      </div>
    </details>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [showAuxiliary, setShowAuxiliary] = useState(false);

  useEffect(() => {
    fetch("./data/dashboard.json", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("数据文件读取失败");
        return response.json();
      })
      .then(setData)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const categoryMap = useMemo(
    () =>
      new Map<string, CategorySummary>(
        data?.categories.map((category) => [category.id, category]) ?? [],
      ),
    [data],
  );

  const filteredIndicators = useMemo(() => {
    if (!data) return [];
    const needle = search.trim().toLowerCase();
    return data.indicators.filter((indicator) => {
      if (!showAuxiliary && !indicator.core) return false;
      if (
        selectedCategory !== "all" &&
        indicator.category !== selectedCategory
      )
        return false;
      if (!needle) return true;
      return `${indicator.name} ${indicator.family} ${indicator.source}`
        .toLowerCase()
        .includes(needle);
    });
  }, [data, search, selectedCategory, showAuxiliary]);

  if (error) {
    return (
      <main className="status-screen">
        <span className="brand-mark">MP</span>
        <h1>数据暂时没有准备好</h1>
        <p>{error}。请先运行每日更新脚本生成 dashboard.json。</p>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="status-screen">
        <span className="brand-mark">MP</span>
        <h1>正在整理今日宏观信号</h1>
        <p>聚合指标族、检查数据新鲜度并计算债市方向。</p>
      </main>
    );
  }

  const selected =
    selectedCategory === "all"
      ? null
      : categoryMap.get(selectedCategory) ?? null;

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#" aria-label="宏观脉搏首页">
          <span className="brand-mark">MP</span>
          <span>
            <strong>宏观脉搏</strong>
            <small>MACRO PULSE</small>
          </span>
        </a>
        <nav aria-label="页面导航">
          <a href="#overview">总览</a>
          <a href="#matrix">趋势矩阵</a>
          <a href="#indicators">指标明细</a>
        </nav>
        <div className="update-status">
          <span className="live-dot" />
          <span>
            数据更新
            <strong>
              {new Date(data.generatedAt).toLocaleString("zh-CN", {
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </strong>
          </span>
        </div>
      </header>

      <section className="hero shell" id="overview">
        <div className="hero-copy">
          <span className="eyebrow">今日宏观判断</span>
          <h1>{data.overall.title}</h1>
          <p>{data.overall.narrative}</p>
          <div className="hero-actions">
            <SignalBadge signal={data.overall.signal} />
            <span className="hero-score">
              综合强度{" "}
              <strong style={{ color: scoreTone(data.overall.score) }}>
                {data.overall.score > 0 ? "+" : ""}
                {Math.round(data.overall.score)}
              </strong>
            </span>
          </div>
        </div>
        <div className="quality-panel">
          <span className="eyebrow">信号质量</span>
          <div className="quality-grid">
            <div>
              <strong>{data.overall.breadth}%</strong>
              <span>利多扩散度</span>
            </div>
            <div>
              <strong>{data.overall.confidence}%</strong>
              <span>模型置信度</span>
            </div>
            <div>
              <strong>{data.overall.freshness}%</strong>
              <span>数据新鲜度</span>
            </div>
          </div>
          <p>
            先在指标族内合成，再计算大类信号，避免同一产业链或多个期限重复投票。
          </p>
        </div>
      </section>

      <section className="category-grid shell" aria-label="九大类宏观信号">
        {data.categories.map((category) => (
          <CategoryCard
            key={category.id}
            category={category}
            active={selectedCategory === category.id}
            onSelect={() =>
              setSelectedCategory((current) =>
                current === category.id ? "all" : category.id,
              )
            }
          />
        ))}
      </section>

      <section className="panel shell" id="matrix">
        <div className="section-heading">
          <div>
            <span className="eyebrow">最近13周</span>
            <h2>宏观信号趋势矩阵</h2>
            <p>颜色表示对债市的方向与强度，灰色代表中性。</p>
          </div>
          <div className="legend" aria-label="颜色图例">
            <span>
              <i className="legend-bull" /> 利多
            </span>
            <span>
              <i className="legend-neutral" /> 中性
            </span>
            <span>
              <i className="legend-bear" /> 利空
            </span>
          </div>
        </div>
        <div className="heatmap-scroll">
          <div
            className="heatmap"
            style={{
              gridTemplateColumns: `112px repeat(${data.dates.length}, minmax(42px, 1fr))`,
            }}
          >
            <div className="heatmap-corner">类别 / 周末</div>
            {data.dates.map((date) => (
              <div className="heatmap-date" key={date}>
                {date.slice(5)}
              </div>
            ))}
            {data.categories.map((category) => (
              <div className="heatmap-row" key={category.id}>
                <button
                  onClick={() => setSelectedCategory(category.id)}
                  className="heatmap-label"
                >
                  {category.name}
                </button>
                {category.weeklyScores.map((score, index) => (
                  <button
                    key={`${category.id}-${index}`}
                    className="heat-cell"
                    style={{ background: heatColor(score) }}
                    title={`${category.name} ${data.dates[index]}：${score > 0 ? "+" : ""}${Math.round(score)}`}
                    aria-label={`${category.name} ${data.dates[index]} 信号 ${Math.round(score)}`}
                  >
                    {Math.abs(score) >= 55 ? Math.round(score) : ""}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="panel shell indicators-panel" id="indicators">
        <div className="section-heading indicators-heading">
          <div>
            <span className="eyebrow">可解释的底层信号</span>
            <h2>{selected ? `${selected.name}核心指标` : "核心指标明细"}</h2>
            <p>
              {selected
                ? selected.summary
                : "默认仅展示参与评分的核心指标；辅助指标保留在数据库，但不会重复影响大类方向。"}
            </p>
          </div>
          <div className="indicator-tools">
            <label className="search-box">
              <span>搜索</span>
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="指标、产业链或来源"
              />
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={showAuxiliary}
                onChange={(event) => setShowAuxiliary(event.target.checked)}
              />
              <span>显示辅助指标</span>
            </label>
          </div>
        </div>

        <div className="category-tabs" role="tablist" aria-label="指标分类">
          <button
            className={selectedCategory === "all" ? "active" : ""}
            onClick={() => setSelectedCategory("all")}
          >
            全部核心
          </button>
          {data.categories.map((category) => (
            <button
              key={category.id}
              className={selectedCategory === category.id ? "active" : ""}
              onClick={() => setSelectedCategory(category.id)}
            >
              {category.name}
            </button>
          ))}
        </div>

        <div className="indicator-table">
          <div className="indicator-columns" aria-hidden="true">
            <span>指标 / 指标族</span>
            <span>最新 / 周变化</span>
            <span>信号强度</span>
            <span>债市方向</span>
            <span>日期 / 来源</span>
            <span />
          </div>
          {filteredIndicators.map((indicator) => (
            <IndicatorRow
              key={indicator.id}
              indicator={indicator}
              category={categoryMap.get(indicator.category)}
            />
          ))}
          {!filteredIndicators.length && (
            <div className="empty-state">没有符合当前筛选条件的指标。</div>
          )}
        </div>
      </section>

      <footer className="shell">
        <span>MACRO PULSE / 宏观脉搏</span>
        <p>
          信号用于宏观观察，不构成投资建议。数据模式：{data.mode} ·
          配置驱动、每日自动更新。
        </p>
      </footer>
    </main>
  );
}
