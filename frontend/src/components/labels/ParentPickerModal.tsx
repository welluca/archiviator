import { CornerLeftUp } from 'lucide-react';
import Modal from '../browse/Modal';
import EntityIcon from '../browse/EntityIcon';
import type { Entity, EntityKind } from '../../types';
import { KIND_META } from '../../types';

interface ParentPickerModalProps {
  open: boolean;
  /** Kind being created — containment rules decide which parents are valid. */
  kind: EntityKind;
  roots: Entity[];
  childrenOf: Map<number, Entity[]>;
  /** Currently selected parent id; null = root level (spaces only). */
  selectedId: number | null;
  onPick: (id: number | null) => void;
  onClose: () => void;
}

/** Tree picker for the claim create-variant — same pattern as MoveEntityModal,
 * valid targets are the nodes allowed to contain the chosen kind. */
export function ParentPickerModal({
  open,
  kind,
  roots,
  childrenOf,
  selectedId,
  onPick,
  onClose,
}: ParentPickerModalProps) {
  if (!open) return null;

  const pick = (id: number | null) => {
    onPick(id);
    onClose();
  };

  const renderNode = (node: Entity): React.ReactNode => {
    const children = childrenOf.get(node.id) ?? [];
    const valid = KIND_META[node.kind].allowedChildren.includes(kind);
    return (
      <div key={node.id}>
        <button
          type="button"
          disabled={!valid}
          onClick={() => pick(node.id)}
          style={{ paddingLeft: `${node.depth * 14 + 8}px` }}
          className={`w-full flex items-center gap-2 pr-2 py-1.5 rounded-md text-sm text-left transition-colors ${
            selectedId === node.id
              ? 'bg-blue-500/20 text-blue-300'
              : valid
                ? 'text-gray-300 hover:bg-space-800 hover:text-white'
                : 'text-gray-600 cursor-not-allowed'
          }`}
        >
          <EntityIcon entity={node} />
          <span className="truncate">{node.name}</span>
        </button>
        {children.map(renderNode)}
      </div>
    );
  };

  return (
    <Modal open={open} title="Where does it live?" onClose={onClose} maxWidth="max-w-lg">
      <p className="text-xs text-gray-500 mb-3">
        Pick the location for the new {KIND_META[kind].label.toLowerCase()}. Places that
        cannot contain it are disabled.
      </p>

      <div className="border border-space-700 rounded-lg bg-space-950 max-h-72 overflow-y-auto p-1.5">
        {kind === 'space' && (
          <button
            type="button"
            onClick={() => pick(null)}
            className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-left transition-colors ${
              selectedId === null
                ? 'bg-blue-500/20 text-blue-300'
                : 'text-gray-300 hover:bg-space-800 hover:text-white'
            }`}
          >
            <CornerLeftUp className="w-4 h-4 text-gray-500 shrink-0" />
            <span>Root level (no parent)</span>
          </button>
        )}
        {roots.map(renderNode)}
      </div>
    </Modal>
  );
}

export default ParentPickerModal;
