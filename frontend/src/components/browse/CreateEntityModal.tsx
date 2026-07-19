import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import Modal from './Modal';
import { entitiesApi, apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import type { Entity, EntityKind } from '../../types';
import { KIND_META } from '../../types';

interface CreateEntityModalProps {
  open: boolean;
  /** Parent to create under; null = root level (spaces only). */
  parent: Entity | null;
  onClose: () => void;
  onCreated: (entity: Entity) => void;
}

const inputClass =
  'w-full bg-space-950 border border-space-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500';

export function CreateEntityModal({ open, parent, onClose, onCreated }: CreateEntityModalProps) {
  const toast = useToast();
  const allowedKinds: EntityKind[] = parent ? KIND_META[parent.kind].allowedChildren : ['space'];

  const [kind, setKind] = useState<EntityKind>(allowedKinds[0] ?? 'space');
  const [name, setName] = useState('');
  const [subtype, setSubtype] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);

  // Reset the form each time the modal opens (parent may have changed).
  useEffect(() => {
    if (open) {
      setKind(parent ? KIND_META[parent.kind].allowedChildren[0] ?? 'space' : 'space');
      setName('');
      setSubtype('');
      setDescription('');
      setSaving(false);
    }
  }, [open, parent]);

  if (!open) return null;

  const suggestions = KIND_META[kind].subtypeSuggestions;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || saving) return;
    setSaving(true);
    try {
      const created = await entitiesApi.create({
        name: trimmed,
        kind,
        parent_id: parent ? parent.id : null,
        subtype: subtype.trim() || undefined,
        description: description.trim() || undefined,
      });
      toast.success(`Created ${KIND_META[kind].label.toLowerCase()} “${created.name}”`);
      onCreated(created);
      onClose();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to create entity'));
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      title={parent ? `New in “${parent.name}”` : 'New space'}
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Kind</label>
          <div className="flex flex-wrap gap-2">
            {allowedKinds.map((k) => {
              const Icon = KIND_META[k].icon;
              return (
                <button
                  key={k}
                  type="button"
                  onClick={() => setKind(k)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                    kind === k
                      ? 'bg-blue-500/20 border-blue-500/50 text-blue-300'
                      : 'bg-space-950 border-space-700 text-gray-400 hover:text-white hover:border-space-600'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {KIND_META[k].label}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Name *</label>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={kind === 'space' ? 'e.g. House' : 'Name'}
            className={inputClass}
          />
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Subtype</label>
          <input
            value={subtype}
            onChange={(e) => setSubtype(e.target.value)}
            list={suggestions.length > 0 ? 'subtype-suggestions' : undefined}
            placeholder={suggestions.length > 0 ? suggestions.join(' / ') : 'Optional'}
            className={inputClass}
          />
          {suggestions.length > 0 && (
            <datalist id="subtype-suggestions">
              {suggestions.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          )}
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="Optional"
            className={`${inputClass} resize-none`}
          />
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 bg-space-800 hover:bg-space-700 text-gray-300 rounded-lg text-sm border border-space-600 transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!name.trim() || saving}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors flex items-center gap-2"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            Create
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default CreateEntityModal;
