import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "创金固收投资部宏观数据研究",
    template: "%s · 创金固收投资部宏观数据研究",
  },
  description:
    "创金固收投资部中国宏观高频指标观测、去重评分与债市信号研究面板",
  openGraph: {
    title: "创金固收投资部宏观数据研究",
    description: "从高频数据到可解释的宏观观点与债市信号",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
