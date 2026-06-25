"use client";

import { useRef, useState } from "react";
import { Bot, Send, Sparkles, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

type Role = "user" | "assistant";
type Message = { role: Role; content: string };

const MODELS = [
  { id: "anthropic/claude-opus-4.8", label: "Opus 4.8" },
  { id: "anthropic/claude-sonnet-4.6", label: "Sonnet 4.6" },
  { id: "google/gemini-2.5-flash", label: "Gemini Flash" },
];

const SUGGESTIONS = [
  "What's the single most important thing in today's digest?",
  "Did I already act on the last few recommendations?",
  "How concentrated is my book, and what's the biggest risk?",
];

export function DigestChat({ digestDate }: { digestDate: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState(MODELS[0].id);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
  };

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || isStreaming) return;
    setError(null);
    setInput("");

    const history: Message[] = [...messages, { role: "user", content: trimmed }];
    // Append the user message and an empty assistant message to stream into.
    setMessages([...history, { role: "assistant", content: "" }]);
    setIsStreaming(true);
    scrollToBottom();

    try {
      const res = await fetch("/api/digest/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages: history, digestDate, model }),
      });
      if (!res.ok || !res.body) {
        throw new Error(`chat failed (${res.status})`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let streaming = true;

      while (streaming) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const frames = buf.split("\n\n");
        buf = frames.pop() ?? "";
        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (payload === "[DONE]") {
            streaming = false;
            break;
          }
          let token = "";
          try {
            token = JSON.parse(payload) as string;
          } catch {
            continue;
          }
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.role === "assistant") {
              next[next.length - 1] = { ...last, content: last.content + token };
            }
            return next;
          });
          scrollToBottom();
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "chat failed");
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === "assistant" && last.content === "") next.pop();
        return next;
      });
    } finally {
      setIsStreaming(false);
      scrollToBottom();
    }
  }

  return (
    <section className="rounded-xl border border-border bg-card">
      <header className="flex flex-col gap-2 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <h2 className="text-base font-semibold tracking-normal text-foreground">
            Ask about this digest
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Model</span>
          <Select value={model} onValueChange={setModel}>
            <SelectTrigger className="h-8 w-[150px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MODELS.map((m) => (
                <SelectItem key={m.id} value={m.id} className="text-xs">
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </header>

      <div ref={scrollRef} className="max-h-[28rem] overflow-y-auto px-4 py-4">
        {messages.length === 0 ? (
          <div className="flex flex-col gap-3 py-2">
            <p className="text-sm text-muted-foreground">
              Chat with full context of your portfolio, holdings, the congressional
              signal, and the last several days of digests.
            </p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  className="rounded-full border border-border bg-secondary px-3 py-1 text-xs text-foreground hover:bg-secondary/70"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ul className="flex flex-col gap-4">
            {messages.map((m, i) => (
              <li key={i} className="flex gap-3">
                <div
                  className={cn(
                    "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border",
                    m.role === "user" ? "bg-secondary" : "bg-primary/15 text-primary",
                  )}
                >
                  {m.role === "user" ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium uppercase tracking-normal text-muted-foreground">
                    {m.role === "user" ? "You" : "Analyst"}
                  </div>
                  <div className="mt-1 whitespace-pre-wrap break-words text-sm text-foreground">
                    {m.content || (isStreaming && i === messages.length - 1 ? "…" : "")}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error ? (
        <div className="border-t border-border px-4 py-2 text-xs text-destructive-foreground">
          {error}
        </div>
      ) : null}

      <form
        className="flex items-center gap-2 border-t border-border p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about today's digest, your holdings, the cash plan…"
          disabled={isStreaming}
          aria-label="Chat message"
        />
        <Button type="submit" size="icon" disabled={isStreaming || !input.trim()}>
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </section>
  );
}
