import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, MousePointerClick, Package, Trash2 } from 'lucide-react';
import { mapApi } from '../../api/map';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import EntityIcon from '../browse/EntityIcon';
import type { Entity, FloorPlanDetail } from '../../types';
import { clamp, clientToImage, pointsAttr } from './geometry';
import CanvasBackground from './CanvasBackground';

interface PlacementEditorProps {
  floor: FloorPlanDetail;
  /** Non-space descendants of the floor entity (furniture/containers to place). */
  furniture: Entity[];
  /** Depth of the floor entity — for sidebar indentation. */
  floorDepth: number;
  /** Refetch the floor detail after a placement PUT/DELETE. */
  onFloorChanged: () => Promise<void>;
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

type Corner = 'nw' | 'ne' | 'se' | 'sw';
type DragTarget =
  | { kind: 'move'; startX: number; startY: number; box: Box }
  | { kind: 'resize'; corner: Corner; box: Box };

const MIN_SIZE = 24; // canvas units — a footprint can't shrink below this

/** Furniture-footprint editor: pick a furniture on the left to drop it, then
 * drag the box to move it and its corners to resize (axis-aligned, no rotation
 * in v1). Saves via PUT — immediately on drop, debounced 400ms on drag. Mirrors
 * RegionEditor's ref-mirroring + staleness discipline. */
export function PlacementEditor({
  floor,
  furniture,
  floorDepth,
  onFloorChanged,
}: PlacementEditorProps) {
  const toast = useToast();

  const w = floor.image_w || 1600;
  const h = floor.image_h || 1200;

  const placementByEntity = useMemo(
    () => new Map(floor.placements.map((p) => [p.entity.id, p])),
    [floor.placements]
  );

  const [selectedEntityId, setSelectedEntityId] = useState<number | null>(null);
  const [box, setBoxState] = useState<Box | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  // Refs mirror state synchronously — pointer handlers and the debounced save
  // must never read a stale closure.
  const boxRef = useRef<Box | null>(null);
  const setBox = (v: Box | null) => {
    boxRef.current = v;
    setBoxState(v);
  };

  const dirtyRef = useRef(false);
  const dragRef = useRef<DragTarget | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const pendingRef = useRef<{ entityId: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // ── Screen-size-invariant handles: canvas units per CSS pixel ─────────────
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0) setScale(w / rect.width);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [w]);

  const handleR = 7 * scale;
  const stroke = Math.max(2, 2 * scale);

