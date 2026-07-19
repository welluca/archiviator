import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  ChevronRight,
  ImagePlus,
  Loader2,
  Map as MapIcon,
  MousePointerClick,
  PenLine,
  Plus,
  Trash2,
} from 'lucide-react';
import { mapApi } from '../api/map';
import { entitiesApi, apiErrorDetail } from '../api/entities';
import { useEntityTree } from '../hooks/useEntityTree';
import { useToast } from '../components/ui/Toast';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import FloorTabs from '../components/map/FloorTabs';
import FloorCanvas from '../components/map/FloorCanvas';
import RegionEditor from '../components/map/RegionEditor';
import RoomPanel from '../components/map/RoomPanel';
import GridView from '../components/map/GridView';
import AddFloorModal from '../components/map/AddFloorModal';
import ReplaceFloorImageModal from '../components/map/ReplaceFloorImageModal';
import type { Entity, FloorPlan, FloorPlanDetail, PathSegment } from '../types';

const intParam = (params: URLSearchParams, key: string): number | null => {
  const raw = params.get(key);
  if (raw === null) return null;
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
};

/** M8: the house map — floor plans traced into rooms, furniture rendered as
 * grids. Pure view layer over the entity tree: every clickable shape binds to
 * an entity id, so contents, breadcrumbs, search and QR flows keep working.
 * Shareable state lives in the query string: ?floor= &room= &grid_entity=. */
