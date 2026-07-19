import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Clock, CornerDownLeft, Loader2, Search, SearchX } from 'lucide-react';
import { searchApi } from '../../api/search';
import EntityIcon from '../browse/EntityIcon';
import TagChip from '../ui/TagChip';
import type { Entity, EntityKind } from '../../types';
import { KIND_ORDER } from '../../types';

const RECENT_KEY = 'archiviator_recent_searches';
const MAX_RECENT = 5;

const KIND_PLURAL: Record<EntityKind, string> = {
  space: 'Spaces',
  furniture: 'Furniture',
  container: 'Containers',
  item: 'Items',
};

const loadRecent = (): string[] => {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]');
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === 'string').slice(0, MAX_RECENT)
      : [];
  } catch {
    return [];
  }
};

const pushRecent = (q: string): string[] => {
  const next = [
    q,
    ...loadRecent().filter((r) => r.toLowerCase() !== q.toLowerCase()),
  ].slice(0, MAX_RECENT);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage full/blocked — recents are best-effort */
  }
  return next;
};

interface OmniboxProps {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}

/** Global search overlay. Stays mounted in the layout so the Ctrl/Cmd+K
 * shortcut works from anywhere; renders nothing while closed. */
export function Omnibox({ open, onOpen, onClose }: OmniboxProps) {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Entity[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [active, setActive] = useState(0);
  const [recent, setRecent] = useState<string[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const requestSeq = useRef(0);

  // Global shortcut: Ctrl/Cmd+K toggles, Escape closes while open.
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k') {
        ev.preventDefault();
        if (open) onClose();
        else onOpen();
      } else if (open && ev.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onOpen, onClose]);

  // Fresh state on every open.
  useEffect(() => {
    if (open) {
      setQ('');
      setResults([]);
      setSearched(false);
      setSearching(false);
      setActive(0);
      setRecent(loadRecent());
    } else {
      abortRef.current?.abort();
    }
  }, [open]);

  // Debounced search with a stale-response guard (seq + AbortController).
  useEffect(() => {
    if (!open) return;
    const term = q.trim();
    if (term === '') {
      abortRef.current?.abort();
      requestSeq.current++;
      setResults([]);
      setSearching(false);
      setSearched(false);
      return;
    }
    setSearching(true);
    const timer = setTimeout(async () => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const seq = ++requestSeq.current;
      try {
        const found = await searchApi.search({ q: term, limit: 30 }, controller.signal);
        if (seq !== requestSeq.current) return; // a newer request superseded us
        setResults(found);
        setActive(0);
        setSearched(true);
        setSearching(false);
      } catch (err) {
        if (axios.isCancel(err) || seq !== requestSeq.current) return;
        setResults([]);
        setSearched(true);
        setSearching(false);
      }
    }, 200);
    return () => clearTimeout(timer);
  }, [q, open]);

  // Group by kind (kind order), keeping bm25 order within each group.
  const groups = useMemo(() => {
    const byKind = new Map<EntityKind, Entity[]>();
    for (const e of results) {
      const list = byKind.get(e.kind);
      if (list) list.push(e);
      else byKind.set(e.kind, [e]);
    }
    return [...byKind.entries()].sort((a, b) => KIND_ORDER[a[0]] - KIND_ORDER[b[0]]);
  }, [results]);

  /** Flattened in rendered order — the keyboard navigation space. */
  const flat = useMemo(() => groups.flatMap(([, list]) => list), [groups]);

  useEffect(() => {
    document.getElementById(`omni-item-${active}`)?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const openEntity = useCallback(
    (e: Entity) => {
      const term = q.trim();
      if (term) setRecent(pushRecent(term));
      onClose();
      if (e.kind === 'item') navigate(`/entity/${e.id}`);
      else navigate(`/browse?sel=${e.id}`);
    },
    [q, navigate, onClose]
  );

  const onInputKeyDown = (ev: React.KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      setActive((i) => Math.min(i + 1, Math.max(flat.length - 1, 0)));
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      const target = flat[active];
      if (target) openEntity(target);
    }
  };

  if (!open) return null;

  const term = q.trim();
  let cursor = 0;
  const sections = groups.map(([kind, list]) => {
    const start = cursor;
    cursor += list.length;
    return { kind, list, start };
  });

  return (
    <div
      className="fixed inset-0 z-[80] bg-black/60 backdrop-blur-sm flex items-start justify-center px-4 pt-[12vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-xl bg-space-900 border border-space-700 rounded-xl shadow-2xl shadow-black/50 flex flex-col max-h-[70vh] overflow-hidden">
        {/* Input row */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-space-700 shrink-0">
          <Search className="w-5 h-5 text-gray-500 shrink-0" />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Search names, tags, fields, asset tags…"
            className="flex-1 min-w-0 bg-transparent text-sm text-white placeholder-gray-600 focus:outline-none"
          />
          {searching && <Loader2 className="w-4 h-4 animate-spin text-gray-500 shrink-0" />}
          <kbd className="text-[10px] px-1.5 py-0.5 rounded border border-space-700 bg-space-800 text-gray-500 shrink-0">
            esc
          </kbd>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto py-1.5">
          {term === '' ? (
            <div className="px-2">
              {recent.length === 0 ? (
                <p className="text-sm text-gray-500 px-2 py-8 text-center">
                  Search everything — names, descriptions, locations, tags, custom
                  fields and asset tags.
                </p>
              ) : (
                <>
                  <p className="text-[10px] uppercase tracking-wide text-gray-500 px-2 pt-1.5 pb-1">
                    Recent searches
                  </p>
                  {recent.map((r) => (
                    <button
                      key={r}
                      onClick={() => setQ(r)}
                      className="w-full flex items-center gap-2.5 px-2 py-2 rounded-md text-sm text-gray-300 hover:bg-space-800 hover:text-white text-left transition-colors"
                    >
                      <Clock className="w-3.5 h-3.5 text-gray-500 shrink-0" />
                      <span className="truncate">{r}</span>
                    </button>
                  ))}
                </>
              )}
            </div>
          ) : searched && !searching && flat.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <SearchX className="w-8 h-8 text-space-500" />
              <p className="text-sm text-gray-500">No matches for “{term}”</p>
            </div>
          ) : (
            sections.map(({ kind, list, start }) => (
              <div key={kind}>
                <p className="text-[10px] uppercase tracking-wide text-gray-500 px-4 pt-2 pb-1">
                  {KIND_PLURAL[kind]}
                </p>
                {list.map((e, i) => {
                  const flatIndex = start + i;
                  const isActive = flatIndex === active;
                  return (
                    <button
                      key={e.id}
                      id={`omni-item-${flatIndex}`}
                      onClick={() => openEntity(e)}
                      onMouseEnter={() => setActive(flatIndex)}
                      className={`w-full flex items-center gap-3 px-4 py-2 text-left transition-colors ${
                        isActive ? 'bg-space-800' : ''
                      }`}
                    >
                      <EntityIcon entity={e} className="w-4 h-4" />
                      <span className="flex-1 min-w-0">
                        <span className="flex items-center gap-2 min-w-0">
                          <span className="text-sm text-white truncate">{e.name}</span>
                          {(e.tags ?? []).slice(0, 3).map((t) => (
                            <TagChip key={t.id} tag={t} />
                          ))}
                        </span>
                        {e.breadcrumb && (
                          <span className="block text-xs text-gray-500 truncate">
                            {e.breadcrumb}
                          </span>
                        )}
                      </span>
                      {isActive && (
                        <CornerDownLeft className="w-3.5 h-3.5 text-gray-500 shrink-0" />
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Key hints */}
        <div className="px-4 py-2 border-t border-space-700 flex items-center gap-4 text-[10px] text-gray-600 shrink-0">
          <span>↑↓ navigate</span>
          <span>↵ open</span>
          <span>esc close</span>
        </div>
      </div>
    </div>
  );
}

export default Omnibox;
