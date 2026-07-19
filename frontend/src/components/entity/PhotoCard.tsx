import { useState } from 'react';
import { Check, Loader2, Pencil, Star, Trash2, X } from 'lucide-react';
import type { Attachment } from '../../types';

interface PhotoCardProps {
  photo: Attachment;
  isCover: boolean;
  onOpen: () => void;
  onSetCover: () => void;
  /** Persist a new title (null clears it). Resolves when saved. */
  onSaveTitle: (title: string | null) => Promise<void>;
  onDelete: () => void;
}

const toolbarBtn =
  'p-1.5 rounded-md bg-black/60 backdrop-blur-sm transition-colors';

/** One gallery tile: 320px thumb, cover badge, hover toolbar, inline title editor. */
export function PhotoCard({
  photo,
  isCover,
  onOpen,
  onSetCover,
  onSaveTitle,
  onDelete,
}: PhotoCardProps) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);

  const startEdit = () => {
    setTitle(photo.title ?? '');
    setEditing(true);
  };

  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await onSaveTitle(title.trim() || null);
      setEditing(false);
    } catch {
      // parent already toasted — keep the editor open
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="group relative aspect-square rounded-lg overflow-hidden border border-space-700 bg-space-900">
      <button onClick={onOpen} className="block w-full h-full" aria-label="View photo">
        <img
          src={photo.urls.thumb ?? photo.urls.original}
          alt={photo.title ?? 'Photo'}
          loading="lazy"
          className="w-full h-full object-cover transition-transform duration-200 group-hover:scale-[1.03]"
        />
      </button>

      {/* Cover badge */}
      {isCover && (
        <span
          title="Cover photo"
          className="absolute top-1.5 left-1.5 p-1 rounded-full bg-black/60 backdrop-blur-sm text-yellow-400"
        >
          <Star className="w-3.5 h-3.5 fill-current" />
        </span>
      )}

      {/* Hover toolbar */}
      {!editing && (
        <div className="absolute top-1.5 right-1.5 flex gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
          {!isCover && (
            <button
              onClick={onSetCover}
              title="Make cover"
              className={`${toolbarBtn} text-gray-300 hover:text-yellow-400`}
            >
              <Star className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={startEdit}
            title="Edit title"
            className={`${toolbarBtn} text-gray-300 hover:text-white`}
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onDelete}
            title="Delete photo"
            className={`${toolbarBtn} text-gray-300 hover:text-red-400`}
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Title strip */}
      {photo.title && !editing && (
        <div className="absolute bottom-0 inset-x-0 px-2 py-1 bg-black/60 backdrop-blur-sm text-[11px] text-gray-200 truncate pointer-events-none">
          {photo.title}
        </div>
      )}

      {/* Inline title editor popover */}
      {editing && (
        <div className="absolute inset-x-1.5 bottom-1.5 z-10">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
            className="flex items-center gap-1 bg-space-950/95 border border-space-600 rounded-lg p-1"
          >
            <input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setEditing(false);
              }}
              placeholder="Title…"
              className="flex-1 min-w-0 bg-transparent px-1.5 py-1 text-xs text-white placeholder-gray-600 focus:outline-none"
            />
            <button
              type="submit"
              disabled={saving}
              title="Save title"
              className="p-1 rounded text-green-400 hover:bg-space-800 disabled:opacity-50"
            >
              {saving ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Check className="w-3.5 h-3.5" />
              )}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              title="Cancel"
              className="p-1 rounded text-gray-400 hover:bg-space-800 hover:text-white"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

export default PhotoCard;
