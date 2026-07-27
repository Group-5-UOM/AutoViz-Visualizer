import { useEffect, useRef, useState, type FormEvent } from 'react';
import { SendHorizontal, Sparkles, X } from 'lucide-react';
import type { ChatMessage } from '../../types/dashboard';
import './ChatPanel.css';

interface ChatPanelProps {
  open: boolean;
  messages: ChatMessage[];
  isThinking: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onClose: () => void;
  onSend: (text: string) => void;
  onFocusChart?: (chartId: string) => void;
}

// Deliberately generic: the agent answers against whatever CSV was uploaded,
// so these have to read as prompts rather than promises about the data.
const SUGGESTIONS = [
  'Summarize this dataset',
  'Show the distribution of the main numeric column',
  'Compare the categories by average value',
  'How do the two most related columns compare?',
];

export function ChatPanel({
  open,
  messages,
  isThinking,
  disabled = false,
  disabledReason = 'Add a CSV file to start chatting.',
  onClose,
  onSend,
  onFocusChart,
}: ChatPanelProps) {
  const [draft, setDraft] = useState('');
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, isThinking, open]);

  if (!open) return null;

  const canSend = (text: string) => Boolean(text.trim()) && !isThinking && !disabled;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSend(draft)) return;
    onSend(draft);
    setDraft('');
  };

  return (
    <section className="chat-panel" aria-label="AI chat">
      <header className="chat-header">
        <div className="chat-header-title">
          <Sparkles size={16} />
          <span>AI Chat</span>
        </div>
        <button
          type="button"
          className="chat-close-btn"
          onClick={onClose}
          aria-label="Close chat"
        >
          <X size={16} />
        </button>
      </header>

      <div className="chat-messages" ref={listRef}>
        {messages.map((msg) => (
          <article
            key={msg.id}
            className={`chat-bubble chat-bubble--${msg.role}`}
          >
            <p>{msg.content}</p>
            {msg.options && msg.options.length > 0 && (
              <div className="chat-options">
                {msg.options.map((option) => (
                  <button
                    key={option.label}
                    type="button"
                    className={
                      option.recommended
                        ? 'suggestion-chip suggestion-chip--recommended'
                        : 'suggestion-chip'
                    }
                    disabled={isThinking || disabled}
                    // The label is the reply the backend matches on, so it is
                    // sent exactly as shown.
                    onClick={() => onSend(option.label)}
                    title={option.technique}
                  >
                    <span className="suggestion-chip__label">
                      {option.label}
                      {option.recommended && (
                        <span className="suggestion-chip__badge">Recommended</span>
                      )}
                    </span>
                    {option.detail && (
                      <span className="suggestion-chip__detail">{option.detail}</span>
                    )}
                  </button>
                ))}
              </div>
            )}
            {msg.chartId && onFocusChart && (
              <button
                type="button"
                className="chat-chart-link"
                onClick={() => onFocusChart(msg.chartId!)}
              >
                View on canvas
              </button>
            )}
          </article>
        ))}

        {isThinking && (
          <article className="chat-bubble chat-bubble--assistant chat-bubble--thinking">
            <span className="thinking-dots" aria-label="Thinking">
              <i />
              <i />
              <i />
            </span>
          </article>
        )}

        {messages.length <= 1 && !isThinking && !disabled && (
          <div className="chat-suggestions">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                className="suggestion-chip"
                onClick={() => onSend(s)}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>

      {disabled && (
        <div className="chat-disabled-note" role="note">
          {disabledReason}
        </div>
      )}

      <form className="chat-composer" onSubmit={handleSubmit}>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={disabled ? 'Add a CSV file first…' : 'Ask for a chart…'}
          rows={2}
          disabled={disabled}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              if (canSend(draft)) {
                onSend(draft);
                setDraft('');
              }
            }
          }}
        />
        <button
          type="submit"
          className="chat-send-btn"
          disabled={!canSend(draft)}
          aria-label="Send message"
        >
          <SendHorizontal size={18} />
        </button>
      </form>
    </section>
  );
}
