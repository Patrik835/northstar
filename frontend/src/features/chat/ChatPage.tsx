export function ChatPage() {
  return <><header className="page-header"><div><p className="eyebrow">Portfolio-aware</p><h1>AI assistant</h1></div></header><section className="panel chat-placeholder"><div><span className="empty-mark">✦</span><h2>Ask your portfolio</h2><p className="muted">The conversation UI is scaffolded. It will activate when the OpenAI service, stored history endpoints, and portfolio context builder are implemented.</p><div className="disclaimer">Informational and educational only—not financial advice.</div></div><div className="chat-input"><input disabled placeholder="How diversified is my portfolio?"/><button disabled>Send</button></div></section></>;
}

