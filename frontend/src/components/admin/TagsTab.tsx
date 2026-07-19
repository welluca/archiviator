import { useCallback, useEffect, useRef, useState } from 'react';
import { Ban, Check, Loader2, Pencil, Tags, Trash2, X } from 'lucide-react';
import { tagsApi } from '../../api/metadata';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import type { Tag } from '../../types';

const FALLBACK_DOT = '#64748b';

/** Preset swatches offered by the recolor popover. */
const PALETTE = [
  '#ef4444', '#f97316', '#f59e0b', '#84cc16', '#22c55e', '#14b8a6',
  '#0ea5e9', '#3b82f6', '#8b5cf6', '#d946ef', '#ec4899', '#94a3b8',
];

const inputSm =
  'bg-space-950 border border-space-700 rounded-md px-2 py-1.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500';

function SwatchPicker({
  current,
  onPick,
  onClose,
}: {
  current: string | null;
  onPick: (color: string | null) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (ev: MouseEvent) => {
      if (ref.current && !ref.current.contains(ev.target as Node)) onClose();
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="absolute left-0 top-full mt-1 z-30 p-2 bg-space-900 border border-space-700 rounded-lg shadow-lg shadow-black/40 w-40"
    >
      <div className="grid grid-cols-6 gap-1.5">
        {PALETTE.map((c) => (
          <button
            key={c}
            onClick={() => onPick(c)}
            title={c}
            className={`w-5 h-5 rounded-full border-2 transition-transform hover:scale-110 ${
              current === c ? 'border-white' : 'border-transparent'
            }`}
            style={{ backgroundColor: c }}
          />
        ))}
      </div>
      <button
        onClick={() => onPick(null)}
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-2 py-1 rounded-md text-xs text-gray-400 hover:text-white hover:bg-space-800 transition-colors"
      >
        <Ban className="w-3 h-3" /> No color
      </button>
    </div>
  );
}

export default function TagsTab() {
  const toast = useToast();
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [savingName, setSavingName] = useState(false);
  const [pickerId, setPickerId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Tag | null>(null);

  const load = useCallback(async () => {
    try {
      setTags(await tagsApi.list());
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to load tags'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRename = async () => {
    if (editId === null || savingName) return;
    const name = editName.trim();
    if (name === '') return;
    setSavingName(true);
    try {
      await tagsApi.update(editId, { name });
      setEditId(null);
      await load();
      toast.success('Tag renamed');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to rename tag'));
    } finally {
      setSavingName(false);
    }
  };

  const handleRecolor = async (tag: Tag, color: string | null) => {
    setPickerId(null);
    try {
      const updated = await tagsApi.update(tag.id, { color });
      setTags((prev) => prev.map((t) => (t.id === tag.id ? { ...t, color: updated.color } : t)));
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to recolor tag'));
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setDeleteTarget(null);
    try {
      await tagsApi.remove(target.id);
      await load();
      toast.success(`Tag “${target.name}” deleted`);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to delete tag'));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-sm py-12 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading…
      </div>
    );
  }

  return (
    <div className="bg-space-900 border border-space-700 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Tags className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-semibold text-white">Tags</h3>
        <span className="text-xs text-gray-500">{tags.length}</span>
      </div>

      {tags.length === 0 ? (
        <p className="text-sm text-gray-500 py-6 text-center">
          No tags yet — they are created on the fly when you tag entries.
        </p>
      ) : (
        <div className="space-y-0.5">
          {tags.map((tag) => (
            <div
              key={tag.id}
              className="group flex items-center gap-3 px-2 py-1.5 rounded-lg hover:bg-space-800/60 transition-colors"
            >
              {/* Color swatch + picker */}
              <div className="relative shrink-0">
                <button
                  onClick={() => setPickerId(pickerId === tag.id ? null : tag.id)}
                  title="Change color"
                  className="w-4 h-4 rounded-full border border-space-600 hover:scale-110 transition-transform"
                  style={{ backgroundColor: tag.color || FALLBACK_DOT }}
                />
                {pickerId === tag.id && (
                  <SwatchPicker
                    current={tag.color}
                    onPick={(c) => handleRecolor(tag, c)}
                    onClose={() => setPickerId(null)}
                  />
                )}
              </div>

              {/* Name (inline rename) */}
              {editId === tag.id ? (
                <div className="flex items-center gap-1.5 flex-1 min-w-0">
                  <input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRename();
                      if (e.key === 'Escape') setEditId(null);
                    }}
                    autoFocus
                    className={`${inputSm} flex-1 min-w-0`}
                  />
                  <button
                    onClick={handleRename}
                    disabled={savingName || editName.trim() === ''}
                    title="Save"
                    className="p-1.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white transition-colors"
                  >
                    {savingName ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Check className="w-3.5 h-3.5" />
                    )}
                  </button>
                  <button
                    onClick={() => setEditId(null)}
                    title="Cancel"
                    className="p-1.5 rounded-md text-gray-500 hover:text-white hover:bg-space-700 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ) : (
                <>
                  <span className="flex-1 min-w-0 text-sm text-white truncate">{tag.name}</span>
                  <span className="text-xs text-gray-500 shrink-0">
                    {tag.usage_count ?? 0} {(tag.usage_count ?? 0) === 1 ? 'entry' : 'entries'}
                  </span>
                  <button
                    onClick={() => {
                      setEditId(tag.id);
                      setEditName(tag.name);
                    }}
                    title="Rename"
                    className="p-1.5 rounded-md text-gray-600 hover:text-white hover:bg-space-700 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setDeleteTarget(tag)}
                    title="Delete tag"
                    className="p-1.5 rounded-md text-gray-600 hover:text-red-400 hover:bg-space-700 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete tag"
        message={`Delete “${deleteTarget?.name ?? ''}”? It is removed from ${
          deleteTarget?.usage_count ?? 0
        } entr${(deleteTarget?.usage_count ?? 0) === 1 ? 'y' : 'ies'}.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
