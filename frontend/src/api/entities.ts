import { AxiosError } from 'axios';
import apiClient from './client';
import type { Entity, EntityKind, PathSegment } from '../types';

export interface CreateEntityPayload {
  name: string;
  kind: EntityKind;
  parent_id: number | null;
  subtype?: string;
  description?: string;
  notes?: string;
}

export interface UpdateEntityPayload {
  name?: string;
  subtype?: string;
  description?: string;
  notes?: string;
  /** M4: assign / clear the category (null clears). */
  category_id?: number | null;
}

export const entitiesApi = {
  /** Flat list of all entities ordered by path — tree is rebuilt client-side. */
  async getTree(includeArchived = false): Promise<Entity[]> {
    const { data } = await apiClient.get<Entity[]>('/entities/tree', {
      params: { include_archived: includeArchived },
    });
    return data;
  },

  async get(id: number): Promise<Entity> {
    const { data } = await apiClient.get<Entity>(`/entities/${id}`);
    return data;
  },

  async getChildren(id: number, includeArchived = false): Promise<Entity[]> {
    const { data } = await apiClient.get<Entity[]>(`/entities/${id}/children`, {
      params: { include_archived: includeArchived },
    });
    return data;
  },

  /** Root-first path including the entity itself. */
  async getPath(id: number): Promise<PathSegment[]> {
    const { data } = await apiClient.get<PathSegment[]>(`/entities/${id}/path`);
    return data;
  },

  async create(payload: CreateEntityPayload): Promise<Entity> {
    const { data } = await apiClient.post<Entity>('/entities', payload);
    return data;
  },

  async update(id: number, payload: UpdateEntityPayload): Promise<Entity> {
    const { data } = await apiClient.patch<Entity>(`/entities/${id}`, payload);
    return data;
  },

  async move(id: number, parentId: number | null): Promise<Entity> {
    const { data } = await apiClient.post<Entity>(`/entities/${id}/move`, {
      parent_id: parentId,
    });
    return data;
  },

  async archive(id: number): Promise<Entity> {
    const { data } = await apiClient.post<Entity>(`/entities/${id}/archive`);
    return data;
  },

  async unarchive(id: number): Promise<Entity> {
    const { data } = await apiClient.post<Entity>(`/entities/${id}/unarchive`);
    return data;
  },

  async remove(id: number): Promise<void> {
    await apiClient.delete(`/entities/${id}`);
  },
};

/** Extract the backend's {"detail": "..."} message from an axios error. */
export function apiErrorDetail(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string' && detail.length > 0) return detail;
  }
  return fallback;
}
