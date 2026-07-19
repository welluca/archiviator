import apiClient from './client';
import type {
  Entity,
  EntityKind,
  LabelBatch,
  LabelResolveResult,
  LabelTemplate,
  PrintedLabel,
} from '../types';

/** Same normalization the backend applies everywhere: trim + uppercase. */
export const normalizeTag = (raw: string): string => raw.trim().toUpperCase();

/** Payload for the create-variant of claim (normal containment rules apply). */
export interface ClaimCreatePayload {
  name: string;
  kind: EntityKind;
  parent_id: number | null;
  subtype?: string;
  description?: string;
}

export interface CreateBatchPayload {
  template_id: number;
  /** Blank-labels mode: allocate this many NEW tags. */
  count?: number;
  /** Existing-entities mode: print labels for these entities. */
  entity_ids?: number[];
  /** Positions to leave empty on a partially-used sheet. */
  skip_first?: number;
  note?: string;
}

let cachedBaseUrl: string | null = null;

export const labelsApi = {
  /** Public base URL QR codes point at ({base_url}/a/{tag}) — cached. */
  async getConfig(): Promise<{ base_url: string }> {
    if (cachedBaseUrl !== null) return { base_url: cachedBaseUrl };
    const { data } = await apiClient.get<{ base_url: string }>('/labels/config');
    cachedBaseUrl = data.base_url;
    return data;
  },

  /** Case-insensitive lookup; 404 (unknown or void tag) rejects. */
  async resolve(tag: string): Promise<LabelResolveResult> {
    const { data } = await apiClient.get<LabelResolveResult>(
      `/labels/resolve/${encodeURIComponent(normalizeTag(tag))}`
    );
    return data;
  },

  /** Bind an unclaimed printed label to an existing entity. */
  async claimExisting(tag: string, entityId: number): Promise<Entity> {
    const { data } = await apiClient.post<Entity>(
      `/labels/${encodeURIComponent(normalizeTag(tag))}/claim`,
      { entity_id: entityId }
    );
    return data;
  },

  /** Create a new entity and bind the label to it in one transaction. */
  async claimCreate(tag: string, create: ClaimCreatePayload): Promise<Entity> {
    const { data } = await apiClient.post<Entity>(
      `/labels/${encodeURIComponent(normalizeTag(tag))}/claim`,
      { create }
    );
    return data;
  },

  /** unclaimed -> void only; 409 otherwise. */
  async voidLabel(tag: string): Promise<PrintedLabel> {
    const { data } = await apiClient.post<PrintedLabel>(
      `/labels/${encodeURIComponent(normalizeTag(tag))}/void`
    );
    return data;
  },

  async templates(): Promise<LabelTemplate[]> {
    const { data } = await apiClient.get<LabelTemplate[]>('/labels/templates');
    return data;
  },

  async createBatch(payload: CreateBatchPayload): Promise<LabelBatch> {
    const { data } = await apiClient.post<LabelBatch>('/labels/batches', payload);
    return data;
  },

  async listBatches(): Promise<LabelBatch[]> {
    const { data } = await apiClient.get<LabelBatch[]>('/labels/batches');
    return data;
  },

  async getBatch(id: number): Promise<LabelBatch> {
    const { data } = await apiClient.get<LabelBatch>(`/labels/batches/${id}`);
    return data;
  },

  /** Bearer-authed PDF download: axios blob -> object URL -> a.click(). */
  async downloadBatchPdf(id: number): Promise<void> {
    const { data } = await apiClient.get<Blob>(`/labels/batches/${id}/pdf`, {
      responseType: 'blob',
    });
    const url = URL.createObjectURL(data);
    const a = document.createElement('a');
    a.href = url;
    a.download = `batch-${id}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Immediate revocation has historically aborted in-flight downloads in
    // some browsers; defer it well past the click.
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  },
};

export type AssignTagPayload = { auto: true } | { tag: string | null };

/** Assign / clear an entity's asset tag. auto -> next free from the sequence;
 * a tag matching an unclaimed printed label runs the full claim flow;
 * null clears (a claimed printed label reverts to 'unclaimed'). */
export async function assignAssetTag(
  entityId: number,
  payload: AssignTagPayload
): Promise<Entity> {
  const body =
    'auto' in payload ? { auto: true } : { tag: payload.tag === null ? null : normalizeTag(payload.tag) };
  const { data } = await apiClient.post<Entity>(`/entities/${entityId}/asset-tag`, body);
  return data;
}
