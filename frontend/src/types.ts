import type { LucideIcon } from 'lucide-react';
import { Home, Columns3, Box, Package } from 'lucide-react';

export interface User {
  id: number;
  username: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
}

// ── M2: Entities ─────────────────────────────────────────────────────────────

export type EntityKind = 'space' | 'furniture' | 'container' | 'item';

export interface Entity {
  id: number;
  kind: EntityKind;
  subtype: string | null;
  name: string;
  description: string | null;
  notes: string | null;
  parent_id: number | null;
  depth: number;
  breadcrumb: string;
  asset_tag: string | null;
  draft: boolean;
  archived: boolean;
  /** True only for the seeded Inbox root — cannot be moved, deleted, or archived. */
  protected: boolean;
  child_count: number;
  created_at: string;
  updated_at: string;
}

export interface PathSegment {
  id: number;
  name: string;
  kind: EntityKind;
}

export interface KindMeta {
  label: string;
  icon: LucideIcon;
  /** Containment matrix: which kinds may be created/moved under this kind. */
  allowedChildren: EntityKind[];
  /** Free-text subtype suggestions offered in the create modal. */
  subtypeSuggestions: string[];
}

export const KIND_META: Record<EntityKind, KindMeta> = {
  space: {
    label: 'Space',
    icon: Home,
    allowedChildren: ['space', 'furniture', 'container', 'item'],
    subtypeSuggestions: ['house', 'floor', 'room'],
  },
  furniture: {
    label: 'Furniture',
    icon: Columns3,
    allowedChildren: ['container', 'item'],
    subtypeSuggestions: ['wardrobe', 'desk', 'shelf-unit'],
  },
  container: {
    label: 'Container',
    icon: Box,
    allowedChildren: ['container', 'item'],
    subtypeSuggestions: ['box', 'drawer', 'binder'],
  },
  item: {
    label: 'Item',
    icon: Package,
    allowedChildren: [],
    subtypeSuggestions: [],
  },
};

/** Sort order shared with the backend children listing: kind order, then name. */
export const KIND_ORDER: Record<EntityKind, number> = {
  space: 0,
  furniture: 1,
  container: 2,
  item: 3,
};

/** Inbox look-alike check — for ICON purposes only. Action gating must use
 * `entity.protected`, which the server keys to the seeded row's identity. */
export const isInboxRoot = (e: Entity): boolean =>
  e.protected || (e.kind === 'space' && e.subtype === 'inbox' && e.parent_id === null);
