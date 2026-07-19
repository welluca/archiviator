import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ExternalLink,
  Layers,
  Link2,
  Link2Off,
  Loader2,
  Minus,
  Plus,
  Sparkles,
  X,
} from 'lucide-react';
import { mapApi } from '../../api/map';
import { entitiesApi, apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import EntityRow from '../browse/EntityRow';
import type { CellType, Entity, FurnitureGrid, GridCell } from '../../types';
import { CELL_TYPES, CELL_TYPE_LABEL } from '../../types';

interface CellPanelProps {
  grid: FurnitureGrid;
  cell: GridCell;
  /** Direct children of the grid's entity — bind candidates come from here. */
  gridChildren: Entity[] | null;
  /** Entity ids already bound to a cell in any loaded grid (client-side filter;
   * the server's UNIQUE constraint is the real guard, mapped to 409). */
  boundEntityIds: Set<number>;
  onCellChanged: (cell: GridCell) => void;
  /** Binding changed — counts and cascades need a grids refetch. */
  onGridsDirty: () => void;
  /** Drill into the bound entity's own layout (stacked sub-grid). */
  onDrill: (entityId: number) => void;
  onClose: () => void;
}

const selectCls =
  'w-full bg-space-950 border border-space-700 rounded-lg px-2 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500';
const fieldLabel = 'block text-[10px] uppercase tracking-wide text-gray-500 mb-1';

function Stepper({
  label,
  value,
  min,
  max,
  onChange,
  disabled = false,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  const btn =
    'p-1 rounded-md text-gray-400 hover:text-white hover:bg-space-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors';
  return (
    <div>
      <span className={fieldLabel}>{label}</span>
      <div className="flex items-center gap-1 bg-space-950 border border-space-700 rounded-lg px-1 py-0.5">
        <button
          onClick={() => onChange(value - 1)}
          disabled={disabled || value <= min}
          className={btn}
          aria-label={`Decrease ${label}`}
        >
          <Minus className="w-3.5 h-3.5" />
        </button>
        <span className="flex-1 text-center text-sm text-white tabular-nums">{value}</span>
        <button
          onClick={() => onChange(value + 1)}
          disabled={disabled || value >= max}
          className={btn}
          aria-label={`Increase ${label}`}
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

/** Side panel for the selected grid cell: bind flows for unbound cells,
 * contents + inner-layout for bound cells, and type/label/span settings. */
export function CellPanel({
  grid,
  cell,
  gridChildren,
  boundEntityIds,
  onCellChanged,
  onGridsDirty,
  onDrill,
  onClose,
}: CellPanelProps) {
  const toast = useToast();
  const navigate = useNavigate();

  const [busy, setBusy] = useState(false);
  const [labelDraft, setLabelDraft] = useState(cell.label ?? '');
  const [pickId, setPickId] = useState('');

  // Bound-entity extras (lazy): contents + whether an inner layout exists.
  const [contents, setContents] = useState<Entity[] | null>(null);
  const [innerGridCount, setInnerGridCount] = useState<number | null>(null);
  const [innerForm, setInnerForm] = useState<{ rows: number; cols: number } | null>(null);

  // Label draft follows the server value; the contents/inner-layout fetch only
  // re-runs when the cell or its binding changes (not on label edits).
  useEffect(() => {
    setLabelDraft(cell.label ?? '');
  }, [cell.id, cell.label]);

  useEffect(() => {
    setPickId('');
    setInnerForm(null);
    setContents(null);
    setInnerGridCount(null);
    const boundId = cell.entity?.id;
    if (boundId === undefined) return;
    let alive = true;
    entitiesApi
      .getChildren(boundId)
      .then((list) => alive && setContents(list))
      .catch(() => alive && setContents([]));
    mapApi
      .getGrids(boundId)
      .then((g) => alive && setInnerGridCount(g.length))
      .catch(() => alive && setInnerGridCount(0));
    return () => {
      alive = false;
    };
  }, [cell.id, cell.entity?.id]);

  const suggestedName =
    cell.label?.trim() || `${CELL_TYPE_LABEL[cell.cell_type]} ${cell.row + 1}-${cell.col + 1}`;

  const run = async (fn: () => Promise<void>, fallback: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      toast.error(apiErrorDetail(err, fallback));
    } finally {
      setBusy(false);
    }
  };

  // ── Cell settings ─────────────────────────────────────────────────────────
  const patchType = (t: CellType) =>
    run(async () => {
      onCellChanged(await mapApi.patchCell(cell.id, { cell_type: t }));
    }, 'Failed to change cell type');

  const saveLabel = () => {
    const trimmed = labelDraft.trim();
    if ((cell.label ?? '') === trimmed) return;
    run(async () => {
      onCellChanged(await mapApi.patchCell(cell.id, { label: trimmed === '' ? null : trimmed }));
    }, 'Failed to save label');
  };

  const patchSpan = (key: 'row_span' | 'col_span', v: number) =>
    run(async () => {
      onCellChanged(await mapApi.patchCell(cell.id, { [key]: v }));
      onGridsDirty(); // a grown span may have swallowed empty cells
    }, 'Cannot resize — the span would overlap another cell');

  // ── Binding ───────────────────────────────────────────────────────────────
  const bindAuto = () =>
    run(async () => {
      onCellChanged(await mapApi.bindCell(cell.id, { auto: true }));
      onGridsDirty();
      toast.success(`Created and bound “${suggestedName}”`);
    }, 'Failed to create the container');

  const bindExisting = () => {
    const id = Number(pickId);
    if (!Number.isInteger(id) || id <= 0) return;
    run(async () => {
      onCellChanged(await mapApi.bindCell(cell.id, { entity_id: id }));
      onGridsDirty();
      toast.success('Container bound');
    }, 'Failed to bind — is it already bound to another cell?');
  };

  const unbind = () =>
    run(async () => {
      onCellChanged(await mapApi.bindCell(cell.id, { entity_id: null }));
      onGridsDirty();
      toast.success('Cell unbound — the container itself is kept');
    }, 'Failed to unbind');

  // ── Inner layout ──────────────────────────────────────────────────────────
  const createInner = () => {
    const bound = cell.entity;
    if (!bound || !innerForm) return;
    run(async () => {
      await mapApi.createGrid({
        entity_id: bound.id,
        rows: innerForm.rows,
        cols: innerForm.cols,
        parent_cell_id: cell.id,
      });
      onDrill(bound.id);
    }, 'Failed to create the inner layout');
  };

  const candidates = (gridChildren ?? []).filter(
    (c) => c.kind === 'container' && !boundEntityIds.has(c.id)
  );

  const bound = cell.entity;

  return (
    <div className="bg-space-900 border border-space-700 rounded-xl p-3 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-white">
          {CELL_TYPE_LABEL[cell.cell_type]} {cell.row + 1}-{cell.col + 1}
        </span>
        {busy && <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-500" />}
        <div className="flex-1" />
        <button
          onClick={onClose}
          aria-label="Close cell panel"
          className="p-1 rounded-md text-gray-500 hover:text-white hover:bg-space-800 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {bound ? (
        <>
          {/* Bound: entity + contents */}
          <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-space-950 border border-space-700">
            <Link2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span className="flex-1 min-w-0 text-sm text-white truncate">{bound.name}</span>
            <span className="text-xs text-gray-500 shrink-0">
              {bound.item_count} {bound.item_count === 1 ? 'item' : 'items'}
            </span>
            <button
              onClick={() => navigate(`/entity/${bound.id}`)}
              title="Open entity"
              className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-space-700 transition-colors shrink-0"
            >
              <ExternalLink className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Inner layout */}
          {innerGridCount === null ? null : innerGridCount > 0 ? (
            <button
              onClick={() => onDrill(bound.id)}
              className="flex items-center justify-center gap-1.5 px-3 py-1.5 bg-space-800 hover:bg-space-700 text-gray-300 border border-space-600 rounded-lg text-sm transition-colors"
            >
              <Layers className="w-4 h-4" /> Open inner layout
            </button>
          ) : innerForm ? (
            <div className="flex items-end gap-2">
              <Stepper
                label="Rows"
                value={innerForm.rows}
                min={1}
                max={12}
                onChange={(v) => setInnerForm({ ...innerForm, rows: v })}
              />
              <Stepper
                label="Cols"
                value={innerForm.cols}
                min={1}
                max={12}
                onChange={(v) => setInnerForm({ ...innerForm, cols: v })}
              />
              <button
                onClick={createInner}
                disabled={busy}
                className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm transition-colors"
              >
                Create
              </button>
              <button
                onClick={() => setInnerForm(null)}
                className="p-1.5 rounded-md text-gray-500 hover:text-white hover:bg-space-800 transition-colors"
                aria-label="Cancel inner layout"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setInnerForm({ rows: 2, cols: 2 })}
              className="flex items-center justify-center gap-1.5 px-3 py-1.5 bg-space-800 hover:bg-space-700 text-gray-300 border border-space-600 rounded-lg text-sm transition-colors"
            >
              <Layers className="w-4 h-4" /> Add inner layout
            </button>
          )}

          {/* Contents */}
          <div>
            <p className={fieldLabel}>Contents</p>
            {contents === null ? (
              <div className="flex items-center gap-2 text-gray-500 text-xs py-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
              </div>
            ) : contents.length === 0 ? (
              <p className="text-xs text-gray-500 py-1">Empty.</p>
            ) : (
              <div className="max-h-56 overflow-y-auto -mx-1">
                {contents.map((child) => (
                  <EntityRow
                    key={child.id}
                    entity={child}
                    onOpen={(e) => navigate(`/entity/${e.id}`)}
                  />
                ))}
              </div>
            )}
          </div>

          <button
            onClick={unbind}
            disabled={busy}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-gray-400 hover:text-red-400 hover:bg-red-900/20 border border-space-700 rounded-lg text-xs transition-colors disabled:opacity-50"
          >
            <Link2Off className="w-3.5 h-3.5" /> Unbind cell (container is kept)
          </button>
        </>
      ) : cell.cell_type === 'void' ? (
        // Voids are holes for neighbouring spans — no bind affordance (the
        // backend 409s a void bind); the type select below converts it back.
        <p className="text-xs text-gray-500">
          A void cell is a hole that a neighbouring span can cover. Change its type
          below to make it bindable again.
        </p>
      ) : (
        <>
          {/* Unbound: bind flows */}
          <button
            onClick={bindAuto}
            disabled={busy}
            className="flex items-center justify-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm transition-colors"
          >
            <Sparkles className="w-4 h-4" /> Create “{suggestedName}”
          </button>

          <div>
            <p className={fieldLabel}>Or bind an existing container</p>
            {candidates.length === 0 ? (
              <p className="text-xs text-gray-500">
                No unbound containers directly inside this {grid.parent_cell_id ? 'container' : 'furniture'} —
                “Create” above makes one for you.
              </p>
            ) : (
              <div className="flex items-center gap-2">
                <select
                  value={pickId}
                  onChange={(e) => setPickId(e.target.value)}
                  className={selectCls}
                >
                  <option value="">Pick a container…</option>
                  {candidates.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
                <button
                  onClick={bindExisting}
                  disabled={busy || pickId === ''}
                  className="px-3 py-1.5 bg-space-800 hover:bg-space-700 disabled:opacity-50 text-gray-300 border border-space-600 rounded-lg text-sm transition-colors shrink-0"
                >
                  Bind
                </button>
              </div>
            )}
          </div>
        </>
      )}

      {/* Cell settings */}
      <div className="border-t border-space-700 pt-3 grid grid-cols-2 gap-2">
        <div className="col-span-2">
          <span className={fieldLabel}>Cell type</span>
          <select
            value={cell.cell_type}
            onChange={(e) => patchType(e.target.value as CellType)}
            className={selectCls}
          >
            {CELL_TYPES.map((t) => (
              <option key={t} value={t}>
                {CELL_TYPE_LABEL[t]}
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-2">
          <span className={fieldLabel}>Label</span>
          <input
            value={labelDraft}
            onChange={(e) => setLabelDraft(e.target.value)}
            onBlur={saveLabel}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            }}
            placeholder="e.g. Socks, Tools…"
            className={selectCls}
          />
        </div>
        <Stepper
          label="Row span"
          value={cell.row_span}
          min={1}
          max={grid.rows - cell.row}
          onChange={(v) => patchSpan('row_span', v)}
          disabled={busy}
        />
        <Stepper
          label="Col span"
          value={cell.col_span}
          min={1}
          max={grid.cols - cell.col}
          onChange={(v) => patchSpan('col_span', v)}
          disabled={busy}
        />
      </div>
    </div>
  );
}

export default CellPanel;
