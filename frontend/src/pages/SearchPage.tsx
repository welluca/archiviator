import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import {
  Loader2,
  MapPin,
  Search,
  SearchX,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { searchApi } from '../api/search';
import { tagsApi, categoriesApi } from '../api/metadata';
import { apiErrorDetail } from '../api/entities';
import { useEntityTree } from '../hooks/useEntityTree';
import EntityRow from '../components/browse/EntityRow';
import EntityIcon from '../components/browse/EntityIcon';
import TagChip from '../components/ui/TagChip';
import LocationPickerModal from '../components/search/LocationPickerModal';
import type { Category, Entity, EntityKind, Tag } from '../types';
import { KIND_META } from '../types';

const ALL_KINDS: EntityKind[] = ['space', 'furniture', 'container', 'item'];
const LIMIT = 50;

const parseIdParam = (v: string | null): number | null => {
  if (!v) return null;
  const n = Number(v);
  return Number.isInteger(n) && n > 0 ? n : null;
};

const sectionLabel = 'text-[10px] uppercase tracking-wide text-gray-500 mb-1.5';

/** Full search page — every filter lives in the URL so searches are shareable. */
export default function SearchPage() {
  const navigate = useNavigate();
  const tree = useEntityTree();
  const [searchParams, setSearchParams] = useSearchParams();

  // ── Filters derived from the URL (single source of truth) ────────────────
  const urlQ = searchParams.get('q') ?? '';
  const kinds = useMemo(
    () =>
      (searchParams.get('kind') ?? '')
        .split(',')
        .filter((k): k is EntityKind => (ALL_KINDS as string[]).includes(k)),
    [searchParams]
  );
  const selTags = useMemo(
    () => (searchParams.get('tags') ?? '').split(',').filter(Boolean),
    [searchParams]
  );
  const categoryId = parseIdParam(searchParams.get('category'));
  const under = parseIdParam(searchParams.get('under'));
  const hasPhotoRaw = searchParams.get('has_photo'); // 'true' | 'false' | null
  const includeArchived = searchParams.get('archived') === '1';

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (value === null || value === '') next.delete(key);
    else next.set(key, value);
    setSearchParams(next, { replace: true });
  };

  // ── Query input (local, debounced into the URL) ──────────────────────────
  const [qInput, setQInput] = useState(urlQ);
  useEffect(() => {
    // Follow external changes (back/forward, omnibox links) — but ignore our
    // own debounced commit of a trimmed value, which would otherwise rewrite
    // the input mid-typing ("new " -> "new").
    if (urlQ.trim() !== qInput.trim()) setQInput(urlQ);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQ]);
  useEffect(() => {
    const t = setTimeout(() => {
      const q = qInput.trim();
      if (q === urlQ) return;
      // Functional form: filters toggled during the debounce window live in
      // the latest params — committing a render-time snapshot would revert them.
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (q) next.set('q', q);
          else next.delete('q');
          return next;
        },
        { replace: true }
      );
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qInput]);

  // ── Results ──────────────────────────────────────────────────────────────
  const [results, setResults] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const paramsKey = searchParams.toString();
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    searchApi
      .search(
        {
          q: urlQ || undefined,
          kinds,
          tags: selTags,
          categoryId,
          under,
          hasPhoto: hasPhotoRaw === null ? undefined : hasPhotoRaw === 'true',
          includeArchived,
          limit: LIMIT,
        },
        controller.signal
      )
      .then((found) => {
        setResults(found);
        setError(null);
        setLoading(false);
      })
      .catch((err) => {
        if (axios.isCancel(err)) return;
        setError(apiErrorDetail(err, 'Search failed'));
        setLoading(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey]);

  // ── Filter rail data ─────────────────────────────────────────────────────
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  useEffect(() => {
    tagsApi.list().then(setAllTags).catch(() => {});
    categoriesApi.list().then(setCategories).catch(() => {});
  }, []);

  const [filtersOpen, setFiltersOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  const underEntity = under !== null ? tree.byId.get(under) : undefined;

  const toggleKind = (k: EntityKind) => {
    const next = kinds.includes(k) ? kinds.filter((x) => x !== k) : [...kinds, k];
    setParam('kind', next.length > 0 ? next.join(',') : null);
  };

  const toggleTag = (name: string) => {
    const next = selTags.includes(name)
      ? selTags.filter((t) => t !== name)
      : [...selTags, name];
    setParam('tags', next.length > 0 ? next.join(',') : null);
  };

  const activeFilterCount =
    kinds.length +
    selTags.length +
    (categoryId !== null ? 1 : 0) +
    (under !== null ? 1 : 0) +
    (hasPhotoRaw !== null ? 1 : 0) +
    (includeArchived ? 1 : 0);

  const clearAll = () => {
    const next = new URLSearchParams();
    if (urlQ) next.set('q', urlQ);
    setSearchParams(next, { replace: true });
  };

  // ── Row wiring (reuses EntityRow; kebab only offers Details) ─────────────
  const rowActions = {
    onDetails: (e: Entity) => navigate(`/entity/${e.id}`),
  };
  const handleOpenRow = (e: Entity) => {
    if (e.kind === 'item') navigate(`/entity/${e.id}`);
    else navigate(`/browse?sel=${e.id}`);
  };

  const photoBtn = (value: 'any' | 'true' | 'false', label: string) => {
    const current = hasPhotoRaw === null ? 'any' : hasPhotoRaw;
    return (
      <button
        key={value}
        onClick={() => setParam('has_photo', value === 'any' ? null : value)}
        className={`flex-1 px-2 py-1.5 text-xs transition-colors ${
          current === value
            ? 'bg-blue-500/20 text-blue-300'
            : 'text-gray-400 hover:text-white hover:bg-space-800'
        }`}
      >
        {label}
      </button>
    );
  };

  return (
    <div className="flex flex-col lg:flex-row lg:gap-6 h-full min-h-0">
      {/* ── Filter rail ─────────────────────────────────────────────────── */}
      <aside
        className={`${filtersOpen ? 'block' : 'hidden'} lg:block lg:w-64 xl:w-72 shrink-0 mb-4 lg:mb-0 lg:overflow-y-auto`}
      >
        <div className="bg-space-900 border border-space-700 rounded-xl p-4 space-y-5">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-white">Filters</span>
            {activeFilterCount > 0 && (
              <button
                onClick={clearAll}
                className="text-xs text-gray-400 hover:text-white transition-colors"
              >
                Clear all ({activeFilterCount})
              </button>
            )}
          </div>

          {/* Kind */}
          <div>
            <p className={sectionLabel}>Kind</p>
            <div className="space-y-1">
              {ALL_KINDS.map((k) => (
                <label
                  key={k}
                  className="flex items-center gap-2.5 px-1 py-1 rounded-md text-sm text-gray-300 hover:text-white cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={kinds.includes(k)}
                    onChange={() => toggleKind(k)}
                    className="accent-blue-600"
                  />
                  {KIND_META[k].label}
                </label>
              ))}
            </div>
          </div>

          {/* Tags */}
          <div>
            <p className={sectionLabel}>Tags</p>
            {allTags.length === 0 ? (
              <p className="text-xs text-gray-600">No tags yet.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {allTags.map((t) => (
                  <TagChip
                    key={t.id}
                    tag={t}
                    selected={selTags.includes(t.name)}
                    onClick={() => toggleTag(t.name)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Category */}
          <div>
            <p className={sectionLabel}>Category</p>
            <select
              value={categoryId ?? ''}
              onChange={(e) => setParam('category', e.target.value || null)}
              className="w-full bg-space-950 border border-space-700 rounded-lg px-2 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option value="">Any category</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          {/* Photos (tri-state) */}
          <div>
            <p className={sectionLabel}>Photos</p>
            <div className="flex rounded-lg border border-space-700 bg-space-950 overflow-hidden divide-x divide-space-700">
              {photoBtn('any', 'Any')}
              {photoBtn('true', 'With')}
              {photoBtn('false', 'Without')}
            </div>
          </div>

          {/* Inside */}
          <div>
            <p className={sectionLabel}>Inside</p>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setPickerOpen(true)}
                className="flex-1 min-w-0 flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-space-950 border border-space-700 hover:border-space-600 text-sm text-left transition-colors"
              >
                {underEntity ? (
                  <>
                    <EntityIcon entity={underEntity} />
                    <span className="text-white truncate">{underEntity.name}</span>
                  </>
                ) : (
                  <>
                    <MapPin className="w-4 h-4 text-gray-500 shrink-0" />
                    <span className="text-gray-400 truncate">Anywhere</span>
                  </>
                )}
              </button>
              {under !== null && (
                <button
                  onClick={() => setParam('under', null)}
                  title="Clear location"
                  className="p-1.5 rounded-md text-gray-500 hover:text-white hover:bg-space-800 transition-colors shrink-0"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>

          {/* Archived */}
          <label className="flex items-center gap-2.5 text-sm text-gray-300 hover:text-white cursor-pointer">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => setParam('archived', e.target.checked ? '1' : null)}
              className="accent-blue-600"
            />
            Include archived
          </label>
        </div>
      </aside>

      {/* ── Results column ──────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <div className="flex items-center gap-2 mb-3">
          <div className="relative flex-1 min-w-0">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input
              autoFocus
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              placeholder="Search names, descriptions, tags, fields, asset tags…"
              className="w-full bg-space-900 border border-space-700 rounded-lg pl-9 pr-9 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
            />
            {qInput !== '' && (
              <button
                onClick={() => setQInput('')}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md text-gray-500 hover:text-white hover:bg-space-700 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
          <button
            onClick={() => setFiltersOpen((v) => !v)}
            className={`lg:hidden flex items-center gap-1.5 px-3 py-2.5 rounded-lg border text-sm transition-colors shrink-0 ${
              filtersOpen || activeFilterCount > 0
                ? 'border-blue-500/50 bg-blue-500/10 text-blue-300'
                : 'border-space-700 text-gray-400 hover:text-white hover:bg-space-800'
            }`}
          >
            <SlidersHorizontal className="w-4 h-4" />
            {activeFilterCount > 0 && <span>{activeFilterCount}</span>}
          </button>
        </div>

        {!loading && !error && (
          <p className="text-xs text-gray-500 mb-2">
            {results.length} result{results.length === 1 ? '' : 's'}
            {results.length === LIMIT && ` (showing first ${LIMIT})`}
          </p>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto">
          {loading ? (
            <div className="flex items-center gap-2 text-gray-500 text-sm py-12 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" /> Searching…
            </div>
          ) : error ? (
            <p className="text-sm text-red-400 py-8 text-center">{error}</p>
          ) : results.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <SearchX className="w-10 h-10 text-space-500 mb-3" />
              <p className="text-gray-500 text-sm">
                {urlQ || activeFilterCount > 0
                  ? 'Nothing matches this search.'
                  : 'Type a query or pick filters to search your inventory.'}
              </p>
            </div>
          ) : (
            <div className="space-y-1">
              {results.map((e) => (
                <EntityRow
                  key={e.id}
                  entity={e}
                  onOpen={handleOpenRow}
                  actions={rowActions}
                  showBreadcrumb
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <LocationPickerModal
        open={pickerOpen}
        roots={tree.roots}
        childrenOf={tree.childrenOf}
        selectedId={under}
        onPick={(id) => setParam('under', id === null ? null : String(id))}
        onClose={() => setPickerOpen(false)}
      />
    </div>
  );
}
