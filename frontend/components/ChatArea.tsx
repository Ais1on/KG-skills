"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Copy, Wrench } from "lucide-react";
import ReactMarkdown from "react-markdown";

import { ChatInput } from "@/components/ChatInput";
import { GraphPanel } from "@/components/GraphPanel";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";

type MarkdownCodeProps = {
  inline?: boolean;
  className?: string;
  children?: ReactNode;
};

type TimelineTone = "neutral" | "running" | "success" | "error";

type TimelineEntry = {
  id: string;
  kind: "status" | "tool" | "orchestration" | "graph";
  label: string;
  detail?: string;
  tone: TimelineTone;
  timestamp?: number;
};

type GraphEntity = {
  name: string;
  type?: string;
  properties?: Record<string, unknown>;
};

type GraphTriplet = {
  head: string;
  relation: string;
  tail: string;
  properties?: Record<string, unknown>;
};

type GraphSnapshot = {
  entities: GraphEntity[];
  triplets: GraphTriplet[];
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timeline?: TimelineEntry[];
  graph?: GraphSnapshot;
};

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

function summarizePreview(value: unknown) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
}

function friendlyPhaseLabel(phase: string) {
  const mapping: Record<string, string> = {
    request_received: "收到请求",
    assistant_thinking: "正在思考",
    assistant_done: "回答已生成",
    tool_execution: "调用外部工具",
    tool_execution_done: "工具调用完成",
    orchestrator_running: "分析任务",
    orchestrator_done: "已确定处理方式",
    skill_running: "提取实体和关系",
    skill_done: "提取完成",
    sandbox_running: "执行代码处理",
    sandbox_done: "代码处理完成",
    validator_running: "整理图谱",
    validator_done: "图谱整理完成",
    finalizer_running: "生成结果",
    finalizer_done: "结果已生成",
  };
  return mapping[phase] || phase;
}

function friendlyToolLabel(phase: string, tool: string) {
  const mapping: Record<string, string> = {
    planned: `准备调用 ${tool}`,
    start: `正在执行 ${tool}`,
    end: `${tool} 已完成`,
  };
  return mapping[phase] || `${tool} 处理中`;
}

function friendlyOrchestrationLabel(status: string, nodeName: string) {
  const nodeLabels: Record<string, string> = {
    orchestrator: "分析任务",
    search_gate: "准备搜索",
    text_extraction_skill: "提取实体和关系",
    assistant: "生成回答",
    tools: "执行工具",
    danger_tools_node: "等待工具审批",
    sandbox: "执行代码处理",
    validator: "整理图谱",
    finalizer: "生成结果",
    tool_confirmation: "人工审批",
  };
  const statusLabels: Record<string, string> = {
    running: "进行中",
    success: "已完成",
    error: "失败",
    planned: "已安排",
    updated: "已更新",
  };
  const base = nodeLabels[nodeName] || nodeName || "处理步骤";
  const suffix = status ? ` · ${statusLabels[status] || status}` : "";
  return `${base}${suffix}`;
}

function timelineFromEvent(eventName: string, payload: Record<string, unknown>): TimelineEntry | null {
  if (eventName === "status") {
    const phase = String(payload.phase || "");
    return {
      id: makeId(),
      kind: "status",
      label: friendlyPhaseLabel(phase),
      tone: phase.includes("done") ? "success" : "running",
    };
  }

  if (eventName === "tool") {
    const phase = String(payload.phase || "");
    const tool = String(payload.tool || "tool");
    const detail = summarizePreview(payload.args_preview || payload.input_preview || payload.output_preview);
    return {
      id: makeId(),
      kind: "tool",
      label: friendlyToolLabel(phase, tool),
      detail: detail || undefined,
      tone: phase === "end" ? "success" : "running",
    };
  }

  if (eventName === "orchestration") {
    const status = String(payload.status || "");
    const nodeName = String(payload.node_name || "");
    const inputs =
      payload.inputs && typeof payload.inputs === "object" ? (payload.inputs as Record<string, unknown>) : {};
    const detail = summarizePreview(inputs.error || inputs.output_preview || inputs.input_preview || "");
    return {
      id: makeId(),
      kind: "orchestration",
      label: friendlyOrchestrationLabel(status, nodeName),
      detail: detail || undefined,
      tone: status === "error" ? "error" : status === "success" ? "success" : "neutral",
      timestamp: typeof payload.timestamp === "number" ? payload.timestamp : undefined,
    };
  }

  if (eventName === "graph_data") {
    const entityCount = Number(payload.entity_count || 0);
    const tripletCount = Number(payload.triplet_count || 0);
    const entities = Array.isArray(payload.entities) ? payload.entities : [];
    const sample = entities
      .map((item) => (item && typeof item === "object" ? String((item as Record<string, unknown>).name || "") : ""))
      .filter(Boolean)
      .slice(0, 4)
      .join(", ");
    return {
      id: makeId(),
      kind: "graph",
      label: `图谱数据：${entityCount} 个实体，${tripletCount} 条关系`,
      detail: sample || undefined,
      tone: "success",
    };
  }

  return null;
}