export default function MapPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const tree = useEntityTree();
  const [searchParams, setSearchParams] = useSearchParams();

  const floorParam = intParam(searchParams, 'floor');
  const roomParam = intParam(searchParams, 'room');
  const gridEntityParam = intParam(searchParams, 'grid_entity');

  const setParams = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(searchParams);
      for (const [k, v] of Object.entries(patch)) {
        if (v === null) next.delete(k);
        else next.set(k, v);
      }
      setSearchParams(next);
    },
    [searchParams, setSearchParams]
  );

  // ── Floors ────────────────────────────────────────────────────────────────
  const [floors, setFloors] = useState<FloorPlan[] | null>(null);
  const [floorDetail, setFloorDetail] = useState<FloorPlanDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [replaceOpen, setReplaceOpen] = useState(false);
  const [deleteFloorTarget, setDeleteFloorTarget] = useState<FloorPlan | null>(null);

  const refreshFloors = useCallback(async () => {
    try {
      setFloors(await mapApi.listFloors());
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to load floor plans'));
      setFloors([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    refreshFloors();
  }, [refreshFloors]);

  const activeFloor: FloorPlan | null = useMemo(() => {
    if (!floors || floors.length === 0) return null;
    return floors.find((f) => f.id === floorParam) ?? floors[0];
  }, [floors, floorParam]);

  // Mirrors the ACTIVE floor id for in-flight fetches: refreshFloorDetail is
  // handed to children (RegionEditor) whose closures may outlive a floor
  // switch — e.g. a debounce-flushed PUT+refresh from the floor we just left.
  const activeFloorIdRef = useRef<number | null>(null);
  useEffect(() => {
    activeFloorIdRef.current = activeFloor?.id ?? null;
  }, [activeFloor?.id]);

  const refreshFloorDetail = useCallback(async () => {
    if (!activeFloor) {
      setFloorDetail(null);
      return;
    }
    try {
      const detail = await mapApi.getFloor(activeFloor.id);
      // Staleness guard: only apply the response if this is still the active
      // floor — a late refresh must never overwrite the new floor's canvas.
      if (detail.id !== activeFloorIdRef.current) return;
      setFloorDetail(detail);
      // Keep tab pills (region_count) in sync without a full floors refetch.
      setFloors((prev) =>
        prev
          ? prev.map((f) =>
              f.id === detail.id ? { ...f, region_count: detail.regions.length } : f
            )
          : prev
      );
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to load the floor'));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFloor?.id]);

  useEffect(() => {
    setFloorDetail(null);
    if (!activeFloor) return;
    setDetailLoading(true);
    refreshFloorDetail().finally(() => setDetailLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFloor?.id]);

  // ── Region editor data: descendant spaces of the floor entity ─────────────
  const floorEntityId = floorDetail?.entity.id ?? null;
  const descendantSpaces = useMemo(() => {
    if (floorEntityId === null) return [];
    const out: Entity[] = [];
    const walk = (id: number) => {
      for (const child of tree.childrenOf.get(id) ?? []) {
        if (child.kind !== 'space') continue; // only spaces contain spaces
        out.push(child);
        walk(child.id);
      }
    };
    walk(floorEntityId);
    return out;
  }, [floorEntityId, tree.childrenOf]);
  const floorDepth = floorEntityId !== null ? (tree.byId.get(floorEntityId)?.depth ?? 0) : 0;

  const selectedRegion = useMemo(
    () => floorDetail?.regions.find((r) => r.entity.id === roomParam) ?? null,
    [floorDetail, roomParam]
  );

  // ── Grid drill-in breadcrumb ──────────────────────────────────────────────
  const [gridPath, setGridPath] = useState<PathSegment[]>([]);
  useEffect(() => {
    if (gridEntityParam === null) {
      setGridPath([]);
      return;
    }
    let alive = true;
    entitiesApi
      .getPath(gridEntityParam)
      .then((p) => alive && setGridPath(p))
      .catch(() => alive && setGridPath([]));
    return () => {
      alive = false;
    };
  }, [gridEntityParam]);

  const handleDeleteFloor = async () => {
    if (!deleteFloorTarget) return;
    try {
      await mapApi.deleteFloor(deleteFloorTarget.id);
      toast.success(`Floor plan for “${deleteFloorTarget.entity.name}” deleted`);
      setDeleteFloorTarget(null);
      setParams({ floor: null, room: null });
      await refreshFloors();
    } catch (err) {
      setDeleteFloorTarget(null);
      toast.error(apiErrorDetail(err, 'Failed to delete the floor plan'));
    }
  };

  // ── Header (shared) ───────────────────────────────────────────────────────
  const header = (
    <div className="flex items-center gap-2.5 mb-4">
      <MapIcon className="w-6 h-6 text-blue-400" />
      <h1 className="text-xl font-bold text-white">House Map</h1>
    </div>
  );

  // ═══ GRID MODE (?grid_entity=N — furniture/container layout) ══════════════
  if (gridEntityParam !== null) {
    return (
      <div className="max-w-6xl mx-auto">
        {header}

        {/* In-map breadcrumb trail: Map › …path› entity */}
        <div className="flex items-center gap-2 mb-4">
          <button
            onClick={() => setParams({ grid_entity: null })}
            title="Back to the map"
            className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-space-800 border border-space-700 shrink-0 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <nav className="flex items-center gap-1 text-sm overflow-x-auto whitespace-nowrap py-1">
            <button
              onClick={() => setParams({ grid_entity: null })}
              className="px-2 py-1 rounded-md text-gray-400 hover:text-white hover:bg-space-800 transition-colors"
            >
              Map
            </button>
            {gridPath.map((seg, i) => (
              <span key={seg.id} className="flex items-center gap-1">
                <ChevronRight className="w-3.5 h-3.5 text-gray-600 shrink-0" />
                {i === gridPath.length - 1 ? (
                  <span className="px-2 py-1 text-white font-medium">{seg.name}</span>
                ) : (
                  <button
                    onClick={() => navigate(`/browse?sel=${seg.id}`)}
                    className="px-2 py-1 rounded-md text-gray-400 hover:text-white hover:bg-space-800 transition-colors"
                  >
                    {seg.name}
                  </button>
                )}
              </span>
            ))}
          </nav>
        </div>

        <GridView
          key={gridEntityParam}
          entityId={gridEntityParam}
          onDrill={(id) => setParams({ grid_entity: String(id) })}
        />
      </div>
    );
  }

  // ═══ FLOOR MODE ═══════════════════════════════════════════════════════════
  return (
    <div className="max-w-7xl mx-auto">
      {header}

      {floors === null ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm py-16 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading floors…
        </div>
      ) : floors.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <MapIcon className="w-12 h-12 text-space-500 mb-4" />
          <h2 className="text-lg font-semibold text-white mb-1">No floor plans yet</h2>
          <p className="text-gray-500 text-sm max-w-md mb-5">
            Upload a plan for each floor and trace its rooms, then give furniture a grid
            of drawers and shelves. Every shape is just a view onto the tree you already
            browse — contents, search and QR labels keep working.
          </p>
          <button
            onClick={() => setAddOpen(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add your first floor
          </button>
        </div>
      ) : (
        <>
          <FloorTabs
            floors={floors}
            activeId={activeFloor?.id ?? null}
            onSelect={(id) => setParams({ floor: String(id), room: null })}
            onAdd={() => setAddOpen(true)}
          />

          {/* Floor toolbar: breadcrumb + edit toggle + image/delete actions */}
          {activeFloor && (
            <div className="flex flex-wrap items-center gap-2 mt-2 mb-3">
              <p className="text-xs text-gray-500 truncate flex-1 min-w-[10rem]">
                {activeFloor.entity.breadcrumb || activeFloor.entity.name}
              </p>
              <button
                onClick={() => {
                  setEditMode((v) => !v);
                  if (!editMode) setParams({ room: null });
                }}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                  editMode
                    ? 'bg-blue-500/20 text-blue-300 border-blue-500/40'
                    : 'text-gray-400 hover:text-white hover:bg-space-800 border-space-700'
                }`}
              >
                <PenLine className="w-4 h-4" />
                Edit regions
              </button>
              <button
                onClick={() => setReplaceOpen(true)}
                title="Replace the plan image"
                className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-space-800 border border-space-700 transition-colors"
              >
                <ImagePlus className="w-4 h-4" />
              </button>
              <button
                onClick={() => setDeleteFloorTarget(activeFloor)}
                title="Delete this floor plan"
                className="p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-red-900/20 border border-space-700 transition-colors"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          )}

          {detailLoading || !floorDetail ? (
            <div className="flex items-center gap-2 text-gray-500 text-sm py-16 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading floor…
            </div>
          ) : editMode ? (
            <RegionEditor
              floor={floorDetail}
              spaces={descendantSpaces}
              floorDepth={floorDepth}
              onFloorChanged={refreshFloorDetail}
            />
          ) : (
            <div className="flex flex-col xl:flex-row gap-4 items-start">
              <div className="flex-1 min-w-0 w-full">
                <FloorCanvas
                  floor={floorDetail}
                  selectedEntityId={roomParam}
                  onSelectRegion={(id) =>
                    setParams({ room: id !== null ? String(id) : null })
                  }
                />
                {floorDetail.regions.length === 0 && (
                  <p className="flex items-center gap-1.5 text-xs text-gray-500 mt-2">
                    <MousePointerClick className="w-3.5 h-3.5 shrink-0" />
                    No rooms traced yet — hit “Edit regions” to outline them on the plan.
                  </p>
                )}
              </div>

              {/* Room panel: sidebar on wide screens, stacked section on mobile */}
              {selectedRegion ? (
                <div className="w-full xl:w-96 shrink-0 xl:sticky xl:top-4 xl:max-h-[80vh] flex flex-col">
                  <RoomPanel
                    region={selectedRegion}
                    onOpenLayout={(id) => setParams({ grid_entity: String(id) })}
                    onClose={() => setParams({ room: null })}
                  />
                </div>
              ) : (
                floorDetail.regions.length > 0 && (
                  <div className="hidden xl:flex w-96 shrink-0 items-center justify-center bg-space-900/50 border border-dashed border-space-700 rounded-xl py-16">
                    <p className="text-xs text-gray-500 px-6 text-center">
                      Click a room on the plan to see what's inside.
                    </p>
                  </div>
                )
              )}
            </div>
          )}
        </>
      )}

      {/* Modals */}
      <AddFloorModal
        open={addOpen}
        roots={tree.roots}
        childrenOf={tree.childrenOf}
        existingEntityIds={new Set((floors ?? []).map((f) => f.entity.id))}
        onClose={() => setAddOpen(false)}
        onCreated={async (floor) => {
          await refreshFloors();
          setParams({ floor: String(floor.id), room: null });
        }}
      />
      <ReplaceFloorImageModal
        open={replaceOpen}
        floor={activeFloor}
        onClose={() => setReplaceOpen(false)}
        onReplaced={async () => {
          await refreshFloors();
          await refreshFloorDetail();
        }}
      />
      <ConfirmDialog
        open={deleteFloorTarget !== null}
        title="Delete floor plan"
        message={`Delete the plan for “${deleteFloorTarget?.entity.name ?? ''}”? Traced regions go with it, but the spaces, furniture and items themselves are untouched.`}
        confirmLabel="Delete plan"
        variant="danger"
        onConfirm={handleDeleteFloor}
        onCancel={() => setDeleteFloorTarget(null)}
      />
    </div>
  );
}
