import { useEffect, useState } from 'react';
import {
  UploadCloud,
  FolderSearch,
  FolderSync,
  Loader2,
  RefreshCw,
  ScanSearch,
  Settings2,
  X,
} from 'lucide-react';
import { driveApi } from '../../api/drive';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import DriveBrowseModal from './DriveBrowseModal';
import type { DriveStatus } from '../../types';

interface SettingsCardProps {
  status: DriveStatus;
  onStatusChange: (s: DriveStatus) => void;
  /** Ask the page to refresh the inbox after a scan found new files. */
  onInboxChanged: () => void;
}

const formatWhen = (iso: string | null): string => {
  if (!iso) return 'never';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};

/** Scans folder, poll interval, backup toggle and the manual action buttons. */
export default function SettingsCard({
  status,
  onStatusChange,
  onInboxChanged,
}: SettingsCardProps) {
  const toast = useToast();

  const [pickerOpen, setPickerOpen] = useState(false);
  const [intervalStr, setIntervalStr] = useState(String(status.poll_interval_min));
  const [savingConfig, setSavingConfig] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [reconciling, setReconciling] = useState(false);
  const [backingUp, setBackingUp] = useState(false);

  // Keep the local interval input in sync with server refreshes.
  useEffect(() => {
    setIntervalStr(String(status.poll_interval_min));
  }, [status.poll_interval_min]);

  const saveConfig = async (
    payload: Parameters<typeof driveApi.updateConfig>[0],
    okMessage: string
  ) => {
    if (savingConfig) return;
    setSavingConfig(true);
    try {
      onStatusChange(await driveApi.updateConfig(payload));
      toast.success(okMessage);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to save the setting'));
    } finally {
      setSavingConfig(false);
    }
  };

  const commitInterval = () => {
    const n = Math.round(Number(intervalStr));
    if (!Number.isFinite(n)) {
      setIntervalStr(String(status.poll_interval_min));
      return;
    }
    const clamped = Math.min(1440, Math.max(5, n));
    setIntervalStr(String(clamped));
    if (clamped !== status.poll_interval_min) {
      saveConfig({ poll_interval_min: clamped }, `Polling every ${clamped} min`);
    }
  };

  const handleScanNow = async () => {
    if (scanning) return;
    setScanning(true);
    try {
      const res = await driveApi.scanNow();
      toast.success(
        `Scan complete — ${res.new} new file${res.new === 1 ? '' : 's'}, ${res.seen} seen`
      );
      onStatusChange(await driveApi.status());
      if (res.new > 0) onInboxChanged();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Scan failed'));
    } finally {
      setScanning(false);
    }
  };

  const handleReconcile = async () => {
    if (reconciling) return;
    setReconciling(true);
    try {
      const res = await driveApi.reconcile();
      const msg = `Reconciled — ${res.ok} ok, ${res.missing} missing, ${res.changed} changed`;
      if (res.missing > 0 || res.changed > 0) toast.warning(msg);
      else toast.success(msg);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Reconcile failed'));
    } finally {
      setReconciling(false);
    }
  };

  const handleBackupNow = async () => {
    if (backingUp) return;
    setBackingUp(true);
    try {
      const res = await driveApi.backupNow();
      toast.success(`Backup uploaded to Drive: ${res.file}`);
      onStatusChange(await driveApi.status());
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Backup upload failed'));
    } finally {
      setBackingUp(false);
    }
  };

  const actionBtn =
    'flex items-center gap-2 px-3 py-2 bg-space-800 hover:bg-space-700 disabled:opacity-50 disabled:cursor-not-allowed text-gray-300 border border-space-600 rounded-lg text-sm transition-colors';

  return (
    <section className="bg-space-900 border border-space-700 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Settings2 className="w-4 h-4 text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Scans &amp; backup settings</h2>
      </div>

      {/* Scans folder */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="text-sm text-gray-400 w-28 shrink-0">Scans folder</span>
        <button
          onClick={() => setPickerOpen(true)}
          disabled={!status.connected}
          className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-space-950 border border-space-700 hover:border-space-600 disabled:opacity-50 disabled:cursor-not-allowed text-sm transition-colors max-w-[16rem]"
          title={status.connected ? 'Choose the Drive folder your scanner drops files into' : 'Connect first'}
        >
          <FolderSearch className="w-4 h-4 text-blue-400 shrink-0" />
          {status.scans_folder ? (
            <span className="text-white truncate">{status.scans_folder.name}</span>
          ) : (
            <span className="text-gray-500">Choose folder…</span>
          )}
        </button>
        {status.scans_folder && (
          <button
            onClick={() =>
              saveConfig(
                { scans_folder_id: null, scans_folder_name: null },
                'Scans folder cleared'
              )
            }
            title="Clear the scans folder (stops polling)"
            className="p-1.5 rounded-md text-gray-500 hover:text-red-400 hover:bg-space-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        )}
        <span className="text-xs text-gray-600">
          polled every {status.poll_interval_min} min — last: {formatWhen(status.last_poll_at)}
        </span>
      </div>

      {/* Poll interval */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="text-sm text-gray-400 w-28 shrink-0">Poll interval</span>
        <input
          type="number"
          min={5}
          max={1440}
          value={intervalStr}
          onChange={(e) => setIntervalStr(e.target.value)}
          onBlur={commitInterval}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          }}
          className="w-24 bg-space-950 border border-space-700 rounded-lg px-2.5 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500"
        />
        <span className="text-xs text-gray-600">minutes (5–1440)</span>
      </div>

      {/* Backup upload toggle */}
      <label className="flex items-start gap-2.5 mb-4 cursor-pointer">
        <input
          type="checkbox"
          checked={status.backup_upload_enabled}
          onChange={(e) =>
            saveConfig(
              { backup_upload_enabled: e.target.checked },
              e.target.checked
                ? 'Nightly backup upload to Drive enabled'
                : 'Nightly backup upload to Drive disabled'
            )
          }
          className="accent-blue-600 mt-0.5"
        />
        <span className="min-w-0">
          <span className="block text-sm text-gray-300">
            Upload nightly database snapshots to Drive
          </span>
          <span className="block text-xs text-gray-600 mt-0.5">
            Pushed into an <span className="text-gray-500">“Archiviator Backups”</span>{' '}
            folder; the newest 7 are kept. Last upload:{' '}
            {formatWhen(status.last_backup_upload_at)}
          </span>
        </span>
      </label>

      {/* Actions */}
      <div className="flex flex-wrap gap-2 pt-3 border-t border-space-800">
        <button
          onClick={handleScanNow}
          disabled={scanning || !status.connected || !status.scans_folder}
          title={
            !status.scans_folder
              ? 'Set a scans folder first'
              : 'Check the scans folder for new files now'
          }
          className={actionBtn}
        >
          {scanning ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <ScanSearch className="w-4 h-4" />
          )}
          Scan now
        </button>
        <button
          onClick={handleReconcile}
          disabled={reconciling || !status.connected}
          title="Re-check every attached Drive file (missing / changed detection)"
          className={actionBtn}
        >
          {reconciling ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          Reconcile links
        </button>
        <button
          onClick={handleBackupNow}
          disabled={backingUp || !status.connected}
          title="Snapshot the database and upload it to Drive now"
          className={actionBtn}
        >
          {backingUp ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <UploadCloud className="w-4 h-4" />
          )}
          Backup to Drive now
        </button>
        {!status.connected && (
          <span className="flex items-center gap-1.5 text-xs text-gray-600">
            <FolderSync className="w-3.5 h-3.5" />
            connect to enable actions
          </span>
        )}
      </div>

      <DriveBrowseModal
        open={pickerOpen}
        mode="folder"
        title="Choose the scans folder"
        onClose={() => setPickerOpen(false)}
        onPickFolder={(f) => {
          setPickerOpen(false);
          saveConfig(
            { scans_folder_id: f.id, scans_folder_name: f.name },
            `Scans folder set to “${f.name}”`
          );
        }}
      />
    </section>
  );
}
