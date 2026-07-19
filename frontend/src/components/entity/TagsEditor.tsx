import { useEffect, useMemo, useState } from 'react';
import { Loader2, Plus, Tag as TagIcon } from 'lucide-react';
import { tagsApi } from '../../api/metadata';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import TagChip from '../ui/TagChip';
import type { Entity, Tag, TagLite } from '../../types';

interface TagsEditorProps {
  entity: Entity;
  /** PUT returns the full EntityOut — propagate so the page stays canonical. */
  onEntityUpdate: (e: Entity) => void;
}

/** Chip row + create-on-type input. Every add/remove PUTs the full name set
 * instantly (optimistic, reverted with a toast on failure). */
export function TagsEditor({ entity, onEntityUpdate }: TagsEditorProps) {
  const toast = useToast();
  const [tags, setTags] = useState<TagLite[]>(entity.tags ?? []);
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [input, setInput] = useState('');
  const [focused, setFocused] = useState(false);
  const [saving, setSaving] = useState(false);

  // Follow the entity (navigation between details, server-canonical updates).
  useEffect(() => {
    setTags(entity.tags ?? []);
  }, [entity]);

  useEffect(() => {
    tagsApi.list().then(setAllTags).catch(() => {});
  }, []);

  const putTags = async (names: string[], prev: TagLite[]) => {
    setSaving(true);
    try {
      const updated = await tagsApi.setEntityTags(entity.id, names);
      setTags(updated.tags ?? []);
      onEntityUpdate(updated);
      tagsApi.list().then(setAllTags).catch(() => {}); // pick up auto-created tags
    } catch (err) {
      setTags(prev);
      toast.error(apiErrorDetail(err, 'Failed to update tags'));
    } finally {
      setSaving(false);
    }
  };

  const addTag = (rawName: string) => {
    const name = rawName.trim().replace(/,+$/, '').trim();
    if (!name || saving) return;
    if (tags.some((t) => t.name.toLowerCase() === name.toLowerCase())) {
      setInput('');
      return;
    }
    const known = allTags.find((t) => t.name.toLowerCase() === name.toLowerCase());
    const prev = tags;
    const optimistic = [
      ...tags,
      known ?? { id: -Date.now(), name, color: null }, // temp id until the PUT echoes back
    ];
    setTags(optimistic);
    setInput('');
    putTags(optimistic.map((t) => t.name), prev);
  };

  const removeTag = (tag: TagLite) => {
    if (saving) return;
    const prev = tags;
    const next = tags.filter((t) => t.id !== tag.id);
    setTags(next);
    putTags(next.map((t) => t.name), prev);
  };

  const onKeyDown = (ev: React.KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === 'Enter' || ev.key === ',') {
      ev.preventDefault();
      addTag(input);
    } else if (ev.key === 'Backspace' && input === '' && tags.length > 0) {
      removeTag(tags[tags.length - 1]);
    } else if (ev.key === 'Escape') {
      (ev.target as HTMLInputElement).blur();
    }
  };

  const suggestions = useMemo(() => {
    const term = input.trim().toLowerCase();
    const taken = new Set(tags.map((t) => t.name.toLowerCase()));
    return allTags
      .filter((t) => !taken.has(t.name.toLowerCase()))
      .filter((t) => term === '' || t.name.toLowerCase().includes(term))
      .slice(0, 8);
  }, [allTags, tags, input]);

  const term = input.trim();
  const exactExists =
    term !== '' &&
    (allTags.some((t) => t.name.toLowerCase() === term.toLowerCase()) ||
      tags.some((t) => t.name.toLowerCase() === term.toLowerCase()));
  const showCreate = term !== '' && !exactExists;
  const dropdownOpen = focused && (suggestions.length > 0 || showCreate);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <TagIcon className="w-4 h-4 text-gray-500 shrink-0" />
      {tags.map((t) => (
        <TagChip key={t.id} tag={t} onRemove={() => removeTag(t)} />
      ))}

      <div className="relative">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={tags.length > 0 ? 'Add tag' : 'Add tags…'}
          className="bg-transparent border border-dashed border-space-700 focus:border-blue-500 rounded-full px-2.5 py-0.5 text-xs text-white w-24 focus:w-40 transition-all placeholder-gray-600 focus:outline-none"
        />
        {saving && (
          <Loader2 className="absolute -right-6 top-1/2 -translate-y-1/2 w-3.5 h-3.5 animate-spin text-gray-500" />
        )}

        {dropdownOpen && (
          <div className="absolute left-0 top-full mt-1 z-30 w-52 bg-space-900 border border-space-700 rounded-lg shadow-lg shadow-black/40 py-1 overflow-hidden">
            {suggestions.map((t) => (
              <button
                key={t.id}
                type="button"
                // mousedown + preventDefault keeps the input focused (no blur race)
                onMouseDown={(e) => {
                  e.preventDefault();
                  addTag(t.name);
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-gray-300 hover:bg-space-800 hover:text-white text-left transition-colors"
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: t.color || '#64748b' }}
                />
                <span className="flex-1 truncate">{t.name}</span>
                {t.usage_count !== undefined && (
                  <span className="text-[10px] text-gray-600 shrink-0">{t.usage_count}</span>
                )}
              </button>
            ))}
            {showCreate && (
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  addTag(term);
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-blue-300 hover:bg-space-800 text-left transition-colors"
              >
                <Plus className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">Create “{term}”</span>
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default TagsEditor;
