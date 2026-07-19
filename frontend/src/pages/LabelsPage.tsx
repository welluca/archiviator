import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import {
  Ban,
  ChevronDown,
  ChevronRight,
  Download,
  Loader2,
  Printer,
  QrCode,
  Search,
  X,
} from 'lucide-react';
import { labelsApi, type CreateBatchPayload } from '../api/labels';
import { searchApi } from '../api/search';
import { apiErrorDetail } from '../api/entities';
import { useToast } from '../components/ui/Toast';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import EntityIcon from '../components/browse/EntityIcon';
import type {
  Entity,
  LabelBatch,
  LabelTemplate,
  PrintedLabel,
  PrintedLabelStatus,
} from '../types';

const inputClass =
  'w-full bg-space-950 border border-space-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500';

const perSheet = (t: LabelTemplate): number => t.cols * t.rows;

const statusChipClass: Record<PrintedLabelStatus, string> = {
  unclaimed: 'bg-space-800 border-space-600 text-gray-400',
  claimed: 'bg-green-900/40 border-green-700/40 text-green-400',
  void: 'bg-red-900/40 border-red-700/40 text-red-400',
};

const StatusChip = ({ status, count }: { status: PrintedLabelStatus; count?: number }) => (
  <span
    className={`text-[10px] px-1.5 py-0.5 rounded-full border shrink-0 ${statusChipClass[status]}`}
  >
    {count !== undefined ? `${count} ` : ''}
    {status}
  </span>
);

const formatDate = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
};

// ── Print wizard card ────────────────────────────────────────────────────────

