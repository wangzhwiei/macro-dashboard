import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "宏观脉搏 · 高频观测",
    template: "%s · 宏观脉搏",
  },
  description: "每天自动更新的中国宏观高频指标观测、去重评分与债市信号面板",
  openGraph: {
    title: "宏观脉搏 · 高频观测",
    description: "从高频数据到可解释的宏观与债市信号",
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
