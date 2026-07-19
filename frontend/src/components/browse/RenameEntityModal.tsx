import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import Modal from './Modal';
import { entitiesApi, apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import type { Entity } from '../../types';

interface RenameEntityModalProps {
  open: boolean;
  entity: Entity | null;
  onClose: () => void;
  onRenamed: () => void;
}

export function RenameEntityModal({ open, entity, onClose, onRenamed }: RenameEntityModalProps) {
  const toast = useToast();
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && entity) {
      setName(entity.name);
      setSaving(false);
    }
  }, [open, entity]);

  if (!open || !entity) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || saving) return;
    if (trimmed === entity.name) {
      onClose();
      return;
    }
    setSaving(true);
    try {
      await entitiesApi.update(entity.id, { name: trimmed });
      toast.success(`Renamed to “${trimmed}”`);
      onRenamed();
      onClose();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to rename'));
      setSaving(false);
    }
  };

  return (
    <Modal open={open} title={`Rename “${entity.name}”`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onFocus={(e) => e.target.select()}
          className="w-full bg-space-950 border border-space-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
        />
        <div className="flex justify-end gap-2">
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
            Rename
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default RenameEntityModal;
