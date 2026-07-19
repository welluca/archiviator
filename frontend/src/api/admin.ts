import apiClient from './client';
import type { BackupInfo, ImportResult } from '../types';

/** Bearer-authed file download: axios blob -> object URL -> a.click().
 * Same pattern as the labels PDF download. */
async function downloadBlob(path: string, filename: string): Promise<void> {
  const { data } = await apiClient.get<Blob>(path, { responseType: 'blob' });
  const url = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Immediate revocation has historically aborted in-flight downloads in
  // some browsers; defer it well past the click.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

const stamp = (): string => new Date().toISOString().slice(0, 10);

export const adminApi = {
  /** Drop and refill the FTS index from live rows (safety net). */
  async rebuildSearch(): Promise<{ indexed: number }> {
    const { data } = await apiClient.post<{ indexed: number }>('/admin/rebuild-search');
    return data;
  },

  /** Full-catalog CSV in our dialect (or the HomeBox HB.* subset). */
  async downloadExportCsv(dialect?: 'homebox'): Promise<void> {
    const suffix = dialect === 'homebox' ? '?dialect=homebox' : '';
    await downloadBlob(
      `/admin/export.csv${suffix}`,
      dialect === 'homebox'
        ? `archiviator-homebox-${stamp()}.csv`
        : `archiviator-export-${stamp()}.csv`
    );
  },

  /** Streamed ZIP: fresh db snapshot + attachments/labels/floorplans. */
  async downloadExportZip(): Promise<void> {
    await downloadBlob('/admin/export.zip', `archiviator-full-${stamp()}.zip`);
  },

  /** Upload a CSV; dry_run validates and reports without committing. */
  async importCsv(file: File, dryRun: boolean): Promise<ImportResult> {
    const form = new FormData();
    form.append('file', file);
    // Axios drops the JSON default Content-Type for FormData so the browser
    // sets the multipart boundary itself.
    const { data } = await apiClient.post<ImportResult>('/admin/import-csv', form, {
      params: { dry_run: dryRun },
    });
    return data;
  },

  async backupNow(): Promise<{ file: string; bytes: number }> {
    const { data } = await apiClient.post<{ file: string; bytes: number }>(
      '/admin/backup-now'
    );
    return data;
  },

  /** Snapshot files on disk, newest first. */
  async listBackups(): Promise<BackupInfo[]> {
    const { data } = await apiClient.get<BackupInfo[]>('/admin/backups');
    return data;
  },
};
