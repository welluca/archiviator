import { useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  FileDown,
  FileSpreadsheet,
  FolderArchive,
  Loader2,
  Upload,
} from 'lucide-react';
import { adminApi } from '../../api/admin';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import type { ImportResult } from '../../types';

export default function ImportExportTab() {
  const toast = useToast();
  const [busyDownload, setBusyDownload] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<ImportResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const download = async (key: string, fn: () => Promise<void>, failMsg: string) => {
    if (busyDownload) return;
    setBusyDownload(key);
    try {
      await fn();
    } catch (err) {
      toast.error(apiErrorDetail(err, failMsg));
    } finally {
      setBusyDownload(null);
    }
  };

  const onPickFile = async (picked: File | null) => {
    setFile(picked);
    setPreview(null);
    setApplied(null);
    if (!picked) return;
    // Dry-run immediately — validates everything without committing.
    setPreviewing(true);
    try {
      setPreview(await adminApi.importCsv(picked, true));
    } catch (err) {
      toast.error(apiErrorDetail(err, 'The CSV could not be read — check the header row'));
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    } finally {
      setPreviewing(false);
    }
  };

  const handleApply = async () => {
    if (!file || applying) return;
    setApplying(true);
    try {
      const result = await adminApi.importCsv(file, false);
      setApplied(result);
      setPreview(null);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      toast.success(
        `Import done — ${result.created} created, ${result.updated} updated` +
          (result.errors.length > 0 ? `, ${result.errors.length} row errors` : '')
      );
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Import failed'));
    } finally {
      setApplying(false);
    }
  };

  const dlBtn =
    'flex items-center gap-2 px-3 py-2 bg-space-800 hover:bg-space-700 disabled:opacity-50 text-gray-300 border border-space-600 rounded-lg text-sm transition-colors';

  const renderResult = (result: ImportResult, appliedMode: boolean) => (
    <div className="mt-3 border border-space-700 rounded-lg bg-space-950 p-3">
      <div className="flex flex-wrap items-center gap-2 mb-1.5">
        {appliedMode ? (
          <span className="flex items-center gap-1.5 text-xs text-green-400">
            <CheckCircle2 className="w-3.5 h-3.5" /> Applied
          </span>
        ) : (
          <span className="text-xs text-gray-400">Dry-run preview — nothing written yet</span>
        )}
        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-900/40 border border-green-700/40 text-green-400">
          {result.created} {appliedMode ? 'created' : 'to create'}
        </span>
        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/10 border border-blue-500/30 text-blue-300">
          {result.updated} {appliedMode ? 'updated' : 'to update'}
        </span>
        {result.errors.length > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-900/40 border border-red-700/40 text-red-400">
            {result.errors.length} row error{result.errors.length === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {result.errors.length > 0 && (
        <div className="mt-2 max-h-52 overflow-y-auto border border-space-700 rounded-md">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-space-900">
              <tr className="text-left text-gray-500">
                <th className="px-2 py-1.5 w-14 font-medium">Row</th>
                <th className="px-2 py-1.5 font-medium">Problem</th>
              </tr>
            </thead>
            <tbody>
              {result.errors.map((e, i) => (
                <tr key={i} className="border-t border-space-800">
                  <td className="px-2 py-1.5 font-mono text-gray-400">{e.row}</td>
                  <td className="px-2 py-1.5 text-red-300">{e.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Export */}
      <div className="bg-space-900 border border-space-700 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-1">
          <FileDown className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-white">Export</h3>
        </div>
        <p className="text-xs text-gray-500 mb-3">
          The CSV round-trips through the importer below (import_ref column matches rows back
          to existing entries). The ZIP is a complete off-site backup: database snapshot plus
          all attachments, labels and floor plans.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() =>
              download('csv', () => adminApi.downloadExportCsv(), 'CSV export failed')
            }
            disabled={busyDownload !== null}
            className={dlBtn}
          >
            {busyDownload === 'csv' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <FileSpreadsheet className="w-4 h-4" />
            )}
            Export CSV
          </button>
          <button
            onClick={() =>
              download('homebox', () => adminApi.downloadExportCsv('homebox'), 'HomeBox export failed')
            }
            disabled={busyDownload !== null}
            className={dlBtn}
            title="HB.* column subset — migration escape hatch to HomeBox"
          >
            {busyDownload === 'homebox' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <FileSpreadsheet className="w-4 h-4" />
            )}
            HomeBox CSV
          </button>
          <button
            onClick={() =>
              download('zip', () => adminApi.downloadExportZip(), 'Full export failed')
            }
            disabled={busyDownload !== null}
            className={dlBtn}
            title="Database snapshot + attachments + labels + floor plans"
          >
            {busyDownload === 'zip' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <FolderArchive className="w-4 h-4" />
            )}
            Full export (.zip)
          </button>
        </div>
      </div>

      {/* Import */}
      <div className="bg-space-900 border border-space-700 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-1">
          <Upload className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-white">Import CSV</h3>
        </div>
        <p className="text-xs text-gray-500 mb-3">
          Picking a file runs a dry-run first: rows with an import_ref matching an existing
          entry update it, everything else is created. Locations are matched level by level;
          missing intermediate places are auto-created as spaces. Row problems are listed —
          they skip that row only, the rest still imports.
        </p>

        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-gray-400 file:mr-3 file:px-3 file:py-2 file:rounded-lg file:border-0 file:bg-space-800 file:text-gray-300 file:text-sm file:cursor-pointer hover:file:bg-space-700 file:transition-colors"
        />

        {previewing && (
          <div className="flex items-center gap-2 text-gray-500 text-sm py-4 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" /> Validating (dry-run)…
          </div>
        )}

        {preview && !previewing && renderResult(preview, false)}
        {applied && renderResult(applied, true)}

        {preview && !previewing && (
          <div className="flex items-center justify-end gap-3 mt-3">
            {preview.errors.length > 0 && (
              <span className="flex items-center gap-1.5 text-xs text-amber-400">
                <AlertTriangle className="w-3.5 h-3.5" />
                Rows with errors are skipped
              </span>
            )}
            <button
              onClick={handleApply}
              disabled={applying}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm transition-colors"
            >
              {applying ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Upload className="w-4 h-4" />
              )}
              Apply import
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
