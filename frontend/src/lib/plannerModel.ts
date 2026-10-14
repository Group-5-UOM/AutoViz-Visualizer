export const PLANNER_MODELS = [
  { key: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
  { key: 'qwen3.5-4b', label: 'Qwen 3.5 4B' },
] as const;

export type PlannerModelKey = (typeof PLANNER_MODELS)[number]['key'];

const STORAGE_KEY = 'autoviz:planner-model';
const DEFAULT_MODEL: PlannerModelKey = 'gemini-3.5-flash';

const isKnown = (key: string | null): key is PlannerModelKey =>
  PLANNER_MODELS.some((m) => m.key === key);

let current: PlannerModelKey = (() => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isKnown(stored) ? stored : DEFAULT_MODEL;
  } catch {
    return DEFAULT_MODEL;
  }
})();

export function getPlannerModel(): PlannerModelKey {
  return current;
}

export function setPlannerModel(key: PlannerModelKey): void {
  current = key;
  try {
    localStorage.setItem(STORAGE_KEY, key);
  } catch {
    return;
  }
}
