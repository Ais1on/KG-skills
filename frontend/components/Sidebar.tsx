"use client";

import { useEffect, useMemo, useState } from "react";
import { Clock3, Grid2x2, Plus, Search, Sparkles } from "lucide-react";

import { useAppStore } from "@/store/useAppStore";

type ThreadRecord = {
  agent_id: string;
  name: string;
  created_at: string;
  model: string;
  api_base: string;
};

export function Sidebar() {
  const currentModel = useAppStore((s) => s.currentModel);
  const isSidebarOpen = useAppStore((s) => s.isSidebarOpen);
  const threads = useAppStore((s) => s.threads);
  const currentThreadId = useAppStore((s) => s.currentThreadId);
  const setThreads = useAppStore((s) => s.setThreads);
  const setCurrentThread = useAppStore((s) => s.setCurrentThread);

  const [loading, setLoading] = useState(false);

  const sortedThreads = useMemo(
    () => [...threads].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))),
    [threads]
  );

  const loadThreads = async () => {
    const res = await fetch("/api/agents");
    if (!res.ok) {
      throw new Error(`加载线程失败: ${res.status}`);
    }
    const data = await res.json();
    const rows: ThreadRecord[] = Array.isArray(data?.agents) ? data.agents : [];
    setThreads(rows);
  };

  useEffect(() => {
    void loadThreads().catch(() => undefined);
  }, []);

  const createThread = async () => {
    if (loading) {
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `thread-${Math.random().toString(36).slice(2, 7)}`,
          model: currentModel,
        }),
      });
      if (!res.ok) {
        throw new Error(`创建线程失败: ${res.status}`);
      }
      const created = await res.json();
      await loadThreads();
      setCurrentThread(created.agent_id, created.name);
    } finally {
      setLoading(false);
    }
  };

  return (
    <aside
      className={[
        "h-screen shrink-0 border-r border-[#2a2a2a] bg-[#171717] text-gray-300 transition-all duration-200",
        isSidebarOpen ? "w-[300px]" : "w-0 overflow-hidden border-r-0",
      ].join(" ")}
    >
      <div className="flex h-full flex-col">
        <div className="p-3">
          <button
            onClick={createThread}
            disabled={loading}
            className="mb-3 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-gray-100 hover:bg-[#232323] disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            新线程
          </button>

          <nav className="space-y-1">
            <button className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-[#232323]">
              <Grid2x2 className="h-4 w-4" />
              技能和应用
            </button>
            <button className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 hover:bg-[#232323]">
              <Clock3 className="h-4 w-4" />
              自动化
            </button>
          </nav>
        </div>

        <div className="flex items-center justify-between px-3 pb-2 pt-1 text-xs text-gray-500">
          <span>线程</span>
          <div className="flex items-center gap-1">
            <Search className="h-3.5 w-3.5" />
            <Plus className="h-3.5 w-3.5" />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {sortedThreads.map((thread) => {
            const active = currentThreadId === thread.agent_id;
            return (
              <button
                key={thread.agent_id}
                onClick={() => setCurrentThread(thread.agent_id, thread.name)}
                className={[
                  "mb-1 block w-full truncate rounded-lg px-3 py-2 text-left text-sm",
                  active ? "bg-[#2f2f2f] text-gray-100" : "text-gray-400 hover:bg-[#232323] hover:text-gray-200",
                ].join(" ")}
                title={thread.name}
              >
                {thread.name}
              </button>
            );
          })}

          {sortedThreads.length === 0 && (
            <div className="mx-2 mt-2 rounded-lg border border-[#2a2a2a] p-3 text-xs text-gray-500">
              还没有线程，点击“新线程”创建。
            </div>
          )}
        </div>

        <div className="border-t border-[#2a2a2a] p-3 text-xs text-gray-500">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4" />
            <span>线程与会话绑定：线程即 Agent</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
