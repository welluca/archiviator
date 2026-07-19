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
  // ── M6: inventory & value ──────────────────────────────────────────────────
  /** NOT NULL server-side (defaults to 1) — never null in responses. */
  quantity: number;
  unit: string | null;
  is_consumable: boolean;
  low_stock_threshold: number | null;
  purchase_date: string | null;
  purchase_price: number | null;
  purchase_from: string | null;
  /** 3-letter uppercase code, or null = instance default. */
  currency: string | null;
  current_value: number | null;
  insured: boolean;
  warranty_expires: string | null;
  warranty_lifetime: boolean;
  warranty_notes: string | null;
  serial_number: string | null;
  model_number: string | null;
  manufacturer: string | null;
  sold_date: string | null;
  sold_to: string | null;
  sold_price: number | null;
  sold_notes: string | null;
  created_at: string;
  updated_at: string;
}

// ── M6: inventory, valuation, admin ──────────────────────────────────────────

export interface ValuationRootRow {
  entity: { id: number; name: string };
  total: number;
  insured_total: number;
}

export interface ValuationCategoryRow {
  /** null = uncategorized bucket. */
  category: { id: number; name: string } | null;
  total: number;
  insured_total: number;
}

/** GET /inventory/valuation — current_value with purchase_price fallback,
 * archived subtrees and sold items excluded. */
export interface ValuationOut {
  total: number;
  insured_total: number;
  /** Instance default currency code the totals are denominated in. */
  currency: string;
  /** Contributing entities whose own currency differs from the default
   * (their values are summed numerically regardless). */
  mixed_currency_count: number;
  by_root: ValuationRootRow[];
  by_category: ValuationCategoryRow[];
}

export interface BackupInfo {
  file: string;
  bytes: number;
  created_at: string;
}

export interface ImportRowError {
  row: number;
  message: string;
}

/** POST /admin/import-csv result (dry-run or applied). */
export interface ImportResult {
  created: number;
  updated: number;
  errors: ImportRowError[];
  dry_run: boolean;
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
  /** Local file path — absent on drive_link rows (the file lives in Drive). */
  original?: string;
  /** 1600px display derivative (photos only). */
  display?: string;
  /** 320px thumb derivative (photos), or cached Drive thumb (drive_link). */
  thumb?: string;
  /** M9 drive_link only: open-in-Drive web URL. */
  open?: string;
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
  // ── M9 drive_link denormalized Drive metadata ─────────────────────────────
  drive_file_id?: string | null;
  drive_name?: string | null;
  /** 'ok' | 'missing' (deleted/trashed in Drive) | 'changed' (md5 drifted). */
  drive_status?: DriveFileStatus | null;
}

// ── M5: Labels & asset tags ──────────────────────────────────────────────────

export interface LabelTemplate {
  id: number;
  name: string;
  page_w_mm: number;
  page_h_mm: number;
  cols: number;
  rows: number;
  label_w_mm: number;
  label_h_mm: number;
  margin_top_mm: number;
  margin_left_mm: number;
  gutter_x_mm: number;
  gutter_y_mm: number;
  qr_size_mm: number;
  show_name: boolean;
  show_breadcrumb: boolean;
}

export type PrintedLabelStatus = 'unclaimed' | 'claimed' | 'void';

export interface PrintedLabel {
  id: number;
  batch_id: number;
  asset_tag: string;
  status: PrintedLabelStatus;
  entity_id: number | null;
  claimed_at: string | null;
  /** Present on batch detail rows when the label is claimed by an entity. */
  entity_name?: string | null;
}

export interface LabelBatchStatusCounts {
  unclaimed: number;
  claimed: number;
  void: number;
}

export interface LabelBatch {
  id: number;
  note: string | null;
  template: LabelTemplate;
  label_count: number;
  /** API path of the rendered PDF — download via blob (Bearer), not href. */
  pdf_url: string;
  created_at: string;
  /** Present on the list endpoint. */
  /** Present on the list endpoint (backend field name: `counts`). */
  counts?: LabelBatchStatusCounts;
  /** Present on create + detail responses. */
  labels?: PrintedLabel[];
}

/** GET /labels/resolve/{tag} — 404s (unknown/void) surface as axios errors. */
export type LabelResolveResult =
  | { status: 'entity'; entity: Entity }
  | { status: 'unclaimed'; label: { asset_tag: string; batch_id: number } };

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

// ── M9: Google Drive — scans inbox, drive_link attachments, backup push ──────

export type DriveFileStatus = 'ok' | 'missing' | 'changed';

