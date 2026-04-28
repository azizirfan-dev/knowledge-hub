"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type AgentType = "TECHNICAL_AGENT" | "HR_AGENT" | "GENERAL_AGENT";

interface SourceRef {
  source: string;
  page: string | number | null;
}

interface ChatMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  agent?: AgentType;
  collection?: string | null;
  streaming?: boolean;
  toolName?: string;
  toolStatus?: "calling" | "done";
  sources?: SourceRef[];
}

const AGENT_LABELS: Record<AgentType, string> = {
  TECHNICAL_AGENT: "Technical Agent",
  HR_AGENT: "HR Agent",
  GENERAL_AGENT: "General Agent",
};

const AGENT_TAG_CLASS: Record<AgentType, string> = {
  TECHNICAL_AGENT: "neo-tag-technical",
  HR_AGENT: "neo-tag-hr",
  GENERAL_AGENT: "neo-tag-general",
};

function AgentBadge({ agent, collection }: { agent: AgentType; collection?: string | null }) {
  return (
    <div className="flex gap-2 mt-2 flex-wrap">
      <span className={`neo-tag ${AGENT_TAG_CLASS[agent]}`}>
        {AGENT_LABELS[agent]}
      </span>
      {collection && (
        <span className="neo-tag bg-white text-black">
          {collection}
        </span>
      )}
    </div>
  );
}

function ToolTrace({ msg }: { msg: ChatMessage }) {
  if (!msg.toolName) return null;
  const isCalling = msg.toolStatus === "calling";
  const sourceCount = msg.sources?.length ?? 0;
  return (
    <div className="mt-2 mb-1 px-3 py-2 border-2 border-black bg-yellow-100 text-xs font-bold">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="uppercase tracking-wider">
          {isCalling ? "🔍 Memanggil tool" : "✓ Tool selesai"}
        </span>
        <code className="bg-black text-yellow-100 px-2 py-0.5">{msg.toolName}</code>
        {msg.collection && (
          <span className="text-black/70">→ collection <code>{msg.collection}</code></span>
        )}
        {!isCalling && sourceCount > 0 && (
          <span className="text-black/70">· {sourceCount} dokumen relevan</span>
        )}
      </div>
    </div>
  );
}

