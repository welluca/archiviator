import { useEffect, useRef, useState } from 'react';
import {
  Archive,
  ArchiveRestore,
  ChevronRight,
  FolderInput,
  MoreVertical,
  Pencil,
  Trash2,
} from 'lucide-react';
import type { Entity } from '../../types';
import EntityIcon from './EntityIcon';

export interface EntityRowActions {
  onRename: (e: Entity) => void;
  onMove: (e: Entity) => void;
  onArchiveToggle: (e: Entity) => void;
  onDelete: (e: Entity) => void;
}

interface EntityRowProps {
  entity: Entity;
  onOpen: (e: Entity) => void;
  actions: EntityRowActions;
}

export function EntityRow({ entity, onOpen, actions }: EntityRowProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (ev: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(ev.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [menuOpen]);

  const locked = entity.protected;
  const canDelete = entity.child_count === 0 && !locked;

  const menuItem =
    'w-full flex items-center gap-2 px-3 py-2 text-sm text-left transition-colors';

  const runAction = (fn: (e: Entity) => void) => {
    setMenuOpen(false);
    fn(entity);
  };

  return (
    <div
      onClick={() => onOpen(entity)}
      className={`group flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer border border-transparent hover:border-space-700 hover:bg-space-900 transition-colors ${
        entity.archived ? 'opacity-50' : ''
      }`}
    >
      <EntityIcon entity={entity} className="w-5 h-5" />

      <div className="flex-1 min-w-0 flex items-center gap-2">
        <span className="text-sm text-white truncate">{entity.name}</span>
        {entity.subtype && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-400 shrink-0">
            {entity.subtype}
          </span>
        )}
        {entity.archived && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-900/40 border border-yellow-700/40 text-yellow-500 shrink-0">
            archived
          </span>
        )}
      </div>

      {entity.kind !== 'item' && (
        <span className="text-xs text-gray-500 shrink-0">
          {entity.child_count} {entity.child_count === 1 ? 'item' : 'items'}
        </span>
      )}

      <div className="relative shrink-0" ref={menuRef} onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className={`p-1.5 rounded-md text-gray-500 hover:text-white hover:bg-space-700 transition-colors ${
            menuOpen ? 'text-white bg-space-700' : ''
          }`}
          aria-label="Actions"
        >
          <MoreVertical className="w-4 h-4" />
        </button>

        {menuOpen && (
          <div className="absolute right-0 top-full mt-1 z-30 w-44 bg-space-900 border border-space-700 rounded-lg shadow-lg shadow-black/40 py-1 overflow-hidden">
            <button
              onClick={() => runAction(actions.onRename)}
              className={`${menuItem} text-gray-300 hover:bg-space-800 hover:text-white`}
            >
              <Pencil className="w-4 h-4" /> Rename
            </button>
            {!locked && (
              <button
                onClick={() => runAction(actions.onMove)}
                className={`${menuItem} text-gray-300 hover:bg-space-800 hover:text-white`}
              >
                <FolderInput className="w-4 h-4" /> Move
              </button>
            )}
            {!locked && (
              <button
                onClick={() => runAction(actions.onArchiveToggle)}
                className={`${menuItem} text-gray-300 hover:bg-space-800 hover:text-white`}
              >
                {entity.archived ? (
                  <>
                    <ArchiveRestore className="w-4 h-4" /> Unarchive
                  </>
                ) : (
                  <>
                    <Archive className="w-4 h-4" /> Archive
                  </>
                )}
              </button>
            )}
            {!locked && (
              <button
                onClick={() => canDelete && runAction(actions.onDelete)}
                disabled={!canDelete}
                title={
                  canDelete ? undefined : 'Cannot delete: contains other entries'
                }
                className={`${menuItem} ${
                  canDelete
                    ? 'text-red-400 hover:bg-red-900/30'
                    : 'text-gray-600 cursor-not-allowed'
                }`}
              >
                <Trash2 className="w-4 h-4" /> Delete
              </button>
            )}
          </div>
        )}
      </div>

      <ChevronRight className="w-4 h-4 text-gray-600 group-hover:text-gray-400 shrink-0" />
    </div>
  );
}

export default EntityRow;