export type ScanInboxStatus = 'new' | 'attached' | 'ignored';

/** GET /drive/status — single-account connection + settings snapshot. */
export interface DriveStatus {
  /** A client-secret path is configured (env or meta key). */
  configured: boolean;
  /** A valid OAuth token exists (token.json cached server-side). */
  connected: boolean;
  /** A server-side OAuth consent flow is currently running. */
  connect_pending: boolean;
  email: string | null;
  scans_folder: { id: string; name: string } | null;
  poll_interval_min: number;
  backup_upload_enabled: boolean;
  last_poll_at: string | null;
  last_backup_upload_at: string | null;
  inbox_counts: { new: number; attached: number; ignored: number };
}

export interface DriveBrowseFolder {
  id: string;
  name: string;
}

export interface DriveBrowseFile {
  id: string;
  name: string;
  /** Drive may omit the mime type for some items. */
  mime: string | null;
  modified_time: string | null;
  size: number | null;
}

/** GET /drive/browse?folder_id=… — one level of a Drive folder. */
export interface DriveBrowseResult {
  folders: DriveBrowseFolder[];
  files: DriveBrowseFile[];
}

/** Row of the scans inbox (poller-discovered files in the scans folder). */
export interface ScanInboxRow {
  id: number;
  drive_file_id: string;
  name: string;
  mime: string;
  modified_time: string | null;
  md5: string | null;
  size_bytes: number | null;
  discovered_at: string;
  status: ScanInboxStatus;
  attachment_id: number | null;
  /** Present on attached rows when the backend resolves the attachment's entity. */
  entity_id?: number | null;
  entity_name?: string | null;
  /** Set when the server already has the thumbnail cached. */
  thumbnail_url?: string | null;
}

// ── M8: House map — floor plans, regions, furniture grids ────────────────────

export type CellType = 'drawer' | 'shelf' | 'door' | 'box' | 'void' | 'other';

export const CELL_TYPES: CellType[] = ['drawer', 'shelf', 'door', 'box', 'void', 'other'];

export const CELL_TYPE_LABEL: Record<CellType, string> = {
  drawer: 'Drawer',
  shelf: 'Shelf',
  door: 'Door',
  box: 'Box',
  void: 'Void',
  other: 'Other',
};

/** Entity ref embedded on floor plans. */
export interface FloorEntityRef {
  id: number;
  name: string;
  breadcrumb: string;
}

/** Entity ref embedded on regions and bound grid cells (with live counts).
 * item_count = non-archived 'item' descendants of the subtree. */
export interface MapEntityRef {
  id: number;
  name: string;
  child_count: number;
  item_count: number;
}

/** [x, y] in IMAGE-PIXEL coordinates (scale-free via the SVG viewBox). */
export type PolygonPoint = [number, number];

export interface FloorPlan {
  id: number;
  entity: FloorEntityRef;
  /** null for a blank-canvas floor (drawn in-app, no background image). */
  image_url: string | null;
  /** The FIXED canvas coordinate space (SVG viewBox); always set server-side. */
  image_w: number | null;
  image_h: number | null;
  sort_order: number;
  region_count: number;
  placement_count: number;
}

export interface MapRegion {
  id: number;
  entity: MapEntityRef;
  polygon: PolygonPoint[];
  label_x: number | null;
  label_y: number | null;
}

/** A furniture/container footprint on the top-view floor: an axis-aligned box
 * in canvas coords. Clicking it drills into the entity's front-view grid. */
export interface Placement {
  id: number;
  entity: MapEntityRef;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Degrees clockwise about the box centre. v1 keeps every box axis-aligned. */
  rotation: number;
  label_x: number | null;
  label_y: number | null;
}

/** GET /map/floors/{id} — floor plus its traced regions and furniture footprints. */
export interface FloorPlanDetail extends Omit<FloorPlan, 'region_count' | 'placement_count'> {
  regions: MapRegion[];
  placements: Placement[];
}

export interface GridCell {
  id: number;
  /** 0-based grid coordinates. */
  row: number;
  col: number;
  row_span: number;
  col_span: number;
  cell_type: CellType;
  label: string | null;
  /** 1:1 binding to a direct-child container of the grid's entity, or null. */
  entity: MapEntityRef | null;
}

export interface FurnitureGrid {
  id: number;
  name: string | null;
  rows: number;
  cols: number;
  /** Set when this is a stacked sub-grid anchored to a bound cell. */
  parent_cell_id: number | null;
  sort_order: number;
  cells: GridCell[];
}
