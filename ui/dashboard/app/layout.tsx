import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AutoTrader 대시보드",
  description: "변동성 돌파 자동매매 봇 모니터링",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="bg-gray-950 text-gray-100 min-h-screen">
        <nav className="bg-gray-900 border-b border-gray-800 px-4 py-3 flex gap-6 text-sm font-medium">
          <Link href="/"        className="hover:text-blue-400 transition-colors">대시보드</Link>
          <Link href="/trades"  className="hover:text-blue-400 transition-colors">거래 내역</Link>
          <Link href="/logs"    className="hover:text-blue-400 transition-colors">로그</Link>
          <Link href="/backtest" className="hover:text-blue-400 transition-colors">백테스트</Link>
        </nav>
        <main className="p-4 md:p-6 max-w-4xl mx-auto">
          {children}
        </main>
      </body>
    </html>
  );
}
