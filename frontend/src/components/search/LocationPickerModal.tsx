import { Globe } from 'lucide-react';
import Modal from '../browse/Modal';
import EntityIcon from '../browse/EntityIcon';
import type { Entity } from '../../types';

interface LocationPickerModalProps {
  open: boolean;
  roots: Entity[];
  childrenOf: Map<number, Entity[]>;
  /** Currently selected 'under' entity id, or null for anywhere. */
  selectedId: number | null;
  onPick: (id: number | null) => void;
  onClose: () => void;
}

/** Tree picker for the search 'inside' filter — same pattern as MoveEntityModal,
 * but every non-item node is a valid scope (items cannot contain anything). */
export function LocationPickerModal({
  open,
  roots,
  childrenOf,
  selectedId,
  onPick,
  onClose,
}: LocationPickerModalProps) {
  if (!open) return null;

  const pick = (id: number | null) => {
    onPick(id);
    onClose();
  };

  const renderNode = (node: Entity): React.ReactNode => {
    const children = childrenOf.get(node.id) ?? [];
    const valid = node.kind !== 'item';
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
    <Modal open={open} title="Search inside…" onClose={onClose} maxWidth="max-w-lg">
      <p className="text-xs text-gray-500 mb-3">
        Limit results to a space, furniture or container — everything inside it is
        included.
      </p>

      <div className="border border-space-700 rounded-lg bg-space-950 max-h-72 overflow-y-auto p-1.5">
        <button
          type="button"
          onClick={() => pick(null)}
          className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-left transition-colors ${
            selectedId === null
              ? 'bg-blue-500/20 text-blue-300'
              : 'text-gray-300 hover:bg-space-800 hover:text-white'
          }`}
        >
          <Globe className="w-4 h-4 text-gray-500 shrink-0" />
          <span>Anywhere</span>
        </button>
        {roots.map(renderNode)}
      </div>
    </Modal>
  );
}

export default LocationPickerModal;