function PrintWizard({ onCreated }: { onCreated: (batch: LabelBatch) => void }) {
  const toast = useToast();
  const [templates, setTemplates] = useState<LabelTemplate[]>([]);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [mode, setMode] = useState<'blank' | 'existing'>('blank');
  const [count, setCount] = useState('21');
  const [skipFirst, setSkipFirst] = useState('0');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Existing-entities mode: search + accumulated multi-select.
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Entity[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Map<number, Entity>>(new Map());

  useEffect(() => {
    labelsApi
      .templates()
      .then((list) => {
        setTemplates(list);
        if (list.length > 0) {
          setTemplateId(list[0].id);
          setCount(String(perSheet(list[0])));
        }
      })
      .catch((err) => toast.error(apiErrorDetail(err, 'Failed to load label templates')));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (mode !== 'existing' || q.trim() === '') {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const t = setTimeout(() => {
      setSearching(true);
      searchApi
        .search({ q, limit: 30 }, controller.signal)
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

  const template = useMemo(
    () => templates.find((t) => t.id === templateId) ?? null,
    [templates, templateId]
  );

  const toggleEntity = (e: Entity) => {
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(e.id)) next.delete(e.id);
      else next.set(e.id, e);
      return next;
    });
  };

  const countNum = Number(count);
  const skipNum = Number(skipFirst) || 0;
  const canSubmit =
    template !== null &&
    !submitting &&
    (mode === 'blank'
      ? Number.isInteger(countNum) && countNum > 0
      : selected.size > 0);

  const handleSubmit = async () => {
    if (!canSubmit || !template) return;
    setSubmitting(true);
    try {
      const payload: CreateBatchPayload = {
        template_id: template.id,
        skip_first: skipNum,
        note: note.trim() || undefined,
      };
      if (mode === 'blank') payload.count = countNum;
      else payload.entity_ids = [...selected.keys()];

      const batch = await labelsApi.createBatch(payload);
      try {
        await labelsApi.downloadBatchPdf(batch.id);
        toast.success(`Batch #${batch.id} created — PDF downloading`);
      } catch {
        toast.warning(`Batch #${batch.id} created, but the PDF download failed — use the download button below`);
      }
      onCreated(batch);
      setSelected(new Map());
      setQ('');
      setNote('');
      setSkipFirst('0');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to create the label batch'));
    } finally {
      setSubmitting(false);
    }
  };

  const modeBtn = (value: 'blank' | 'existing', label: string) => (
    <button
      type="button"
      onClick={() => setMode(value)}
      className={`flex-1 px-3 py-2 text-xs sm:text-sm transition-colors ${
        mode === value
          ? 'bg-blue-500/20 text-blue-300'
          : 'text-gray-400 hover:text-white hover:bg-space-800'
      }`}
    >
      {label}
    </button>
  );

  return (
    <section className="bg-space-900 border border-space-700 rounded-xl p-4 sm:p-5 mb-6">
      <div className="flex items-center gap-2 mb-4">
        <Printer className="w-5 h-5 text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Print new labels</h2>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {/* Template */}
        <div className="sm:col-span-2">
          <label className="block text-xs text-gray-400 mb-1.5">Sheet template</label>
          <select
            value={templateId ?? ''}
            onChange={(e) => {
              const id = Number(e.target.value);
              setTemplateId(id);
              const t = templates.find((x) => x.id === id);
              if (t && mode === 'blank') setCount(String(perSheet(t)));
            }}
            className={inputClass}
          >
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          {template && (
            <p className="text-xs text-gray-500 mt-1.5">
              {template.label_w_mm} × {template.label_h_mm} mm labels —{' '}
              {perSheet(template)} per A4 sheet ({template.cols} × {template.rows})
            </p>
          )}
        </div>

        {/* Mode toggle */}
        <div className="sm:col-span-2">
          <div className="flex rounded-lg border border-space-700 bg-space-950 overflow-hidden divide-x divide-space-700">
            {modeBtn('blank', 'Blank labels for future use')}
            {modeBtn('existing', 'Labels for existing entries')}
          </div>
        </div>

        {mode === 'blank' ? (
          <div>
            <label className="block text-xs text-gray-400 mb-1.5">How many labels</label>
            <input
              type="number"
              min={1}
              value={count}
              onChange={(e) => setCount(e.target.value)}
              className={inputClass}
            />
            {template && Number.isInteger(countNum) && countNum > 0 && (
              <p className="text-xs text-gray-500 mt-1.5">
                {Math.ceil((countNum + skipNum) / perSheet(template))} sheet
                {Math.ceil((countNum + skipNum) / perSheet(template)) === 1 ? '' : 's'} —
                new tags are allocated and stay unclaimed until scanned
              </p>
            )}
          </div>
        ) : (
          <div className="sm:col-span-2 space-y-2.5">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search entries to print labels for…"
                className={`${inputClass} pl-9`}
              />
            </div>

            {searching ? (
              <div className="flex items-center gap-2 text-gray-500 text-xs py-3 justify-center">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Searching…
              </div>
            ) : results.length > 0 ? (
              <div className="border border-space-700 rounded-lg bg-space-950 max-h-56 overflow-y-auto p-1.5 space-y-0.5">
                {results.map((e) => (
                  <label
                    key={e.id}
                    className="flex items-center gap-2.5 px-2 py-1.5 rounded-md hover:bg-space-800 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(e.id)}
                      onChange={() => toggleEntity(e)}
                      className="accent-blue-600"
                    />
                    <EntityIcon entity={e} className="w-4 h-4" />
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm text-white truncate">{e.name}</span>
                      {e.breadcrumb && (
                        <span className="block text-[11px] text-gray-500 truncate">
                          {e.breadcrumb}
                        </span>
                      )}
                    </span>
                    {e.asset_tag ? (
                      <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-space-800 border border-space-700 text-gray-400 shrink-0">
                        {e.asset_tag}
                      </span>
                    ) : (
                      <span className="text-[10px] text-gray-600 shrink-0">no tag yet</span>
                    )}
                  </label>
                ))}
              </div>
            ) : q.trim() !== '' ? (
              <p className="text-xs text-gray-600 text-center py-2">No matches.</p>
            ) : null}

            {selected.size > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {[...selected.values()].map((e) => (
                  <span
                    key={e.id}
                    className="flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-blue-500/10 border border-blue-500/30 text-blue-300"
                  >
                    {e.name}
                    <button
                      onClick={() => toggleEntity(e)}
                      aria-label={`Remove ${e.name}`}
                      className="hover:text-white"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <p className="text-xs text-gray-500">
              Entries without a tag get one allocated; the label shows the QR, the tag and
              the name.
            </p>
          </div>
        )}

        {/* Skip-first */}
        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Skip first positions</label>
          <input
            type="number"
            min={0}
            value={skipFirst}
            onChange={(e) => setSkipFirst(e.target.value)}
            className={inputClass}
          />
          <p className="text-xs text-gray-500 mt-1.5">
            Positions already used on a partially-used sheet are left empty.
          </p>
        </div>

        {/* Note */}
        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Note</label>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional (e.g. garage boxes)"
            className={inputClass}
          />
        </div>
      </div>

      <div className="flex justify-end mt-4">
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors"
        >
          {submitting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Printer className="w-4 h-4" />
          )}
          {mode === 'blank'
            ? 'Print blank labels'
            : `Print labels for ${selected.size} entr${selected.size === 1 ? 'y' : 'ies'}`}
        </button>
      </div>
    </section>
  );
}

// ── Batch row ────────────────────────────────────────────────────────────────

function BatchRow({
  batch,
  onCountsChanged,
}: {
  batch: LabelBatch;
  onCountsChanged: () => void;
}) {
  const toast = useToast();
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<LabelBatch | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [voidTarget, setVoidTarget] = useState<PrintedLabel | null>(null);

  const loadDetail = useCallback(async () => {
    setLoadingDetail(true);
    try {
      setDetail(await labelsApi.getBatch(batch.id));
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to load batch labels'));
    } finally {
      setLoadingDetail(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch.id]);

  const toggleExpand = () => {
    const next = !expanded;
    setExpanded(next);
    if (next && detail === null) loadDetail();
  };

  const handleDownload = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      await labelsApi.downloadBatchPdf(batch.id);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to download the PDF'));
    } finally {
      setDownloading(false);
    }
  };

  const handleVoid = async () => {
    if (!voidTarget) return;
    const tag = voidTarget.asset_tag;
    setVoidTarget(null);
    try {
      await labelsApi.voidLabel(tag);
      toast.success(`Label ${tag} voided`);
      await loadDetail();
      onCountsChanged();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to void the label'));
    }
  };

  const counts = batch.counts;

  return (
    <div className="border border-space-700 rounded-xl bg-space-900 overflow-hidden">
      <div className="flex items-center gap-3 px-3 sm:px-4 py-3">
        <button
          onClick={toggleExpand}
          aria-label={expanded ? 'Collapse batch' : 'Expand batch'}
          className="p-1 rounded-md text-gray-500 hover:text-white hover:bg-space-800 transition-colors shrink-0"
        >
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-mono text-sm text-white">#{String(batch.id).padStart(4, '0')}</span>
            <span className="text-xs text-gray-500 shrink-0">{formatDate(batch.created_at)}</span>
            {batch.note && (
              <span className="text-xs text-gray-400 truncate">— {batch.note}</span>
            )}
          </div>
          <p className="text-[11px] text-gray-500 truncate mt-0.5">
            {batch.template.name} · {batch.label_count} label
            {batch.label_count === 1 ? '' : 's'}
          </p>
        </div>

        <div className="hidden sm:flex items-center gap-1.5 shrink-0">
          {counts && (
            <>
              <StatusChip status="unclaimed" count={counts.unclaimed} />
              <StatusChip status="claimed" count={counts.claimed} />
              {counts.void > 0 && <StatusChip status="void" count={counts.void} />}
            </>
          )}
        </div>

        <button
          onClick={handleDownload}
          disabled={downloading}
          title="Download PDF"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-gray-300 bg-space-800 hover:bg-space-700 border border-space-600 disabled:opacity-50 transition-colors shrink-0"
        >
          {downloading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Download className="w-3.5 h-3.5" />
          )}
          <span className="hidden sm:inline">PDF</span>
        </button>
      </div>

      {expanded && (
        <div className="border-t border-space-700 px-3 sm:px-4 py-3">
          {loadingDetail ? (
            <div className="flex items-center gap-2 text-gray-500 text-sm py-4 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading labels…
            </div>
          ) : detail?.labels && detail.labels.length > 0 ? (
            <div className="space-y-0.5">
              {detail.labels.map((label) => (
                <div
                  key={label.id}
                  className="flex items-center gap-3 px-2 py-1.5 rounded-md hover:bg-space-800/60 transition-colors"
                >
                  <span className="font-mono text-sm text-blue-300 tracking-wider w-20 shrink-0">
                    {label.asset_tag}
                  </span>
                  <StatusChip status={label.status} />
                  <span className="flex-1 min-w-0 text-sm truncate">
                    {label.entity_id !== null ? (
                      <Link
                        to={`/entity/${label.entity_id}`}
                        className="text-gray-300 hover:text-white hover:underline"
                      >
                        {label.entity_name || `Entry #${label.entity_id}`}
                      </Link>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </span>
                  {label.status === 'unclaimed' && (
                    <button
                      onClick={() => setVoidTarget(label)}
                      title="Void this label (e.g. sticker damaged or lost)"
                      className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-500 hover:text-red-400 hover:bg-space-700 transition-colors shrink-0"
                    >
                      <Ban className="w-3.5 h-3.5" /> void
                    </button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-600 text-center py-3">No labels in this batch.</p>
          )}
        </div>
      )}

      <ConfirmDialog
        open={voidTarget !== null}
        title="Void label"
        message={`Mark ${voidTarget?.asset_tag ?? ''} as void? A voided sticker can never be claimed — use this when a printed label is damaged or lost.`}
        confirmLabel="Void label"
        variant="danger"
        onConfirm={handleVoid}
        onCancel={() => setVoidTarget(null)}
      />
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function LabelsPage() {
  const toast = useToast();
  const [batches, setBatches] = useState<LabelBatch[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setBatches(await labelsApi.listBatches());
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to load label batches'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center gap-2.5 mb-4">
        <QrCode className="w-6 h-6 text-blue-400" />
        <h1 className="text-xl font-bold text-white">Labels</h1>
      </div>

      <PrintWizard onCreated={refresh} />

      <h2 className="text-sm font-semibold text-white mb-2.5">Printed batches</h2>
      {loading ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm py-10 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : batches.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-14 text-center border border-dashed border-space-700 rounded-xl px-6">
          <QrCode className="w-10 h-10 text-space-500 mb-3" />
          <p className="text-gray-400 text-sm max-w-md">
            Print a sheet of blank QR labels, stick them on boxes and items, then scan one
            with your phone to attach it to an entry on the spot.
          </p>
          <p className="text-gray-600 text-xs mt-1.5 max-w-md">
            You can also print labels for entries that already exist — those come out
            pre-linked with the tag and name on them.
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {batches.map((b) => (
            <BatchRow key={b.id} batch={b} onCountsChanged={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}
