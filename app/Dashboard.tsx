"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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

const rangeDays: Record<string, number> = {
  "1m": 31,
  "3m": 93,
  "6m": 186,
  "1y": 366,
};

function formatNumber(value: number, unit: string) {
  if (!Number.isFinite(value)) return "—";
  const absolute = Math.abs(value);
  const digits = absolute >= 1000 ? 0 : absolute >= 100 ? 1 : 2;
  const number = value.toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
  return unit === "指数" || unit === "z" || !unit ? number : `${number} ${unit}`;
}

function scoreTone(score: number) {
  if (score >= 15) return "var(--bull)";
  if (score <= -15) return "var(--bear)";
  return "var(--neutral)";
}

function heatColor(score: number) {
  const strength = Math.min(1, Math.abs(score) / 100);
  if (score >= 15) return `rgba(213, 75, 72, ${0.16 + strength * 0.76})`;
  if (score <= -15) return `rgba(0, 143, 102, ${0.16 + strength * 0.76})`;
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
  const detail = category.breadthDetail;
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
        <span
          title={`利多指标族 ${detail.bullish}，利空指标族 ${detail.bearish}，中性 ${detail.neutral}；中性不计入扩散度分母`}
        >
          利多扩散 {category.breadth}%
        </span>
        <span>
          核心 {category.validCount}/{category.totalCount}
        </span>
      </div>
    </button>
  );
}

function HistoryCanvas({
  points,
  color,
  onHover,
}: {
  points: Array<{ date: string; value: number }>;
  color: string;
  onHover: (point: { date: string; value: number } | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !points.length) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(rect.width * ratio));
    canvas.height = Math.max(1, Math.round(rect.height * ratio));
    const context = canvas.getContext("2d");
    if (!context) return;
    context.scale(ratio, ratio);
    const width = rect.width;
    const height = rect.height;
    const padding = { left: 52, right: 18, top: 20, bottom: 30 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const values = points.map((point) => point.value);
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    const span = rawMax - rawMin || Math.abs(rawMax) || 1;
    const min = rawMin - span * 0.08;
    const max = rawMax + span * 0.08;
    const x = (index: number) =>
      padding.left + (index / Math.max(1, points.length - 1)) * plotWidth;
    const y = (value: number) =>
      padding.top + ((max - value) / (max - min)) * plotHeight;

    context.clearRect(0, 0, width, height);
    context.strokeStyle = "rgba(105, 115, 111, .17)";
    context.fillStyle = "#69736f";
    context.font = "10px Aptos, Microsoft YaHei UI, sans-serif";
    context.textAlign = "right";
    context.textBaseline = "middle";
    for (let row = 0; row <= 4; row += 1) {
      const yPos = padding.top + (plotHeight / 4) * row;
      const label = max - ((max - min) / 4) * row;
      context.beginPath();
      context.moveTo(padding.left, yPos);
      context.lineTo(width - padding.right, yPos);
      context.stroke();
      context.fillText(
        label.toLocaleString("zh-CN", { maximumFractionDigits: 2 }),
        padding.left - 8,
        yPos,
      );
    }

    context.beginPath();
    points.forEach((point, index) => {
      const xPos = x(index);
      const yPos = y(point.value);
      if (index === 0) context.moveTo(xPos, yPos);
      else context.lineTo(xPos, yPos);
    });
    context.strokeStyle = color;
    context.lineWidth = 2;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.stroke();

    const firstDate = points[0].date.slice(0, 7);
    const lastDate = points[points.length - 1].date.slice(0, 7);
    context.fillStyle = "#69736f";
    context.textBaseline = "top";
    context.textAlign = "left";
    context.fillText(firstDate, padding.left, height - 20);
    context.textAlign = "right";
    context.fillText(lastDate, width - padding.right, height - 20);

    if (hoverIndex !== null && points[hoverIndex]) {
      const point = points[hoverIndex];
      const xPos = x(hoverIndex);
      const yPos = y(point.value);
      context.beginPath();
      context.moveTo(xPos, padding.top);
      context.lineTo(xPos, padding.top + plotHeight);
      context.strokeStyle = "rgba(24, 33, 31, .28)";
      context.lineWidth = 1;
      context.stroke();
      context.beginPath();
      context.arc(xPos, yPos, 4, 0, Math.PI * 2);
      context.fillStyle = color;
      context.fill();
    }
  }, [color, hoverIndex, points]);

  useEffect(() => {
    draw();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      className="history-canvas"
      onMouseMove={(event) => {
        if (!points.length) return;
        const rect = event.currentTarget.getBoundingClientRect();
        const ratio = Math.max(
          0,
          Math.min(1, (event.clientX - rect.left - 52) / (rect.width - 70)),
        );
        const index = Math.round(ratio * (points.length - 1));
        setHoverIndex(index);
        onHover(points[index]);
      }}
      onMouseLeave={() => {
        setHoverIndex(null);
        onHover(null);
      }}
      aria-label="指标历史数据走势图"
    />
  );
}

