import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, streamApi } from "../../api/client";
import type { Conversation, FeatureStatus, PortfolioReview } from "../../api/types";
import { MarkdownContent } from "../../components/MarkdownContent";

function when(value: string) {
  return new Intl.DateTimeFormat("en-IE", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function ChatPage() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [review, setReview] = useState<PortfolioReview | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const active = conversations.find((item) => item.id === activeId) ?? null;

  async function refresh() {
    const [latestReview, items] = await Promise.all([
      api<PortfolioReview | null>("/assistant/review"),
      api<Conversation[]>("/assistant/conversations"),
    ]);
    setReview(latestReview);
    setConversations(items);
    setActiveId((current) => current && items.some((item) => item.id === current)
      ? current
      : items[0]?.id ?? null);
  }

  useEffect(() => {
    api<FeatureStatus>("/dashboard/features").then((features) => {
      setEnabled(features.ai);
      if (features.ai) refresh().catch((reason: Error) => setError(reason.message));
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active?.messages]);

  async function generateReview(force = false) {
    setReviewBusy(true);
    setError("");
    try {
      setReview(await api<PortfolioReview>(`/assistant/review${force ? "?force=true" : ""}`, { method: "POST" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not generate review");
    } finally {
      setReviewBusy(false);
    }
  }

  async function newConversation() {
    const item = await api<Conversation>("/assistant/conversations", { method: "POST" });
    setConversations((current) => [item, ...current]);
    setActiveId(item.id);
  }

  async function removeConversation(id: string) {
    await api<void>(`/assistant/conversations/${id}`, { method: "DELETE" });
    const next = conversations.filter((item) => item.id !== id);
    setConversations(next);
    setActiveId(next[0]?.id ?? null);
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!active) return;
    const form = event.currentTarget;
    const input = form.elements.namedItem("message") as HTMLTextAreaElement;
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    setBusy(true);
    setError("");
    const userId = `local-user-${Date.now()}`;
    const assistantId = `local-assistant-${Date.now()}`;
    const now = new Date().toISOString();
    setConversations((current) => current.map((item) => item.id === active.id ? {
      ...item,
      messages: [
        ...item.messages,
        { id: userId, role: "user", content: message, created_at: now },
        { id: assistantId, role: "assistant", content: "", created_at: now },
      ],
    } : item));
    try {
      await streamApi(`/assistant/conversations/${active.id}/messages/stream`, { message }, (type, data) => {
        if (type === "error") throw new Error(String(data.message ?? "The response failed"));
        if (type !== "delta") return;
        setConversations((current) => current.map((item) => item.id === active.id ? {
          ...item,
          messages: item.messages.map((entry) => entry.id === assistantId
            ? { ...entry, content: entry.content + String(data.text ?? "") }
            : entry),
        } : item));
      });
      await refresh();
      setActiveId(active.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send message");
      setConversations((current) => current.map((item) => item.id === active.id
        ? { ...item, messages: item.messages.filter((entry) => entry.id !== assistantId) }
        : item));
    } finally {
      setBusy(false);
    }
  }

  if (enabled === false) return <>
    <header className="page-header"><div><p className="eyebrow">Portfolio-aware</p><h1>AI assistant</h1></div></header>
    <section className="panel assistant-unavailable"><h2>Assistant is off</h2><p className="muted">Configure the server-side OpenAI key and enable AI when you are ready. Your portfolio remains fully usable without it.</p></section>
  </>;

  return <>
    <header className="page-header compact-page-header">
      <div><p className="eyebrow">Portfolio-aware</p><h1>AI assistant</h1></div>
      <span className="as-of">Redacted analytics · processed by OpenAI</span>
    </header>
    {error && <p className="error">{error}</p>}

    <section className="panel review-card">
      <div className="panel-heading">
        <div><p className="eyebrow">Evidence-based review</p><h2>Portfolio insights</h2></div>
        <button
          className="secondary compact-button review-generate-button"
          disabled={reviewBusy}
          aria-busy={reviewBusy}
          onClick={() => void generateReview(Boolean(review))}
        >
          {reviewBusy && <span className="review-loading-spinner" aria-hidden="true" />}
          <span aria-live="polite">
            {reviewBusy ? "Generating…" : review ? "Refresh" : "Generate"}
          </span>
        </button>
      </div>
      {review ? <>
        <MarkdownContent className="review-content" content={review.content} />
        <small>Generated {when(review.generated_at)} · {review.context_version}</small>
      </> : <p className="muted">Generate improvement priorities and deeper insights from your portfolio analytics.</p>}
    </section>

    <section className="assistant-layout">
      <aside className="panel conversation-sidebar">
        <button className="secondary new-chat-button" onClick={() => void newConversation()}>New conversation</button>
        <div className="conversation-list">
          {conversations.map((item) => <button
            key={item.id}
            className={item.id === activeId ? "active" : ""}
            onClick={() => setActiveId(item.id)}
          ><strong>{item.title}</strong><small>{when(item.updated_at)}</small></button>)}
        </div>
      </aside>

      <article className="panel chat-panel">
        {active ? <>
          <div className="chat-toolbar">
            <strong>{active.title}</strong>
            <button className="text-button muted-action" onClick={() => void removeConversation(active.id)}>Delete</button>
          </div>
          <div className="message-list">
            {active.messages.length ? active.messages.map((message) => (
              <div className={`chat-message ${message.role}`} key={message.id}>
                <small>{message.role === "user" ? "You" : "Northstar"}</small>
                {message.content
                  ? message.role === "assistant"
                    ? <MarkdownContent content={message.content} />
                    : <p>{message.content}</p>
                  : <p><span className="typing">Thinking…</span></p>}
              </div>
            )) : <div className="chat-empty"><h2>Ask about your portfolio</h2><p className="muted">Try “What would most improve my risk-adjusted portfolio construction?”</p></div>}
            <div ref={endRef} />
          </div>
          <form className="assistant-composer" onSubmit={send}>
            <textarea name="message" rows={2} maxLength={2000} disabled={busy} placeholder="Ask about diversification, risk, targets, or data quality…" />
            <button className="primary" disabled={busy}>Send</button>
          </form>
        </> : <div className="chat-empty"><h2>Start a conversation</h2><p className="muted">Questions are answered from your latest calculated portfolio context.</p><button className="primary" onClick={() => void newConversation()}>New conversation</button></div>}
      </article>
    </section>
    <p className="assistant-disclaimer">Informational and educational only—not financial advice. AI can be wrong; verify important decisions independently.</p>
  </>;
}
