import { useCallback, useEffect, useState } from 'react';
import { AxiosError } from 'axios';
import {
  ChevronRight,
  CornerLeftUp,
  FolderTree,
  Home,
  Loader2,
  PackageOpen,
  Plus,
  X,
} from 'lucide-react';
import { entitiesApi, apiErrorDetail } from '../api/entities';
import { useEntityTree } from '../hooks/useEntityTree';
import { useToast } from '../components/ui/Toast';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import TreePanel from '../components/browse/TreePanel';
import EntityRow from '../components/browse/EntityRow';
import EntityIcon from '../components/browse/EntityIcon';
import CreateEntityModal from '../components/browse/CreateEntityModal';
import RenameEntityModal from '../components/browse/RenameEntityModal';
import MoveEntityModal from '../components/browse/MoveEntityModal';
import type { Entity, PathSegment } from '../types';
import { KIND_META } from '../types';

export default function BrowsePage() {
  const toast = useToast();
  const tree = useEntityTree();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [path, setPath] = useState<PathSegment[]>([]);
  const [children, setChildren] = useState<Entity[]>([]);
  const [childrenLoading, setChildrenLoading] = useState(false);

  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [mobileTreeOpen, setMobileTreeOpen] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Entity | null>(null);
  const [moveTarget, setMoveTarget] = useState<Entity | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Entity | null>(null);

  // ── Selection data (entity + breadcrumb path + children via the API) ──────
  const refreshSelection = useCallback(async () => {
    if (selectedId === null) {
      setSelectedEntity(null);
      setPath([]);
      setChildren([]);
      return;
    }
    setChildrenLoading(true);
    try {
      const [entity, pathData, childrenData] = await Promise.all([
        entitiesApi.get(selectedId),
        entitiesApi.getPath(selectedId),
        entitiesApi.getChildren(selectedId, tree.includeArchived),
      ]);
      setSelectedEntity(entity);
      setPath(pathData);
      setChildren(childrenData);
    } catch (err) {
      if (err instanceof AxiosError && err.response?.status === 404) {
        toast.warning('This entry no longer exists');
        setSelectedId(null);
      } else {
        toast.error(apiErrorDetail(err, 'Failed to load entry'));
      }
    } finally {
      setChildrenLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, tree.includeArchived]);

  useEffect(() => {
    refreshSelection();
  }, [refreshSelection]);

  // Reveal the selection in the tree by expanding all its ancestors.
  useEffect(() => {
    if (selectedId === null) return;
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.add(selectedId);
      let current = tree.byId.get(selectedId);
      while (current && current.parent_id !== null) {
        next.add(current.parent_id);
        current = tree.byId.get(current.parent_id);
      }
      return next;
    });
  }, [selectedId, tree.byId]);

  const refetchAll = useCallback(async () => {
    await Promise.all([tree.refresh(), refreshSelection()]);
  }, [tree.refresh, refreshSelection]);

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleSelect = (id: number | null) => {
    setSelectedId(id);
    setMobileTreeOpen(false);
  };

  const handleToggleExpand = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleArchiveToggle = async (entity: Entity) => {
    try {
      if (entity.archived) {
        await entitiesApi.unarchive(entity.id);
        toast.success(`Unarchived “${entity.name}”`);
      } else {
        await entitiesApi.archive(entity.id);
        toast.success(`Archived “${entity.name}”`);
      }
      await refetchAll();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Operation failed'));
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await entitiesApi.remove(deleteTarget.id);
      toast.success(`Deleted “${deleteTarget.name}”`);
      setDeleteTarget(null);
      await refetchAll();
    } catch (err) {
      setDeleteTarget(null);
      toast.error(apiErrorDetail(err, 'Failed to delete'));
    }
  };

  const goUp = () => {
    if (selectedId === null) return;
    const parent = path.length >= 2 ? path[path.length - 2] : null;
    handleSelect(parent ? parent.id : null);
  };

  // ── Derived view data ─────────────────────────────────────────────────────
  const atRoot = selectedId === null;
  const listedChildren = atRoot ? tree.roots : children;
  const listLoading = atRoot ? tree.loading : childrenLoading;
  const canCreateHere = atRoot || (selectedEntity !== null && KIND_META[selectedEntity.kind].allowedChildren.length > 0);
  const noRootsYet = !tree.loading && tree.roots.length === 0;

  const rowActions = {
    onRename: (e: Entity) => setRenameTarget(e),
    onMove: (e: Entity) => setMoveTarget(e),
    onArchiveToggle: handleArchiveToggle,
    onDelete: (e: Entity) => setDeleteTarget(e),
  };

  return (
    <div className="flex h-full min-h-0 lg:gap-6">
      {/* Mobile tree drawer overlay */}
      {mobileTreeOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setMobileTreeOpen(false)}
        />
      )}

      {/* Left: tree panel */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-50 w-72 bg-space-900 border-r border-space-700 p-3
          flex flex-col transform transition-transform duration-200 ease-in-out
          lg:relative lg:translate-x-0 lg:z-0 lg:w-64 xl:w-72 lg:rounded-xl lg:border
          ${mobileTreeOpen ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        <div className="flex items-center justify-between mb-1 shrink-0 lg:hidden">
          <span className="text-white font-semibold text-sm">Tree</span>
          <button
            onClick={() => setMobileTreeOpen(false)}
            className="text-gray-400 hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 min-h-0">
          <TreePanel
          roots={tree.roots}
          childrenOf={tree.childrenOf}
          selectedId={selectedId}
          onSelect={handleSelect}
          expandedIds={expandedIds}
          onToggleExpand={handleToggleExpand}
            includeArchived={tree.includeArchived}
            onToggleArchived={tree.setIncludeArchived}
            loading={tree.loading}
          />
        </div>
      </aside>

      {/* Right: main panel */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Breadcrumb bar */}
        <div className="flex items-center gap-2 mb-4">
          <button
            onClick={() => setMobileTreeOpen(true)}
            className="lg:hidden p-2 rounded-lg text-gray-400 hover:text-white hover:bg-space-800 border border-space-700 shrink-0"
            aria-label="Open tree"
          >
            <FolderTree className="w-4 h-4" />
          </button>

          <button
            onClick={goUp}
            disabled={atRoot}
            title="Up one level"
            className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-space-800 border border-space-700 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            <CornerLeftUp className="w-4 h-4" />
          </button>

          <nav className="flex items-center gap-1 text-sm overflow-x-auto whitespace-nowrap flex-1 min-w-0 py-1">
            <button
              onClick={() => handleSelect(null)}
              className={`flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors ${
                atRoot ? 'text-white font-medium' : 'text-gray-400 hover:text-white hover:bg-space-800'
              }`}
            >
              <Home className="w-3.5 h-3.5" />
              All spaces
            </button>
            {path.map((seg, i) => (
              <span key={seg.id} className="flex items-center gap-1">
                <ChevronRight className="w-3.5 h-3.5 text-gray-600 shrink-0" />
                <button
                  onClick={() => handleSelect(seg.id)}
                  className={`px-2 py-1 rounded-md transition-colors ${
                    i === path.length - 1
                      ? 'text-white font-medium'
                      : 'text-gray-400 hover:text-white hover:bg-space-800'
                  }`}
                >
                  {seg.name}
                </button>
              </span>
            ))}
          </nav>

          {canCreateHere && !noRootsYet && (
            <button
              onClick={() => setCreateOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm transition-colors shrink-0"
            >
              <Plus className="w-4 h-4" />
              <span className="hidden sm:inline">New</span>
            </button>
          )}
        </div>

        {/* Selected entity header */}
        {selectedEntity && (
          <div className="flex items-center gap-2.5 mb-3">
            <EntityIcon entity={selectedEntity} className="w-6 h-6" />
            <h1 className="text-xl font-bold text-white truncate">{selectedEntity.name}</h1>
            <span className="text-xs text-gray-500">{KIND_META[selectedEntity.kind].label}</span>
            {selectedEntity.subtype && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-400">
                {selectedEntity.subtype}
              </span>
            )}
            {selectedEntity.archived && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-900/40 border border-yellow-700/40 text-yellow-500">
                archived
              </span>
            )}
          </div>
        )}
        {selectedEntity?.description && (
          <p className="text-sm text-gray-500 mb-3 -mt-1">{selectedEntity.description}</p>
        )}
        {atRoot && !noRootsYet && (
          <h1 className="text-xl font-bold text-white mb-3">All spaces</h1>
        )}

        {/* Children list */}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {tree.error ? (
            <p className="text-sm text-red-400 py-8 text-center">{tree.error}</p>
          ) : noRootsYet ? (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <PackageOpen className="w-12 h-12 text-space-500 mb-4" />
              <h2 className="text-lg font-semibold text-white mb-1">Nothing here yet</h2>
              <p className="text-gray-500 text-sm mb-5">
                Start by creating your first space (e.g. House).
              </p>
              <button
                onClick={() => setCreateOpen(true)}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm transition-colors"
              >
                <Plus className="w-4 h-4" />
                Create your first space
              </button>
            </div>
          ) : listLoading ? (
            <div className="flex items-center gap-2 text-gray-500 text-sm py-8 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading…
            </div>
          ) : listedChildren.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <PackageOpen className="w-10 h-10 text-space-500 mb-3" />
              <p className="text-gray-500 text-sm mb-4">
                {selectedEntity && KIND_META[selectedEntity.kind].allowedChildren.length === 0
                  ? 'Items cannot contain anything.'
                  : 'Nothing inside yet.'}
              </p>
              {canCreateHere && (
                <button
                  onClick={() => setCreateOpen(true)}
                  className="flex items-center gap-2 px-3 py-1.5 bg-space-800 hover:bg-space-700 text-gray-300 border border-space-600 rounded-lg text-sm transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  Add something
                </button>
              )}
            </div>
          ) : (
            <div className="space-y-1">
              {listedChildren.map((child) => (
                <EntityRow
                  key={child.id}
                  entity={child}
                  onOpen={(e) => handleSelect(e.id)}
                  actions={rowActions}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Modals */}
      <CreateEntityModal
        open={createOpen}
        parent={atRoot ? null : selectedEntity}
        onClose={() => setCreateOpen(false)}
        onCreated={() => refetchAll()}
      />
      <RenameEntityModal
        open={renameTarget !== null}
        entity={renameTarget}
        onClose={() => setRenameTarget(null)}
        onRenamed={() => refetchAll()}
      />
      <MoveEntityModal
        open={moveTarget !== null}
        entity={moveTarget}
        roots={tree.roots}
        childrenOf={tree.childrenOf}
        onClose={() => setMoveTarget(null)}
        onMoved={() => refetchAll()}
      />
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete entry"
        message={`Permanently delete “${deleteTarget?.name ?? ''}”? This cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