function appendTimeline(
  messages: ChatMessage[],
  assistantId: string,
  eventName: string,
  payload: Record<string, unknown>
) {
  const entry = timelineFromEvent(eventName, payload);
  if (!entry) {
    return messages;
  }

  return messages.map((message) =>
    message.id === assistantId ? { ...message, timeline: [...(message.timeline || []), entry] } : message
  );
}

function graphFromPayload(payload: Record<string, unknown>): GraphSnapshot {
  const entities = (Array.isArray(payload.entities) ? payload.entities : [])
    .filter(
      (item): item is GraphEntity =>
        Boolean(item) && typeof item === "object" && typeof (item as GraphEntity).name === "string"
    )
    .map((item) => ({
      name: String(item.name),
      type: typeof item.type === "string" ? item.type : undefined,
      properties:
        item.properties && typeof item.properties === "object"
          ? (item.properties as Record<string, unknown>)
          : undefined,
    }));

  const triplets = (Array.isArray(payload.triplets) ? payload.triplets : [])
    .filter(
      (item): item is GraphTriplet =>
        Boolean(item) &&
        typeof item === "object" &&
        typeof (item as GraphTriplet).head === "string" &&
        typeof (item as GraphTriplet).relation === "string" &&
        typeof (item as GraphTriplet).tail === "string"
    )
    .map((item) => ({
      head: String(item.head),
      relation: String(item.relation),
      tail: String(item.tail),
      properties:
        item.properties && typeof item.properties === "object"
          ? (item.properties as Record<string, unknown>)
          : undefined,
    }));

  return { entities, triplets };
}

function appendGraphData(messages: ChatMessage[], assistantId: string, payload: Record<string, unknown>) {
  const graph = graphFromPayload(payload);
  return messages.map((message) => (message.id === assistantId ? { ...message, graph } : message));
}

function parseSseChunk(chunk: string) {
  const blocks = chunk.split("\n\n");
  const complete = chunk.endsWith("\n\n");
  const events = complete ? blocks.slice(0, -1) : blocks.slice(0, -1);
  const rest = complete ? "" : blocks[blocks.length - 1] || "";

  const parsed = events
    .map((block) => {
      const lines = block.split(/\r?\n/);
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trim());
        }
      }
      if (!dataLines.length) {
        return null;
      }
      try {
        return { event: eventName, data: JSON.parse(dataLines.join("\n")) as Record<string, unknown> };
      } catch {
        return null;
      }
    })
    .filter((item): item is { event: string; data: Record<string, unknown> } => item !== null);

  return { events: parsed, rest };
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

const starters = ["在这个仓库实现一个经典贪吃蛇", "生成应用的一页 PDF 总结", "创建一个可执行的开发计划"];

