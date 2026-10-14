import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Sparkles } from 'lucide-react';
import {
  PLANNER_MODELS,
  getPlannerModel,
  setPlannerModel,
  type PlannerModelKey,
} from '../../lib/plannerModel';

export function ModelPicker({ disabled = false }: { disabled?: boolean }) {
  const [model, setModel] = useState<PlannerModelKey>(getPlannerModel);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const current = PLANNER_MODELS.find((m) => m.key === model) ?? PLANNER_MODELS[0];

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('keydown', onKeyDown, true);
    };
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const choose = (key: PlannerModelKey) => {
    setPlannerModel(key);
    setModel(key);
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div className="model-picker" ref={rootRef}>
      {open && (
        <div className="model-picker__menu" role="listbox" aria-label="Model">
          {PLANNER_MODELS.map((m) => (
            <button
              key={m.key}
              type="button"
              role="option"
              aria-selected={m.key === model}
              className="model-picker__option"
              onClick={() => choose(m.key)}
            >
              <span className="model-picker__text">
                <span className="model-picker__label">{m.label}</span>
                <span className="model-picker__hint">{m.hint}</span>
              </span>
              {m.key === model && <Check size={14} className="model-picker__check" />}
            </button>
          ))}
        </div>
      )}
      <button
        ref={triggerRef}
        type="button"
        className="model-picker__trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Model: ${current.label}`}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <Sparkles size={12} aria-hidden="true" />
        <span>{current.label}</span>
        <ChevronDown size={12} aria-hidden="true" className="model-picker__chevron" />
      </button>
    </div>
  );
}