  // ── Debounced PUT ─────────────────────────────────────────────────────────
  const doSave = useCallback(async () => {
    const pending = pendingRef.current;
    const b = boxRef.current;
    if (!pending || !b) return;
    pendingRef.current = null;
    setSaving(true);
    try {
      await mapApi.putPlacement(floor.id, pending.entityId, {
        x: b.x,
        y: b.y,
        w: b.w,
        h: b.h,
      });
      if (pendingRef.current === null) dirtyRef.current = false;
      await onFloorChanged();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to save the footprint'));
    } finally {
      setSaving(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [floor.id, onFloorChanged]);

  const scheduleSave = useCallback(
    (entityId: number, immediate = false) => {
      pendingRef.current = { entityId };
      dirtyRef.current = true;
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
      if (immediate) {
        saveTimerRef.current = null;
        doSave();
      } else {
        saveTimerRef.current = window.setTimeout(doSave, 400);
      }
    },
    [doSave]
  );

  const flushSave = useCallback(() => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
      doSave();
    }
  }, [doSave]);

  useEffect(() => flushSave, [flushSave]); // flush on unmount

  // ── Selection sync: load the box of the selected furniture ────────────────
  useEffect(() => {
    if (dirtyRef.current) return; // never clobber local edits mid-save
    const placement =
      selectedEntityId !== null ? placementByEntity.get(selectedEntityId) : undefined;
    setBox(placement ? { x: placement.x, y: placement.y, w: placement.w, h: placement.h } : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEntityId, placementByEntity]);

  const selectEntity = (id: number | null) => {
    if (id === selectedEntityId) return;
    flushSave();
    dirtyRef.current = false;
    setSelectedEntityId(id);
  };

  // ── Escape deselects ──────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') setSelectedEntityId(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ── Drop an unplaced furniture: a default box at the canvas centre ────────
  const dropFurniture = async (entityId: number) => {
    if (placementByEntity.has(entityId)) {
      selectEntity(entityId);
      return;
    }
    const bw = clamp(Math.round(w * 0.15), MIN_SIZE, w);
    const bh = clamp(Math.round(h * 0.12), MIN_SIZE, h);
    const b: Box = {
      x: Math.round((w - bw) / 2),
      y: Math.round((h - bh) / 2),
      w: bw,
      h: bh,
    };
    setSaving(true);
    try {
      await mapApi.putPlacement(floor.id, entityId, b);
      await onFloorChanged();
      setSelectedEntityId(entityId);
      setBox(b);
      toast.success('Furniture placed — drag it into position');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to place the furniture'));
    } finally {
      setSaving(false);
    }
  };

  // ── Move / resize dragging ────────────────────────────────────────────────
  const startMove = (ev: React.PointerEvent<SVGRectElement>) => {
    if (!svgRef.current || boxRef.current === null) return;
    ev.stopPropagation();
    ev.preventDefault();
    (ev.target as Element).setPointerCapture(ev.pointerId);
    const p = clientToImage(svgRef.current, ev.clientX, ev.clientY);
    if (!p) return;
    dragRef.current = { kind: 'move', startX: p.x, startY: p.y, box: { ...boxRef.current } };
  };

  const startResize = (ev: React.PointerEvent<SVGCircleElement>, corner: Corner) => {
    if (boxRef.current === null) return;
    ev.stopPropagation();
    ev.preventDefault();
    (ev.target as Element).setPointerCapture(ev.pointerId);
    dragRef.current = { kind: 'resize', corner, box: { ...boxRef.current } };
  };

  const onDragMove = (ev: React.PointerEvent<Element>) => {
    const drag = dragRef.current;
    if (!drag || !svgRef.current) return;
    const p = clientToImage(svgRef.current, ev.clientX, ev.clientY);
    if (!p) return;

    if (drag.kind === 'move') {
      const dx = p.x - drag.startX;
      const dy = p.y - drag.startY;
      const nx = clamp(drag.box.x + dx, 0, w - drag.box.w);
      const ny = clamp(drag.box.y + dy, 0, h - drag.box.h);
      setBox({ ...drag.box, x: nx, y: ny });
    } else {
      // Resize: the corner opposite the dragged one stays pinned.
      const px = clamp(p.x, 0, w);
      const py = clamp(p.y, 0, h);
      const { box } = drag;
      const right = box.x + box.w;
      const bottom = box.y + box.h;
      const west = drag.corner === 'nw' || drag.corner === 'sw';
      const north = drag.corner === 'nw' || drag.corner === 'ne';
      // The corner OPPOSITE the dragged one stays pinned; the dragged corner
      // follows the pointer (px, py).
      const fixedX = west ? right : box.x;
      const fixedY = north ? bottom : box.y;
      let x1 = Math.min(px, fixedX);
      let x2 = Math.max(px, fixedX);
      let y1 = Math.min(py, fixedY);
      let y2 = Math.max(py, fixedY);
      // Enforce a minimum size while keeping the fixed corner anchored.
      if (x2 - x1 < MIN_SIZE) {
        if (west) x1 = x2 - MIN_SIZE;
        else x2 = x1 + MIN_SIZE;
      }
      if (y2 - y1 < MIN_SIZE) {
        if (north) y1 = y2 - MIN_SIZE;
        else y2 = y1 + MIN_SIZE;
      }
      setBox({ x: x1, y: y1, w: x2 - x1, h: y2 - y1 });
    }
    dirtyRef.current = true;
  };

  const endDrag = () => {
    if (!dragRef.current) return;
    dragRef.current = null;
    if (selectedEntityId !== null) scheduleSave(selectedEntityId);
  };

  // ── Delete a footprint (the furniture entity is untouched) ────────────────
  const handleDelete = async () => {
    if (selectedEntityId === null) return;
    setDeleteConfirm(false);
    try {
      await mapApi.deletePlacement(floor.id, selectedEntityId);
      dirtyRef.current = false;
      setBox(null);
      setSelectedEntityId(null);
      await onFloorChanged();
      toast.success('Footprint removed — the furniture itself is untouched');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to remove the footprint'));
    }
  };

  const selectedName = furniture.find((f) => f.id === selectedEntityId)?.name ?? '';

  const hint =
    selectedEntityId === null
      ? 'Pick a furniture on the left to drop it — or click a box on the plan.'
      : box === null
        ? 'Placing…'
        : 'Drag the box to move it, drag a corner to resize. Esc deselects.';

  const corners: { corner: Corner; cx: number; cy: number; cursor: string }[] = box
    ? [
        { corner: 'nw', cx: box.x, cy: box.y, cursor: 'nwse-resize' },
        { corner: 'ne', cx: box.x + box.w, cy: box.y, cursor: 'nesw-resize' },
        { corner: 'se', cx: box.x + box.w, cy: box.y + box.h, cursor: 'nwse-resize' },
        { corner: 'sw', cx: box.x, cy: box.y + box.h, cursor: 'nesw-resize' },
      ]
    : [];

  return (
    <div className="flex flex-col md:flex-row gap-3">
      {/* Sidebar: placeable furniture, placed vs not */}
      <aside className="md:w-60 shrink-0 bg-space-900 border border-space-700 rounded-xl p-2 md:max-h-[75vh] overflow-y-auto">
        <p className="text-[10px] uppercase tracking-wide text-gray-500 px-2 pt-1 pb-2">
          Furniture on this floor
        </p>
        {furniture.length === 0 ? (
          <div className="px-2 pb-2 text-xs text-gray-500">
            No furniture or containers under this floor yet. Add some in Browse, then
            place them here.
          </div>
        ) : (
          furniture.map((f) => {
            const placed = placementByEntity.has(f.id);
            const selected = f.id === selectedEntityId;
            return (
              <button
                key={f.id}
                onClick={() => (placed ? selectEntity(selected ? null : f.id) : dropFurniture(f.id))}
                style={{ paddingLeft: `${Math.max(0, f.depth - floorDepth - 1) * 14 + 8}px` }}
                className={`w-full flex items-center gap-2 pr-2 py-1.5 rounded-md text-sm text-left transition-colors ${
                  selected
                    ? 'bg-amber-500/20 text-amber-200'
                    : 'text-gray-300 hover:bg-space-800 hover:text-white'
                }`}
              >
                <EntityIcon entity={f} />
                <span className="truncate flex-1">{f.name}</span>
                {placed ? (
                  <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0" title="Placed" />
                ) : (
                  <span
                    className="w-2 h-2 rounded-full border border-gray-600 shrink-0"
                    title="Not placed yet"
                  />
                )}
              </button>
            );
          })
        )}
      </aside>

      {/* Canvas + toolbar */}
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-2 min-h-[2rem]">
          <p className="text-xs text-gray-400 flex items-center gap-1.5">
            <MousePointerClick className="w-3.5 h-3.5 text-gray-500 shrink-0" />
            {hint}
          </p>
          <div className="flex-1" />
          {saving && (
            <span className="flex items-center gap-1.5 text-xs text-gray-500">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving…
            </span>
          )}
          {box !== null && selectedEntityId !== null && (
            <button
              onClick={() => setDeleteConfirm(true)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 bg-space-800 hover:bg-red-900/40 text-red-400 border border-space-600 hover:border-red-700/50 rounded-lg text-xs transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" /> Remove footprint
            </button>
          )}
        </div>

        <div className="relative select-none">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${w} ${h}`}
            onClick={() => selectEntity(null)}
            className="block w-full h-auto rounded-xl border border-space-700 bg-space-950"
            style={{ touchAction: 'none' }}
          >
            <CanvasBackground imageUrl={floor.image_url} w={w} h={h} idSuffix={floor.id} />

            {/* Context: room polygons, faint and non-interactive */}
            {floor.regions.map((r) => (
              <polygon
                key={r.id}
                points={pointsAttr(r.polygon)}
                strokeWidth={stroke}
                strokeLinejoin="round"
                className="fill-blue-500/10 stroke-blue-500/30 pointer-events-none"
              />
            ))}

            {/* Other furniture footprints (not the selected one), clickable */}
            {floor.placements
              .filter((p) => p.entity.id !== selectedEntityId)
              .map((p) => (
                <rect
                  key={p.id}
                  x={p.x}
                  y={p.y}
                  width={p.w}
                  height={p.h}
                  rx={Math.min(p.w, p.h) * 0.06}
                  onClick={(e) => {
                    e.stopPropagation();
                    selectEntity(p.entity.id);
                  }}
                  strokeWidth={stroke}
                  strokeLinejoin="round"
                  className="fill-amber-500/50 stroke-amber-300/80 hover:fill-amber-500/70 cursor-pointer"
                />
              ))}

            {/* Selected footprint: draggable body + corner handles */}
            {box !== null && (
              <>
                <rect
                  x={box.x}
                  y={box.y}
                  width={box.w}
                  height={box.h}
                  rx={Math.min(box.w, box.h) * 0.06}
                  onPointerDown={startMove}
                  onPointerMove={onDragMove}
                  onPointerUp={endDrag}
                  strokeWidth={stroke * 1.4}
                  strokeLinejoin="round"
                  className="fill-amber-500/75 stroke-amber-200 cursor-move"
                />
                {corners.map((c) => (
                  <circle
                    key={c.corner}
                    cx={c.cx}
                    cy={c.cy}
                    r={handleR}
                    onPointerDown={(e) => startResize(e, c.corner)}
                    onPointerMove={onDragMove}
                    onPointerUp={endDrag}
                    style={{ cursor: c.cursor }}
                    className="fill-white stroke-amber-500"
                    strokeWidth={stroke}
                  />
                ))}
              </>
            )}
          </svg>

          {furniture.length > 0 && floor.placements.length === 0 && selectedEntityId === null && (
            <p className="flex items-center gap-1.5 text-xs text-gray-500 mt-2">
              <Package className="w-3.5 h-3.5 shrink-0" />
              Click a furniture on the left to drop its footprint onto the plan.
            </p>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={deleteConfirm}
        title="Remove footprint"
        message={`Remove the footprint for “${selectedName}” from this floor? The furniture and everything inside it stay exactly as they are.`}
        confirmLabel="Remove footprint"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteConfirm(false)}
      />
    </div>
  );
}

export default PlacementEditor;
