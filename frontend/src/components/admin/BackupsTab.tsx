import { useCallback, useEffect, useState } from 'react';
import { DatabaseBackup, HardDriveDownload, Loader2 } from 'lucide-react';
import { adminApi } from '../../api/admin';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { formatBytes } from '../../utils/format';
import type { BackupInfo } from '../../types';

const formatWhen = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};

export default function BackupsTab() {
  const toast = useToast();
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      setBackups(await adminApi.listBackups());
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to load backups'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleBackupNow = async () => {
    if (running) return;
    setRunning(true);
    try {
      const result = await adminApi.backupNow();
      toast.success(`Snapshot written: ${result.file} (${formatBytes(result.bytes)})`);
      await load();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Backup failed'));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="bg-space-900 border border-space-700 rounded-xl p-4">
      <div className="flex flex-wrap items-center gap-2 mb-1">
        <DatabaseBackup className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-semibold text-white">Database backups</h3>
        <div className="flex-1" />
        <button
          onClick={handleBackupNow}
          disabled={running}
          className="flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm transition-colors"
        >
          {running ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <HardDriveDownload className="w-4 h-4" />
          )}
          Backup now
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        A WAL-safe snapshot runs automatically every night at 03:30; the newest 14 are kept.
        Files live in the server data directory under{' '}
        <code className="font-mono text-gray-400">backups\</code> (e.g.{' '}
        <code className="font-mono text-gray-400">C:\archiviator-data\backups</code>) — copy
        them off the machine for real safety, or use the full export ZIP.
      </p>

      {loading ? (
        <div className="flex items-center gap-2 text-gray-500 text-sm py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : backups.length === 0 ? (
        <p className="text-sm text-gray-500 py-6 text-center">
          No snapshots yet — run one now or wait for tonight&apos;s job.
        </p>
      ) : (
        <div className="space-y-0.5">
          {backups.map((b) => (
            <div
              key={b.file}
              className="flex items-center gap-3 px-2 py-1.5 rounded-lg hover:bg-space-800/60 transition-colors"
            >
              <span className="flex-1 min-w-0 font-mono text-sm text-gray-300 truncate">
                {b.file}
              </span>
              <span className="text-xs text-gray-500 shrink-0">{formatBytes(b.bytes)}</span>
              <span className="text-xs text-gray-500 shrink-0 w-40 text-right">
                {formatWhen(b.created_at)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
