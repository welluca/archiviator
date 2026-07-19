import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  Ban,
  Check,
  Copy,
  Loader2,
  Plus,
  Smartphone,
} from 'lucide-react';
import { deviceTokensApi, type DeviceToken, type DeviceTokenCreated } from '../../api/auth-tokens';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { ConfirmDialog } from '../ui/ConfirmDialog';

const formatDate = (iso: string | null): string => {
  if (!iso) return 'never';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};

/** Capture-scope device tokens for headless clients (iOS Shortcuts). The
 * plaintext token appears exactly once after creation — copy it or lose it. */
export default function DeviceTokensTab() {
  const toast = useToast();
  const [tokens, setTokens] = useState<DeviceToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [label, setLabel] = useState('');
  const [creating, setCreating] = useState(false);
  const [fresh, setFresh] = useState<DeviceTokenCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<DeviceToken | null>(null);

  const load = useCallback(async () => {
    try {
      setTokens(await deviceTokensApi.list());
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to load device tokens'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = label.trim();
    if (name === '' || creating) return;
    setCreating(true);
    try {
      const created = await deviceTokensApi.create(name);
      setFresh(created);
      setCopied(false);
      setLabel('');
      await load();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to create device token'));
    } finally {
      setCreating(false);
    }
  };

  const handleCopy = async () => {
    if (!fresh) return;
    try {
      await navigator.clipboard.writeText(fresh.token);
      setCopied(true);
      toast.success('Token copied to clipboard');
    } catch {
      toast.warning('Clipboard blocked — select and copy the token manually');
    }
  };

  const handleRevoke = async () => {
    if (!revokeTarget) return;
    try {
      await deviceTokensApi.revoke(revokeTarget.id);
      toast.success(`Token “${revokeTarget.label}” revoked`);
      setRevokeTarget(null);
      await load();
    } catch (err) {
      setRevokeTarget(null);
      toast.error(apiErrorDetail(err, 'Failed to revoke token'));
    }
  };

  return (
    <div className="space-y-4">
      {/* Help */}
      <div className="bg-space-900 border border-space-700 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-1.5">
          <Smartphone className="w-4 h-4 text-blue-400" />
          <h2 className="text-sm font-semibold text-white">Device tokens</h2>
        </div>
        <p className="text-xs text-gray-500">
          Capture-only credentials for headless clients. For iOS Shortcuts: Scan QR →
          Take Photo → POST to{' '}
          <code className="font-mono text-blue-300 bg-space-950 px-1 py-0.5 rounded">
            /api/v1/intake/capture
          </code>{' '}
          with header{' '}
          <code className="font-mono text-blue-300 bg-space-950 px-1 py-0.5 rounded">
            Authorization: Bearer &lt;token&gt;
          </code>
          . A device token can only capture, resolve labels and upload attachments —
          it can never read the tree, search, export or delete anything.
        </p>
      </div>

      {/* Create */}
      <form
        onSubmit={handleCreate}
        className="bg-space-900 border border-space-700 rounded-xl p-4"
      >
        <label className="block text-xs text-gray-400 mb-1.5">New token label</label>
        <div className="flex gap-2">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. Luca's iPhone shortcut"
            className="flex-1 bg-space-950 border border-space-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            disabled={label.trim() === '' || creating}
            className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors shrink-0"
          >
            {creating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Plus className="w-4 h-4" />
            )}
            Create
          </button>
        </div>

        {/* Fresh token — shown ONCE */}
        {fresh && (
          <div className="mt-3 rounded-lg border border-amber-700/50 bg-amber-900/20 p-3">
            <p className="flex items-center gap-1.5 text-xs text-amber-400 mb-2">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              Copy this token now — it will never be shown again.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 min-w-0 font-mono text-xs text-blue-300 bg-space-950 border border-space-700 rounded-lg px-3 py-2 overflow-x-auto whitespace-nowrap select-all">
                {fresh.token}
              </code>
              <button
                type="button"
                onClick={handleCopy}
                className="flex items-center gap-1.5 px-3 py-2 bg-space-800 hover:bg-space-700 text-gray-300 border border-space-600 rounded-lg text-sm transition-colors shrink-0"
              >
                {copied ? (
                  <Check className="w-4 h-4 text-green-400" />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <p className="text-[11px] text-gray-500 mt-2">
              Token for “{fresh.label}”. Done copying?{' '}
              <button
                type="button"
                onClick={() => setFresh(null)}
                className="text-blue-400 hover:underline"
              >
                Dismiss
              </button>
            </p>
          </div>
        )}
      </form>

      {/* List */}
      <div className="bg-space-900 border border-space-700 rounded-xl p-4">
        {loading ? (
          <div className="flex items-center gap-2 text-gray-500 text-sm py-6 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        ) : tokens.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">
            No device tokens yet — create one above for your phone shortcut.
          </p>
        ) : (
          <div className="space-y-1">
            {tokens.map((t) => {
              const revoked = t.revoked_at !== null;
              return (
                <div
                  key={t.id}
                  className={`flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 rounded-lg border border-transparent hover:border-space-700 hover:bg-space-800/60 transition-colors ${
                    revoked ? 'opacity-50' : ''
                  }`}
                >
                  <Smartphone className="w-4 h-4 text-blue-400 shrink-0" />
                  <span className="text-sm text-white truncate">{t.label}</span>
                  {revoked && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-900/40 border border-red-700/40 text-red-400 shrink-0">
                      revoked
                    </span>
                  )}
                  <div className="flex-1" />
                  <span className="text-xs text-gray-500 shrink-0">
                    created {formatDate(t.created_at)}
                  </span>
                  <span className="text-xs text-gray-500 shrink-0">
                    last used {formatDate(t.last_used_at)}
                  </span>
                  {!revoked && (
                    <button
                      onClick={() => setRevokeTarget(t)}
                      title="Revoke token"
                      className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-400 hover:text-red-400 hover:bg-red-900/30 transition-colors shrink-0"
                    >
                      <Ban className="w-3.5 h-3.5" /> Revoke
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke device token"
        message={`Revoke “${revokeTarget?.label ?? ''}”? Any shortcut using it will stop working immediately. This cannot be undone.`}
        confirmLabel="Revoke"
        variant="danger"
        onConfirm={handleRevoke}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}
