import { useEffect, useState } from 'react';
import { Layers, Loader2, Minus, Plus, Trash2 } from 'lucide-react';
import { mapApi } from '../../api/map';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import type { FurnitureGrid } from '../../types';

interface GridToolbarProps {
  grids: FurnitureGrid[];
  active: FurnitureGrid;
  onSelectGrid: (id: number) => void;
  onGridPatched: (grid: FurnitureGrid) => void;
  onGridDeleted: (gridId: number) => void;
  /** Open the add-another-layout form. */
  onAddGrid: () => void;
}

export const gridDisplayName = (g: FurnitureGrid, index: number): string =>
  g.name?.trim() || (g.parent_cell_id !== null ? 'Inner layout' : `Layout ${index + 1}`);

/** Tabs (multiple grids per entity: 'Front', 'Inside left door', …), name
 * editing, rows/cols steppers (server 409s — e.g. a shrink dropping a bound
 * cell — surface as toasts) and grid deletion. */
export function GridToolbar({
  grids,
  active,
  onSelectGrid,
  onGridPatched,
  onGridDeleted,
  onAddGrid,
}: GridToolbarProps) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [nameDraft, setNameDraft] = useState(active.name ?? '');
  const [deleteOpen, setDeleteOpen] = useState(false);

  useEffect(() => {
    setNameDraft(active.name ?? '');
  }, [active.id, active.name]);

  const patch = async (payload: Parameters<typeof mapApi.patchGrid>[1], fallback: string) => {
    if (busy) return;
    setBusy(true);
    try {
      onGridPatched(await mapApi.patchGrid(active.id, payload));
    } catch (err) {
      toast.error(apiErrorDetail(err, fallback));
    } finally {
      setBusy(false);
    }
  };

  const saveName = () => {
    const trimmed = nameDraft.trim();
    if ((active.name ?? '') === trimmed) return;
    patch({ name: trimmed === '' ? null : trimmed }, 'Failed to rename the layout');
  };

  const resize = (key: 'rows' | 'cols', v: number) =>
    patch({ [key]: v }, 'Cannot shrink — a bound cell would be dropped');

  const handleDelete = async () => {
    setDeleteOpen(false);
    try {
      await mapApi.deleteGrid(active.id);
      toast.success('Layout deleted — bound containers and their contents are kept');
      onGridDeleted(active.id);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to delete the layout'));
    }
  };

  const stepBtn =
    'p-1 rounded-md text-gray-400 hover:text-white hover:bg-space-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors';

  const stepper = (label: string, key: 'rows' | 'cols', value: number) => (
    <div className="flex items-center gap-1 bg-space-950 border border-space-700 rounded-lg pl-2 pr-1 py-0.5">
      <span className="text-[10px] uppercase tracking-wide text-gray-500">{label}</span>
      <button
        onClick={() => resize(key, value - 1)}
        disabled={busy || value <= 1}
        className={stepBtn}
        aria-label={`Fewer ${key}`}
      >
        <Minus className="w-3.5 h-3.5" />
      </button>
      <span className="w-5 text-center text-sm text-white tabular-nums">{value}</span>
      <button
        onClick={() => resize(key, value + 1)}
        disabled={busy || value >= 12}
        className={stepBtn}
        aria-label={`More ${key}`}
      >
        <Plus className="w-3.5 h-3.5" />
      </button>
    </div>
  );

  return (
    <div className="flex flex-col gap-2">
      {/* Grid tabs */}
      {grids.length > 1 && (
        <div className="flex items-center gap-1 overflow-x-auto">
          {grids.map((g, i) => (
            <button
              key={g.id}
              onClick={() => onSelectGrid(g.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm whitespace-nowrap transition-colors ${
                g.id === active.id
                  ? 'bg-blue-500/20 text-blue-300 border border-blue-500/40'
                  : 'text-gray-400 hover:text-white hover:bg-space-800 border border-space-700'
              }`}
            >
              {g.parent_cell_id !== null && <Layers className="w-3.5 h-3.5" />}
              {gridDisplayName(g, i)}
            </button>
          ))}
        </div>
      )}

      {/* Active grid controls */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={nameDraft}
          onChange={(e) => setNameDraft(e.target.value)}
          onBlur={saveName}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          }}
          placeholder="Layout name (e.g. Front)"
          className="w-44 bg-space-950 border border-space-700 rounded-lg px-2.5 py-1.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
        />
        {stepper('Rows', 'rows', active.rows)}
        {stepper('Cols', 'cols', active.cols)}
        {busy && <Loader2 className="w-4 h-4 animate-spin text-gray-500" />}
        <div className="flex-1" />
        <button
          onClick={onAddGrid}
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-space-800 hover:bg-space-700 text-gray-300 border border-space-600 rounded-lg text-xs transition-colors"
        >
          <Plus className="w-3.5 h-3.5" /> Add layout
        </button>
        <button
          onClick={() => setDeleteOpen(true)}
          title="Delete this layout"
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-space-800 hover:bg-red-900/40 text-red-400 border border-space-600 hover:border-red-700/50 rounded-lg text-xs transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" /> Delete
        </button>
      </div>

      <ConfirmDialog
        open={deleteOpen}
        title="Delete layout"
        message="Delete this layout? The grid is only a view — every bound container and everything inside it stays in the tree."
        confirmLabel="Delete layout"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  );
}

export default GridToolbar;
