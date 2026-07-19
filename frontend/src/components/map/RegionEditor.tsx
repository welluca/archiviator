import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Loader2, MousePointerClick, Trash2, Undo2, X } from 'lucide-react';
import { mapApi } from '../../api/map';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import EntityIcon from '../browse/EntityIcon';
import type { Entity, FloorPlanDetail, PolygonPoint } from '../../types';
import { clamp, clientToImage, pointsAttr, polygonCentroid } from './geometry';

interface RegionEditorProps {
  floor: FloorPlanDetail;
  /** Descendant spaces of the floor entity, tree order (rooms to trace). */
  spaces: Entity[];
  /** Depth of the floor entity — for sidebar indentation. */
  floorDepth: number;
  /** Refetch the floor detail after a region PUT/DELETE. */
  onFloorChanged: () => Promise<void>;
}

type DragTarget = { kind: 'vertex'; index: number } | { kind: 'label' };

/** Trace mode: pick a room in the sidebar, click on the plan to add vertices,
 * click the first vertex (or 'Close region') to finish; drag circles to
 * adjust, double-click a vertex to remove it, drag the amber handle to move
 * the label. Saves via PUT — immediately on close, debounced 400ms on drags. */
export function RegionEditor({ floor, spaces, floorDepth, onFloorChanged }: RegionEditorProps) {
  const toast = useToast();
  const navigate = useNavigate();

  const w = floor.image_w || 1600;
  const h = floor.image_h || 1200;

  const regionByEntity = useMemo(
    () => new Map(floor.regions.map((r) => [r.entity.id, r])),
    [floor.regions]
  );

  const [selectedSpaceId, setSelectedSpaceId] = useState<number | null>(null);
  /** Editable polygon of the selected TRACED space (image coords). */
  const [points, setPointsState] = useState<PolygonPoint[] | null>(null);
  /** In-progress trace of an UNTRACED space. */
  const [draft, setDraft] = useState<PolygonPoint[]>([]);
  /** Explicit label anchor of the selected region (null = centroid). */
  const [label, setLabelState] = useState<{ x: number; y: number } | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  // Refs mirror state synchronously — pointer handlers and the debounced save
  // must never read a stale closure.
  const pointsRef = useRef<PolygonPoint[] | null>(null);
  const labelRef = useRef<{ x: number; y: number } | null>(null);
  const setPoints = (v: PolygonPoint[] | null) => {
    pointsRef.current = v;
    setPointsState(v);
  };
  const setLabel = (v: { x: number; y: number } | null) => {
    labelRef.current = v;
    setLabelState(v);
  };

  // Draft mirror for the once-registered Escape listener (keeps the state
  // updater pure — no side-effects smuggled into setDraft).
  const draftRef = useRef<PolygonPoint[]>([]);
  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  const dirtyRef = useRef(false);
  const dragRef = useRef<DragTarget | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const pendingRef = useRef<{ entityId: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // ── Screen-size-invariant handles: image units per CSS pixel ──────────────
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

  const handleR = 6 * scale;
  const midR = 4 * scale;
  const stroke = Math.max(2, 2 * scale);
  const closeRadius = 14 * scale;

  // ── Debounced PUT ─────────────────────────────────────────────────────────
  const doSave = useCallback(async () => {
    const pending = pendingRef.current;
    const pts = pointsRef.current;
    if (!pending || !pts || pts.length < 3) return;
    pendingRef.current = null;
    setSaving(true);
    try {
      const lbl = labelRef.current;
      await mapApi.putRegion(floor.id, pending.entityId, {
        polygon: pts,
        label_x: lbl ? lbl.x : null,
        label_y: lbl ? lbl.y : null,
      });
      // Only clear the dirty flag if no NEWER edit was scheduled while this
      // save was in flight — otherwise the refetch would clobber it.
      if (pendingRef.current === null) dirtyRef.current = false;
      await onFloorChanged();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to save region'));
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

  /** Flush a pending debounce right now (space switch / unmount). */
  const flushSave = useCallback(() => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
      doSave();
    }
  }, [doSave]);

  useEffect(() => flushSave, [flushSave]); // flush on unmount

  // ── Selection sync: load the region of the selected space ────────────────
  useEffect(() => {
    if (dirtyRef.current) return; // never clobber local edits mid-save
    const region = selectedSpaceId !== null ? regionByEntity.get(selectedSpaceId) : undefined;
    setPoints(region ? region.polygon.map((p) => [p[0], p[1]] as PolygonPoint) : null);
    setLabel(
      region && region.label_x !== null && region.label_y !== null
        ? { x: region.label_x, y: region.label_y }
        : null
    );
    setDraft([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSpaceId, regionByEntity]);

  const selectSpace = (id: number | null) => {
    if (id === selectedSpaceId) return;
    flushSave();
    dirtyRef.current = false;
    setDraft([]);
    setSelectedSpaceId(id);
  };

  // ── Escape: cancel trace, then deselect ───────────────────────────────────
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== 'Escape') return;
      // Branch on the ref, OUTSIDE any updater: updaters must stay pure (React
      // may invoke them twice), and the ref keeps this handler current.
      if (draftRef.current.length > 0) setDraft([]);
      else setSelectedSpaceId(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ── Tracing ───────────────────────────────────────────────────────────────
  const tracing = selectedSpaceId !== null && points === null;

  const finishDraft = (pts: PolygonPoint[]) => {
    if (selectedSpaceId === null || pts.length < 3) return;
    setDraft([]);
    setPoints(pts);
    setLabel(null);
    scheduleSave(selectedSpaceId, true);
  };

  const onSvgClick = (ev: React.MouseEvent<SVGSVGElement>) => {
    if (!tracing || !svgRef.current) return;
    const p = clientToImage(svgRef.current, ev.clientX, ev.clientY);
    if (!p) return;
    const pt: PolygonPoint = [clamp(p.x, 0, w), clamp(p.y, 0, h)];
    // Click near the first vertex closes the polygon.
    if (draft.length >= 3) {
      const [fx, fy] = draft[0];
      if (Math.hypot(pt[0] - fx, pt[1] - fy) <= closeRadius) {
        finishDraft(draft);
        return;
      }
    }
    setDraft((d) => [...d, pt]);
  };

  const onSvgMove = (ev: React.MouseEvent<SVGSVGElement>) => {
    if (!tracing || !svgRef.current) return;
    const p = clientToImage(svgRef.current, ev.clientX, ev.clientY);
    setCursor(p ? { x: clamp(p.x, 0, w), y: clamp(p.y, 0, h) } : null);
  };

  // ── Vertex / label dragging (pointer capture on the handle) ──────────────
  const startDrag = (ev: React.PointerEvent<SVGCircleElement>, target: DragTarget) => {
    ev.stopPropagation();
    ev.preventDefault();
    (ev.target as Element).setPointerCapture(ev.pointerId);
    dragRef.current = target;
  };

  const onHandleMove = (ev: React.PointerEvent<SVGCircleElement>) => {
    const drag = dragRef.current;
    if (!drag || !svgRef.current) return;
    const p = clientToImage(svgRef.current, ev.clientX, ev.clientY);
    if (!p) return;
    const x = clamp(p.x, 0, w);
    const y = clamp(p.y, 0, h);
    if (drag.kind === 'label') {
      setLabel({ x, y });
    } else {
      const pts = pointsRef.current;
      if (!pts) return;
      const next = pts.map((pt, i) => (i === drag.index ? ([x, y] as PolygonPoint) : pt));
      setPoints(next);
    }
    dirtyRef.current = true;
  };

  const endDrag = () => {
    if (!dragRef.current) return;
    dragRef.current = null;
    if (selectedSpaceId !== null) scheduleSave(selectedSpaceId);
  };

  const insertVertex = (ev: React.PointerEvent<SVGCircleElement>, afterIndex: number) => {
    const pts = pointsRef.current;
    if (!pts) return;
    const a = pts[afterIndex];
    const b = pts[(afterIndex + 1) % pts.length];
    const mid: PolygonPoint = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const next = [...pts.slice(0, afterIndex + 1), mid, ...pts.slice(afterIndex + 1)];
    setPoints(next);
    startDrag(ev, { kind: 'vertex', index: afterIndex + 1 });
  };

  const removeVertex = (index: number) => {
    const pts = pointsRef.current;
    if (!pts || pts.length <= 3 || selectedSpaceId === null) return;
    setPoints(pts.filter((_, i) => i !== index));
    scheduleSave(selectedSpaceId);
  };

  // ── Region actions ────────────────────────────────────────────────────────
  const handleDeleteRegion = async () => {
    if (selectedSpaceId === null) return;
    setDeleteConfirm(false);
    try {
      await mapApi.deleteRegion(floor.id, selectedSpaceId);
      dirtyRef.current = false;
      setPoints(null);
      setLabel(null);
      await onFloorChanged();
      toast.success('Region removed — the room itself is untouched');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to delete region'));
    }
  };

  const resetLabel = () => {
    if (selectedSpaceId === null || !pointsRef.current) return;
    setLabel(null);
    scheduleSave(selectedSpaceId);
  };

  // ── Derived render data ───────────────────────────────────────────────────
  const selectedSpace = spaces.find((s) => s.id === selectedSpaceId) ?? null;
  const labelPos =
    points !== null ? (label ?? polygonCentroid(points)) : null;

  const hint =
    selectedSpaceId === null
      ? 'Pick a room on the left — or click a traced shape on the plan.'
      : tracing
        ? draft.length === 0
          ? `Tracing “${selectedSpace?.name}” — click on the plan to add corners.`
          : draft.length < 3
            ? `${draft.length} point${draft.length === 1 ? '' : 's'} — add at least 3, Esc cancels.`
            : 'Click the first point (or “Close region”) to finish — Esc cancels.'
        : 'Drag circles to adjust, double-click one to remove it, drag the amber dot to move the label.';

  return (
    <div className="flex flex-col md:flex-row gap-3">
      {/* Sidebar: descendant spaces, traced vs untraced */}
      <aside className="md:w-60 shrink-0 bg-space-900 border border-space-700 rounded-xl p-2 md:max-h-[75vh] overflow-y-auto">
        <p className="text-[10px] uppercase tracking-wide text-gray-500 px-2 pt-1 pb-2">
          Rooms on this floor
        </p>
        {spaces.length === 0 ? (
          <div className="px-2 pb-2 text-xs text-gray-500">
            No rooms under this floor yet.{' '}
            <button
              onClick={() => navigate(`/browse?sel=${floor.entity.id}`)}
              className="text-blue-400 hover:text-blue-300 hover:underline"
            >
              Create spaces in Browse
            </button>{' '}
            first, then trace them here.
          </div>
        ) : (
          spaces.map((s) => {
            const traced = regionByEntity.has(s.id);
            const selected = s.id === selectedSpaceId;
            return (
              <button
                key={s.id}
                onClick={() => selectSpace(selected ? null : s.id)}
                style={{ paddingLeft: `${Math.max(0, s.depth - floorDepth - 1) * 14 + 8}px` }}
                className={`w-full flex items-center gap-2 pr-2 py-1.5 rounded-md text-sm text-left transition-colors ${
                  selected
                    ? 'bg-blue-500/20 text-blue-300'
                    : 'text-gray-300 hover:bg-space-800 hover:text-white'
                }`}
              >
                <EntityIcon entity={s} />
                <span className="truncate flex-1">{s.name}</span>
                {traced ? (
                  <Check className="w-3.5 h-3.5 text-green-400 shrink-0" />
                ) : (
                  <span
                    className="w-2 h-2 rounded-full border border-gray-600 shrink-0"
                    title="Not traced yet"
                  />
                )}
              </button>
            );
          })
        )}
      </aside>

      {/* Canvas + trace toolbar */}
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
          {tracing && draft.length > 0 && (
            <>
              {draft.length >= 3 && (
                <button
                  onClick={() => finishDraft(draft)}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs transition-colors"
                >
                  <Check className="w-3.5 h-3.5" /> Close region
                </button>
              )}
              <button
                onClick={() => setDraft([])}
                className="flex items-center gap-1.5 px-2.5 py-1.5 bg-space-800 hover:bg-space-700 text-gray-300 border border-space-600 rounded-lg text-xs transition-colors"
              >
                <X className="w-3.5 h-3.5" /> Cancel
              </button>
            </>
          )}
          {points !== null && selectedSpaceId !== null && (
            <>
              {label !== null && (
                <button
                  onClick={resetLabel}
                  title="Move the label back to the shape's center"
                  className="flex items-center gap-1.5 px-2.5 py-1.5 bg-space-800 hover:bg-space-700 text-gray-300 border border-space-600 rounded-lg text-xs transition-colors"
                >
                  <Undo2 className="w-3.5 h-3.5" /> Reset label
                </button>
              )}
              <button
                onClick={() => setDeleteConfirm(true)}
                className="flex items-center gap-1.5 px-2.5 py-1.5 bg-space-800 hover:bg-red-900/40 text-red-400 border border-space-600 hover:border-red-700/50 rounded-lg text-xs transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" /> Delete region
              </button>
            </>
          )}
        </div>

        <div className="relative select-none">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${w} ${h}`}
            onClick={onSvgClick}
            onMouseMove={onSvgMove}
            onMouseLeave={() => setCursor(null)}
            className={`block w-full h-auto rounded-xl border border-space-700 bg-space-950 ${
              tracing ? 'cursor-crosshair' : ''
            }`}
            style={{ touchAction: 'none' }}
          >
            <image href={floor.image_url} x={0} y={0} width={w} height={h} />

            {/* Context: every OTHER traced region, faint but clickable */}
            {floor.regions
              .filter((r) => r.entity.id !== selectedSpaceId)
              .map((r) => (
                <polygon
                  key={r.id}
                  points={pointsAttr(r.polygon)}
                  strokeWidth={stroke}
                  strokeLinejoin="round"
                  onClick={(e) => {
                    if (tracing && draft.length > 0) return; // mid-trace: clicks add points
                    e.stopPropagation();
                    selectSpace(r.entity.id);
                  }}
                  className={`${
                    tracing && draft.length > 0 ? '' : 'cursor-pointer'
                  } fill-gray-500/10 stroke-gray-400/40 hover:fill-gray-500/20`}
                />
              ))}

            {/* Selected region: editable polygon */}
            {points !== null && (
              <>
                <polygon
                  points={pointsAttr(points)}
                  strokeWidth={stroke * 1.4}
                  strokeLinejoin="round"
                  className="fill-blue-500/25 stroke-blue-400"
                />
                {/* Midpoint handles: press to insert + drag a new vertex */}
                {points.map((pt, i) => {
                  const nxt = points[(i + 1) % points.length];
                  return (
                    <circle
                      key={`m${i}`}
                      cx={(pt[0] + nxt[0]) / 2}
                      cy={(pt[1] + nxt[1]) / 2}
                      r={midR}
                      onPointerDown={(e) => insertVertex(e, i)}
                      onPointerMove={onHandleMove}
                      onPointerUp={endDrag}
                      className="fill-space-900 stroke-blue-400/70 cursor-copy"
                      strokeWidth={stroke * 0.7}
                    />
                  );
                })}
                {/* Vertex handles */}
                {points.map((pt, i) => (
                  <circle
                    key={`v${i}`}
                    cx={pt[0]}
                    cy={pt[1]}
                    r={handleR}
                    onPointerDown={(e) => startDrag(e, { kind: 'vertex', index: i })}
                    onPointerMove={onHandleMove}
                    onPointerUp={endDrag}
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      removeVertex(i);
                    }}
                    className="fill-white stroke-blue-500 cursor-move"
                    strokeWidth={stroke}
                  />
                ))}
                {/* Label anchor handle */}
                {labelPos && (
                  <circle
                    cx={labelPos.x}
                    cy={labelPos.y}
                    r={handleR * 1.1}
                    onPointerDown={(e) => startDrag(e, { kind: 'label' })}
                    onPointerMove={onHandleMove}
                    onPointerUp={endDrag}
                    className="fill-amber-400 stroke-amber-600 cursor-move"
                    strokeWidth={stroke}
                  >
                    <title>Label position — drag to move</title>
                  </circle>
                )}
              </>
            )}

            {/* In-progress trace */}
            {tracing && draft.length > 0 && (
              <>
                <polyline
                  points={pointsAttr(cursor ? [...draft, [cursor.x, cursor.y]] : draft)}
                  fill="none"
                  strokeWidth={stroke * 1.4}
                  strokeLinejoin="round"
                  strokeDasharray={`${6 * scale} ${5 * scale}`}
                  className="stroke-blue-400"
                />
                {draft.length >= 3 && (
                  <polygon
                    points={pointsAttr(draft)}
                    className="fill-blue-500/10"
                    stroke="none"
                  />
                )}
                {draft.map((pt, i) => (
                  <circle
                    key={i}
                    cx={pt[0]}
                    cy={pt[1]}
                    r={i === 0 ? handleR * 1.25 : handleR * 0.8}
                    onClick={(e) => {
                      // Every draft vertex swallows its click — bubbling to the
                      // SVG would drop a near-duplicate point on top of it.
                      e.stopPropagation();
                      if (i === 0 && draft.length >= 3) finishDraft(draft);
                    }}
                    className={
                      i === 0
                        ? draft.length >= 3
                          ? 'fill-green-400 stroke-green-600 cursor-pointer'
                          : 'fill-white stroke-blue-500'
                        : 'fill-blue-400 stroke-blue-600'
                    }
                    strokeWidth={stroke}
                  />
                ))}
              </>
            )}
          </svg>
        </div>
      </div>

      <ConfirmDialog
        open={deleteConfirm}
        title="Delete region"
        message={`Remove the traced shape for “${selectedSpace?.name ?? ''}” from this floor plan? The room and its contents stay exactly as they are.`}
        confirmLabel="Delete region"
        variant="danger"
        onConfirm={handleDeleteRegion}
        onCancel={() => setDeleteConfirm(false)}
      />
    </div>
  );
}

export default RegionEditor;
