"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import ReactMarkdown from "react-markdown";

import { useAppStore } from "@/store/useAppStore";
import { ChatInput } from "@/components/ChatInput";

type MarkdownCodeProps = {
  inline?: boolean;
  className?: string;
  children?: ReactNode;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

function CodeBlock({ inline, className, children }: MarkdownCodeProps) {
  const [copied, setCopied] = useState(false);
  const rawCode = String(children || "").replace(/\n$/, "");
  const language = /language-([\w-]+)/.exec(className || "")?.[1] ?? "text";

  if (inline) {
    return <code className="rounded bg-[#2f2f2f] px-1.5 py-0.5 text-sm text-gray-100">{children}</code>;
  }

  const onCopy = async () => {
    await navigator.clipboard.writeText(rawCode);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-[#3a3a3a]">
      <div className="flex items-center justify-between bg-[#2f2f2f] px-3 py-2 text-xs text-gray-300">
        <span className="uppercase tracking-wide">{language}</span>
        <button
          onClick={onCopy}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-[#3a3a3a]"
          aria-label="copy code"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto bg-[#0d0d0d] p-4 text-sm text-gray-100">
        <code className="font-mono">{rawCode}</code>
      </pre>
    </div>
  );
}

const starters = [
  "在这个仓库实现一个经典贪吃蛇",
  "生成应用的一页 PDF 总结",
  "创建一个可执行的开发计划",
];

export function ChatArea() {
  const currentThreadId = useAppStore((s) => s.currentThreadId);
  const currentThreadName = useAppStore((s) => s.currentThreadName);
  const getBoundSession = useAppStore((s) => s.getBoundSession);
  const setBoundSession = useAppStore((s) => s.setBoundSession);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const listRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const chatMessages = useMemo(() => messages, [messages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chatMessages, loading]);

  useEffect(() => {
    return () => {
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, []);

  const ensureSession = async (threadId: string): Promise<string> => {
    const bound = getBoundSession(threadId);
    if (bound) {
      return bound;
    }

    const listRes = await fetch(`/api/agents/${encodeURIComponent(threadId)}/conversations?limit=1&offset=0`);
    if (!listRes.ok) {
      throw new Error(`读取会话失败: ${listRes.status}`);
    }
    const listData = await listRes.json();
    const first = Array.isArray(listData?.items) ? listData.items[0] : null;
    if (first?.id) {
      const id = String(first.id);
      setBoundSession(threadId, id);
      return id;
    }

    const createRes = await fetch(`/api/agents/${encodeURIComponent(threadId)}/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: currentThreadName || "新线程" }),
    });
    if (!createRes.ok) {
      throw new Error(`创建会话失败: ${createRes.status}`);
    }
    const created = await createRes.json();
    const id = String(created?.id || "");
    if (!id) {
      throw new Error("创建会话返回为空");
    }
    setBoundSession(threadId, id);
    return id;
  };

  useEffect(() => {
    const loadHistory = async () => {
      if (!currentThreadId) {
        setMessages([]);
        return;
      }
      try {
        const sessionId = await ensureSession(currentThreadId);
        const res = await fetch(
          `/api/agents/${encodeURIComponent(currentThreadId)}/conversations/${encodeURIComponent(sessionId)}/messages?limit=200&offset=0`
        );
        if (!res.ok) {
          throw new Error(`读取历史失败: ${res.status}`);
        }
        const data = await res.json();
        const rows = Array.isArray(data?.items) ? data.items : [];
        const mapped: ChatMessage[] = rows
          .filter((row: any) => row?.role === "user" || row?.role === "assistant")
          .map((row: any) => ({
            id: String(row.id || makeId()),
            role: row.role,
            content: String(row.content || ""),
          }));
        setMessages(mapped);
      } catch {
        setMessages([]);
      }
    };

    void loadHistory();
  }, [currentThreadId]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) {
      return;
    }
    if (!currentThreadId) {
      setError("请先创建或选择线程");
      return;
    }

    setError("");
    setLoading(true);
    setInput("");

    const userMessage: ChatMessage = { id: makeId(), role: "user", content: text };
    const assistantId = makeId();
    setMessages((prev) => [...prev, userMessage, { id: assistantId, role: "assistant", content: "" }]);

    try {
      const sessionId = await ensureSession(currentThreadId);
      const params = new URLSearchParams({
        message: text,
        thread_id: currentThreadId,
        conversation_id: sessionId,
      });
      const url = `/api/agents/${encodeURIComponent(currentThreadId)}/chat/stream?${params.toString()}`;

      sourceRef.current?.close();
      const source = new EventSource(url);
      sourceRef.current = source;

      source.addEventListener("token", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data || "{}");
        const token = String(data?.text || "");
        if (!token) {
          return;
        }
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + token } : m)));
      });

      source.addEventListener("tool_confirm_required", async (ev) => {
        const data = JSON.parse((ev as MessageEvent).data || "{}");
        const confirmationId = String(data?.confirmation_id || "");
        const toolName = String(data?.tool_name || "危险工具");
        if (!confirmationId) {
          return;
        }
        const approved = window.confirm(`线程将调用危险工具：${toolName}，是否继续？`);
        await fetch("/api/v1/tools/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmation_id: confirmationId, approved }),
        });
      });

      source.addEventListener("error", (ev) => {
        try {
          const data = JSON.parse((ev as MessageEvent).data || "{}");
          setError(String(data?.detail || "请求失败"));
        } catch {
          setError("请求失败");
        }
      });

      source.addEventListener("done", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data || "{}");
        if (!data?.ok && !error) {
          setError("生成失败");
        }
        setLoading(false);
        source.close();
        if (sourceRef.current === source) {
          sourceRef.current = null;
        }
      });
    } catch (err) {
      setLoading(false);
      setError(err instanceof Error ? err.message : "发送失败");
    }
  };

  return (
    <section className="flex h-[calc(100vh-56px)] flex-col bg-[#111214]">
      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-4 pb-2 pt-5">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 pb-4">
          {chatMessages.length === 0 && (
            <div className="mt-10 text-center text-gray-300">
              <p className="mb-10 text-left text-xl font-semibold">{currentThreadName || "新线程"}</p>
              <div className="mx-auto mb-8 flex h-10 w-10 items-center justify-center rounded-full border border-[#3a3a3a] text-lg">
                ✦
              </div>
              <h2 className="text-5xl font-semibold tracking-tight">开始构建</h2>
              <p className="mt-1 text-5xl font-medium text-gray-500">{currentThreadName || "New project"}</p>

              <div className="mt-16 grid grid-cols-1 gap-3 md:grid-cols-3">
                {starters.map((text) => (
                  <button
                    key={text}
                    onClick={() => setInput(text)}
                    className="rounded-3xl border border-[#2f2f2f] bg-[#1a1c20] p-5 text-left text-lg text-gray-200 hover:border-[#4a4d55]"
                  >
                    {text}
                  </button>
                ))}
              </div>
            </div>
          )}

          {chatMessages.map((message) => {
            const isUser = message.role === "user";
            return (
              <div key={message.id} className={isUser ? "flex justify-end" : "flex justify-start"}>
                <div
                  className={[
                    "max-w-[85%] rounded-2xl px-4 py-3",
                    isUser ? "bg-[#2a2d33] text-gray-100" : "bg-transparent text-gray-100",
                  ].join(" ")}
                >
                  <div className="max-w-none text-[15px] leading-7 text-gray-100">
                    <ReactMarkdown
                      components={{
                        code: (props) => {
                          const { inline, className, children } = props as {
                            inline?: boolean;
                            className?: string;
                            children?: ReactNode;
                          };
                          return (
                            <CodeBlock inline={inline} className={className}>
                              {children}
                            </CodeBlock>
                          );
                        },
                      }}
                    >
                      {message.content || (loading && !isUser ? "思考中..." : "")}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            );
          })}

          {error && <p className="text-sm text-red-400">请求失败：{error}</p>}
          <div ref={bottomRef} />
        </div>
      </div>

      <ChatInput value={input} onChange={setInput} onSend={sendMessage} disabled={loading} />
    </section>
  );
}
