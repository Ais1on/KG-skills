import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Agent Platform",
  description: "Single/Multi Agent Platform UI",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" className="dark">
      <body className="h-screen overflow-hidden bg-[#212121] font-sans text-gray-100 antialiased">
        <div className="flex h-screen w-screen overflow-hidden">
          <Sidebar />
          <main className="min-w-0 flex-1 bg-[#212121]">{children}</main>
        </div>
      </body>
    </html>
  );
}
