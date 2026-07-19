import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AxiosError } from 'axios';
import axios from 'axios';
import {
  Archive,
  FolderTree,
  Link2,
  Loader2,
  MapPin,
  Plus,
  QrCode,
  ScanLine,
  Search,
  X,
} from 'lucide-react';
import { labelsApi, normalizeTag } from '../api/labels';
import { searchApi } from '../api/search';
import { apiErrorDetail } from '../api/entities';
import { useEntityTree } from '../hooks/useEntityTree';
import { useToast } from '../components/ui/Toast';
import Modal from '../components/browse/Modal';
import EntityIcon from '../components/browse/EntityIcon';
import ParentPickerModal from '../components/labels/ParentPickerModal';
import type { Entity, EntityKind } from '../types';
import { KIND_META, isInboxRoot } from '../types';

type PageState =
  | { phase: 'loading' }
  | { phase: 'unknown' }
  | { phase: 'error' }
  | { phase: 'claim' };

type ClaimMode = 'attach' | 'create' | null;

const inputClass =
  'w-full bg-space-950 border border-space-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500';

/** Tag chip shared by the claim screens. */
const TagChipMono = ({ tag }: { tag: string }) => (
  <span className="font-mono text-sm px-2.5 py-1 rounded-md bg-space-800 border border-space-600 text-blue-300 tracking-wider">
    {tag}
  </span>
);

/** Tree picker for "attach to existing" — any non-Inbox entity without a tag. */
function AttachTreePickerModal({
  open,
  roots,
  childrenOf,
  onPick,
  onClose,
}: {
  open: boolean;
  roots: Entity[];
  childrenOf: Map<number, Entity[]>;
  onPick: (e: Entity) => void;
  onClose: () => void;
}) {
  if (!open) return null;

  const renderNode = (node: Entity): React.ReactNode => {
    const children = childrenOf.get(node.id) ?? [];
    const valid = !isInboxRoot(node) && !node.asset_tag;
    return (
      <div key={node.id}>
        <button
          type="button"
          disabled={!valid}
          onClick={() => {
            onPick(node);
            onClose();
          }}
          style={{ paddingLeft: `${node.depth * 14 + 8}px` }}
          className={`w-full flex items-center gap-2 pr-2 py-1.5 rounded-md text-sm text-left transition-colors ${
            valid
              ? 'text-gray-300 hover:bg-space-800 hover:text-white'
              : 'text-gray-600 cursor-not-allowed'
          }`}
        >
          <EntityIcon entity={node} />
          <span className="truncate">{node.name}</span>
          {node.asset_tag && (
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-space-800 border border-space-700 text-gray-500 shrink-0">
              {node.asset_tag}
            </span>
          )}
        </button>
        {children.map(renderNode)}
      </div>
    );
  };

  return (
    <Modal open={open} title="Pick from the tree" onClose={onClose} maxWidth="max-w-lg">
      <p className="text-xs text-gray-500 mb-3">
        Entries that already carry a tag (and the Inbox) are disabled.
      </p>
      <div className="border border-space-700 rounded-lg bg-space-950 max-h-72 overflow-y-auto p-1.5">
        {roots.map(renderNode)}
      </div>
    </Modal>
  );
}

/** Landing page for scanned QR labels (/a/:tag) — mobile-first: this is
 * almost always opened from the iPhone camera. */
