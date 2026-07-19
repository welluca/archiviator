import { Layers2, Plus } from 'lucide-react';
import type { FloorPlan } from '../../types';

interface FloorTabsProps {
  floors: FloorPlan[];
  activeId: number | null;
  onSelect: (id: number) => void;
  onAdd: () => void;
}

/** Floor switcher across the top of the map page. */
export function FloorTabs({ floors, activeId, onSelect, onAdd }: FloorTabsProps) {
  return (
    <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
      {floors.map((f) => (
        <button
          key={f.id}
          onClick={() => onSelect(f.id)}
          className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm whitespace-nowrap transition-colors border ${
            f.id === activeId
              ? 'bg-blue-500/20 text-blue-300 border-blue-500/40'
              : 'text-gray-400 hover:text-white hover:bg-space-800 border-space-700'
          }`}
        >
          <Layers2 className="w-4 h-4" />
          {f.entity.name}
          <span
            className={`text-[10px] px-1.5 py-px rounded-full ${
              f.id === activeId ? 'bg-blue-500/30 text-blue-200' : 'bg-space-800 text-gray-500'
            }`}
          >
            {f.region_count}
          </span>
        </button>
      ))}
      <button
        onClick={onAdd}
        className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm whitespace-nowrap text-gray-400 hover:text-white hover:bg-space-800 border border-dashed border-space-600 transition-colors"
      >
        <Plus className="w-4 h-4" />
        Add floor
      </button>
    </div>
  );
}

export default FloorTabs;
