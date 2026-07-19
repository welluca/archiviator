import { useCallback, useEffect, useRef, useState } from 'react';
import { Cloud, Loader2 } from 'lucide-react';
import { driveApi } from '../api/drive';
import { apiErrorDetail } from '../api/entities';
import { useToast } from '../components/ui/Toast';
import ConnectionCard from '../components/drive/ConnectionCard';
import SettingsCard from '../components/drive/SettingsCard';
import InboxCard from '../components/drive/InboxCard';
import type { DriveStatus } from '../types';

/** M9: Google Drive — connection, scans folder settings and the scans inbox. */
export default function DrivePage() {
  const toast = useToast();

  const [status, setStatus] = useState<DriveStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [connectPending, setConnectPending] = useState(false);
  const [inboxReloadKey, setInboxReloadKey] = useState(0);
  const wasConnected = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const s = await driveApi.status();
      setStatus(s);
      setLoadError(null);
      return s;
    } catch (err) {
      setLoadError(apiErrorDetail(err, 'Failed to load the Drive status'));
      return null;
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // While the server-side OAuth flow runs, poll status every 2s until the
  // token lands. When the server reports the flow is over (connect_pending
  // false) without a token, stop polling and surface the failure instead of
  // spinning forever.
  useEffect(() => {
    if (!connectPending) return;
    const timer = window.setInterval(async () => {
      const s = await refresh();
      if (!s) return; // transient status fetch error — keep polling
      if (s.connected) {
        setConnectPending(false);
      } else if (!s.connect_pending) {
        setConnectPending(false);
        toast.error('Google authorization was not completed');
      }
    }, 2000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectPending, refresh]);

  // One "connected" toast per not-connected -> connected transition we watched.
  useEffect(() => {
    if (!status) return;
    if (status.connected && !wasConnected.current && connectPending) {
      toast.success(`Google Drive connected${status.email ? ` as ${status.email}` : ''}`);
    }
    wasConnected.current = status.connected;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.connected]);

  if (status === null) {
    return loadError ? (
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-2.5 mb-4">
          <Cloud className="w-6 h-6 text-blue-400" />
          <h1 className="text-xl font-bold text-white">Google Drive</h1>
        </div>
        <p className="text-sm text-red-400">{loadError}</p>
      </div>
    ) : (
      <div className="flex items-center gap-2 text-gray-500 text-sm py-16 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading…
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="flex items-center gap-2.5">
        <Cloud className="w-6 h-6 text-blue-400" />
        <h1 className="text-xl font-bold text-white">Google Drive</h1>
        <p className="hidden sm:block text-xs text-gray-500">
          scanned documents inbox + off-site backup push
        </p>
      </div>

      <ConnectionCard
        status={status}
        onStatusChange={setStatus}
        connectPending={connectPending}
        onConnectStart={() => setConnectPending(true)}
        onConnectCancel={() => setConnectPending(false)}
      />

      {status.configured && (
        <SettingsCard
          status={status}
          onStatusChange={setStatus}
          onInboxChanged={() => setInboxReloadKey((k) => k + 1)}
        />
      )}

      {status.connected && (
        <InboxCard status={status} onStatusChange={setStatus} reloadKey={inboxReloadKey} />
      )}
    </div>
  );
}