function HistoryModal({
  indicator,
  category,
  onClose,
}: {
  indicator: Indicator;
  category?: CategorySummary;
  onClose: () => void;
}) {
  const [range, setRange] = useState("1y");
  const firstDate = indicator.series[0]?.date ?? "";
  const lastDate = indicator.series.at(-1)?.date ?? "";
  const [customStart, setCustomStart] = useState(firstDate);
  const [customEnd, setCustomEnd] = useState(lastDate);
  const [hovered, setHovered] = useState<{
    date: string;
    value: number;
  } | null>(null);

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

  const filtered = useMemo(() => {
    if (range === "all") return indicator.series;
    const end = new Date(range === "custom" ? customEnd : lastDate);
    const start =
      range === "custom"
        ? new Date(customStart)
        : new Date(end.getTime() - rangeDays[range] * 86_400_000);
    return indicator.series.filter((point) => {
      const day = new Date(point.date);
      return day >= start && day <= end;
    });
  }, [customEnd, customStart, indicator.series, lastDate, range]);

  const displayed = hovered ?? filtered.at(-1) ?? null;
  const values = filtered.map((point) => point.value);
  const periodChange =
    values.length > 1 && values[0] !== 0
      ? ((values.at(-1)! / values[0] - 1) * 100)
      : 0;

  const downloadCsv = () => {
    const rows = [
      ["日期", "数值", "单位", "指标", "来源"],
      ...filtered.map((point) => [
        point.date,
        String(point.value),
        indicator.unit,
        indicator.name,
        indicator.source,
      ]),
    ];
    const csv = `\uFEFF${rows
      .map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(","))
      .join("\n")}`;
    const url = URL.createObjectURL(
      new Blob([csv], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${indicator.name}-${range}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="history-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${indicator.name}历史走势`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="history-header">
          <div>
            <span className="eyebrow">
              {category?.name} / {indicator.family} / {indicator.frequency}
            </span>
            <h2>{indicator.name}</h2>
            <p>{indicator.reason}</p>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="history-kpis">
          <div>
            <span>{displayed?.date ?? "—"}</span>
            <strong>
              {displayed
                ? formatNumber(displayed.value, indicator.unit)
                : "—"}
            </strong>
            <small>{hovered ? "悬停位置" : "区间最新值"}</small>
          </div>
          <div>
            <span>区间变化</span>
            <strong className={periodChange >= 0 ? "value-up" : "value-down"}>
              {periodChange >= 0 ? "+" : ""}
              {periodChange.toFixed(2)}%
            </strong>
            <small>{filtered.length} 个数据点</small>
          </div>
          <div>
            <span>区间最高</span>
            <strong>
              {values.length
                ? formatNumber(Math.max(...values), indicator.unit)
                : "—"}
            </strong>
            <small>历史分位 {indicator.percentile}%</small>
          </div>
          <div>
            <span>区间最低</span>
            <strong>
              {values.length
                ? formatNumber(Math.min(...values), indicator.unit)
                : "—"}
            </strong>
            <small>{indicator.source}</small>
          </div>
        </div>

        <div className="history-toolbar">
          <div className="range-tabs" aria-label="选择时间范围">
            {[
              ["1m", "1个月"],
              ["3m", "3个月"],
              ["6m", "6个月"],
              ["1y", "1年"],
              ["all", "全部"],
            ].map(([value, label]) => (
              <button
                key={value}
                className={range === value ? "active" : ""}
                onClick={() => setRange(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="custom-range">
            <input
              type="date"
              value={customStart}
              min={firstDate}
              max={customEnd}
              onChange={(event) => {
                setCustomStart(event.target.value);
                setRange("custom");
              }}
              aria-label="开始日期"
            />
            <span>至</span>
            <input
              type="date"
              value={customEnd}
              min={customStart}
              max={lastDate}
              onChange={(event) => {
                setCustomEnd(event.target.value);
                setRange("custom");
              }}
              aria-label="结束日期"
            />
          </div>
          <button className="download-button" onClick={downloadCsv}>
            下载当前区间 CSV
          </button>
        </div>

        <div className="chart-shell">
          <HistoryCanvas
            points={filtered}
            color={scoreTone(indicator.score)}
            onHover={setHovered}
          />
          {!filtered.length && (
            <div className="chart-empty">当前区间没有可用数据。</div>
          )}
        </div>

        <section className="methodology-panel" aria-label="指标计算方法">
          <div className="methodology-heading">
            <div>
              <span className="eyebrow">计算方法可复核</span>
              <h3>{indicator.methodology.title}</h3>
            </div>
            <span className="methodology-tag">
              {indicator.methodology.components.length > 1 ? "合成指标" : "单序列"}
            </span>
          </div>
          <div className="formula-box">{indicator.methodology.formula}</div>
          <p className="calibration-note">
            {indicator.methodology.calibration}
          </p>
          <div className="methodology-grid">
            <ol>
              {indicator.methodology.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
            <div className="component-table">
              <span>原始分项与权重</span>
              {indicator.methodology.components.map((component) => (
                <div key={component.code}>
                  <code>{component.code}</code>
                  <strong>{component.weight.toFixed(1)}</strong>
                </div>
              ))}
            </div>
          </div>
          <p className="signal-method-note">
            页面信号分值还会将该指标的周变化减去历史周变化均值，再除以历史标准差，
            乘以债市方向与35，最后限制在 −100 至 +100；正值为债市利多，负值为债市利空。
          </p>
        </section>

        <footer className="history-footer">
          <span>
            当前信号 <SignalBadge signal={indicator.signal} />
          </span>
          <span>最近更新 {indicator.updatedAt}</span>
          <span>{indicator.core ? "参与大类评分" : "辅助观察，不重复计票"}</span>
        </footer>
      </section>
    </div>
  );
}

function IndicatorRow({
  indicator,
  category,
  onOpenHistory,
}: {
  indicator: Indicator;
  category?: CategorySummary;
  onOpenHistory: () => void;
}) {
  return (
    <div className="indicator-row">
      <div className="indicator-name">
        <span className="indicator-category">{category?.code}</span>
        <button className="indicator-name-button" onClick={onOpenHistory}>
          <strong>{indicator.name}</strong>
          <small>
            {indicator.family} · {indicator.frequency} ·{" "}
            {indicator.core ? "核心" : "辅助"}
          </small>
        </button>
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
      <button
        className="research-button"
        onClick={onOpenHistory}
        aria-label={`研究${indicator.name}历史走势`}
      >
        走势
      </button>
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [showAuxiliary, setShowAuxiliary] = useState(false);
  const [sortBy, setSortBy] = useState("category");
  const [matrixRange, setMatrixRange] = useState("13w");
  const [matrixStart, setMatrixStart] = useState("");
  const [matrixEnd, setMatrixEnd] = useState("");
  const [historyIndicator, setHistoryIndicator] = useState<Indicator | null>(
    null,
  );

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
    const filtered = data.indicators.filter((indicator) => {
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
    return [...filtered].sort((left, right) => {
      if (sortBy === "strength")
        return Math.abs(right.score) - Math.abs(left.score);
      if (sortBy === "latest")
        return right.updatedAt.localeCompare(left.updatedAt);
      if (sortBy === "name") return left.name.localeCompare(right.name, "zh-CN");
      return (
        data.categories.findIndex((item) => item.id === left.category) -
        data.categories.findIndex((item) => item.id === right.category)
      );
    });
  }, [data, search, selectedCategory, showAuxiliary, sortBy]);

  const matrixSelection = useMemo(() => {
    if (!data) return { dates: [] as string[], indices: [] as number[] };
    let indices = data.dates.map((_, index) => index);
    if (matrixRange === "custom") {
      indices = indices.filter((index) => {
        const day = data.dates[index];
        return (
          (!matrixStart || day >= matrixStart) &&
          (!matrixEnd || day <= matrixEnd)
        );
      });
    } else if (matrixRange !== "all") {
      const count = Number.parseInt(matrixRange, 10);
      indices = indices.slice(-count);
    }
    return {
      dates: indices.map((index) => data.dates[index]),
      indices,
    };
  }, [data, matrixEnd, matrixRange, matrixStart]);

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
  const coreCount = data.indicators.filter((indicator) => indicator.core).length;
  const auxiliaryCount = data.indicators.length - coreCount;
  const supportive = [...data.categories]
    .sort((left, right) => right.score - left.score)
    .slice(0, 2);
  const headwinds = [...data.categories]
    .sort((left, right) => left.score - right.score)
    .slice(0, 2);
  const overallBreadth = data.overall.breadthDetail;

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
          <a href="#overview">今日观点</a>
          <a href="#matrix">趋势矩阵</a>
          <a href="#indicators">数据研究</a>
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
          <span className="eyebrow">今日债市观点</span>
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
          <div className="driver-strip">
            <div>
              <span>主要利多</span>
              {supportive.map((category) => (
                <button
                  key={category.id}
                  onClick={() => setSelectedCategory(category.id)}
                  className="driver-bull"
                >
                  {category.name} {category.score > 0 ? "+" : ""}
                  {Math.round(category.score)}
                </button>
              ))}
            </div>
            <div>
              <span>主要利空</span>
              {headwinds.map((category) => (
                <button
                  key={category.id}
                  onClick={() => setSelectedCategory(category.id)}
                  className="driver-bear"
                >
                  {category.name} {Math.round(category.score)}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="quality-panel">
          <span className="eyebrow">观点可信度</span>
          <div className="quality-grid">
            <div>
              <strong>{data.overall.breadth}%</strong>
              <span>利多扩散度</span>
            </div>
            <div>
              <strong>{data.overall.confidence}%</strong>
              <span>数据完整度</span>
            </div>
            <div>
              <strong>{data.overall.freshness}%</strong>
              <span>数据新鲜度</span>
            </div>
          </div>
          <p>
            当前有方向的大类中，{overallBreadth.bullish}类利多、
            {overallBreadth.bearish}类利空；{overallBreadth.neutral}
            类中性不进入扩散度分母。
          </p>
        </div>
      </section>

      <section className="reading-guide shell" aria-label="面板阅读指南">
        <div>
          <span className="guide-number">01</span>
          <strong>利多扩散度</strong>
          <p>利多大类 ÷（利多＋利空大类）。越高说明利多信号覆盖面越广。</p>
        </div>
        <div>
          <span className="guide-number">02</span>
          <strong>信号强度</strong>
          <p>按各指标自身历史波动标准化。正值利多债市，负值利空债市。</p>
        </div>
        <div>
          <span className="guide-number">03</span>
          <strong>去重规则</strong>
          <p>同产业链、期限或地区先在指标族内合成，再参与大类评分。</p>
        </div>
        <div>
          <span className="guide-number">04</span>
          <strong>核心与辅助</strong>
          <p>核心指标决定观点；辅助指标仅用于验证、拆分和深入研究。</p>
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
            <span className="eyebrow">
              {matrixSelection.dates.length}周历史 · 每格均显示信号分值
            </span>
            <h2>宏观信号趋势矩阵</h2>
            <p>
              红色为债市利多，绿色为债市利空；正负号表示方向，绝对值与颜色深浅表示强度。
            </p>
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
        <div className="matrix-toolbar">
          <div className="matrix-range-tabs" aria-label="矩阵历史范围">
            {[
              ["13w", "13周"],
              ["26w", "26周"],
              ["52w", "52周"],
              ["all", "全部"],
            ].map(([value, label]) => (
              <button
                key={value}
                className={matrixRange === value ? "active" : ""}
                onClick={() => setMatrixRange(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="matrix-custom-range">
            <input
              type="date"
              value={matrixStart || data.dates[0]}
              min={data.dates[0]}
              max={matrixEnd || data.dates.at(-1)}
              onChange={(event) => {
                setMatrixStart(event.target.value);
                setMatrixRange("custom");
              }}
              aria-label="矩阵开始日期"
            />
            <span>至</span>
            <input
              type="date"
              value={matrixEnd || data.dates.at(-1)}
              min={matrixStart || data.dates[0]}
              max={data.dates.at(-1)}
              onChange={(event) => {
                setMatrixEnd(event.target.value);
                setMatrixRange("custom");
              }}
              aria-label="矩阵结束日期"
            />
          </div>
          <span className="matrix-count">
            {matrixSelection.dates[0]} — {matrixSelection.dates.at(-1)}
          </span>
        </div>
        <div className="heatmap-scroll">
          <div
            className="heatmap"
            style={{
              gridTemplateColumns: `112px repeat(${matrixSelection.dates.length}, minmax(42px, 1fr))`,
            }}
          >
            <div className="heatmap-corner">类别 / 周末</div>
            {matrixSelection.dates.map((date) => (
              <div className="heatmap-date" key={date}>
                {date.slice(5)}
              </div>
            ))}
            {data.categories.map((category) => (
              <div className="heatmap-row" key={category.id}>
                <button
                  onClick={() => {
                    setSelectedCategory(category.id);
                    document
                      .getElementById("indicators")
                      ?.scrollIntoView({ behavior: "smooth" });
                  }}
                  className="heatmap-label"
                >
                  {category.name}
                </button>
                {matrixSelection.indices.map((historyIndex) => {
                  const score = category.weeklyScores[historyIndex] ?? 0;
                  const day = data.dates[historyIndex];
                  return (
                    <button
                      key={`${category.id}-${historyIndex}`}
                      className="heat-cell"
                      style={{
                        background: heatColor(score),
                        color: Math.abs(score) >= 45 ? "#fff" : "#27312e",
                      }}
                      title={`${category.name} ${day}：${score > 0 ? "+" : ""}${Math.round(score)}`}
                      aria-label={`${category.name} ${day} 信号 ${Math.round(score)}`}
                    >
                      {score > 0 ? "+" : ""}
                      {Math.round(score)}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="panel shell indicators-panel" id="indicators">
        <div className="section-heading indicators-heading">
          <div>
            <span className="eyebrow">从观点下钻到原始数据</span>
            <h2>
              {selected ? `${selected.name}指标研究` : "全部指标研究"}
              <span className="result-count">{filteredIndicators.length}</span>
            </h2>
            <p>
              {selected
                ? selected.summary
                : `共${data.indicators.length}个序列：${coreCount}个核心指标参与观点，${auxiliaryCount}个辅助指标用于交叉验证。`}
            </p>
          </div>
          <div className="indicator-tools">
            <label className="search-box">
              <span>搜索指标</span>
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="名称、指标族或来源"
              />
            </label>
            <label className="sort-box">
              <span>排序</span>
              <select
                value={sortBy}
                onChange={(event) => setSortBy(event.target.value)}
              >
                <option value="category">按分类</option>
                <option value="strength">按信号强度</option>
                <option value="latest">按更新时间</option>
                <option value="name">按指标名称</option>
              </select>
            </label>
          </div>
        </div>

        <div className="scope-switch" aria-label="指标范围">
          <button
            className={!showAuxiliary ? "active" : ""}
            onClick={() => setShowAuxiliary(false)}
          >
            核心指标 <span>{coreCount}</span>
          </button>
          <button
            className={showAuxiliary ? "active" : ""}
            onClick={() => setShowAuxiliary(true)}
          >
            全部指标 <span>{data.indicators.length}</span>
          </button>
          <p>辅助指标不会重复影响上方观点与扩散度。</p>
        </div>

        <div className="category-tabs" role="tablist" aria-label="指标分类">
          <button
            className={selectedCategory === "all" ? "active" : ""}
            onClick={() => setSelectedCategory("all")}
          >
            全部分类
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
            <span>最新值 / 周变化</span>
            <span>信号强度</span>
            <span>债市方向</span>
            <span>日期 / 来源</span>
            <span>研究</span>
          </div>
          {filteredIndicators.map((indicator) => (
            <IndicatorRow
              key={indicator.id}
              indicator={indicator}
              category={categoryMap.get(indicator.category)}
              onOpenHistory={() => setHistoryIndicator(indicator)}
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
          红色表示债市利多，绿色表示债市利空。数据模式：{data.mode} ·
          信号仅用于宏观观察，不构成投资建议。
        </p>
      </footer>

      {historyIndicator && (
        <HistoryModal
          indicator={historyIndicator}
          category={categoryMap.get(historyIndicator.category)}
          onClose={() => setHistoryIndicator(null)}
        />
      )}
    </main>
  );
}
