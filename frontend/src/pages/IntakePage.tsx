import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Camera,
  Check,
  CheckCircle2,
  FolderInput,
  Inbox,
  LayoutGrid,
  Loader2,
  MapPin,
  RefreshCw,
  RotateCw,
  Save,
  X,
} from 'lucide-react';
import { intakeApi, type PromotePayload } from '../api/intake';
import { entitiesApi, apiErrorDetail } from '../api/entities';
import { attachmentsApi } from '../api/attachments';
import { tagsApi, categoriesApi, presetsApi } from '../api/metadata';
import { useEntityTree } from '../hooks/useEntityTree';
import { useToast } from '../components/ui/Toast';
import EntityIcon from '../components/browse/EntityIcon';
import TagChip from '../components/ui/TagChip';
import Lightbox from '../components/entity/Lightbox';
import LocationPickerModal from '../components/search/LocationPickerModal';
import type { Attachment, Category, Entity, Preset, Tag } from '../types';

// ── Sticky defaults (localStorage) ───────────────────────────────────────────

const DEFAULTS_KEY = 'intake.defaults';
/** Bump when the stored shape changes — old payloads are discarded, not guessed at. */
const DEFAULTS_VERSION = 1;

interface IntakeDefaults {
  parentId: number | null;
  categoryId: number | null;
  tags: string[];
}

const loadDefaults = (): IntakeDefaults => {
  try {
    const raw = localStorage.getItem(DEFAULTS_KEY);
    if (raw) {
      const p = JSON.parse(raw);
      if (p?.v === DEFAULTS_VERSION) {
        return {
          parentId: typeof p.parentId === 'number' ? p.parentId : null,
          categoryId: typeof p.categoryId === 'number' ? p.categoryId : null,
          tags: Array.isArray(p.tags)
            ? p.tags.filter((t: unknown): t is string => typeof t === 'string')
            : [],
        };
      }
    }
  } catch {
    /* corrupted storage — fall through to clean defaults */
  }
  return { parentId: null, categoryId: null, tags: [] };
};

// ── Lite tag chips input (local state only — applied on promote) ─────────────

function ChipsInput({
  value,
  onChange,
  allTags,
  placeholder = 'Add tag',
}: {
  value: string[];
  onChange: (tags: string[]) => void;
  allTags: Tag[];
  placeholder?: string;
}) {
  const [input, setInput] = useState('');
  const listId = useId();

  const colorOf = (name: string): string | null =>
    allTags.find((t) => t.name.toLowerCase() === name.toLowerCase())?.color ?? null;

  const commit = (raw: string) => {
    const name = raw.trim().replace(/,+$/, '').trim();
    setInput('');
    if (!name) return;
    if (value.some((v) => v.toLowerCase() === name.toLowerCase())) return;
    onChange([...value, name]);
  };

  const onKeyDown = (ev: React.KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === 'Enter' || ev.key === ',') {
      ev.preventDefault();
      ev.stopPropagation(); // don't trigger the card's Enter-to-file flow
      commit(input);
    } else if (ev.key === 'Backspace' && input === '' && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  };

  const suggestions = allTags
    .filter((t) => !value.some((v) => v.toLowerCase() === t.name.toLowerCase()))
    .slice(0, 20);

  return (
    <div className="flex flex-wrap items-center gap-1">
      {value.map((name, i) => (
        <TagChip
          key={name}
          tag={{ id: i, name, color: colorOf(name) }}
          onRemove={() => onChange(value.filter((v) => v !== name))}
        />
      ))}
      <input
        value={input}
        list={listId}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => commit(input)}
        placeholder={placeholder}
        className="bg-transparent border border-dashed border-space-700 focus:border-blue-500 rounded-full px-2 py-0.5 text-xs text-white w-20 focus:w-32 transition-all placeholder-gray-600 focus:outline-none"
      />
      <datalist id={listId}>
        {suggestions.map((t) => (
          <option key={t.id} value={t.name} />
        ))}
      </datalist>
    </div>
  );
}

// ── Capture queue types ──────────────────────────────────────────────────────

type QueueStatus = 'pending' | 'uploading' | 'done' | 'error';

