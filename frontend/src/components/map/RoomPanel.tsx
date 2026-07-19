import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FolderOpen, Grid3x3, Loader2, PackageOpen, X } from 'lucide-react';
import { mapApi } from '../../api/map';
import { entitiesApi, apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import EntityRow from '../browse/EntityRow';
import type { Entity, MapRegion } from '../../types';

interface RoomPanelProps {
  region: MapRegion;
  /** Open the layout (GridView) of a furniture/container child. */
  onOpenLayout: (entityId: number) => void;
  onClose: () => void;
}

/** Right/bottom panel for the selected room: its children (EntityRow reuse),
 * an 'open in Browse' link, and a lazy has-layout badge on furniture and
 * container rows. Clicking those rows opens the grid view in place. */
export function RoomPanel({ region, onOpenLayout, onClose }: RoomPanelProps) {
  const toast = useToast();
  const navigate = useNavigate();

  const [children, setChildren] = useState<Entity[] | null>(null);
  /** entity id -> grid count (lazy; only furniture/container children). */
  const [gridCounts, setGridCounts] = useState<Map<number, number>>(new Map());

  useEffect(() => {
    let alive = true;
    setChildren(null);
    setGridCounts(new Map());
    (async () => {
      try {
        const list = await entitiesApi.getChildren(region.entity.id);
        if (!alive) return;
        setChildren(list);
        // Lazy badge fetch — rooms hold few furniture pieces, so per-child
        // requests are fine and keep the floors endpoint lean.
        const gridded = list.filter((c) => c.kind === 'furniture' || c.kind === 'container');
        const counts = await Promise.all(
          gridded.map(async (c) => {
            try {
              return [c.id, (await mapApi.getGrids(c.id)).length] as const;
            } catch {
              return [c.id, 0] as const;
            }
          })
        );
        if (alive) setGridCounts(new Map(counts));
      } catch (err) {
        if (alive) {
          setChildren([]);
          toast.error(apiErrorDetail(err, 'Failed to load the room'));
        }
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [region.entity.id]);

  const handleOpen = (e: Entity) => {
    if (e.kind === 'furniture' || e.kind === 'container') onOpenLayout(e.id);
    else if (e.kind === 'item') navigate(`/entity/${e.id}`);
    else navigate(`/browse?sel=${e.id}`);
  };

  return (
    <div className="bg-space-900 border border-space-700 rounded-xl p-3 flex flex-col min-h-0">
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <h2 className="text-sm font-semibold text-white truncate">{region.entity.name}</h2>
        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-400 shrink-0">
          {region.entity.item_count} {region.entity.item_count === 1 ? 'item' : 'items'}
        </span>
        <div className="flex-1" />
        <button
          onClick={() => navigate(`/browse?sel=${region.entity.id}`)}
          title="Open in Browse"
          className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-400 hover:text-white hover:bg-space-800 transition-colors shrink-0"
        >
          <FolderOpen className="w-3.5 h-3.5" /> Browse
        </button>
        <button
          onClick={onClose}
          aria-label="Close room panel"
          className="p-1 rounded-md text-gray-500 hover:text-white hover:bg-space-800 transition-colors shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Children */}
      {children === null ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm py-6 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : children.length === 0 ? (
        <div className="flex flex-col items-center py-8 text-center">
          <PackageOpen className="w-8 h-8 text-space-500 mb-2" />
          <p className="text-gray-500 text-xs">Nothing in this room yet.</p>
        </div>
      ) : (
        <div className="overflow-y-auto min-h-0 -mx-1">
          {children.map((child) => (
            <EntityRow
              key={child.id}
              entity={child}
              onOpen={handleOpen}
              badge={
                (gridCounts.get(child.id) ?? 0) > 0 ? (
                  <span
                    title="Has a layout"
                    className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/15 border border-blue-500/40 text-blue-300 shrink-0"
                  >
                    <Grid3x3 className="w-2.5 h-2.5" /> layout
                  </span>
                ) : undefined
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default RoomPanel;