function SourcePanel({ sources }: { sources: SourceRef[] }) {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="mt-3 pt-2 border-t-2 border-black/20">
      <div className="text-[10px] uppercase tracking-widest font-black mb-1.5 text-black/60">
        Sumber Dokumen
      </div>
      <div className="flex gap-1.5 flex-wrap">
        {sources.map((s, i) => (
          <span
            key={`${s.source}-${s.page}-${i}`}
            className="neo-tag bg-white text-black text-[10px] py-1 px-2"
            title={`${s.source} — halaman/chunk ${s.page ?? "?"}`}
          >
            📄 {s.source} <span className="opacity-60">· hal {String(s.page ?? "?")}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="chat-bubble-user">
          <p className="text-sm font-semibold whitespace-pre-wrap">{msg.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="chat-bubble-agent">
        <ToolTrace msg={msg} />
        <p className="text-sm font-medium whitespace-pre-wrap leading-relaxed">
          {msg.content}
          {msg.streaming && (
            <span className="inline-block w-2 h-4 bg-black ml-0.5 animate-pulse" />
          )}
        </p>
        {!msg.streaming && msg.agent && (
          <AgentBadge agent={msg.agent} collection={msg.collection} />
        )}
        {!msg.streaming && msg.sources && msg.sources.length > 0 && (
          <SourcePanel sources={msg.sources} />
        )}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const n = sessionStorage.getItem("kb_name");
    const r = sessionStorage.getItem("kb_role");
    if (!n || !r) {
      router.replace("/");
      return;
    }
    setName(n);
    setRole(r);
  }, [router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleLogout() {
    abortRef.current?.abort();
    sessionStorage.removeItem("kb_name");
    sessionStorage.removeItem("kb_role");
    router.replace("/");
  }

  const buildHistory = useCallback(() => {
    return messages
      .filter((m) => !m.streaming)
      .map((m) => ({ role: m.role === "user" ? "user" : "assistant", content: m.content }));
  }, [messages]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || isStreaming) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };

    const agentMsgId = crypto.randomUUID();
    const agentMsg: ChatMessage = {
      id: agentMsgId,
      role: "agent",
      content: "",
      streaming: true,
    };

    setMessages((prev) => [...prev, userMsg, agentMsg]);
    setInput("");
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          role,
          message: text,
          history: buildHistory(),
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Server error ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          try {
            const event = JSON.parse(raw);

            if (event.token !== undefined) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === agentMsgId
                    ? { ...m, content: m.content + event.token }
                    : m
                )
              );
            }

            if (event.tool_call) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === agentMsgId
                    ? {
                        ...m,
                        toolName: event.tool_name,
                        toolStatus: "calling",
                        collection: event.collection ?? null,
                        sources: event.sources ?? [],
                      }
                    : m
                )
              );
            }

            if (event.done) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === agentMsgId
                    ? {
                        ...m,
                        streaming: false,
                        agent: event.agent as AgentType,
                        collection: event.collection ?? null,
                        toolStatus: m.toolName ? "done" : m.toolStatus,
                        sources:
                          event.sources && event.sources.length > 0
                            ? event.sources
                            : m.sources,
                      }
                    : m
                )
              );
            }
          } catch {
            // skip malformed events
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === agentMsgId
            ? {
                ...m,
                content: "Error: could not reach the server. Is the API running?",
                streaming: false,
                agent: "GENERAL_AGENT",
              }
            : m
        )
      );
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="flex flex-col h-screen bg-white">
      {/* Top bar */}
      <header className="flex items-center justify-between px-4 py-3 border-b-[3px] border-black bg-[#FFD700]">
        <div className="flex items-center gap-3">
          <div className="neo-box-sm bg-black text-[#FFD700] px-2 py-0.5 text-xs font-black uppercase tracking-widest">
            KnowledgeHub
          </div>
          <div className="hidden sm:block">
            <span className="font-black text-sm">{name}</span>
            <span className="mx-2 text-black/40">·</span>
            <span className="text-xs font-bold uppercase tracking-wide">{role}</span>
          </div>
        </div>
        <button
          onClick={handleLogout}
          className="neo-btn neo-btn-outline text-xs py-2 px-4 font-black uppercase tracking-wider"
        >
          Logout
        </button>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto scrollbar-hide px-4 py-6">
        <div className="max-w-2xl mx-auto flex flex-col gap-4">
          {messages.length === 0 && (
            <div className="text-center py-16">
              <div className="neo-box inline-block bg-[#FFD700] px-6 py-4 mb-4">
                <p className="font-black text-xl uppercase">Hello, {name}!</p>
              </div>
              <p className="text-sm font-medium text-gray-500">
                Ask anything about internal documents.
              </p>
              <p className="text-xs font-medium text-gray-400 mt-1">
                Shift+Enter for new line · Enter to send
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}

          {isStreaming && (
            <div className="flex items-center gap-2 ml-1">
              <div className="neo-spinner" style={{ width: "1.2rem", height: "1.2rem" }} />
              <span className="text-xs font-bold text-gray-500 uppercase tracking-widest">
                Thinking...
              </span>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input bar */}
      <div className="border-t-[3px] border-black px-4 py-3 bg-white">
        <div className="max-w-2xl mx-auto flex gap-3">
          <div className="flex-1 neo-box-sm relative">
            <textarea
              ref={inputRef}
              className="w-full resize-none bg-white p-3 text-sm font-medium outline-none min-h-[3rem] max-h-36"
              placeholder="Ask a question..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              disabled={isStreaming}
            />
          </div>
          <button
            onClick={sendMessage}
            disabled={isStreaming || !input.trim()}
            className="neo-btn font-black text-sm uppercase tracking-wider disabled:opacity-40 disabled:cursor-not-allowed disabled:transform-none disabled:shadow-[4px_4px_0px_#000] self-end py-3 px-5"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
