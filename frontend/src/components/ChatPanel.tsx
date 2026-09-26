"use client";

import { ArrowUp, Bot, Check, MessageCircle, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { postChat } from "@/lib/api";
import type { ChatAction, ChatMessage, UiState } from "@/lib/types";

interface ChatPanelProps {
  cityName: string;
  slug: string;
  uiState: UiState;
  onActions: (actions: ChatAction[]) => void;
}

interface ChatEntry extends ChatMessage {
  id: number;
  actions?: ChatAction[];
  fallback?: boolean;
}

const STARTERS = [
  "Summarize this city",
  "Why is the reddest area red?",
  "Show the top scenario",
  "Download the briefing",
];

function actionLabel(action: ChatAction) {
  switch (action.type) {
    case "select_hex": return "Selected an area";
    case "highlight_scenario": return "Opened a scenario";
    case "open_panel": return `Opened ${action.panel === "comparison" ? "comparison" : action.panel}`;
    case "toggle_crashes": return action.on ? "Showing crashes" : "Hid crashes";
    case "fly_to": return "Moved the map";
    case "open_city": return "Opened a city";
    case "download_briefing": return `Downloaded .${action.format} briefing`;
  }
}

export function ChatPanel({ cityName, slug, uiState, onActions }: ChatPanelProps) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [input, setInput] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState("");
  const nextId = useRef(1);
  const messagesRef = useRef<HTMLDivElement>(null);

  // Scroll only the message list. scrollIntoView would also scroll .evidence-panel sideways toward the
  // closed (off-panel) drawer, hiding the tabs.
  useEffect(() => {
    const list = messagesRef.current;
    list?.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
  }, [entries, waiting, error]);

  async function send(text: string) {
    const cleaned = text.trim();
    if (!cleaned || waiting) return;

    const userEntry: ChatEntry = { id: nextId.current++, role: "user", text: cleaned };
    const messages = [...entries, userEntry]
      .slice(-10)
      .map(({ role, text: messageText }) => ({ role, text: messageText }));
    setEntries((current) => [...current, userEntry]);
    setInput("");
    setError("");
    setWaiting(true);

    try {
      const response = await postChat(slug, messages, uiState);
      onActions(Array.isArray(response.actions) ? response.actions : []);
      setEntries((current) => [
        ...current,
        {
          id: nextId.current++,
          role: "model",
          text: response.reply,
          actions: response.actions,
          fallback: response.fallback,
        },
      ]);
    } catch {
      setError("Couldn't reach the assistant. Try again.");
    } finally {
      setWaiting(false);
    }
  }

  return (
    <div className={`city-chat${open ? " is-open" : ""}`}>
      <button
        type="button"
        className="chat-launcher"
        aria-expanded={open}
        aria-controls="cityshift-chat-drawer"
        onClick={() => setOpen(true)}
      >
        <MessageCircle size={17} /> Ask CityShift
      </button>

      <section id="cityshift-chat-drawer" className="chat-drawer" aria-label={`Ask CityShift about ${cityName}`} aria-hidden={!open}>
        <header className="chat-header">
          <div className="chat-mark"><Sparkles size={16} /></div>
          <div><small>City data assistant</small><h2>Ask CityShift</h2></div>
          <button type="button" aria-label="Close assistant" onClick={() => setOpen(false)}><X size={18} /></button>
        </header>

        <div className="chat-messages" aria-live="polite" ref={messagesRef}>
          {entries.length === 0 && (
            <div className="chat-welcome">
              <Bot size={22} />
              <h3>Explore {cityName}</h3>
              <p>Ask for a summary, inspect an area, or move through the evidence without leaving the map.</p>
              <div className="chat-starters">
                {STARTERS.map((starter) => (
                  <button type="button" key={starter} disabled={waiting} onClick={() => void send(starter)}>{starter}</button>
                ))}
              </div>
            </div>
          )}

          {entries.map((entry) => (
            <article key={entry.id} className={`chat-message is-${entry.role}`}>
              <small>{entry.role === "user" ? "You" : "CityShift"}</small>
              <div className="chat-markdown"><ReactMarkdown skipHtml>{entry.text}</ReactMarkdown></div>
              {entry.role === "model" && entry.actions && entry.actions.length > 0 && (
                <div className="chat-action-trace">
                  {entry.actions.map((action, index) => (
                    <span key={`${entry.id}-${index}`}><Check size={11} /> {actionLabel(action)}</span>
                  ))}
                </div>
              )}
              {entry.fallback && <p className="chat-fallback">AI unavailable. Showing a data summary.</p>}
            </article>
          ))}

          {waiting && <div className="chat-typing"><span /><span /><span /><b>Reading city data</b></div>}
          {error && <p className="chat-error" role="alert">{error}</p>}
        </div>

        <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); void send(input); }}>
          <label htmlFor="cityshift-chat-input">Ask about this city</label>
          <div>
            <input
              id="cityshift-chat-input"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about an area or scenario…"
              disabled={waiting}
              autoComplete="off"
            />
            <button type="submit" aria-label="Send message" disabled={waiting || !input.trim()}><ArrowUp size={17} /></button>
          </div>
        </form>
        <footer>AI answers use only CityShift&apos;s data. Red = unfamiliar to the car, not dangerous.</footer>
      </section>
    </div>
  );
}
