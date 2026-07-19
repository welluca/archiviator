import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import type { Entity } from '../../types';
import EntityIcon from './EntityIcon';

interface TreePanelProps {
  roots: Entity[];
  childrenOf: Map<number, Entity[]>;
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  expandedIds: Set<number>;
  onToggleExpand: (id: number) => void;
  includeArchived: boolean;
  onToggleArchived: (v: boolean) => void;
  loading: boolean;
}

interface TreeNodeProps {
  entity: Entity;
  childrenOf: Map<number, Entity[]>;
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  expandedIds: Set<number>;
  onToggleExpand: (id: number) => void;
}

function TreeNode({
  entity,
  childrenOf,
  selectedId,
  onSelect,
  expandedIds,
  onToggleExpand,
}: TreeNodeProps) {
  const children = childrenOf.get(entity.id) ?? [];
  const hasChildren = children.length > 0;
  const expanded = expandedIds.has(entity.id);
  const selected = selectedId === entity.id;

  return (
    <div>
      <div
        onClick={() => onSelect(entity.id)}
        style={{ paddingLeft: `${entity.depth * 14 + 4}px` }}
        className={`flex items-center gap-1.5 pr-2 py-1.5 rounded-md cursor-pointer text-sm transition-colors ${
          selected
            ? 'bg-blue-500/20 text-blue-300'
            : 'text-gray-300 hover:bg-space-800 hover:text-white'
        } ${entity.archived ? 'opacity-50' : ''}`}
      >
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggleExpand(entity.id);
            }}
            className="text-gray-500 hover:text-gray-300 shrink-0"
            aria-label={expanded ? 'Collapse' : 'Expand'}
          >
            {expanded ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" />
            )}
          </button>
        ) : (
          <span className="w-3.5 shrink-0" />
        )}
        <EntityIcon entity={entity} />
        <span className="truncate flex-1">{entity.name}</span>
        {entity.child_count > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-400 shrink-0">
            {entity.child_count}
          </span>
        )}
      </div>
      {expanded &&
        children.map((child) => (
          <TreeNode
            key={child.id}
            entity={child}
            childrenOf={childrenOf}
            selectedId={selectedId}
            onSelect={onSelect}
            expandedIds={expandedIds}
            onToggleExpand={onToggleExpand}
          />
        ))}
    </div>
  );
}

export function TreePanel({
  roots,
  childrenOf,
  selectedId,
  onSelect,
  expandedIds,
  onToggleExpand,
  includeArchived,
  onToggleArchived,
  loading,
}: TreePanelProps) {
  return (
    <div className="flex flex-col h-full">
      <button
        onClick={() => onSelect(null)}
        className={`text-left text-xs font-semibold uppercase tracking-wider px-2 py-2 rounded-md transition-colors ${
          selectedId === null
            ? 'text-blue-300 bg-blue-500/10'
            : 'text-gray-500 hover:text-gray-300'
        }`}
      >
        All spaces
      </button>

      <div className="flex-1 overflow-y-auto min-h-0 pr-1">
        {loading && roots.length === 0 ? (
          <div className="flex items-center gap-2 text-gray-500 text-sm px-2 py-3">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        ) : (
          roots.map((root) => (
            <TreeNode
              key={root.id}
              entity={root}
              childrenOf={childrenOf}
              selectedId={selectedId}
              onSelect={onSelect}
              expandedIds={expandedIds}
              onToggleExpand={onToggleExpand}
            />
          ))
        )}
      </div>

      <label className="flex items-center gap-2 px-2 py-3 border-t border-space-700 text-xs text-gray-400 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={includeArchived}
          onChange={(e) => onToggleArchived(e.target.checked)}
          className="accent-blue-500"
        />
        Include archived
      </label>
    </div>
  );
}

export default TreePanel;
