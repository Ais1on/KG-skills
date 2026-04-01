"use client";

import { ChevronDown, MoreHorizontal, PanelLeft } from "lucide-react";

import { useAppStore } from "@/store/useAppStore";

const models = ["deepseek-chat", "gpt-4o-mini", "gpt-4.1", "o3-mini"];

export function ChatHeader() {
  const currentModel = useAppStore((s) => s.currentModel);
  const currentThreadName = useAppStore((s) => s.currentThreadName);
  const setCurrentModel = useAppStore((s) => s.setCurrentModel);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);

  return (
    <header className="flex h-14 items-center justify-between border-b border-[#2a2a2a] px-4">
      <div className="flex items-center gap-2">
        <button
          onClick={toggleSidebar}
          className="rounded-md p-2 text-gray-400 transition-colors hover:bg-[#2a2a2a] hover:text-gray-200"
          aria-label="toggle sidebar"
        >
          <PanelLeft className="h-4 w-4" />
        </button>

        <div className="text-sm text-gray-500">{currentThreadName || "新线程"}</div>
      </div>

      <div className="flex items-center gap-2">
        <label className="relative inline-flex items-center">
          <select
            value={currentModel}
            onChange={(e) => setCurrentModel(e.target.value)}
            className="appearance-none rounded-lg bg-transparent pr-7 text-sm font-semibold text-gray-200 outline-none"
          >
            {models.map((model) => (
              <option key={model} value={model} className="bg-[#171717] text-gray-100">
                {model}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-0 h-4 w-4 text-gray-400" />
        </label>
        <button className="rounded-lg p-2 text-gray-400 hover:bg-[#2a2a2a] hover:text-gray-200">
          <MoreHorizontal className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
