// Framework-free offers client and helpers (INK-131, decision 0097). Fetch is injected like ask.ts.
export interface Offer {
  id: string;
  document_id: string;
  kind: string;
  anchor_chunk: string;
  reason: string;
  payload: Record<string, unknown>;
  score: number;
  status: string;
}
