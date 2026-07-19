import apiClient from './client';
import type { Entity, EntityKind } from '../types';

export interface SearchQuery {
  /** Optional — omit for a pure filter browse (name-ordered). */
  q?: string;
  kinds?: EntityKind[];
  /** Tag NAMES, combined with AND. */
  tags?: string[];
  categoryId?: number | null;
  /** Restrict to the subtree under this entity id. */
  under?: number | null;
  /** undefined = any; true/false filter on a photo attachment existing. */
  hasPhoto?: boolean;
  includeArchived?: boolean;
  limit?: number;
}

export const searchApi = {
  /** Ranked by bm25 when q is given, by name otherwise. */
  async search(query: SearchQuery, signal?: AbortSignal): Promise<Entity[]> {
    const params: Record<string, string | number | boolean> = {
      limit: query.limit ?? 50,
    };
    const q = query.q?.trim();
    if (q) params.q = q;
    if (query.kinds && query.kinds.length > 0) params.kind = query.kinds.join(',');
    if (query.tags && query.tags.length > 0) params.tags = query.tags.join(',');
    if (query.categoryId !== undefined && query.categoryId !== null) {
      params.category_id = query.categoryId;
    }
    if (query.under !== undefined && query.under !== null) params.under = query.under;
    if (query.hasPhoto !== undefined) params.has_photo = query.hasPhoto;
    if (query.includeArchived) params.include_archived = true;

    const { data } = await apiClient.get<{ results: Entity[] }>('/search', {
      params,
      signal,
    });
    return data.results;
  },
};
