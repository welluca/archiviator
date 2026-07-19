import apiClient from './client';
import type { Attachment, Entity } from '../types';

/** POST /intake/capture — one round trip: draft item in the Inbox with the
 * photo attached and set as cover. */
export interface CaptureResult {
  entity: Entity;
  attachment: Attachment;
}

export interface PromotePayload {
  entity_ids: number[];
  /** Move each entity here (containment validated per entity). Omit = stay put. */
  parent_id?: number;
  /** Set the category (null clears). Omit = keep current. */
  category_id?: number | null;
  /** REPLACES the full tag set. Omit = keep current. */
  tags?: string[];
  clear_draft: true;
}

export interface PromoteError {
  entity_id: number;
  message: string;
}

/** Per-entity error isolation: each entity is fully applied or untouched —
 * one failing containment check does not abort the rest. */
export interface PromoteResult {
  promoted: Entity[];
  errors: PromoteError[];
}

export const intakeApi = {
  /** Quick capture. Same upload pipeline / limits as attachments (415/413).
   * Name defaults server-side to 'Capture YYYY-MM-DD HH:MM:SS'. */
  async capture(
    file: File,
    opts: { name?: string; note?: string; signal?: AbortSignal } = {}
  ): Promise<CaptureResult> {
    const form = new FormData();
    form.append('file', file);
    if (opts.name) form.append('name', opts.name);
    if (opts.note) form.append('note', opts.note);
    // Axios drops the JSON default Content-Type for FormData so the browser
    // sets the multipart boundary itself.
    const { data } = await apiClient.post<CaptureResult>('/intake/capture', form, {
      signal: opts.signal,
    });
    return data;
  },

  /** ALL draft entities (wherever they live), newest first. */
  async drafts(): Promise<Entity[]> {
    const { data } = await apiClient.get<Entity[]>('/intake/drafts');
    return data;
  },

  /** Batch-file drafts into real locations — always check `errors`. */
  async promote(payload: PromotePayload): Promise<PromoteResult> {
    const { data } = await apiClient.post<PromoteResult>('/intake/promote', payload);
    return data;
  },
};
