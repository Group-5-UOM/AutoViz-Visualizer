import { useEffect, useRef, useState, type FormEvent } from 'react';
import { AlertTriangle, AtSign, BarChart3, Info, RotateCcw, SendHorizontal, X } from 'lucide-react';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';
import { MessageContent } from './MessageContent';
import type { ChartWidget, ChatMessage } from '../../types/dashboard';
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
  /**
   * Charts that can be attached to a message. Only those this conversation
   * produced: one restored from a saved dashboard has no thread behind it, so
   * there is nothing for a request to modify.
   */
  referenceable?: ChartWidget[];
  referencedWidgetId?: string | null;
  onReference?: (id: string | null) => void;
  /** The newest turn failed in a way that re-running it may fix. */
  canRetry?: boolean;
  /** Re-run the failed turn without the user retyping it. */
  onRetry?: () => void;
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
  referenceable = [],
  referencedWidgetId = null,
  onReference,
  canRetry = false,
  onRetry,
}: ChatPanelProps) {
  const [draft, setDraft] = useState('');
  const [picking, setPicking] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const referenced = referenceable.find((w) => w.id === referencedWidgetId) ?? null;

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, isThinking, open]);

  useEscapeToClose(onClose, open);

  if (!open) return null;

  const canSend = (text: string) => Boolean(text.trim()) && !isThinking && !disabled;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSend(draft)) return;
    onSend(draft);
    setDraft('');
  };

  const attach = (id: string | null) => {
    onReference?.(id);
    setPicking(false);
  };

  return (
    <section className="chat-panel" aria-label="AI chat">
      <div className="chat-messages" ref={listRef}>
        {messages.map((msg, index) => (
          <article
            key={msg.id}
            className={`chat-bubble chat-bubble--${msg.role}${
              msg.tone ? ` chat-bubble--${msg.tone}` : ''
            }`}
          >
            {msg.referencedTitle && (
              <p className="chat-bubble-reference" title={msg.referencedTitle}>
                <AtSign size={11} />
                {msg.referencedTitle}
              </p>
            )}
            {/* Carries the same distinction the bubble's colour does, for
                readers who cannot use colour to make it. */}
            {msg.tone && (
              <p className="chat-bubble-tone">
                {msg.tone === 'validation' ? <Info size={12} /> : <AlertTriangle size={12} />}
                {msg.tone === 'validation' ? 'Request not accepted' : 'Something went wrong'}
              </p>
            )}
            <MessageContent content={msg.content} role={msg.role} />
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
            {/* Only on the newest turn: an older failure has been superseded by
                whatever the user did next, and retrying it would replay a
                request from the middle of the conversation. */}
            {msg.tone === 'error' &&
              index === messages.length - 1 &&
              canRetry &&
              onRetry &&
              !isThinking && (
                <button type="button" className="chat-retry-btn" onClick={onRetry}>
                  <RotateCcw size={13} />
                  Try again
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

      {picking && referenceable.length > 0 && (
        <div className="chat-picker" role="listbox" aria-label="Charts on the canvas">
          {referenceable.map((w) => (
            <button
              key={w.id}
              type="button"
              role="option"
              aria-selected={w.id === referencedWidgetId}
              className="chat-picker-item"
              onClick={() => attach(w.id)}
            >
              <BarChart3 size={13} />
              <span>{w.title}</span>
            </button>
          ))}
        </div>
      )}

      {referenced && (
        <div className="chat-reference">
          <AtSign size={12} />
          <span className="chat-reference-title" title={referenced.title}>
            {referenced.title}
          </span>
          <button
            type="button"
            aria-label={`Stop editing ${referenced.title}`}
            onClick={() => attach(null)}
          >
            <X size={12} />
          </button>
        </div>
      )}

      <form className="chat-composer" onSubmit={handleSubmit}>
        {onReference && referenceable.length > 0 && (
          <button
            type="button"
            className="chat-attach-btn"
            title="Reference a chart"
            aria-label="Reference a chart"
            aria-expanded={picking}
            disabled={disabled}
            onClick={() => setPicking((on) => !on)}
          >
            <AtSign size={16} />
          </button>
        )}
        <textarea
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            // Typing "@" opens the picker, the same gesture as referencing a
            // file elsewhere. The character is left in the draft and simply
            // reads as part of the sentence if nothing is picked.
            if (e.target.value.endsWith('@') && referenceable.length > 0) setPicking(true);
          }}
          placeholder={
            disabled
              ? 'Add a CSV file first…'
              : referenced
                ? `Change "${referenced.title}"…`
                : 'Ask for a chart, or @ to reference one…'
          }
          rows={2}
          disabled={disabled}
          onKeyDown={(e) => {
            if (e.key === 'Escape' && picking) {
              e.preventDefault();
              setPicking(false);
              return;
            }
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
