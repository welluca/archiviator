import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Loader2, QrCode, Tag, Trash2, Wand2 } from 'lucide-react';
import { assignAssetTag, labelsApi, normalizeTag } from '../../api/labels';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import QrCanvas from '../labels/QrCanvas';
import type { Entity } from '../../types';

interface AssetTagSectionProps {
  entity: Entity;
  onEntityUpdate: (e: Entity) => void;
}

/** Asset-tag block for the entity detail header: existing tag -> mono chip +
 * client-rendered QR + remove; no tag -> assign menu (auto / custom input). */
export function AssetTagSection({ entity, onEntityUpdate }: AssetTagSectionProps) {
  const toast = useToast();
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [customMode, setCustomMode] = useState(false);
  const [customTag, setCustomTag] = useState('');
  const [busy, setBusy] = useState(false);
  const [removeOpen, setRemoveOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const tag = entity.asset_tag;

  // base_url only matters when a QR is shown.
  useEffect(() => {
    if (!tag) return;
    labelsApi
      .getConfig()
      .then(({ base_url }) => setBaseUrl(base_url))
      .catch(() => setBaseUrl(null));
  }, [tag]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (ev: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(ev.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [menuOpen]);

  const assign = async (payload: { auto: true } | { tag: string | null }) => {
    if (busy) return;
    setBusy(true);
    try {
      const updated = await assignAssetTag(entity.id, payload);
      onEntityUpdate(updated);
      if ('auto' in payload) toast.success(`Tag ${updated.asset_tag} assigned`);
      else if (payload.tag === null) toast.success('Tag removed — the sticker is free again');
      else toast.success(`Tag ${updated.asset_tag} assigned`);
      setMenuOpen(false);
      setCustomMode(false);
      setCustomTag('');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to update the asset tag'));
    } finally {
      setBusy(false);
    }
  };

  // ── With tag: chip + QR + remove ──────────────────────────────────────────
  if (tag) {
    return (
      <>
        <div className="inline-flex items-center gap-3 mt-2 mb-1 px-3 py-2 rounded-lg bg-space-900 border border-space-700">
          {baseUrl && <QrCanvas value={`${baseUrl}/a/${tag}`} size={56} />}
          <div className="flex flex-col gap-1">
            <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-gray-500">
              <QrCode className="w-3 h-3" /> Asset tag
            </span>
            <span className="font-mono text-sm text-blue-300 tracking-wider">{tag}</span>
          </div>
          <button
            onClick={() => setRemoveOpen(true)}
            disabled={busy}
            title="Remove tag"
            className="p-1.5 rounded-md text-gray-500 hover:text-red-400 hover:bg-space-800 disabled:opacity-50 transition-colors self-start -mr-1"
          >
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
          </button>
        </div>

        <ConfirmDialog
          open={removeOpen}
          title="Remove asset tag"
          message={`Remove ${tag} from “${entity.name}”? If this tag came from a printed sticker, the sticker frees up and can be attached to something else.`}
          confirmLabel="Remove tag"
          variant="danger"
          onConfirm={() => {
            setRemoveOpen(false);
            assign({ tag: null });
          }}
          onCancel={() => setRemoveOpen(false)}
        />
      </>
    );
  }

  // ── No tag: assign menu ───────────────────────────────────────────────────
  return (
    <div className="relative inline-block mt-2 mb-1" ref={menuRef}>
      <button
        onClick={() => {
          setMenuOpen((v) => !v);
          setCustomMode(false);
        }}
        disabled={busy}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white bg-space-900 hover:bg-space-800 border border-space-700 disabled:opacity-50 transition-colors"
      >
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Tag className="w-3.5 h-3.5" />}
        Assign tag
        <ChevronDown className="w-3 h-3" />
      </button>

      {menuOpen && (
        <div className="absolute left-0 top-full mt-1 z-30 w-60 bg-space-900 border border-space-700 rounded-lg shadow-lg shadow-black/40 py-1 overflow-hidden">
          {!customMode ? (
            <>
              <button
                onClick={() => assign({ auto: true })}
                disabled={busy}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left text-gray-300 hover:bg-space-800 hover:text-white disabled:opacity-50 transition-colors"
              >
                <Wand2 className="w-4 h-4" /> Next free tag
              </button>
              <button
                onClick={() => setCustomMode(true)}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left text-gray-300 hover:bg-space-800 hover:text-white transition-colors"
              >
                <QrCode className="w-4 h-4" /> Enter custom / printed tag
              </button>
            </>
          ) : (
            <form
              className="p-2.5 space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (customTag.trim()) assign({ tag: customTag });
              }}
            >
              <input
                autoFocus
                value={customTag}
                onChange={(e) => setCustomTag(normalizeTag(e.target.value))}
                placeholder="A-0042"
                className="w-full bg-space-950 border border-space-700 rounded-lg px-2.5 py-1.5 font-mono text-sm text-white tracking-wider placeholder-gray-600 focus:outline-none focus:border-blue-500"
              />
              <button
                type="submit"
                disabled={!customTag.trim() || busy}
                className="w-full flex items-center justify-center gap-2 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-xs transition-colors"
              >
                {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Assign
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}

export default AssetTagSection;
