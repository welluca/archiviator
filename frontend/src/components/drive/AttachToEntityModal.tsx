import { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { FolderTree, Link2, Loader2, Search, SearchX } from 'lucide-react';
import Modal from '../browse/Modal';
import EntityIcon from '../browse/EntityIcon';
import { searchApi } from '../../api/search';
import { useEntityTree } from '../../hooks/useEntityTree';
import type { Entity } from '../../types';

interface AttachToEntityModalProps {
  open: boolean;
  /** Drive file name shown in the header + used as the default title. */
  fileName: string;
  onClose: () => void;
  /** Perform the attach; keep the modal open on a thrown error. */
  onAttach: (entity: Entity, title: string | undefined) => Promise<void>;
}

/** Entity picker for filing a Drive scan: omnibox-style search first, full
 * tree as the fallback, plus an optional attachment title. */
export default function AttachToEntityModal({
  open,
  fileName,
  onClose,
  onAttach,
}: AttachToEntityModalProps) {
  const tree = useEntityTree();

  const [q, setQ] = useState('');
  const [results, setResults] = useState<Entity[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [showTree, setShowTree] = useState(false);
  const [selected, setSelected] = useState<Entity | null>(null);
  const [title, setTitle] = useState('');
  const [attaching, setAttaching] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const requestSeq = useRef(0);

  // Fresh state on every open.
  useEffect(() => {
    if (open) {
      setQ('');
      setResults([]);
      setSearched(false);
      setSearching(false);
      setShowTree(false);
      setSelected(null);
      setTitle('');
      setAttaching(false);
    } else {
      abortRef.current?.abort();
    }
  }, [open]);

  // Debounced search with a stale-response guard (same recipe as the Omnibox).
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
        const found = await searchApi.search({ q: term, limit: 20 }, controller.signal);
        if (seq !== requestSeq.current) return;
        setResults(found);
        setSearched(true);
        setSearching(false);
      } catch (err) {
        if (axios.isCancel(err) || seq !== requestSeq.current) return;
        setResults([]);
        setSearched(true);
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [q, open]);

  const term = q.trim();
  const listMode: 'tree' | 'search' = showTree || term === '' ? 'tree' : 'search';

  const treeNodes = useMemo(() => tree.roots, [tree.roots]);

  if (!open) return null;

  const handleAttach = async () => {
    if (!selected || attaching) return;
    setAttaching(true);
    try {
      const t = title.trim();
      await onAttach(selected, t === '' ? undefined : t);
    } catch {
      /* the caller toasts — keep the modal open for a retry */
    } finally {
      setAttaching(false);
    }
  };

  const rowClass = (active: boolean) =>
    `w-full flex items-center gap-2 pr-2 py-1.5 rounded-md text-sm text-left transition-colors ${
      active ? 'bg-blue-500/20 text-blue-300' : 'text-gray-300 hover:bg-space-800 hover:text-white'
    }`;

  const renderNode = (node: Entity): React.ReactNode => {
    const children = tree.childrenOf.get(node.id) ?? [];
    return (
      <div key={node.id}>
        <button
          type="button"
          onClick={() => setSelected(node)}
          style={{ paddingLeft: `${node.depth * 14 + 8}px` }}
          className={rowClass(selected?.id === node.id)}
        >
          <EntityIcon entity={node} />
          <span className="truncate">{node.name}</span>
        </button>
        {children.map(renderNode)}
      </div>
    );
  };

  return (
    <Modal open={open} title="Attach scan to…" onClose={onClose} maxWidth="max-w-lg">
      <p className="text-xs text-gray-500 mb-3 truncate">
        Linking <span className="text-gray-300 font-mono">{fileName}</span> — the file stays
        in Drive, only a link is stored.
      </p>

      {/* Search box + tree toggle */}
      <div className="flex items-center gap-2 mb-2">
        <div className="flex-1 flex items-center gap-2 bg-space-950 border border-space-700 rounded-lg px-3 py-2 focus-within:border-blue-500 transition-colors">
          <Search className="w-4 h-4 text-gray-500 shrink-0" />
          <input
            autoFocus
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setShowTree(false);
            }}
            placeholder="Search names, tags, asset tags…"
            className="flex-1 min-w-0 bg-transparent text-sm text-white placeholder-gray-600 focus:outline-none"
          />
          {searching && <Loader2 className="w-4 h-4 animate-spin text-gray-500 shrink-0" />}
        </div>
        <button
          type="button"
          onClick={() => setShowTree((v) => !v)}
          title="Browse the full tree instead"
          className={`p-2 rounded-lg border transition-colors ${
            listMode === 'tree'
              ? 'bg-blue-500/20 border-blue-500/40 text-blue-300'
              : 'border-space-700 text-gray-400 hover:text-white hover:bg-space-800'
          }`}
        >
          <FolderTree className="w-4 h-4" />
        </button>
      </div>

      {/* Results / tree */}
      <div className="border border-space-700 rounded-lg bg-space-950 h-60 overflow-y-auto p-1.5 mb-3">
        {listMode === 'search' ? (
          searched && !searching && results.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-8 text-center">
              <SearchX className="w-7 h-7 text-space-500" />
              <p className="text-sm text-gray-500">No matches for “{term}”</p>
            </div>
          ) : (
            results.map((e) => (
              <button
                key={e.id}
                type="button"
                onClick={() => setSelected(e)}
                className={`${rowClass(selected?.id === e.id)} pl-2`}
              >
                <EntityIcon entity={e} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{e.name}</span>
                  {e.breadcrumb && (
                    <span className="block text-xs text-gray-500 truncate">
                      {e.breadcrumb}
                    </span>
                  )}
                </span>
              </button>
            ))
          )
        ) : tree.loading ? (
          <div className="flex items-center gap-2 text-gray-500 text-sm py-8 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading tree…
          </div>
        ) : (
          treeNodes.map(renderNode)
        )}
      </div>

      {/* Title + submit */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={`Title (optional, default: ${fileName})`}
          className="flex-1 min-w-[12rem] bg-space-950 border border-space-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
        />
        <button
          type="button"
          onClick={handleAttach}
          disabled={!selected || attaching}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
        >
          {attaching ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Link2 className="w-4 h-4" />
          )}
          {selected ? `Attach to “${selected.name}”` : 'Pick an entry'}
        </button>
      </div>
    </Modal>
  );
}
