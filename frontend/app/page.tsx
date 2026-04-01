"use client";

import { ChatArea } from "@/components/ChatArea";
import { ChatHeader } from "@/components/ChatHeader";

export default function HomePage() {
  return (
    <div className="flex h-screen flex-col bg-[#212121]">
      <ChatHeader />
      <ChatArea />
    </div>
  );
}
