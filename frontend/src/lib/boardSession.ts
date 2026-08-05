import type { ChatMessage } from '../types/dashboard';

export interface BoardSession {
  dashboardId?: string | null;
  messages?: ChatMessage[];
  updatedAt: number;
}

const keyFor = (datasetId: string) => `autoviz:board-session:${datasetId}`;

export function loadBoardSession(datasetId: string): BoardSession | null {
  try {
    const raw = localStorage.getItem(keyFor(datasetId));
    if (!raw) return null;
    return JSON.parse(raw) as BoardSession;
  } catch {
    return null;
  }
}

export function saveBoardSession(
  datasetId: string,
  patch: Partial<Omit<BoardSession, 'updatedAt'>>,
): void {
  try {
    const prev = loadBoardSession(datasetId) ?? { updatedAt: 0 };
    const next: BoardSession = {
      ...prev,
      ...patch,
      updatedAt: Date.now(),
    };
    localStorage.setItem(keyFor(datasetId), JSON.stringify(next));
  } catch {
    /* ignore quota / private mode */
  }
}
