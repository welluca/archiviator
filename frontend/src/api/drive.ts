import apiClient from './client';
import type {
  Attachment,
  DriveBrowseResult,
  DriveStatus,
  ScanInboxRow,
  ScanInboxStatus,
} from '../types';

export interface DriveConfigPayload {
  /** Absolute path to an existing client_secret_*.json ('installed' app). */
  credentials_path?: string;
  scans_folder_id?: string | null;
  scans_folder_name?: string | null;
  /** 5–1440 minutes. */
  poll_interval_min?: number;
  backup_upload_enabled?: boolean;
}

export interface ScanNowResult {
  new: number;
  seen: number;
}

export interface ReconcileResult {
  ok: number;
  missing: number;
  changed: number;
}

// ── Module-level status cache ────────────────────────────────────────────────
// EntityDetailPage only needs "is Drive connected + where is the scans folder"
// to decide whether to offer 'Attach from Drive' — one fetch per minute is
// plenty and avoids a status request on every entity navigation.

let cachedStatus: DriveStatus | null = null;
let cachedAt = 0;

const rememberStatus = (s: DriveStatus): DriveStatus => {
  cachedStatus = s;
  cachedAt = Date.now();
  return s;
};

/** Cached /drive/status (60s TTL). Returns null when it has never succeeded. */
export async function getCachedDriveStatus(maxAgeMs = 60_000): Promise<DriveStatus | null> {
  if (cachedStatus && Date.now() - cachedAt < maxAgeMs) return cachedStatus;
  try {
    return rememberStatus(
      (await apiClient.get<DriveStatus>('/drive/status')).data
    );
  } catch {
    return cachedStatus; // stale beats nothing; null when never fetched
  }
}

// ── API wrappers ─────────────────────────────────────────────────────────────

export const driveApi = {
  async status(): Promise<DriveStatus> {
    const { data } = await apiClient.get<DriveStatus>('/drive/status');
    return rememberStatus(data);
  },

  /** Partial update; returns the fresh status. 409 on a bad credentials path. */
  async updateConfig(payload: DriveConfigPayload): Promise<DriveStatus> {
    const { data } = await apiClient.put<DriveStatus>('/drive/config', payload);
    return rememberStatus(data);
  },

  /** Starts the OAuth InstalledAppFlow in a server worker thread (202) — a
   * browser window opens ON THE SERVER PC. Poll status() until connected. */
  async connect(): Promise<{ status: string; message?: string }> {
    const { data } = await apiClient.post<{ status: string; message?: string }>(
      '/drive/connect'
    );
    return data;
  },

  /** Deletes token.json and clears the account email. */
  async disconnect(): Promise<void> {
    await apiClient.post('/drive/disconnect');
    if (cachedStatus) {
      cachedStatus = { ...cachedStatus, connected: false, email: null };
    }
  },

  /** One level of a Drive folder ('root' = My Drive). */
  async browse(folderId = 'root'): Promise<DriveBrowseResult> {
    const { data } = await apiClient.get<DriveBrowseResult>('/drive/browse', {
      params: { folder_id: folderId },
    });
    return data;
  },

  /** Run the scans-folder poller once. */
  async scanNow(): Promise<ScanNowResult> {
    const { data } = await apiClient.post<ScanNowResult>('/drive/scan-now');
    return data;
  },

  async inbox(status: ScanInboxStatus): Promise<ScanInboxRow[]> {
    const { data } = await apiClient.get<ScanInboxRow[]>('/drive/inbox', {
      params: { status },
    });
    return data;
  },

  async ignoreInboxRow(id: number): Promise<ScanInboxRow> {
    const { data } = await apiClient.post<ScanInboxRow>(`/drive/inbox/${id}/ignore`);
    return data;
  },

  /** Attach an inbox scan to an entity as a drive_link. 409 if already attached. */
  async attachInboxRow(
    id: number,
    entityId: number,
    title?: string
  ): Promise<{ row: ScanInboxRow; attachment: Attachment }> {
    const payload: { entity_id: number; title?: string } = { entity_id: entityId };
    if (title !== undefined) payload.title = title;
    const { data } = await apiClient.post<{ row: ScanInboxRow; attachment: Attachment }>(
      `/drive/inbox/${id}/attach`,
      payload
    );
    return data;
  },

  /** Attach ANY browsed Drive file to an entity. 409 on a duplicate file_id
   * on the same entity. */
  async attachDriveFile(
    entityId: number,
    fileId: string,
    title?: string
  ): Promise<Attachment> {
    const payload: { file_id: string; title?: string } = { file_id: fileId };
    if (title !== undefined) payload.title = title;
    const { data } = await apiClient.post<Attachment>(
      `/entities/${entityId}/attachments/drive`,
      payload
    );
    return data;
  },

  /** Ensure the server-side thumbnail cache for a Drive file.
   * url is null when Drive offers no thumbnail for the file. */
  async ensureThumbnail(fileId: string): Promise<{ url: string | null }> {
    const { data } = await apiClient.post<{ url: string | null }>(
      `/drive/thumbnail/${fileId}`
    );
    return data;
  },

  /** Re-check every attached Drive file against Drive (also runs nightly). */
  async reconcile(): Promise<ReconcileResult> {
    const { data } = await apiClient.post<ReconcileResult>('/drive/reconcile');
    return data;
  },

  /** Snapshot the db and push it to the 'Archiviator Backups' Drive folder now. */
  async backupNow(): Promise<{ file: string; drive_file_id: string }> {
    const { data } = await apiClient.post<{ file: string; drive_file_id: string }>(
      '/drive/backup-now'
    );
    return data;
  },
};
