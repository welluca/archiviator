import { useCallback, useEffect, useMemo, useState } from 'react';
import { entitiesApi } from '../api/entities';
import type { Entity } from '../types';
import { KIND_ORDER } from '../types';

export interface EntityTree {
  entities: Entity[];
  byId: Map<number, Entity>;
  /** parent id -> sorted children (kind order: space, furniture, container, item; then name). */
  childrenOf: Map<number, Entity[]>;
  roots: Entity[];
  loading: boolean;
  error: string | null;
  includeArchived: boolean;
  setIncludeArchived: (v: boolean) => void;
  refresh: () => Promise<void>;
}

const sortSiblings = (list: Entity[]): Entity[] =>
  [...list].sort(
    (a, b) =>
      KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || a.name.localeCompare(b.name)
  );

export function useEntityTree(): EntityTree {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await entitiesApi.getTree(includeArchived);
      setEntities(data);
      setError(null);
    } catch (err: any) {
      setError(err?.message || 'Failed to load entities');
    } finally {
      setLoading(false);
    }
  }, [includeArchived]);

  useEffect(() => {
    setLoading(true);
    refresh();
  }, [refresh]);

  const byId = useMemo(() => {
    const map = new Map<number, Entity>();
    for (const e of entities) map.set(e.id, e);
    return map;
  }, [entities]);

  const { childrenOf, roots } = useMemo(() => {
    const children = new Map<number, Entity[]>();
    const rootList: Entity[] = [];
    for (const e of entities) {
      if (e.parent_id === null) {
        rootList.push(e);
      } else {
        const list = children.get(e.parent_id);
        if (list) list.push(e);
        else children.set(e.parent_id, [e]);
      }
    }
    const sorted = new Map<number, Entity[]>();
    for (const [pid, list] of children) sorted.set(pid, sortSiblings(list));
    return { childrenOf: sorted, roots: sortSiblings(rootList) };
  }, [entities]);

  return {
    entities,
    byId,
    childrenOf,
    roots,
    loading,
    error,
    includeArchived,
    setIncludeArchived,
    refresh,
  };
}
