import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  CheckCircle2,
  EyeOff,
  FileText,
  Inbox,
  Link2,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { driveApi } from '../../api/drive';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { formatBytes } from '../../utils/format';
import AttachToEntityModal from './AttachToEntityModal';
import type { DriveStatus, Entity, ScanInboxRow, ScanInboxStatus } from '../../types';

// ── Lazy thumbnail ───────────────────────────────────────────────────────────
// The ensure endpoint downloads the thumb bytes from Drive server-side, so we
// only call it for rows actually scrolled into view. Results (including "Drive
// has no thumb" = null) are cached by the parent per drive_file_id.

function DriveThumb({
  fileId,
  /** undefined = not tried yet, null = no thumb available, string = cached url. */
  url,
  onNeedThumb,
}: {
  fileId: string;
  url: string | null | undefined;
  onNeedThumb: (fileId: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const requested = useRef(false);

  useEffect(() => {
    if (url !== undefined || requested.current) return;
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && !requested.current) {
          requested.current = true;
          onNeedThumb(fileId);
          observer.disconnect();
        }
      },
      { rootMargin: '100px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [url, fileId, onNeedThumb]);

  return (
    <div
      ref={ref}
      className="w-12 h-12 rounded-lg bg-space-950 border border-space-700 overflow-hidden flex items-center justify-center shrink-0"
    >
      {url ? (
        <img src={url} alt="" loading="lazy" className="w-full h-full object-cover" />
      ) : (
        <FileText className="w-5 h-5 text-space-500" />
      )}
    </div>
  );
}

// ── Card ─────────────────────────────────────────────────────────────────────

interface InboxCardProps {
  status: DriveStatus;
  /** Sync inbox counts and status after attach/ignore. */
  onStatusChange: (s: DriveStatus) => void;
  /** Incremented by the page when a scan found new files — triggers a reload. */
  reloadKey: number;
}

const TABS: { id: ScanInboxStatus; label: string }[] = [
  { id: 'new', label: 'New' },
  { id: 'attached', label: 'Attached' },
  { id: 'ignored', label: 'Ignored' },
];

export default function InboxCard({ status, onStatusChange, reloadKey }: InboxCardProps) {
  const toast = useToast();

  const [tab, setTab] = useState<ScanInboxStatus>('new');
  const [rows, setRows] = useState<ScanInboxRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  /** drive_file_id -> ensured thumb url (null = Drive offers none). */
  const [thumbs, setThumbs] = useState<Record<string, string | null>>({});
  const thumbsInFlight = useRef(new Set<string>());
  /** Ids waiting for a free slot — at most MAX_THUMB_CONCURRENCY ensures run. */
  const thumbQueue = useRef<string[]>([]);
  const [attachRow, setAttachRow] = useState<ScanInboxRow | null>(null);
  const [busyRowId, setBusyRowId] = useState<number | null>(null);

  const load = useCallback(
    async (which: ScanInboxStatus) => {
      setLoading(true);
      try {
        const list = await driveApi.inbox(which);
        setRows(list);
        // Seed already-cached thumbs the server told us about.
        setThumbs((prev) => {
          const next = { ...prev };
          for (const r of list) {
            if (r.thumbnail_url && next[r.drive_file_id] === undefined) {
              next[r.drive_file_id] = r.thumbnail_url;
            }
          }
          return next;
        });
      } catch (err) {
        toast.error(apiErrorDetail(err, 'Failed to load the scans inbox'));
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  useEffect(() => {
    setRows(null);
    load(tab);
  }, [tab, reloadKey, load]);

  const ensureThumb = useCallback((fileId: string) => {
    // Simple queue over the in-flight set: at most 4 ensure calls run at once
    // (each is a server-side Drive download — don't stampede on long lists).
    const pump = () => {
      while (thumbsInFlight.current.size < 4 && thumbQueue.current.length > 0) {
        const next = thumbQueue.current.shift();
        if (next === undefined || thumbsInFlight.current.has(next)) continue;
        thumbsInFlight.current.add(next);
        driveApi
          .ensureThumbnail(next)
          .then((res) => setThumbs((prev) => ({ ...prev, [next]: res.url })))
          .catch(() => {
            // Leave it undefined-ish: mark as no-thumb so we don't hammer the API.
            setThumbs((prev) => ({ ...prev, [next]: null }));
          })
          .finally(() => {
            thumbsInFlight.current.delete(next);
            pump();
          });
      }
    };
    if (thumbsInFlight.current.has(fileId) || thumbQueue.current.includes(fileId)) return;
    thumbQueue.current.push(fileId);
    pump();
  }, []);

  const refreshStatus = async () => {
    try {
      onStatusChange(await driveApi.status());
    } catch {
      /* counts are cosmetic — ignore */
    }
  };

  const handleIgnore = async (row: ScanInboxRow) => {
    if (busyRowId !== null) return;
    setBusyRowId(row.id);
    try {
      await driveApi.ignoreInboxRow(row.id);
      setRows((prev) => (prev ? prev.filter((r) => r.id !== row.id) : prev));
      toast.success(`Ignored “${row.name}”`);
      refreshStatus();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to ignore the scan'));
    } finally {
      setBusyRowId(null);
    }
  };

  const handleAttach = async (entity: Entity, title: string | undefined) => {
    if (!attachRow) return;
    try {
      await driveApi.attachInboxRow(attachRow.id, entity.id, title);
      setAttachRow(null);
      setRows((prev) => (prev ? prev.filter((r) => r.id !== attachRow.id) : prev));
      // Toasts are text-only — the Attached tab rows carry the entity link.
      toast.success(`Attached “${attachRow.name}” to “${entity.name}”`);
      refreshStatus();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to attach the scan'));
      throw err; // keep the modal open
    }
  };

  const counts = status.inbox_counts;
  const countOf: Record<ScanInboxStatus, number> = {
    new: counts.new,
    attached: counts.attached,
    ignored: counts.ignored,
  };

  return (
    <section className="bg-space-900 border border-space-700 rounded-xl p-4">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <Inbox className="w-4 h-4 text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Scans inbox</h2>
        <div className="flex-1" />
        <button
          onClick={() => {
            load(tab);
            refreshStatus();
          }}
          disabled={loading}
          title="Refresh the list"
          className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-space-800 border border-space-700 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex rounded-lg border border-space-700 overflow-hidden w-fit mb-3">
        {TABS.map(({ id, label }, i) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-sm transition-colors ${
              i > 0 ? 'border-l border-space-700' : ''
            } ${
              tab === id
                ? 'bg-blue-500/20 text-blue-300'
                : 'text-gray-400 hover:text-white hover:bg-space-800'
            }`}
          >
            {label}
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                tab === id ? 'bg-blue-500/20 text-blue-300' : 'bg-space-800 text-gray-500'
              }`}
            >
              {countOf[id]}
            </span>
          </button>
        ))}
      </div>

      {/* Rows */}
      {rows === null || loading ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm py-10 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm text-gray-500 py-8 text-center">
          {tab === 'new'
            ? 'No new scans — drop files into the scans folder and run a scan.'
            : tab === 'attached'
              ? 'Nothing attached yet.'
              : 'Nothing ignored.'}
        </p>
      ) : (
        <div className="space-y-1">
          {rows.map((row) => (
            <div
              key={row.id}
              className="flex items-center gap-3 px-2 py-2 rounded-lg border border-transparent hover:border-space-700 hover:bg-space-800/60 transition-colors"
            >
              <DriveThumb
                fileId={row.drive_file_id}
                url={thumbs[row.drive_file_id]}
                onNeedThumb={ensureThumb}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{row.name}</p>
                <p className="text-xs text-gray-500 truncate">
                  {row.modified_time
                    ? new Date(row.modified_time).toLocaleString()
                    : new Date(row.discovered_at).toLocaleString()}
                  {row.size_bytes !== null && ` — ${formatBytes(row.size_bytes)}`}
                </p>
              </div>

              {tab === 'new' && (
                <>
                  <button
                    onClick={() => setAttachRow(row)}
                    disabled={busyRowId !== null}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-xs transition-colors shrink-0"
                  >
                    <Link2 className="w-3.5 h-3.5" /> Attach
                  </button>
                  <button
                    onClick={() => handleIgnore(row)}
                    disabled={busyRowId !== null}
                    title="Ignore this scan"
                    className="flex items-center gap-1.5 px-2.5 py-1.5 bg-space-800 hover:bg-space-700 disabled:opacity-50 text-gray-400 hover:text-white border border-space-600 rounded-lg text-xs transition-colors shrink-0"
                  >
                    {busyRowId === row.id ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <EyeOff className="w-3.5 h-3.5" />
                    )}
                    Ignore
                  </button>
                </>
              )}

              {tab === 'attached' &&
                (row.entity_id != null ? (
                  <Link
                    to={`/entity/${row.entity_id}`}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-blue-400 hover:text-blue-300 hover:bg-space-800 transition-colors shrink-0"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    {row.entity_name || 'Open entry'}
                  </Link>
                ) : (
                  <span className="flex items-center gap-1.5 text-xs text-green-400 shrink-0">
                    <CheckCircle2 className="w-3.5 h-3.5" /> attached
                  </span>
                ))}

              {tab === 'ignored' && (
                <span className="flex items-center gap-1.5 text-xs text-gray-500 shrink-0">
                  <EyeOff className="w-3.5 h-3.5" /> ignored
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Attach picker — mounted on demand so the tree only loads when needed */}
      {attachRow && (
        <AttachToEntityModal
          open
          fileName={attachRow.name}
          onClose={() => setAttachRow(null)}
          onAttach={handleAttach}
        />
      )}
    </section>
  );
}
