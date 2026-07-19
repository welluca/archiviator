import { useState } from 'react';
import {
  AlertTriangle,
  Cloud,
  KeyRound,
  Loader2,
  LogIn,
  MonitorUp,
  Unplug,
} from 'lucide-react';
import { driveApi } from '../../api/drive';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import type { DriveStatus } from '../../types';

interface ConnectionCardProps {
  status: DriveStatus;
  onStatusChange: (s: DriveStatus) => void;
  /** True while the server-side OAuth flow is running (page polls status). */
  connectPending: boolean;
  onConnectStart: () => void;
  onConnectCancel: () => void;
}

/** Drive connection lifecycle: unconfigured → configured → connected. */
export default function ConnectionCard({
  status,
  onStatusChange,
  connectPending,
  onConnectStart,
  onConnectCancel,
}: ConnectionCardProps) {
  const toast = useToast();

  const [credentialsPath, setCredentialsPath] = useState('');
  const [editingPath, setEditingPath] = useState(false);
  const [savingPath, setSavingPath] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  const showPathForm = !status.configured || editingPath;

  const savePath = async () => {
    const path = credentialsPath.trim();
    if (path === '' || savingPath) return;
    setSavingPath(true);
    try {
      const s = await driveApi.updateConfig({ credentials_path: path });
      onStatusChange(s);
      setEditingPath(false);
      setCredentialsPath('');
      toast.success('Client secret path saved');
    } catch (err) {
      toast.error(
        apiErrorDetail(err, 'Invalid path — must be an existing client_secret JSON file')
      );
    } finally {
      setSavingPath(false);
    }
  };

  const handleConnect = async () => {
    if (connecting || connectPending) return;
    setConnecting(true);
    try {
      await driveApi.connect();
      onConnectStart();
      toast.info('Authorization started — check the browser window on the server PC');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to start the Google authorization'));
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    setConfirmDisconnect(false);
    if (disconnecting) return;
    setDisconnecting(true);
    try {
      await driveApi.disconnect();
      onStatusChange(await driveApi.status());
      toast.success('Disconnected from Google Drive');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to disconnect'));
    } finally {
      setDisconnecting(false);
    }
  };

  return (
    <section className="bg-space-900 border border-space-700 rounded-xl p-4">
      <div className="flex flex-wrap items-center gap-2 mb-1">
        <Cloud className="w-4 h-4 text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Google Drive connection</h2>
        <div className="flex-1" />
        {status.connected ? (
          <span className="flex items-center gap-1.5 text-xs text-green-400">
            <span className="w-2 h-2 rounded-full bg-green-400" />
            Connected{status.email ? ` as ${status.email}` : ''}
          </span>
        ) : status.configured ? (
          <span className="flex items-center gap-1.5 text-xs text-gray-500">
            <span className="w-2 h-2 rounded-full bg-gray-600" />
            Not connected
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-xs text-yellow-500">
            <span className="w-2 h-2 rounded-full bg-yellow-500" />
            Not configured
          </span>
        )}
      </div>

      {/* ── State 1: credentials path ─────────────────────────────────────── */}
      {showPathForm && (
        <div className="mt-3">
          <p className="text-xs text-gray-500 mb-2">
            Paste the full path to your OAuth <span className="text-gray-400">client secret</span>{' '}
            JSON (a desktop-app credential). You can reuse the existing{' '}
            <code className="font-mono text-gray-400">client_secret_*.json</code> from the
            gdriveexchanger credentials folder — the file is referenced in place, never
            copied.
          </p>
          <div className="flex items-start gap-2 px-3 py-2 mb-3 rounded-lg bg-yellow-900/20 border border-yellow-700/40">
            <AlertTriangle className="w-4 h-4 text-yellow-500 shrink-0 mt-0.5" />
            <p className="text-xs text-yellow-500/90">
              The Google Cloud consent screen must be set to{' '}
              <span className="font-semibold">“In production”</span>. In “Testing” mode
              Google kills the token after 7 days and you would have to reconnect weekly.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              value={credentialsPath}
              onChange={(e) => setCredentialsPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') savePath();
              }}
              placeholder="C:\...\credentials\client_secret_xxxx.json"
              className="flex-1 min-w-[16rem] bg-space-950 border border-space-700 rounded-lg px-3 py-2 text-sm font-mono text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
            />
            <button
              onClick={savePath}
              disabled={savingPath || credentialsPath.trim() === ''}
              className="flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors"
            >
              {savingPath ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <KeyRound className="w-4 h-4" />
              )}
              Save path
            </button>
            {editingPath && (
              <button
                onClick={() => {
                  setEditingPath(false);
                  setCredentialsPath('');
                }}
                className="px-3 py-2 text-sm text-gray-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── State 2: configured, not connected ────────────────────────────── */}
      {status.configured && !status.connected && !editingPath && (
        <div className="mt-3">
          {connectPending ? (
            <div className="flex items-start gap-3 px-3 py-3 rounded-lg bg-blue-900/20 border border-blue-700/40">
              <Loader2 className="w-4 h-4 text-blue-400 animate-spin shrink-0 mt-0.5" />
              <div className="min-w-0">
                <p className="text-sm text-blue-300">Waiting for Google authorization…</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  A browser window opened on the server PC — sign in and grant access
                  there. This page refreshes automatically.
                </p>
              </div>
              <button
                onClick={onConnectCancel}
                className="ml-auto text-xs text-gray-500 hover:text-white transition-colors shrink-0"
              >
                Stop waiting
              </button>
            </div>
          ) : (
            <>
              <div className="flex items-start gap-2 mb-3">
                <MonitorUp className="w-4 h-4 text-gray-500 shrink-0 mt-0.5" />
                <p className="text-xs text-gray-500">
                  Connecting opens a Google sign-in window{' '}
                  <span className="text-gray-400">on the PC running the server</span> (they
                  are the same machine). Complete the consent there once — the token is
                  cached and refreshed automatically afterwards.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={handleConnect}
                  disabled={connecting}
                  className="flex items-center gap-2 px-3.5 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
                >
                  {connecting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <LogIn className="w-4 h-4" />
                  )}
                  Connect Google Drive
                </button>
                <button
                  onClick={() => setEditingPath(true)}
                  className="text-xs text-gray-500 hover:text-white transition-colors"
                >
                  change client secret path
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── State 3: connected ────────────────────────────────────────────── */}
      {status.connected && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p className="text-xs text-gray-500">
            Full Drive access (read + write) — scans inbox, file attach and backup upload
            are available.
          </p>
          <div className="flex-1" />
          <button
            onClick={() => setConfirmDisconnect(true)}
            disabled={disconnecting}
            className="flex items-center gap-2 px-3 py-2 bg-space-800 hover:bg-space-700 disabled:opacity-50 text-gray-300 border border-space-600 rounded-lg text-sm transition-colors"
          >
            {disconnecting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Unplug className="w-4 h-4" />
            )}
            Disconnect
          </button>
        </div>
      )}

      <ConfirmDialog
        open={confirmDisconnect}
        title="Disconnect Google Drive"
        message="The cached token is deleted and polling, attach and backup upload stop working until you reconnect. Existing Drive-link attachments are kept."
        confirmLabel="Disconnect"
        variant="danger"
        onConfirm={handleDisconnect}
        onCancel={() => setConfirmDisconnect(false)}
      />
    </section>
  );
}
