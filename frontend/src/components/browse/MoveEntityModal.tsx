import { useEffect, useMemo, useState } from 'react';
import { CornerLeftUp, Loader2 } from 'lucide-react';
import Modal from './Modal';
import EntityIcon from './EntityIcon';
import { entitiesApi, apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import type { Entity } from '../../types';
import { KIND_META } from '../../types';

interface MoveEntityModalProps {
  open: boolean;
  entity: Entity | null;
  roots: Entity[];
  childrenOf: Map<number, Entity[]>;
  onClose: () => void;
  onMoved: () => void;
}

/** Sentinel for the root-level target (parent_id = null). */
const ROOT_TARGET = 0;

export function MoveEntityModal({
  open,
  entity,
  roots,
  childrenOf,
  onClose,
  onMoved,
}: MoveEntityModalProps) {
  const toast = useToast();
  const [targetId, setTargetId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setTargetId(null);
      setSaving(false);
    }
  }, [open, entity]);

  // Self + all descendants are forbidden targets (cycle guard, mirrored client-side).
  const forbiddenIds = useMemo(() => {
    const set = new Set<number>();
    if (!entity) return set;
    const stack = [entity.id];
    while (stack.length > 0) {
      const id = stack.pop()!;
      set.add(id);
      for (const child of childrenOf.get(id) ?? []) stack.push(child.id);
    }
    return set;
  }, [entity, childrenOf]);

  if (!open || !entity) return null;

  const canGoToRoot = entity.kind === 'space';

  const isValidTarget = (target: Entity): boolean =>
    !forbiddenIds.has(target.id) &&
    KIND_META[target.kind].allowedChildren.includes(entity.kind);

  const handleMove = async () => {
    if (targetId === null || saving) return;
    setSaving(true);
    try {
      await entitiesApi.move(entity.id, targetId === ROOT_TARGET ? null : targetId);
      toast.success(`Moved “${entity.name}”`);
      onMoved();
      onClose();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to move'));
      setSaving(false);
    }
  };

  const renderNode = (node: Entity): React.ReactNode => {
    const children = childrenOf.get(node.id) ?? [];
    const valid = isValidTarget(node);
    const isCurrent = node.id === entity.parent_id;
    const isSelf = forbiddenIds.has(node.id);
    return (
      <div key={node.id}>
        <button
          type="button"
          disabled={!valid}
          onClick={() => setTargetId(node.id)}
          style={{ paddingLeft: `${node.depth * 14 + 8}px` }}
          className={`w-full flex items-center gap-2 pr-2 py-1.5 rounded-md text-sm text-left transition-colors ${
            targetId === node.id
              ? 'bg-blue-500/20 text-blue-300'
              : valid
                ? 'text-gray-300 hover:bg-space-800 hover:text-white'
                : 'text-gray-600 cursor-not-allowed'
          }`}
        >
          <EntityIcon entity={node} />
          <span className="truncate">{node.name}</span>
          {isCurrent && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-500 shrink-0">
              current
            </span>
          )}
          {isSelf && node.id === entity.id && (
            <span className="text-[10px] text-gray-600 shrink-0">(this)</span>
          )}
        </button>
        {children.map(renderNode)}
      </div>
    );
  };

  return (
    <Modal open={open} title={`Move “${entity.name}”`} onClose={onClose} maxWidth="max-w-lg">
      <p className="text-xs text-gray-500 mb-3">
        Pick a new location. Invalid targets (wrong kind, itself, or its own contents) are
        disabled.
      </p>

      <div className="border border-space-700 rounded-lg bg-space-950 max-h-72 overflow-y-auto p-1.5 mb-4">
        {canGoToRoot && (
          <button
            type="button"
            onClick={() => setTargetId(ROOT_TARGET)}
            className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-left transition-colors ${
              targetId === ROOT_TARGET
                ? 'bg-blue-500/20 text-blue-300'
                : 'text-gray-300 hover:bg-space-800 hover:text-white'
            }`}
          >
            <CornerLeftUp className="w-4 h-4 text-gray-500 shrink-0" />
            <span>Root level (no parent)</span>
            {entity.parent_id === null && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-500 shrink-0">
                current
              </span>
            )}
          </button>
        )}
        {roots.map(renderNode)}
      </div>

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="px-4 py-2 bg-space-800 hover:bg-space-700 text-gray-300 rounded-lg text-sm border border-space-600 transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleMove}
          disabled={targetId === null || saving}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors flex items-center gap-2"
        >
          {saving && <Loader2 className="w-4 h-4 animate-spin" />}
          Move here
        </button>
      </div>
    </Modal>
  );
}

export default MoveEntityModal;
