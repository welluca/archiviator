import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Grid3x3, Loader2, Minus, PenLine, Plus } from 'lucide-react';
import { mapApi } from '../../api/map';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import GridSvg from './GridSvg';
import { gridDisplayName } from './GridToolbar';
import type { Entity, FurnitureGrid } from '../../types';

const blockLabel = 'text-[10px] uppercase tracking-wide text-gray-500';

/** M8: 'Layout' section on the entity detail page (furniture/container only) —
 * mini read-only grid preview linking into the /map grid editor, or a quick
 * rows×cols create form when no layout exists yet. */
export function LayoutSection({ entity }: { entity: Entity }) {
  const toast = useToast();
  const navigate = useNavigate();
  const eligible = entity.kind === 'furniture' || entity.kind === 'container';

  const [grids, setGrids] = useState<FurnitureGrid[] | null>(null);
  const [rows, setRows] = useState(3);
  const [cols, setCols] = useState(3);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!eligible) return;
    let alive = true;
    setGrids(null);
    mapApi
      .getGrids(entity.id)
      .then((g) => alive && setGrids(g))
      .catch(() => alive && setGrids([]));
    return () => {
      alive = false;
    };
  }, [entity.id, eligible]);

  if (!eligible) return null;

  const editHref = `/map?grid_entity=${entity.id}`;

  const create = async () => {
    if (creating) return;
    setCreating(true);
    try {
      await mapApi.createGrid({ entity_id: entity.id, rows, cols });
      navigate(editHref);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to create the layout'));
      setCreating(false);
    }
  };

  const stepBtn =
    'p-1 rounded-md text-gray-400 hover:text-white hover:bg-space-700 disabled:opacity-30 transition-colors';
  const stepper = (label: string, value: number, set: (v: number) => void) => (
    <div className="flex items-center gap-1 bg-space-950 border border-space-700 rounded-lg pl-2 pr-1 py-1">
      <span className={blockLabel}>{label}</span>
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
    <section className="mt-4 bg-space-900 border border-space-700 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Grid3x3 className="w-4 h-4 text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Layout</h2>
        {grids !== null && grids.length > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-400">
            {grids.length === 1 ? '1 grid' : `${grids.length} grids`}
          </span>
        )}
        <div className="flex-1" />
        {grids !== null && grids.length > 0 && (
          <button
            onClick={() => navigate(editHref)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 bg-space-800 hover:bg-space-700 text-gray-300 border border-space-600 rounded-lg text-xs transition-colors"
          >
            <PenLine className="w-3.5 h-3.5" /> Edit layout
          </button>
        )}
      </div>

      {grids === null ? (
        <div className="flex items-center gap-2 text-gray-500 text-xs py-3">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
        </div>
      ) : grids.length === 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-xs text-gray-500 w-full mb-1">
            Sketch the front as a grid of drawers, shelves and doors — each cell binds to
            a container inside.
          </p>
          {stepper('Rows', rows, setRows)}
          {stepper('Cols', cols, setCols)}
          <button
            onClick={create}
            disabled={creating}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm transition-colors"
          >
            {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Create layout
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-4">
          {grids.slice(0, 2).map((g, i) => (
            <button
              key={g.id}
              onClick={() => navigate(editHref)}
              title="Open in the map editor"
              className="group text-left"
              style={{ width: `${Math.min(260, g.cols * 64)}px` }}
            >
              <GridSvg grid={g} compact className="opacity-90 group-hover:opacity-100 transition-opacity" />
              <p className="text-[10px] text-gray-500 mt-1 truncate group-hover:text-gray-400">
                {gridDisplayName(g, i)} · {g.rows}×{g.cols}
              </p>
            </button>
          ))}
          {grids.length > 2 && (
            <p className="text-xs text-gray-500 self-center">+{grids.length - 2} more</p>
          )}
        </div>
      )}
    </section>
  );
}

export default LayoutSection;
