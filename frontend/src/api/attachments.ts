import apiClient from './client';
import type { Attachment, Entity } from '../types';

export interface PatchAttachmentPayload {
  title?: string | null;
  sort_order?: number;
}

export const attachmentsApi = {
  /** Upload one file. Type (photo/document) is inferred server-side from content.
   * Axios drops the JSON default Content-Type for FormData so the browser sets
   * the multipart boundary itself. */
  async upload(entityId: number, file: File, title?: string): Promise<Attachment> {
    const form = new FormData();
    form.append('file', file);
    if (title !== undefined) form.append('title', title);
    const { data } = await apiClient.post<Attachment>(
      `/entities/${entityId}/attachments`,
      form
    );
    return data;
  },

  /** Attachments of an entity ordered by (sort_order, created_at). */
  async list(entityId: number): Promise<Attachment[]> {
    const { data } = await apiClient.get<Attachment[]>(
      `/entities/${entityId}/attachments`
    );
    return data;
  },

  async patchMeta(id: number, payload: PatchAttachmentPayload): Promise<Attachment> {
    const { data } = await apiClient.patch<Attachment>(`/attachments/${id}`, payload);
    return data;
  },

  async remove(id: number): Promise<void> {
    await apiClient.delete(`/attachments/${id}`);
  },

  /** Set (or clear with null) the entity cover. Returns the updated entity. */
  async setCover(entityId: number, attachmentId: number | null): Promise<Entity> {
    const { data } = await apiClient.put<Entity>(`/entities/${entityId}/cover`, {
      attachment_id: attachmentId,
    });
    return data;
  },
};
