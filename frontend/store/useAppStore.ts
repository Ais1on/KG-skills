import { create } from "zustand";

type ThreadRecord = {
  agent_id: string;
  name: string;
  created_at: string;
  model: string;
  api_base: string;
};

type AppStore = {
  currentModel: string;
  threads: ThreadRecord[];
  currentThreadId: string;
  currentThreadName: string;
  sessionByThread: Record<string, string>;
  isSidebarOpen: boolean;
  setCurrentModel: (model: string) => void;
  setThreads: (threads: ThreadRecord[]) => void;
  setCurrentThread: (threadId: string, threadName?: string) => void;
  setBoundSession: (threadId: string, sessionId: string) => void;
  getBoundSession: (threadId: string) => string;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
};

export const useAppStore = create<AppStore>((set, get) => ({
  currentModel: "deepseek-chat",
  threads: [],
  currentThreadId: "",
  currentThreadName: "",
  sessionByThread: {},
  isSidebarOpen: true,
  setCurrentModel: (model) => set({ currentModel: model }),
  setThreads: (threads) =>
    set((state) => {
      const resolvedId = state.currentThreadId || threads[0]?.agent_id || "";
      const matched = threads.find((item) => item.agent_id === resolvedId);
      return {
        threads,
        currentThreadId: resolvedId,
        currentThreadName: matched?.name ?? "",
      };
    }),
  setCurrentThread: (threadId, threadName) => set({ currentThreadId: threadId, currentThreadName: threadName ?? "" }),
  setBoundSession: (threadId, sessionId) =>
    set((state) => ({ sessionByThread: { ...state.sessionByThread, [threadId]: sessionId } })),
  getBoundSession: (threadId) => get().sessionByThread[threadId] || "",
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
  setSidebarOpen: (open) => set({ isSidebarOpen: open }),
}));
