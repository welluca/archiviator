import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Cloud,
  File,
  FileText,
  Folder,
  Image,
  Loader2,
} from 'lucide-react';
import Modal from '../browse/Modal';
import { driveApi } from '../../api/drive';
import { apiErrorDetail } from '../../api/entities';
import { formatBytes } from '../../utils/format';
import type { DriveBrowseFile, DriveBrowseFolder } from '../../types';

const MY_DRIVE = { id: 'root', name: 'My Drive' };

interface Crumb {
  id: string;
  name: string;
}

interface DriveBrowseModalProps {
  open: boolean;
  /** 'folder' = pick the current folder (settings); 'file' = pick a file. */
  mode: 'folder' | 'file';
  title?: string;
  /** Starting folder (e.g. the scans folder). Defaults to My Drive root. */
  root?: Crumb;
  onClose: () => void;
  /** folder mode: the currently open folder was chosen. */
  onPickFolder?: (folder: DriveBrowseFolder) => void;
  /** file mode: a file was chosen. Async — the row shows a spinner until done. */
  onPickFile?: (file: DriveBrowseFile) => Promise<void> | void;
}

const fileIcon = (mime: string | null) => {
  if (!mime) return File;
  if (mime.startsWith('image/')) return Image;
  if (mime === 'application/pdf') return FileText;
  return File;
};

/** Google Drive folder/file browser with breadcrumbs. Adapted from the proven
 * gdriveexchanger GDriveFolderPicker UX — crumbs are a plain navigation stack,
 * and a rooted browse (scans folder) can still jump up to My Drive. */
export default function DriveBrowseModal({
  open,
  mode,
  title,
  root,
  onClose,
  onPickFolder,
  onPickFile,
}: DriveBrowseModalProps) {
  const [crumbs, setCrumbs] = useState<Crumb[]>([root ?? MY_DRIVE]);
  const [folders, setFolders] = useState<DriveBrowseFolder[]>([]);
  const [files, setFiles] = useState<DriveBrowseFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** File id currently being handed to onPickFile (spinner + lock). */
  const [pickingId, setPickingId] = useState<string | null>(null);

  const current = crumbs[crumbs.length - 1];

  const load = useCallback(async (folderId: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await driveApi.browse(folderId);
      setFolders(res.folders);
      setFiles(res.files);
    } catch (err) {
      setFolders([]);
      setFiles([]);
      setError(apiErrorDetail(err, 'Failed to browse Google Drive'));
    } finally {
      setLoading(false);
    }
  }, []);

  // Reset to the root and load it on every open.
  useEffect(() => {
    if (!open) return;
    const start = root ?? MY_DRIVE;
    setCrumbs([start]);
    setPickingId(null);
    load(start.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, root?.id]);

  if (!open) return null;

  const navigateTo = (crumb: Crumb, stack: Crumb[]) => {
    if (pickingId) return;
    setCrumbs(stack);
    load(crumb.id);
  };

  const enterFolder = (f: DriveBrowseFolder) =>
    navigateTo(f, [...crumbs, { id: f.id, name: f.name }]);

  const pickFile = async (f: DriveBrowseFile) => {
    if (!onPickFile || pickingId) return;
    setPickingId(f.id);
    try {
      await onPickFile(f);
    } finally {
      setPickingId(null);
    }
  };

  // A browse rooted below My Drive still offers the jump up to the real root.
  const rootedBelowMyDrive = crumbs[0].id !== 'root';

  return (
    <Modal
      open={open}
      title={title ?? (mode === 'folder' ? 'Choose a Drive folder' : 'Attach from Google Drive')}
      onClose={onClose}
      maxWidth="max-w-xl"
    >
      {/* Breadcrumbs */}
      <div className="flex items-center gap-0.5 text-sm overflow-x-auto whitespace-nowrap pb-2 mb-2 border-b border-space-800">
        {rootedBelowMyDrive && (
          <>
            <button
              type="button"
              onClick={() => navigateTo(MY_DRIVE, [MY_DRIVE])}
              className="flex items-center gap-1.5 px-2 py-1 rounded-md text-gray-400 hover:text-white hover:bg-space-800 transition-colors shrink-0"
              title="Jump up to My Drive"
            >
              <Cloud className="w-3.5 h-3.5" />
              My Drive
            </button>
            <ChevronRight className="w-3.5 h-3.5 text-gray-600 shrink-0" />
          </>
        )}
        {crumbs.map((c, i) => (
          <span key={`${c.id}-${i}`} className="flex items-center gap-0.5 shrink-0">
            {i > 0 && <ChevronRight className="w-3.5 h-3.5 text-gray-600 shrink-0" />}
            <button
              type="button"
              onClick={() => navigateTo(c, crumbs.slice(0, i + 1))}
              className={`px-2 py-1 rounded-md transition-colors max-w-[12rem] truncate ${
                i === crumbs.length - 1
                  ? 'text-white font-medium'
                  : 'text-gray-400 hover:text-white hover:bg-space-800'
              }`}
            >
              {c.name}
            </button>
          </span>
        ))}
      </div>

      {/* Listing */}
      <div className="border border-space-700 rounded-lg bg-space-950 h-72 overflow-y-auto p-1.5">
        {loading ? (
          <div className="flex items-center gap-2 text-gray-500 text-sm py-10 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 text-yellow-400 text-sm px-3 py-6">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            {error}
          </div>
        ) : folders.length === 0 && (mode === 'folder' || files.length === 0) ? (
          <p className="text-gray-500 text-sm text-center py-10">
            {mode === 'folder' ? 'No subfolders' : 'Nothing in this folder'}
          </p>
        ) : (
          <div className="space-y-0.5">
            {folders.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => enterFolder(f)}
                disabled={pickingId !== null}
                className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm text-left text-gray-300 hover:bg-space-800 hover:text-white disabled:opacity-50 transition-colors group"
              >
                <Folder className="w-4 h-4 text-blue-400 shrink-0" />
                <span className="flex-1 min-w-0 truncate">{f.name}</span>
                <ChevronRight className="w-4 h-4 text-gray-600 group-hover:text-gray-400 shrink-0" />
              </button>
            ))}
            {mode === 'file' &&
              files.map((f) => {
                const Icon = fileIcon(f.mime);
                const busy = pickingId === f.id;
                return (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => pickFile(f)}
                    disabled={pickingId !== null}
                    className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm text-left text-gray-300 hover:bg-space-800 hover:text-white disabled:opacity-50 transition-colors"
                  >
                    {busy ? (
                      <Loader2 className="w-4 h-4 animate-spin text-blue-400 shrink-0" />
                    ) : (
                      <Icon className="w-4 h-4 text-gray-500 shrink-0" />
                    )}
                    <span className="flex-1 min-w-0 truncate">{f.name}</span>
                    {f.size !== null && (
                      <span className="text-xs text-gray-600 shrink-0">
                        {formatBytes(f.size)}
                      </span>
                    )}
                    {f.modified_time && (
                      <span className="text-xs text-gray-600 shrink-0 hidden sm:inline">
                        {new Date(f.modified_time).toLocaleDateString()}
                      </span>
                    )}
                  </button>
                );
              })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 mt-3">
        <p className="text-xs text-gray-500 truncate min-w-0">
          {mode === 'folder'
            ? `Selecting: ${current.name}`
            : 'Click a file to attach it as a Drive link.'}
        </p>
        <div className="flex gap-2 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 text-sm text-gray-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          {mode === 'folder' && (
            <button
              type="button"
              onClick={() => onPickFolder?.({ id: current.id, name: current.name })}
              className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors"
            >
              <Check className="w-4 h-4" /> Use this folder
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}
