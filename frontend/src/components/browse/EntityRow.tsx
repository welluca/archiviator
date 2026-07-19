import { useEffect, useRef, useState } from 'react';
import {
  Archive,
  ArchiveRestore,
  ChevronRight,
  Eye,
  FolderInput,
  MoreVertical,
  Pencil,
  Trash2,
} from 'lucide-react';
import type { Entity } from '../../types';
import EntityIcon from './EntityIcon';
import TagChip from '../ui/TagChip';

/** Every action is optional — omitted actions disappear from the kebab menu
 * (e.g. search results only offer Details). */
export interface EntityRowActions {
  /** Open the entity detail page (photos & documents). */
  onDetails?: (e: Entity) => void;
  onRename?: (e: Entity) => void;
  onMove?: (e: Entity) => void;
  onArchiveToggle?: (e: Entity) => void;
  onDelete?: (e: Entity) => void;
}

interface EntityRowProps {
  entity: Entity;
  onOpen: (e: Entity) => void;
  actions?: EntityRowActions;
  /** Show the entity breadcrumb as a second line (search results). */
  showBreadcrumb?: boolean;
  /** Extra badge rendered after the name (e.g. the map's has-layout marker). */
  badge?: React.ReactNode;
}

export function EntityRow({ entity, onOpen, actions, showBreadcrumb = false, badge }: EntityRowProps) {
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
  const tags = entity.tags ?? [];

  const hasMenu = Boolean(
    actions &&
      (actions.onDetails ||
        actions.onRename ||
        (!locked && (actions.onMove || actions.onArchiveToggle || actions.onDelete)))
  );

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
      {entity.thumb_url ? (
        // Cover thumb with the kind icon overlaid as a tiny badge
        <div className="relative shrink-0">
          <img
            src={entity.thumb_url}
            alt=""
            loading="lazy"
            className="w-7 h-7 rounded-md object-cover border border-space-700"
          />
          <span className="absolute -bottom-1 -right-1 p-0.5 rounded-full bg-space-950 border border-space-700 flex items-center justify-center">
            <EntityIcon entity={entity} className="w-2.5 h-2.5" />
          </span>
        </div>
      ) : (
        <EntityIcon entity={entity} className="w-5 h-5" />
      )}

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm text-white truncate">{entity.name}</span>
          {entity.subtype && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-400 shrink-0">
              {entity.subtype}
            </span>
          )}
          {badge}
          {entity.draft && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-900/40 border border-violet-700/40 text-violet-400 shrink-0">
              draft
            </span>
          )}
          {tags.slice(0, 2).map((t) => (
            <TagChip key={t.id} tag={t} />
          ))}
          {tags.length > 2 && (
            <span className="text-[10px] text-gray-500 shrink-0">+{tags.length - 2}</span>
          )}
          {entity.archived && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-900/40 border border-yellow-700/40 text-yellow-500 shrink-0">
              archived
            </span>
          )}
        </div>
        {showBreadcrumb && entity.breadcrumb && (
          <p className="text-xs text-gray-500 truncate mt-0.5">{entity.breadcrumb}</p>
        )}
      </div>

      {entity.kind !== 'item' && (
        <span className="text-xs text-gray-500 shrink-0">
          {entity.child_count} {entity.child_count === 1 ? 'item' : 'items'}
        </span>
      )}

      {hasMenu && actions && (
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
              {actions.onDetails && (
                <button
                  onClick={() => runAction(actions.onDetails!)}
                  className={`${menuItem} text-gray-300 hover:bg-space-800 hover:text-white`}
                >
                  <Eye className="w-4 h-4" /> Details
                </button>
              )}
              {actions.onRename && (
                <button
                  onClick={() => runAction(actions.onRename!)}
                  className={`${menuItem} text-gray-300 hover:bg-space-800 hover:text-white`}
                >
                  <Pencil className="w-4 h-4" /> Rename
                </button>
              )}
              {!locked && actions.onMove && (
                <button
                  onClick={() => runAction(actions.onMove!)}
                  className={`${menuItem} text-gray-300 hover:bg-space-800 hover:text-white`}
                >
                  <FolderInput className="w-4 h-4" /> Move
                </button>
              )}
              {!locked && actions.onArchiveToggle && (
                <button
                  onClick={() => runAction(actions.onArchiveToggle!)}
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
              {!locked && actions.onDelete && (
                <button
                  onClick={() => canDelete && runAction(actions.onDelete!)}
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
      )}

      <ChevronRight className="w-4 h-4 text-gray-600 group-hover:text-gray-400 shrink-0" />
    </div>
  );
}

export default EntityRow;