interface QueueItem {
  id: number;
  file: File;
  previewUrl: string;
  name?: string;
  status: QueueStatus;
  error?: string;
}

// ── Page ─────────────────────────────────────────────────────────────────────

/** M7 intake: phone = giant capture button feeding drafts into the Inbox,
 * desktop = triage grid batch-filing drafts into real locations. */
export default function IntakePage() {
  const toast = useToast();
  const tree = useEntityTree();

  // ── Split personality: capture < md, triage >= md, manual override ───────
  const [isDesktop, setIsDesktop] = useState(
    () => window.matchMedia('(min-width: 768px)').matches
  );
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)');
    const onChange = (e: MediaQueryListEvent) => setIsDesktop(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  const [modeOverride, setModeOverride] = useState<'capture' | 'triage' | null>(null);
  const mode: 'capture' | 'triage' = modeOverride ?? (isDesktop ? 'triage' : 'capture');

  // ═══ CAPTURE MODE ══════════════════════════════════════════════════════════

  const [queue, setQueue] = useState<QueueItem[]>([]);
  // Ref mirrors state synchronously so the sequential pump never reads stale data.
  const queueRef = useRef<QueueItem[]>([]);
  const setQueueBoth = (updater: (prev: QueueItem[]) => QueueItem[]) => {
    queueRef.current = updater(queueRef.current);
    setQueue(queueRef.current);
  };

  const busyRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const nextIdRef = useRef(1);
  const fileRef = useRef<HTMLInputElement>(null);

  const [nameEnabled, setNameEnabled] = useState(false);
  const [nameInput, setNameInput] = useState('');

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
      for (const it of queueRef.current) URL.revokeObjectURL(it.previewUrl);
    };
  }, []);

  /** Sequential upload pump — one in flight at a time, no double-submits. */
  const pump = useCallback(async () => {
    if (busyRef.current || !mountedRef.current) return;
    const next = queueRef.current.find((i) => i.status === 'pending');
    if (!next) return;
    busyRef.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    setQueueBoth((prev) =>
      prev.map((i) => (i.id === next.id ? { ...i, status: 'uploading' } : i))
    );
    try {
      await intakeApi.capture(next.file, { name: next.name, signal: controller.signal });
      if (!mountedRef.current) return;
      setQueueBoth((prev) =>
        prev.map((i) => (i.id === next.id ? { ...i, status: 'done' } : i))
      );
    } catch (err) {
      if (!mountedRef.current || controller.signal.aborted) return;
      setQueueBoth((prev) =>
        prev.map((i) =>
          i.id === next.id
            ? { ...i, status: 'error', error: apiErrorDetail(err, 'Upload failed') }
            : i
        )
      );
    } finally {
      busyRef.current = false;
      abortRef.current = null;
      if (mountedRef.current) pump();
    }
  }, []);

  const onShoot = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ''; // allow shooting again immediately
    if (files.length === 0) return;
    const name = nameEnabled && nameInput.trim() !== '' ? nameInput.trim() : undefined;
    const items: QueueItem[] = files.map((f) => ({
      id: nextIdRef.current++,
      file: f,
      previewUrl: URL.createObjectURL(f),
      name,
      status: 'pending',
    }));
    setQueueBoth((prev) => [...prev, ...items]);
    if (name) setNameInput(''); // one name per shot — clear for the next
    pump();
  };

  const retryItem = (id: number) => {
    setQueueBoth((prev) =>
      prev.map((i) =>
        i.id === id && i.status === 'error'
          ? { ...i, status: 'pending', error: undefined }
          : i
      )
    );
    pump();
  };

  const doneCount = queue.filter((i) => i.status === 'done').length;
  const failedCount = queue.filter((i) => i.status === 'error').length;
  const inFlight = queue.some((i) => i.status === 'uploading' || i.status === 'pending');

  // ═══ TRIAGE MODE ═══════════════════════════════════════════════════════════

  const [drafts, setDrafts] = useState<Entity[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [leaving, setLeaving] = useState<Set<number>>(new Set());
  const [cardErrors, setCardErrors] = useState<Record<number, string>>({});
  const [promoting, setPromoting] = useState(false);

  // Sticky last-used location/category/tags.
  const [defaults, setDefaults] = useState<IntakeDefaults>(loadDefaults);
  const defaultsRef = useRef(defaults);
  useEffect(() => {
    defaultsRef.current = defaults;
    try {
      localStorage.setItem(DEFAULTS_KEY, JSON.stringify({ v: DEFAULTS_VERSION, ...defaults }));
    } catch {
      /* storage full/blocked — sticky defaults just won't persist */
    }
  }, [defaults]);

  // Per-card overrides, seeded from entity + sticky defaults when a card appears.
  interface CardState {
    parentId: number | null;
    categoryId: number | null;
    tags: string[];
  }
  const [cardState, setCardState] = useState<Record<number, CardState>>({});
  const [nameDrafts, setNameDrafts] = useState<Record<number, string>>({});
  const [savingName, setSavingName] = useState<number | null>(null);

  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoriesLoaded, setCategoriesLoaded] = useState(false);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetId, setPresetId] = useState('');

  const [pickerFor, setPickerFor] = useState<'batch' | number | null>(null);
  const [lightbox, setLightbox] = useState<{ photos: Attachment[]; index: number } | null>(
    null
  );
  const nameRefs = useRef(new Map<number, HTMLInputElement>());

  const refreshDrafts = useCallback(async (silent = false) => {
    if (!silent) setRefreshing(true);
    try {
      const list = await intakeApi.drafts();
      if (!mountedRef.current) return;
      setDrafts(list);
      setLeaving(new Set());
      setSelection((prev) => {
        const alive = new Set(list.map((d) => d.id));
        const next = new Set([...prev].filter((id) => alive.has(id)));
        return next.size === prev.size ? prev : next;
      });
    } catch (err) {
      if (mountedRef.current) toast.error(apiErrorDetail(err, 'Failed to load drafts'));
    } finally {
      if (mountedRef.current) setRefreshing(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (mode !== 'triage') return;
    refreshDrafts(true);
    tagsApi.list().then(setAllTags).catch(() => {});
    categoriesApi
      .list()
      .then((list) => {
        setCategories(list);
        setCategoriesLoaded(true);
      })
      .catch(() => {});
    presetsApi.list().then(setPresets).catch(() => {});
  }, [mode, refreshDrafts]);

  // Seed per-card state for newly appeared drafts (never clobber edits).
  useEffect(() => {
    if (!drafts) return;
    setCardState((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const d of drafts) {
        if (!next[d.id]) {
          changed = true;
          next[d.id] = {
            parentId: defaultsRef.current.parentId,
            categoryId: d.category_id ?? defaultsRef.current.categoryId,
            tags:
              d.tags.length > 0 ? d.tags.map((t) => t.name) : [...defaultsRef.current.tags],
          };
        }
      }
      return changed ? next : prev;
    });
    setNameDrafts((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const d of drafts) {
        if (next[d.id] === undefined) {
          changed = true;
          next[d.id] = d.name;
        }
      }
      return changed ? next : prev;
    });
  }, [drafts]);

  const patchCard = (id: number, patch: Partial<CardState>) =>
    setCardState((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));

  const visibleDrafts = useMemo(
    () => (drafts ?? []).filter((d) => !leaving.has(d.id)),
    [drafts, leaving]
  );
  // Ref kept in sync for async handlers (Enter-to-next-card): the render
  // closure captured before an await can hold cards that have since left.
  const visibleDraftsRef = useRef<Entity[]>([]);
  useEffect(() => {
    visibleDraftsRef.current = visibleDrafts;
  }, [visibleDrafts]);

  /** Promote-time guard for sticky/seeded ids: a saved parent or category that
   * no longer exists (deleted elsewhere, stale localStorage) is dropped from
   * the request AND pruned from the saved defaults so it never comes back.
   * Empty byId / unloaded categories mean "not loaded yet", never "stale" —
   * the tree always contains at least the Inbox. */
  const validateStickyIds = (parentId: number | null, categoryId: number | null) => {
    const parentOk =
      parentId === null || tree.byId.size === 0 || tree.byId.has(parentId);
    const categoryOk =
      categoryId === null || !categoriesLoaded || categories.some((c) => c.id === categoryId);
    if (!parentOk || !categoryOk) {
      setDefaults((prev) => ({
        ...prev,
        parentId: !parentOk && prev.parentId === parentId ? null : prev.parentId,
        categoryId: !categoryOk && prev.categoryId === categoryId ? null : prev.categoryId,
      }));
      toast.info('Saved default location no longer exists — cleared');
    }
    return { parentOk, categoryOk };
  };

  // ── Name editing: Enter saves and focuses the NEXT card's name ───────────
  const saveName = async (entity: Entity): Promise<boolean> => {
    const name = (nameDrafts[entity.id] ?? entity.name).trim();
    if (name === '' || name === entity.name) return true; // nothing to save
    setSavingName(entity.id);
    try {
      const updated = await entitiesApi.update(entity.id, { name });
      setDrafts((prev) =>
        prev ? prev.map((d) => (d.id === updated.id ? updated : d)) : prev
      );
      return true;
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to rename'));
      return false;
    } finally {
      setSavingName(null);
    }
  };

  const onNameEnter = async (entity: Entity) => {
    const ok = await saveName(entity);
    if (!ok) return;
    // Current visible drafts from the ref — cards may have left during the await.
    const order = visibleDraftsRef.current.map((d) => d.id);
    const nextId = order[order.indexOf(entity.id) + 1];
    if (nextId !== undefined) {
      const el = nameRefs.current.get(nextId);
      el?.focus();
      el?.select();
    }
  };

  // ── Promote ──────────────────────────────────────────────────────────────
  const applyPromoteResult = (
    res: Awaited<ReturnType<typeof intakeApi.promote>>,
    requested: number[]
  ) => {
    const promotedIds = res.promoted.map((e) => e.id);
    setCardErrors((prev) => {
      const next = { ...prev };
      for (const id of requested) delete next[id];
      for (const er of res.errors) next[er.entity_id] = er.message;
      return next;
    });
    if (promotedIds.length > 0) {
      setLeaving((prev) => new Set([...prev, ...promotedIds]));
      setSelection((prev) => {
        const next = new Set(prev);
        for (const id of promotedIds) next.delete(id);
        return next;
      });
      toast.success(
        `Filed ${promotedIds.length} ${promotedIds.length === 1 ? 'entry' : 'entries'}`
      );
      // Let the cards animate out, then re-sync with the server.
      setTimeout(() => refreshDrafts(true), 350);
    }
    if (res.errors.length > 0) {
      toast.error(
        `${res.errors.length} ${res.errors.length === 1 ? 'draft' : 'drafts'} could not be filed`
      );
    }
  };

  const fileSingle = async (entity: Entity) => {
    if (promoting) return;
    const cs = cardState[entity.id];
    const { parentOk, categoryOk } = validateStickyIds(
      cs?.parentId ?? null,
      cs?.categoryId ?? null
    );
    const payload: PromotePayload = { entity_ids: [entity.id], clear_draft: true };
    if (parentOk && cs?.parentId != null) payload.parent_id = cs.parentId;
    // Card controls are visible = applied: send category + tags as shown.
    // A stale category is dropped from the request (kept server-side), never
    // silently turned into a clear.
    if (categoryOk) payload.category_id = cs?.categoryId ?? null;
    payload.tags = cs?.tags ?? [];
    setPromoting(true);
    try {
      // Commit a pending rename first — if it failed, keep the card here
      // (saveName already toasted) instead of filing under the old name.
      if (!(await saveName(entity))) return;
      const res = await intakeApi.promote(payload);
      applyPromoteResult(res, [entity.id]);
      if (res.promoted.length > 0 && cs) {
        // File actions are the "last used" that sticks.
        setDefaults((prev) => ({
          ...prev,
          parentId: parentOk ? (cs.parentId ?? prev.parentId) : prev.parentId,
        }));
      }
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to file'));
    } finally {
      setPromoting(false);
    }
  };

  const fileBatch = async () => {
    if (promoting || selection.size === 0) return;
    const ids = [...selection];
    const { parentOk, categoryOk } = validateStickyIds(
      defaults.parentId,
      defaults.categoryId
    );
    const payload: PromotePayload = { entity_ids: ids, clear_draft: true };
    if (parentOk && defaults.parentId != null) payload.parent_id = defaults.parentId;
    if (categoryOk && defaults.categoryId != null) payload.category_id = defaults.categoryId;
    if (defaults.tags.length > 0) payload.tags = defaults.tags;
    setPromoting(true);
    try {
      const res = await intakeApi.promote(payload);
      applyPromoteResult(res, ids);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to file the selection'));
    } finally {
      setPromoting(false);
    }
  };

  // ── Presets ──────────────────────────────────────────────────────────────
  const applyPreset = (raw: string) => {
    setPresetId(raw);
    if (raw === '') return;
    const preset = presets.find((p) => p.id === Number(raw));
    if (!preset) return;
    setDefaults((prev) => ({
      ...prev,
      categoryId:
        typeof preset.payload.category_id === 'number' ? preset.payload.category_id : null,
      tags: Array.isArray(preset.payload.tags)
        ? preset.payload.tags.filter((t): t is string => typeof t === 'string')
        : [],
    }));
  };

  const saveAsPreset = async () => {
    const name = window.prompt('Preset name');
    if (!name || name.trim() === '') return;
    try {
      const created = await presetsApi.create({
        name: name.trim(),
        payload: { category_id: defaults.categoryId, tags: defaults.tags },
      });
      setPresets((prev) => [...prev, created]);
      setPresetId(String(created.id));
      toast.success(`Preset “${created.name}” saved`);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to save preset'));
    }
  };

  // ── Lightbox (fetch full-size attachment lazily on photo click) ──────────
  const openLightbox = async (entity: Entity) => {
    try {
      const photos = (await attachmentsApi.list(entity.id)).filter(
        (a) => a.type === 'photo'
      );
      if (photos.length === 0) {
        toast.info('This draft has no photos');
        return;
      }
      const coverIdx = photos.findIndex((p) => p.id === entity.cover_attachment_id);
      setLightbox({ photos, index: coverIdx >= 0 ? coverIdx : 0 });
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to open photo'));
    }
  };

  // ── Selection helpers ────────────────────────────────────────────────────
  const allSelected = visibleDrafts.length > 0 && selection.size === visibleDrafts.length;
  const toggleAll = () =>
    setSelection(allSelected ? new Set() : new Set(visibleDrafts.map((d) => d.id)));
  const toggleOne = (id: number) =>
    setSelection((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const parentEntityOf = (id: number | null) =>
    id !== null ? tree.byId.get(id) : undefined;

  const selectSm =
    'bg-space-950 border border-space-700 rounded-lg px-2 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500';

  // ── Header (shared) ──────────────────────────────────────────────────────
  const header = (
    <div className="flex items-center gap-2.5 mb-4">
      <Camera className="w-6 h-6 text-blue-400" />
      <h1 className="text-xl font-bold text-white">Intake</h1>
      {mode === 'capture' && queue.length > 0 && (
        <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/20 border border-blue-500/40 text-blue-300">
          {doneCount} captured
        </span>
      )}
      <div className="flex-1" />
      {mode === 'triage' && (
        <button
          onClick={() => refreshDrafts()}
          disabled={refreshing}
          title="Refresh drafts"
          className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-space-800 border border-space-700 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      )}
      {/* Manual mode toggle for edge cases (tablet triage, desktop webcam capture) */}
      <div className="flex rounded-lg border border-space-700 overflow-hidden">
        <button
          onClick={() => setModeOverride('capture')}
          title="Capture mode"
          className={`flex items-center gap-1.5 px-3 py-2 text-sm transition-colors ${
            mode === 'capture'
              ? 'bg-blue-500/20 text-blue-300'
              : 'text-gray-400 hover:text-white hover:bg-space-800'
          }`}
        >
          <Camera className="w-4 h-4" />
          <span className="hidden sm:inline">Capture</span>
        </button>
        <button
          onClick={() => setModeOverride('triage')}
          title="Triage mode"
          className={`flex items-center gap-1.5 px-3 py-2 text-sm transition-colors border-l border-space-700 ${
            mode === 'triage'
              ? 'bg-blue-500/20 text-blue-300'
              : 'text-gray-400 hover:text-white hover:bg-space-800'
          }`}
        >
          <LayoutGrid className="w-4 h-4" />
          <span className="hidden sm:inline">Triage</span>
        </button>
      </div>
    </div>
  );

  // ═══ RENDER: CAPTURE ═══════════════════════════════════════════════════════

  if (mode === 'capture') {
    return (
      <div className="h-full min-h-0 flex flex-col max-w-2xl mx-auto">
        {header}

        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          onChange={onShoot}
        />

        {/* Giant capture button, centered */}
        <div className="flex-1 min-h-0 flex flex-col items-center justify-center gap-5">
          <button
            onClick={() => fileRef.current?.click()}
            aria-label="Take a photo"
            className="w-40 h-40 sm:w-44 sm:h-44 rounded-full bg-blue-600 hover:bg-blue-500 active:scale-90 transition-all duration-150 flex items-center justify-center shadow-2xl shadow-blue-900/50 ring-8 ring-blue-500/10"
          >
            <Camera className="w-16 h-16 text-white" />
          </button>
          <p className="text-gray-500 text-sm text-center px-6">
            Tap to shoot — each photo becomes a draft in the Inbox.
          </p>

          {/* Optional name — OFF by default (speed!) */}
          {nameEnabled ? (
            <div className="w-full max-w-xs flex items-center gap-2">
              <input
                autoFocus
                value={nameInput}
                onChange={(e) => setNameInput(e.target.value)}
                placeholder="Name for the next shot (optional)"
                className="flex-1 bg-space-950 border border-space-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
              />
              <button
                onClick={() => {
                  setNameEnabled(false);
                  setNameInput('');
                }}
                aria-label="Hide name field"
                className="p-2 rounded-lg text-gray-500 hover:text-white hover:bg-space-800 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setNameEnabled(true)}
              className="text-xs text-gray-500 hover:text-white transition-colors"
            >
              + name the next shot
            </button>
          )}

          <button
            onClick={() => setModeOverride('triage')}
            className="text-xs text-blue-400 hover:text-blue-300 hover:underline"
          >
            triage on desktop later — or peek at the drafts now
          </button>
        </div>

        {/* Session filmstrip */}
        {queue.length > 0 && (
          <div className="shrink-0 border-t border-space-700 pt-3 mt-3">
            <div className="flex items-center gap-2 mb-2 text-xs text-gray-500">
              {inFlight ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> Uploading…
                </>
              ) : failedCount > 0 ? (
                <>
                  <AlertCircle className="w-3.5 h-3.5 text-red-400" />
                  <span className="text-red-400">
                    {failedCount} failed — tap to retry
                  </span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />
                  All {doneCount} uploaded
                </>
              )}
            </div>
            <div className="flex gap-2 overflow-x-auto pb-2">
              {[...queue].reverse().map((item) => (
                <div key={item.id} className="relative shrink-0">
                  <img
                    src={item.previewUrl}
                    alt=""
                    className={`w-16 h-16 rounded-lg object-cover border ${
                      item.status === 'error'
                        ? 'border-red-500/70 opacity-60'
                        : 'border-space-700'
                    }`}
                  />
                  {item.status === 'uploading' && (
                    <span className="absolute inset-0 flex items-center justify-center rounded-lg bg-black/50">
                      <Loader2 className="w-5 h-5 text-white animate-spin" />
                    </span>
                  )}
                  {item.status === 'pending' && (
                    <span className="absolute inset-0 flex items-center justify-center rounded-lg bg-black/40">
                      <span className="text-[10px] text-gray-300">queued</span>
                    </span>
                  )}
                  {item.status === 'done' && (
                    <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-green-600 border border-space-950 flex items-center justify-center">
                      <Check className="w-2.5 h-2.5 text-white" />
                    </span>
                  )}
                  {item.status === 'error' && (
                    <button
                      onClick={() => retryItem(item.id)}
                      className="absolute inset-0 flex flex-col items-center justify-center rounded-lg bg-black/60 text-red-300 hover:text-white transition-colors"
                      title={item.error}
                    >
                      <RotateCw className="w-4 h-4" />
                      <span className="text-[9px] mt-0.5">retry</span>
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ═══ RENDER: TRIAGE ════════════════════════════════════════════════════════

  const batchParent = parentEntityOf(defaults.parentId);

  return (
    <div className="max-w-6xl mx-auto">
      {header}

      {/* Batch bar — sticky while scrolling the grid */}
      {visibleDrafts.length > 0 && (
        <div className="sticky top-0 z-20 -mt-1 pt-1 pb-2 bg-space-950/95 backdrop-blur-sm">
          <div className="bg-space-900 border border-space-700 rounded-xl px-3 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer shrink-0">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                className="accent-blue-600"
              />
              {selection.size > 0 ? (
                <span className="text-white font-medium">{selection.size} selected</span>
              ) : (
                'Select all'
              )}
            </label>

            {selection.size > 0 && (
              <>
                {/* Sticky location */}
                <button
                  onClick={() => setPickerFor('batch')}
                  className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-space-950 border border-space-700 hover:border-space-600 text-sm transition-colors max-w-[14rem]"
                >
                  {batchParent ? (
                    <>
                      <EntityIcon entity={batchParent} />
                      <span className="text-white truncate">{batchParent.name}</span>
                    </>
                  ) : (
                    <>
                      <MapPin className="w-4 h-4 text-gray-500 shrink-0" />
                      <span className="text-gray-400">Leave in place</span>
                    </>
                  )}
                </button>

                {/* Sticky category */}
                <select
                  value={defaults.categoryId ?? ''}
                  onChange={(e) =>
                    setDefaults((prev) => ({
                      ...prev,
                      categoryId: e.target.value === '' ? null : Number(e.target.value),
                    }))
                  }
                  className={selectSm}
                >
                  <option value="">Keep category</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.icon ? `${c.icon} ${c.name}` : c.name}
                    </option>
                  ))}
                </select>

                {/* Sticky tags */}
                <div className="min-w-[8rem]">
                  <ChipsInput
                    value={defaults.tags}
                    onChange={(tags) => setDefaults((prev) => ({ ...prev, tags }))}
                    allTags={allTags}
                    placeholder="Tags"
                  />
                </div>

                <div className="flex-1" />

                {/* Presets */}
                <div className="flex items-center gap-1.5">
                  <select
                    value={presetId}
                    onChange={(e) => applyPreset(e.target.value)}
                    className={selectSm}
                  >
                    <option value="">Preset…</option>
                    {presets.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={saveAsPreset}
                    title="Save current category + tags as a preset"
                    className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-space-800 border border-space-700 transition-colors"
                  >
                    <Save className="w-4 h-4" />
                  </button>
                </div>

                <button
                  onClick={fileBatch}
                  disabled={promoting}
                  className="flex items-center gap-1.5 px-3.5 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
                >
                  {promoting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <FolderInput className="w-4 h-4" />
                  )}
                  File {selection.size} selected
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Grid / states */}
      {drafts === null ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm py-16 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading drafts…
        </div>
      ) : visibleDrafts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <Inbox className="w-12 h-12 text-space-500 mb-4" />
          <p className="text-white font-semibold mb-1">Inbox zero — nothing to triage</p>
          <p className="text-gray-500 text-sm max-w-xs">
            Captures from your phone pile up here as drafts. Switch to capture mode to
            shoot the next batch.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3">
          {visibleDrafts.map((entity) => {
            const cs = cardState[entity.id];
            const cardParent = parentEntityOf(cs?.parentId ?? null);
            const error = cardErrors[entity.id];
            const isLeaving = leaving.has(entity.id);
            return (
              <div
                key={entity.id}
                className={`bg-space-900 border rounded-xl overflow-hidden flex flex-col transition-all duration-300 ${
                  error
                    ? 'border-red-500/70 ring-1 ring-red-500/40'
                    : 'border-space-700'
                } ${isLeaving ? 'opacity-0 scale-95' : ''}`}
              >
                {/* Photo */}
                <div className="relative">
                  <button
                    onClick={() => openLightbox(entity)}
                    className="block w-full aspect-[4/3] bg-space-950"
                    title="View photo"
                  >
                    {entity.thumb_url ? (
                      <img
                        src={entity.thumb_url}
                        alt=""
                        loading="lazy"
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <span className="w-full h-full flex items-center justify-center">
                        <Camera className="w-10 h-10 text-space-600" />
                      </span>
                    )}
                  </button>
                  <input
                    type="checkbox"
                    checked={selection.has(entity.id)}
                    onChange={() => toggleOne(entity.id)}
                    onClick={(e) => e.stopPropagation()}
                    className="absolute top-2 left-2 w-4 h-4 accent-blue-600 cursor-pointer"
                    aria-label={`Select ${entity.name}`}
                  />
                  <span className="absolute top-2 right-2 text-[10px] px-1.5 py-0.5 rounded-full bg-violet-900/70 border border-violet-700/60 text-violet-300">
                    draft
                  </span>
                </div>

                {/* Body */}
                <div className="p-3 flex flex-col gap-2 flex-1">
                  {/* Name — Enter saves and hops to the next card */}
                  <div className="relative">
                    <input
                      ref={(el) => {
                        if (el) nameRefs.current.set(entity.id, el);
                        else nameRefs.current.delete(entity.id);
                      }}
                      value={nameDrafts[entity.id] ?? entity.name}
                      onChange={(e) =>
                        setNameDrafts((prev) => ({ ...prev, [entity.id]: e.target.value }))
                      }
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          onNameEnter(entity);
                        }
                      }}
                      onBlur={() => saveName(entity)}
                      className="w-full bg-space-950 border border-space-700 rounded-lg px-2.5 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500"
                    />
                    {savingName === entity.id && (
                      <Loader2 className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 animate-spin text-gray-500" />
                    )}
                  </div>

                  {/* Location */}
                  <button
                    onClick={() => setPickerFor(entity.id)}
                    className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-space-950 border border-space-700 hover:border-space-600 text-sm text-left transition-colors"
                  >
                    {cardParent ? (
                      <>
                        <EntityIcon entity={cardParent} />
                        <span className="text-white truncate">{cardParent.name}</span>
                      </>
                    ) : (
                      <>
                        <MapPin className="w-4 h-4 text-gray-500 shrink-0" />
                        <span className="text-gray-400 truncate">
                          {entity.breadcrumb || 'Leave in place'}
                        </span>
                      </>
                    )}
                  </button>

                  {/* Category */}
                  <select
                    value={cs?.categoryId ?? ''}
                    onChange={(e) =>
                      patchCard(entity.id, {
                        categoryId: e.target.value === '' ? null : Number(e.target.value),
                      })
                    }
                    className={`${selectSm} w-full`}
                  >
                    <option value="">No category</option>
                    {categories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.icon ? `${c.icon} ${c.name}` : c.name}
                      </option>
                    ))}
                  </select>

                  {/* Tags */}
                  <ChipsInput
                    value={cs?.tags ?? []}
                    onChange={(tags) => patchCard(entity.id, { tags })}
                    allTags={allTags}
                  />

                  {error && (
                    <p className="text-xs text-red-400 flex items-start gap-1.5">
                      <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-px" />
                      {error}
                    </p>
                  )}

                  <div className="flex-1" />
                  <button
                    onClick={() => fileSingle(entity)}
                    disabled={promoting}
                    className="w-full flex items-center justify-center gap-1.5 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors"
                  >
                    <FolderInput className="w-4 h-4" /> File
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Location picker — shared by the batch bar and every card */}
      <LocationPickerModal
        open={pickerFor !== null}
        roots={tree.roots}
        childrenOf={tree.childrenOf}
        selectedId={
          pickerFor === 'batch'
            ? defaults.parentId
            : pickerFor !== null
              ? (cardState[pickerFor]?.parentId ?? null)
              : null
        }
        onPick={(id) => {
          if (pickerFor === 'batch') {
            setDefaults((prev) => ({ ...prev, parentId: id }));
          } else if (pickerFor !== null) {
            patchCard(pickerFor, { parentId: id });
            // Per-card picks are "last used" too — keep the loop fast.
            setDefaults((prev) => ({ ...prev, parentId: id ?? prev.parentId }));
          }
        }}
        onClose={() => setPickerFor(null)}
        title="File into…"
        hint="Pick the space, furniture or container these drafts live in."
        nullLabel="Leave where it is (don't move)"
      />

      {lightbox && (
        <Lightbox
          photos={lightbox.photos}
          index={lightbox.index}
          onClose={() => setLightbox(null)}
          onNavigate={(i) => setLightbox((prev) => (prev ? { ...prev, index: i } : prev))}
        />
      )}
    </div>
  );
}
