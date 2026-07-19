import apiClient from './client';
import type {
  Category,
  Entity,
  FieldDef,
  FieldType,
  FieldValueOut,
  Preset,
  PresetPayload,
  Tag,
} from '../types';

// ── Tags ─────────────────────────────────────────────────────────────────────

export interface CreateTagPayload {
  name: string;
  color?: string;
}

export interface UpdateTagPayload {
  name?: string;
  color?: string | null;
}

export const tagsApi = {
  /** All tags with usage counts, name-ordered. */
  async list(): Promise<Tag[]> {
    const { data } = await apiClient.get<Tag[]>('/tags');
    return data;
  },

  async create(payload: CreateTagPayload): Promise<Tag> {
    const { data } = await apiClient.post<Tag>('/tags', payload);
    return data;
  },

  async update(id: number, payload: UpdateTagPayload): Promise<Tag> {
    const { data } = await apiClient.patch<Tag>(`/tags/${id}`, payload);
    return data;
  },

  async remove(id: number): Promise<void> {
    await apiClient.delete(`/tags/${id}`);
  },

  /** Replace the full tag set of an entity by NAME — unknown names are
   * auto-created server-side (create-on-type, case-insensitive dedup). */
  async setEntityTags(entityId: number, names: string[]): Promise<Entity> {
    const { data } = await apiClient.put<Entity>(`/entities/${entityId}/tags`, {
      tags: names,
    });
    return data;
  },
};

// ── Categories ───────────────────────────────────────────────────────────────

export interface CategoryPayload {
  name?: string;
  icon?: string | null;
  sort_order?: number;
}

export const categoriesApi = {
  async list(withFields = false): Promise<Category[]> {
    const { data } = await apiClient.get<Category[]>('/categories', {
      params: withFields ? { with_fields: true } : undefined,
    });
    return data;
  },

  async create(payload: CategoryPayload & { name: string }): Promise<Category> {
    const { data } = await apiClient.post<Category>('/categories', payload);
    return data;
  },

  async update(id: number, payload: CategoryPayload): Promise<Category> {
    const { data } = await apiClient.patch<Category>(`/categories/${id}`, payload);
    return data;
  },

  /** Field defs + values cascade; entities keep existing but category_id nulls. */
  async remove(id: number): Promise<void> {
    await apiClient.delete(`/categories/${id}`);
  },
};

// ── Field definitions & values ───────────────────────────────────────────────

export interface CreateFieldDefPayload {
  /** null = global def (all categories). */
  category_id: number | null;
  name: string;
  type: FieldType;
  unit?: string;
  required?: boolean;
  sort_order?: number;
}

export interface UpdateFieldDefPayload {
  name?: string;
  type?: FieldType;
  unit?: string | null;
  required?: boolean;
  sort_order?: number;
}

export interface FieldValueInput {
  field_def_id: number;
  /** Canonical string form; empty string removes the entry. */
  value: string;
}

export const fieldsApi = {
  async create(payload: CreateFieldDefPayload): Promise<FieldDef> {
    const { data } = await apiClient.post<FieldDef>('/fields', payload);
    return data;
  },

  async update(id: number, payload: UpdateFieldDefPayload): Promise<FieldDef> {
    const { data } = await apiClient.patch<FieldDef>(`/fields/${id}`, payload);
    return data;
  },

  async remove(id: number): Promise<void> {
    await apiClient.delete(`/fields/${id}`);
  },

  /** Defs applicable to a category: its own + globals. With a null category only
   * the globals apply — the response is filtered client-side as a guard either way. */
  async applicable(categoryId: number | null): Promise<FieldDef[]> {
    const params: Record<string, number | boolean> = { include_global: true };
    if (categoryId !== null) params.category_id = categoryId;
    const { data } = await apiClient.get<FieldDef[]>('/fields', { params });
    return data.filter((d) => d.category_id === null || d.category_id === categoryId);
  },

  /** Current values of an entity, each with its full def. */
  async values(entityId: number): Promise<FieldValueOut[]> {
    const { data } = await apiClient.get<FieldValueOut[]>(`/entities/${entityId}/fields`);
    return data;
  },

  /** Replace the full value set. Per-type coercion happens server-side (422). */
  async setValues(entityId: number, values: FieldValueInput[]): Promise<void> {
    await apiClient.put(`/entities/${entityId}/fields`, { values });
  },

  /** Fast-entry helper: distinct existing values ordered by frequency. */
  async autocomplete(fieldDefId: number, q = '', limit = 20): Promise<string[]> {
    const { data } = await apiClient.get<string[]>(`/fields/${fieldDefId}/values`, {
      params: { q, limit },
    });
    return data;
  },
};

// ── Presets (CRUD only in M4 — apply-UI comes in M7) ─────────────────────────

export const presetsApi = {
  async list(): Promise<Preset[]> {
    const { data } = await apiClient.get<Preset[]>('/presets');
    return data;
  },

  /** payload is a plain object — the backend serializes it for storage. */
  async create(payload: { name: string; payload: PresetPayload }): Promise<Preset> {
    const { data } = await apiClient.post<Preset>('/presets', payload);
    return data;
  },

  async update(
    id: number,
    payload: { name?: string; payload?: PresetPayload }
  ): Promise<Preset> {
    const { data } = await apiClient.patch<Preset>(`/presets/${id}`, payload);
    return data;
  },

  async remove(id: number): Promise<void> {
    await apiClient.delete(`/presets/${id}`);
  },
};

// ── Admin ────────────────────────────────────────────────────────────────────

export const adminApi = {
  /** Drop and refill the FTS index from live rows (safety net). */
  async rebuildSearch(): Promise<{ indexed: number }> {
    const { data } = await apiClient.post<{ indexed: number }>('/admin/rebuild-search');
    return data;
  },
};

// ── Duplicate ────────────────────────────────────────────────────────────────

/** Deep-copy an entity: name + " (copy)", inventory columns, tags and field
 * values travel; asset tag, attachments and children do not. 409 on Inbox. */
export async function duplicateEntity(id: number): Promise<Entity> {
  const { data } = await apiClient.post<Entity>(`/entities/${id}/duplicate`);
  return data;
}
