import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ExternalLink, Grid3x3, Loader2, Minus, Plus, X } from 'lucide-react';
import { mapApi } from '../../api/map';
import { entitiesApi, apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import EntityIcon from '../browse/EntityIcon';
import GridSvg from './GridSvg';
import GridToolbar from './GridToolbar';
import CellPanel from './CellPanel';
import type { Entity, FurnitureGrid, GridCell } from '../../types';
import { KIND_META } from '../../types';

interface GridViewProps {
  /** The furniture/container whose layouts are shown. */
  entityId: number;
  /** Drill into a bound child container's own layout. */
  onDrill: (entityId: number) => void;
}

const sortGrids = (list: FurnitureGrid[]): FurnitureGrid[] =>
  [...list].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);

function CreateGridForm({
  title,
  onCreate,
  onCancel,
  busy,
}: {
  title: string;
  onCreate: (rows: number, cols: number, name: string) => void;
  onCancel?: () => void;
  busy: boolean;
}) {
  const [rows, setRows] = useState(3);
  const [cols, setCols] = useState(3);
  const [name, setName] = useState('');

  const stepBtn =
    'p-1 rounded-md text-gray-400 hover:text-white hover:bg-space-700 disabled:opacity-30 transition-colors';
  const stepper = (label: string, value: number, set: (v: number) => void) => (
    <div className="flex items-center gap-1 bg-space-950 border border-space-700 rounded-lg pl-2 pr-1 py-1">
      <span className="text-[10px] uppercase tracking-wide text-gray-500">{label}</span>
      <button onClick={() => set(value - 1)} disabled={value <= 1} className={stepBtn} aria-label={`Fewer ${label}`}>
        <Minus className="w-3.5 h-3.5" />
      </button>
      <span className="w-5 text-center text-sm text-white tabular-nums">{value}</span>
      <button onClick={() => set(value + 1)} disabled={value >= 12} className={stepBtn} aria-label={`More ${label}`}>
        <Plus className="w-3.5 h-3.5" />
      </button>
    </div>
  );

  return (
    <div className="bg-space-900 border border-space-700 rounded-xl p-4 flex flex-col gap-3 max-w-md">
      <div className="flex items-center gap-2">
        <Grid3x3 className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-semibold text-white">{title}</span>
        {onCancel && (
          <>
            <div className="flex-1" />
            <button
              onClick={onCancel}
              aria-label="Cancel"
              className="p-1 rounded-md text-gray-500 hover:text-white hover:bg-space-800 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {stepper('Rows', rows, setRows)}
        {stepper('Cols', cols, setCols)}
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Name (e.g. Front)"
          className="flex-1 min-w-[8rem] bg-space-950 border border-space-700 rounded-lg px-2.5 py-1.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
        />
      </div>
      <button
        onClick={() => onCreate(rows, cols, name.trim())}
        disabled={busy}
        className="flex items-center justify-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm transition-colors"
      >
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
        Create {rows}×{cols} layout
      </button>
    </div>
  );
}

/** Layout editor for one furniture/container: grid tabs + SVG front + the
 * selected-cell panel (contents for bound cells, bind flows for unbound). */
export function GridView({ entityId, onDrill }: GridViewProps) {
  const toast = useToast();
  const navigate = useNavigate();

  const [entity, setEntity] = useState<Entity | null>(null);
  const [grids, setGrids] = useState<FurnitureGrid[] | null>(null);
  const [children, setChildren] = useState<Entity[] | null>(null);
  const [activeGridId, setActiveGridId] = useState<number | null>(null);
  const [selectedCellId, setSelectedCellId] = useState<number | null>(null);
  const [addFormOpen, setAddFormOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    try {
      const [e, g, ch] = await Promise.all([
        entitiesApi.get(entityId),
        mapApi.getGrids(entityId),
        entitiesApi.getChildren(entityId),
      ]);
      setEntity(e);
      setGrids(sortGrids(g));
      setChildren(ch);
      setLoadError(false);
    } catch (err) {
      setLoadError(true);
      toast.error(apiErrorDetail(err, 'Failed to load the layout'));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId]);

  useEffect(() => {
    setEntity(null);
    setGrids(null);
    setChildren(null);
    setActiveGridId(null);
    setSelectedCellId(null);
    setAddFormOpen(false);
    load();
  }, [load]);

  /** Refetch grids + children after binding changes (auto-bind creates a child). */
  const refreshGrids = useCallback(async () => {
    try {
      const [g, ch] = await Promise.all([
        mapApi.getGrids(entityId),
        entitiesApi.getChildren(entityId),
      ]);
      setGrids(sortGrids(g));
      setChildren(ch);
    } catch (err) {
      // Surface it — a silent failure leaves the layout showing stale bindings.
      toast.error(apiErrorDetail(err, 'Failed to refresh the layout'));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId]);

  const activeGrid = useMemo(() => {
    if (!grids || grids.length === 0) return null;
    return grids.find((g) => g.id === activeGridId) ?? grids[0];
  }, [grids, activeGridId]);

  const selectedCell = useMemo(
    () => activeGrid?.cells.find((c) => c.id === selectedCellId) ?? null,
    [activeGrid, selectedCellId]
  );

  const boundEntityIds = useMemo(() => {
    const set = new Set<number>();
    for (const g of grids ?? [])
      for (const c of g.cells) if (c.entity) set.add(c.entity.id);
    return set;
  }, [grids]);

  const onCellChanged = (updated: GridCell) => {
    setGrids((prev) =>
      prev
        ? prev.map((g) => ({
            ...g,
            cells: g.cells.map((c) => (c.id === updated.id ? updated : c)),
          }))
        : prev
    );
  };

  const createGrid = async (rows: number, cols: number, name: string) => {
    if (creating) return;
    setCreating(true);
    try {
      const created = await mapApi.createGrid({
        entity_id: entityId,
        rows,
        cols,
        ...(name !== '' ? { name } : {}),
      });
      setGrids((prev) => sortGrids([...(prev ?? []), created]));
      setActiveGridId(created.id);
      setAddFormOpen(false);
      toast.success('Layout created — click a cell to bind it');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to create the layout'));
    } finally {
      setCreating(false);
    }
  };

  if (loadError) {
    return <p className="text-sm text-red-400 py-8 text-center">Failed to load the layout.</p>;
  }
  if (!entity || grids === null) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-sm py-12 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading layout…
      </div>
    );
  }

  return (
    <div>
      {/* Entity header */}
      <div className="flex items-center gap-2.5 mb-3">
        <EntityIcon entity={entity} className="w-5 h-5" />
        <h2 className="text-lg font-bold text-white truncate">{entity.name}</h2>
        <span className="text-xs text-gray-500">{KIND_META[entity.kind].label}</span>
        <button
          onClick={() => navigate(`/entity/${entity.id}`)}
          title="Open entity details"
          className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-space-800 transition-colors"
        >
          <ExternalLink className="w-4 h-4" />
        </button>
      </div>

      {grids.length === 0 || !activeGrid ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-gray-500 max-w-md">
            No layout yet. Sketch the front of “{entity.name}” as a grid of drawers,
            shelves and doors — each cell binds to a container inside it.
          </p>
          <CreateGridForm title="Create layout" onCreate={createGrid} busy={creating} />
        </div>
      ) : (
        <div className="flex flex-col lg:flex-row gap-4 items-start">
          <div className="flex-1 min-w-0 w-full">
            <GridToolbar
              grids={grids}
              active={activeGrid}
              onSelectGrid={(id) => {
                setActiveGridId(id);
                setSelectedCellId(null);
              }}
              onGridPatched={(g) => {
                setGrids((prev) =>
                  prev ? sortGrids(prev.map((x) => (x.id === g.id ? g : x))) : prev
                );
                // A shrink may have removed the selected cell.
                setSelectedCellId((sel) =>
                  sel !== null && g.cells.some((c) => c.id === sel) ? sel : null
                );
                // Grow/shrink changes the cell set — re-sync in the background.
                refreshGrids();
              }}
              onGridDeleted={(gridId) => {
                setSelectedCellId(null);
                setActiveGridId(null);
                // Drop it synchronously: the activeGrid fallback (grids[0])
                // must never render the deleted grid while the refetch runs.
                setGrids((prev) => (prev ? prev.filter((g) => g.id !== gridId) : prev));
                refreshGrids();
              }}
              onAddGrid={() => setAddFormOpen(true)}
            />

            {addFormOpen && (
              <div className="mt-3">
                <CreateGridForm
                  title="Add another layout"
                  onCreate={createGrid}
                  onCancel={() => setAddFormOpen(false)}
                  busy={creating}
                />
              </div>
            )}

            {/* The front — capped so a 1×1 grid doesn't balloon full-width */}
            <div
              className="mt-3"
              style={{ maxWidth: `${activeGrid.cols * 170 + 60}px` }}
            >
              <GridSvg
                grid={activeGrid}
                selectedCellId={selectedCellId}
                onCellClick={(cell) =>
                  setSelectedCellId((prev) => (prev === cell.id ? null : cell.id))
                }
              />
              <p className="text-xs text-gray-600 mt-1.5">
                Click a cell — bound cells show their contents, empty ones offer to
                create or bind a container.
              </p>
            </div>
          </div>

          {selectedCell && (
            <div className="w-full lg:w-80 shrink-0 lg:sticky lg:top-4">
              <CellPanel
                grid={activeGrid}
                cell={selectedCell}
                gridChildren={children}
                boundEntityIds={boundEntityIds}
                onCellChanged={onCellChanged}
                onGridsDirty={refreshGrids}
                onDrill={onDrill}
                onClose={() => setSelectedCellId(null)}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default GridView;
