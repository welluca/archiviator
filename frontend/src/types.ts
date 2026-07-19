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
  /** M3: id of the photo attachment used as cover, if any. */
  cover_attachment_id: number | null;
  /** M3: 320px thumb URL of the cover photo (unauthenticated /media path). */
  thumb_url: string | null;
  /** M4: category id, or null when uncategorized. */
  category_id: number | null;
  /** M4: tags carried by the entity (batched server-side, no N+1). */
  tags: TagLite[];
  created_at: string;
  updated_at: string;
}

// ── M4: Tags, categories, custom fields ──────────────────────────────────────

/** Tag shape embedded on EntityOut. */
export interface TagLite {
  id: number;
  name: string;
  color: string | null;
}

export interface Tag extends TagLite {
  /** Number of entities carrying the tag (GET /tags only). */
  usage_count?: number;
}

export interface Category {
  id: number;
  name: string;
  icon: string | null;
  sort_order: number;
  /** Present when listed with ?with_fields=true. */
  fields?: FieldDef[];
}

export type FieldType = 'text' | 'number' | 'date' | 'url';

export interface FieldDef {
  id: number;
  /** null = global field def, applies to every category. */
  category_id: number | null;
  name: string;
  type: FieldType;
  unit: string | null;
  required: boolean;
  sort_order: number;
}

export interface FieldValueOut {
  def: FieldDef;
  value_text: string;
  value_num: number | null;
  value_date: string | null;
}

/** Parsed JSON payload of a preset — the backend stores it serialized and
 * returns it parsed. Known keys are optional; the shape stays open until the
 * apply-UI lands in M7. */
export interface PresetPayload {
  category_id?: number | null;
  tags?: string[];
  fields?: { field_def_id?: number; name?: string; value?: string }[];
  [key: string]: unknown;
}

export interface Preset {
  id: number;
  name: string;
  /** Parsed JSON payload (NOT the serialized string) — the apply-UI lands in M7. */
  payload: PresetPayload;
}

// ── M3: Attachments ──────────────────────────────────────────────────────────

export type AttachmentType = 'photo' | 'document' | 'drive_link';

export interface AttachmentUrls {
  original: string;
  /** 1600px display derivative (photos only). */
  display?: string;
  /** 320px thumb derivative (photos only). */
  thumb?: string;
}

export interface Attachment {
  id: number;
  entity_id: number;
  type: AttachmentType;
  title: string | null;
  sort_order: number;
  mime: string;
  byte_size: number;
  width: number | null;
  height: number | null;
  is_cover: boolean;
  urls: AttachmentUrls;
  created_at: string;
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