export default function ScanLandingPage() {
  const { tag: rawTag } = useParams();
  const tag = normalizeTag(rawTag ?? '');
  const navigate = useNavigate();
  const toast = useToast();
  const tree = useEntityTree();

  const [state, setState] = useState<PageState>({ phase: 'loading' });
  const [mode, setMode] = useState<ClaimMode>(null);
  const [claiming, setClaiming] = useState(false);

  // ── Resolve on mount (retryable) ──────────────────────────────────────────
  const [resolveAttempt, setResolveAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setState({ phase: 'loading' });
    labelsApi
      .resolve(tag)
      .then((res) => {
        if (cancelled) return;
        if (res.status === 'entity') {
          navigate(`/entity/${res.entity.id}`, { replace: true });
        } else {
          setState({ phase: 'claim' });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof AxiosError && err.response?.status === 404) {
          setState({ phase: 'unknown' });
        } else {
          // Transient failure (Wi-Fi blip, server restart) is NOT "unknown
          // label" — offer a retry instead of a misleading dead end.
          toast.error(apiErrorDetail(err, 'Failed to look up this label'));
          setState({ phase: 'error' });
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tag, resolveAttempt]);

  // ── Attach-to-existing state ──────────────────────────────────────────────
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Entity[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Entity | null>(null);
  const [treePickerOpen, setTreePickerOpen] = useState(false);

  useEffect(() => {
    if (mode !== 'attach' || q.trim() === '') {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const t = setTimeout(() => {
      setSearching(true);
      searchApi
        .search({ q, limit: 20 }, controller.signal)
        .then((found) => {
          setResults(found);
          setSearching(false);
        })
        .catch((err) => {
          if (axios.isCancel(err)) return;
          setSearching(false);
        });
    }, 250);
    return () => {
      clearTimeout(t);
      controller.abort();
    };
  }, [q, mode]);

  // ── Create-new state ──────────────────────────────────────────────────────
  const [name, setName] = useState('');
  const [kind, setKind] = useState<EntityKind>('item');
  const [parentId, setParentId] = useState<number | null>(null);
  const [subtype, setSubtype] = useState('');
  const [parentPickerOpen, setParentPickerOpen] = useState(false);

  const parentEntity = useMemo(
    () => (parentId !== null ? tree.byId.get(parentId) : undefined),
    [parentId, tree.byId]
  );

  // Changing kind can invalidate the picked parent (containment rules).
  useEffect(() => {
    if (parentId === null) return;
    const p = tree.byId.get(parentId);
    if (p && !KIND_META[p.kind].allowedChildren.includes(kind)) setParentId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  const canCreate =
    name.trim().length > 0 && (kind === 'space' || parentId !== null) && !claiming;

  // ── Claim actions ─────────────────────────────────────────────────────────
  const handleAttach = async () => {
    if (!selected || claiming) return;
    setClaiming(true);
    try {
      const entity = await labelsApi.claimExisting(tag, selected.id);
      toast.success(`Label ${tag} attached to “${entity.name}”`);
      navigate(`/entity/${entity.id}`, { replace: true });
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to attach the label'));
      setClaiming(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canCreate) return;
    setClaiming(true);
    try {
      const entity = await labelsApi.claimCreate(tag, {
        name: name.trim(),
        kind,
        parent_id: parentId,
        subtype: subtype.trim() || undefined,
      });
      toast.success(`Created “${entity.name}” — add photos now with the camera button`);
      navigate(`/entity/${entity.id}`, { replace: true });
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to create the entry'));
      setClaiming(false);
    }
  };

  // ── Shell ─────────────────────────────────────────────────────────────────
  const shell = (children: React.ReactNode) => (
    <div className="min-h-screen bg-space-950 flex flex-col">
      <header className="flex items-center gap-2.5 px-4 py-3 border-b border-space-700 bg-space-900">
        <Archive className="w-5 h-5 text-blue-400" />
        <Link to="/" className="text-white font-semibold text-sm">
          Archiviator
        </Link>
        <span className="text-gray-600 text-sm">/ scanned label</span>
      </header>
      <main className="flex-1 w-full max-w-lg mx-auto px-4 py-6 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
        {children}
      </main>
    </div>
  );

  if (state.phase === 'loading') {
    return shell(
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <ScanLine className="w-10 h-10 text-blue-400 mb-4 animate-pulse" />
        <p className="text-gray-400 text-sm">Looking up label…</p>
        <p className="font-mono text-blue-300 tracking-wider mt-1">{tag}</p>
      </div>
    );
  }

  if (state.phase === 'error') {
    return shell(
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <QrCode className="w-12 h-12 text-space-500 mb-4" />
        <h1 className="text-lg font-semibold text-white mb-1">Couldn't look up this label</h1>
        <p className="font-mono text-gray-400 tracking-wider mb-3">{tag}</p>
        <p className="text-gray-500 text-sm max-w-xs mb-6">
          The server didn't answer — this is usually a Wi-Fi or connection blip, not a
          problem with the label.
        </p>
        <button
          onClick={() => setResolveAttempt((n) => n + 1)}
          className="px-4 py-2 rounded-lg bg-space-700 hover:bg-space-600 text-white text-sm transition-colors"
        >
          Try again
        </button>
      </div>
    );
  }

  if (state.phase === 'unknown') {
    return shell(
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <QrCode className="w-12 h-12 text-space-500 mb-4" />
        <h1 className="text-lg font-semibold text-white mb-1">Unknown label</h1>
        <p className="font-mono text-gray-400 tracking-wider mb-3">{tag}</p>
        <p className="text-gray-500 text-sm max-w-xs">
          This code doesn't match any printed label or asset tag. It may have been
          voided, or it belongs to a different system.
        </p>
        <Link
          to="/labels"
          className="mt-6 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm transition-colors"
        >
          Go to Labels
        </Link>
      </div>
    );
  }

  // ── Claim UI ──────────────────────────────────────────────────────────────
  const optionCard = (
    active: boolean,
    onClick: () => void,
    icon: React.ReactNode,
    title: string,
    subtitle: string
  ) => (
    <button
      type="button"
      onClick={onClick}
      className={`w-full flex items-center gap-3.5 px-4 py-4 rounded-xl border text-left transition-colors ${
        active
          ? 'bg-blue-500/10 border-blue-500/50'
          : 'bg-space-900 border-space-700 hover:border-space-600'
      }`}
    >
      <span
        className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
          active ? 'bg-blue-600' : 'bg-space-800'
        }`}
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className={`block font-semibold text-sm ${active ? 'text-blue-300' : 'text-white'}`}>
          {title}
        </span>
        <span className="block text-xs text-gray-500 mt-0.5">{subtitle}</span>
      </span>
    </button>
  );

  return shell(
    <>
      <div className="text-center mb-6">
        <p className="text-gray-400 text-sm mb-2">You scanned a fresh label</p>
        <TagChipMono tag={tag} />
        <p className="text-gray-500 text-xs mt-2">
          It isn't attached to anything yet. What is it stuck on?
        </p>
      </div>

      <div className="space-y-3">
        {optionCard(
          mode === 'attach',
          () => setMode(mode === 'attach' ? null : 'attach'),
          <Link2 className="w-5 h-5 text-white" />,
          'Attach to existing entry',
          'The box / item is already in the catalog'
        )}

        {mode === 'attach' && (
          <div className="rounded-xl border border-space-700 bg-space-900 p-4 space-y-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search your inventory…"
                className={`${inputClass} pl-9`}
              />
              {q !== '' && (
                <button
                  onClick={() => setQ('')}
                  aria-label="Clear search"
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md text-gray-500 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>

            <button
              type="button"
              onClick={() => setTreePickerOpen(true)}
              className="flex items-center gap-2 text-xs text-gray-400 hover:text-white transition-colors"
            >
              <FolderTree className="w-3.5 h-3.5" /> or pick from the tree
            </button>

            {searching ? (
              <div className="flex items-center gap-2 text-gray-500 text-sm py-4 justify-center">
                <Loader2 className="w-4 h-4 animate-spin" /> Searching…
              </div>
            ) : results.length > 0 ? (
              <div className="max-h-64 overflow-y-auto space-y-0.5 -mx-1 px-1">
                {results.map((e) => {
                  const taken = Boolean(e.asset_tag) || e.protected;
                  const isSel = selected?.id === e.id;
                  return (
                    <button
                      key={e.id}
                      type="button"
                      disabled={taken}
                      onClick={() => setSelected(isSel ? null : e)}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-colors ${
                        isSel
                          ? 'bg-blue-500/20 border border-blue-500/50'
                          : taken
                            ? 'opacity-40 cursor-not-allowed border border-transparent'
                            : 'hover:bg-space-800 border border-transparent'
                      }`}
                    >
                      <EntityIcon entity={e} className="w-4 h-4" />
                      <span className="flex-1 min-w-0">
                        <span className="block text-sm text-white truncate">{e.name}</span>
                        {e.breadcrumb && (
                          <span className="block text-[11px] text-gray-500 truncate">
                            {e.breadcrumb}
                          </span>
                        )}
                      </span>
                      {e.asset_tag && (
                        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-space-800 border border-space-700 text-gray-500 shrink-0">
                          {e.asset_tag}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ) : q.trim() !== '' ? (
              <p className="text-xs text-gray-600 text-center py-3">No matches.</p>
            ) : null}

            {selected && !results.some((r) => r.id === selected.id) && (
              <div className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg bg-blue-500/20 border border-blue-500/50">
                <EntityIcon entity={selected} className="w-4 h-4" />
                <span className="flex-1 min-w-0">
                  <span className="block text-sm text-white truncate">{selected.name}</span>
                  {selected.breadcrumb && (
                    <span className="block text-[11px] text-gray-500 truncate">
                      {selected.breadcrumb}
                    </span>
                  )}
                </span>
                <button
                  onClick={() => setSelected(null)}
                  className="p-1 rounded-md text-gray-400 hover:text-white shrink-0"
                  aria-label="Clear selection"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            )}

            <button
              onClick={handleAttach}
              disabled={!selected || claiming}
              className="w-full flex items-center justify-center gap-2 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
            >
              {claiming && <Loader2 className="w-4 h-4 animate-spin" />}
              {selected ? `Attach ${tag} to “${selected.name}”` : 'Pick an entry to attach'}
            </button>
          </div>
        )}

        {optionCard(
          mode === 'create',
          () => setMode(mode === 'create' ? null : 'create'),
          <Plus className="w-5 h-5 text-white" />,
          'Create new entry here',
          'Catalog it now and bind the label in one go'
        )}

        {mode === 'create' && (
          <form
            onSubmit={handleCreate}
            className="rounded-xl border border-space-700 bg-space-900 p-4 space-y-3.5"
          >
            <div>
              <label className="block text-xs text-gray-400 mb-1.5">Name *</label>
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="What is it?"
                className={inputClass}
              />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1.5">Kind</label>
              <div className="grid grid-cols-2 gap-2">
                {(['item', 'container', 'furniture', 'space'] as EntityKind[]).map((k) => {
                  const Icon = KIND_META[k].icon;
                  return (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setKind(k)}
                      className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border transition-colors ${
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
              <label className="block text-xs text-gray-400 mb-1.5">
                Location {kind === 'space' ? '' : '*'}
              </label>
              <button
                type="button"
                onClick={() => setParentPickerOpen(true)}
                className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg bg-space-950 border border-space-700 hover:border-space-600 text-sm text-left transition-colors"
              >
                {parentEntity ? (
                  <>
                    <EntityIcon entity={parentEntity} />
                    <span className="text-white truncate">{parentEntity.name}</span>
                  </>
                ) : (
                  <>
                    <MapPin className="w-4 h-4 text-gray-500 shrink-0" />
                    <span className="text-gray-400">
                      {kind === 'space' ? 'Root level (tap to change)' : 'Pick a location…'}
                    </span>
                  </>
                )}
              </button>
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1.5">Subtype</label>
              <input
                value={subtype}
                onChange={(e) => setSubtype(e.target.value)}
                placeholder="Optional (e.g. box, drawer)"
                className={inputClass}
              />
            </div>

            <button
              type="submit"
              disabled={!canCreate}
              className="w-full flex items-center justify-center gap-2 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
            >
              {claiming && <Loader2 className="w-4 h-4 animate-spin" />}
              Create and attach {tag}
            </button>
          </form>
        )}
      </div>

      <AttachTreePickerModal
        open={treePickerOpen}
        roots={tree.roots}
        childrenOf={tree.childrenOf}
        onPick={(e) => setSelected(e)}
        onClose={() => setTreePickerOpen(false)}
      />

      <ParentPickerModal
        open={parentPickerOpen}
        kind={kind}
        roots={tree.roots}
        childrenOf={tree.childrenOf}
        selectedId={parentId}
        onPick={setParentId}
        onClose={() => setParentPickerOpen(false)}
      />
    </>
  );
}