export function ChatArea() {
  const currentThreadId = useAppStore((s) => s.currentThreadId);
  const currentThreadName = useAppStore((s) => s.currentThreadName);
  const getBoundSession = useAppStore((s) => s.getBoundSession);
  const setBoundSession = useAppStore((s) => s.setBoundSession);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expandedTimeline, setExpandedTimeline] = useState<Record<string, boolean>>({});

  const listRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const chatMessages = useMemo(() => messages, [messages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chatMessages, loading]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
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
          `/api/agents/${encodeURIComponent(currentThreadId)}/conversations/${encodeURIComponent(
            sessionId
          )}/messages?limit=200&offset=0`
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
    setExpandedTimeline((prev) => ({ ...prev, [assistantId]: true }));
    setMessages((prev) => [...prev, userMessage, { id: assistantId, role: "assistant", content: "", timeline: [] }]);

    try {
      const sessionId = await ensureSession(currentThreadId);
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const response = await fetch(`/api/agents/${encodeURIComponent(currentThreadId)}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({
          message: text,
          thread_id: currentThreadId,
          conversation_id: sessionId,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`流式请求失败: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseChunk(buffer);
        buffer = parsed.rest;

        for (const evt of parsed.events) {
          if (evt.event === "token") {
            const token = String(evt.data?.text || "");
            if (token) {
              setMessages((prev) =>
                prev.map((message) => (message.id === assistantId ? { ...message, content: message.content + token } : message))
              );
            }
            continue;
          }

          if (evt.event === "status" || evt.event === "tool" || evt.event === "orchestration") {
            setMessages((prev) => appendTimeline(prev, assistantId, evt.event, evt.data));
            continue;
          }

          if (evt.event === "graph_data") {
            setMessages((prev) => appendGraphData(appendTimeline(prev, assistantId, "graph_data", evt.data), assistantId, evt.data));
            continue;
          }

          if (evt.event === "tool_confirm_required") {
            const confirmationId = String(evt.data?.confirmation_id || "");
            const toolName = String(evt.data?.tool_name || "危险工具");
            if (confirmationId) {
              setMessages((prev) =>
                appendTimeline(prev, assistantId, "tool", {
                  phase: "start",
                  tool: toolName,
                  input_preview: "等待人工审批",
                })
              );
              const approved = window.confirm(`线程将调用危险工具：${toolName}，是否继续？`);
              await fetch("/api/v1/tools/confirm", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ confirmation_id: confirmationId, approved }),
              });
              setMessages((prev) =>
                appendTimeline(prev, assistantId, "orchestration", {
                  status: approved ? "success" : "error",
                  node_name: "tool_confirmation",
                  inputs: { output_preview: approved ? "人工审批已通过" : "人工审批已拒绝" },
                })
              );
            }
            continue;
          }

          if (evt.event === "error") {
            setError(String(evt.data?.detail || "请求失败"));
            continue;
          }

          if (evt.event === "done") {
            if (!evt.data?.ok) {
              setError((prev) => prev || "生成失败");
            }
            setLoading(false);
            abortRef.current = null;
            return;
          }
        }
      }

      setLoading(false);
      abortRef.current = null;
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
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
                +
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
            const hasTimeline = !isUser && (message.timeline?.length || 0) > 0;
            const hasGraph =
              !isUser && ((message.graph?.entities.length || 0) > 0 || (message.graph?.triplets.length || 0) > 0);
            const isExpanded = expandedTimeline[message.id] ?? true;
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

                  {hasTimeline && (
                    <div className="mt-3 rounded-2xl border border-[#2b313a] bg-[#171b22]">
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedTimeline((prev) => ({
                            ...prev,
                            [message.id]: !(prev[message.id] ?? true),
                          }))
                        }
                        className="flex w-full items-center justify-between px-3 py-2 text-xs text-[#b7c0cc]"
                      >
                        <span className="inline-flex items-center gap-2">
                          <Wrench className="h-3.5 w-3.5" />
                          运行轨迹
                          <span className="rounded-full bg-[#232a33] px-2 py-0.5 text-[11px] text-[#d7dde5]">
                            {message.timeline?.length}
                          </span>
                        </span>
                        <ChevronDown className={cn("h-4 w-4 transition-transform", isExpanded && "rotate-180")} />
                      </button>

                      {isExpanded && (
                        <div className="border-t border-[#2b313a] px-3 py-2">
                          <div className="space-y-2">
                            {message.timeline?.map((item, index) => (
                              <div key={item.id} className="flex gap-3 text-sm text-[#d8dee8]">
                                <div className="flex flex-col items-center pt-1">
                                  <span
                                    className={cn(
                                      "h-2.5 w-2.5 rounded-full",
                                      item.tone === "success" && "bg-emerald-400",
                                      item.tone === "error" && "bg-rose-400",
                                      item.tone === "running" && "bg-amber-400",
                                      item.tone === "neutral" && "bg-slate-400"
                                    )}
                                  />
                                  {index < (message.timeline?.length || 0) - 1 && (
                                    <span className="mt-1 h-full w-px bg-[#2b313a]" />
                                  )}
                                </div>
                                <div className="min-w-0 flex-1 pb-2">
                                  <div className="text-sm text-[#edf2f8]">{item.label}</div>
                                  {item.detail && (
                                    <div className="mt-1 break-words text-xs text-[#8f9bab]">{item.detail}</div>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {hasGraph && <GraphPanel graph={message.graph!} />}
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
