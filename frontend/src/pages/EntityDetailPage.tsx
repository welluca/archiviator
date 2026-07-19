import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AxiosError } from 'axios';
import {
  Camera,
  ChevronRight,
  Copy,
  ExternalLink,
  FileText,
  FileUp,
  Home,
  ImagePlus,
  Loader2,
  MoreVertical,
  Trash2,
} from 'lucide-react';
import { entitiesApi, apiErrorDetail } from '../api/entities';
import { attachmentsApi } from '../api/attachments';
import { duplicateEntity } from '../api/metadata';
import { useToast } from '../components/ui/Toast';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import EntityIcon from '../components/browse/EntityIcon';
import AssetTagSection from '../components/entity/AssetTagSection';
import PhotoCard from '../components/entity/PhotoCard';
import Lightbox from '../components/entity/Lightbox';
import TagsEditor from '../components/entity/TagsEditor';
import CategoryFieldsSection from '../components/entity/CategoryFieldsSection';
import { formatBytes } from '../utils/format';
import type { Attachment, Entity, PathSegment } from '../types';
import { KIND_META } from '../types';

const isUploadable = (f: File): boolean =>
  f.type.startsWith('image/') ||
  f.type === 'application/pdf' ||
  /\.(heic|heif)$/i.test(f.name); // HEIC often has no mime type on Windows

export default function EntityDetailPage() {
  const { id } = useParams();
  const entityId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();

  const [entity, setEntity] = useState<Entity | null>(null);
  const [path, setPath] = useState<PathSegment[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [loading, setLoading] = useState(true);

  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Attachment | null>(null);
  const [uploading, setUploading] = useState<{ done: number; total: number } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [kebabOpen, setKebabOpen] = useState(false);
  const [duplicating, setDuplicating] = useState(false);

  const photoInputRef = useRef<HTMLInputElement>(null);
  const docInputRef = useRef<HTMLInputElement>(null);
  const kebabRef = useRef<HTMLDivElement>(null);

  // Close the header kebab on outside click.
  useEffect(() => {
    if (!kebabOpen) return;
    const close = (ev: MouseEvent) => {
      if (kebabRef.current && !kebabRef.current.contains(ev.target as Node)) {
        setKebabOpen(false);
      }
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [kebabOpen]);

  // ── Data loading ──────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    // Strict integer ids only — Number('1.5') and Number('1e3') are finite but
    // the backend answers 422 for them, which is not the 404 redirect branch.
    if (!/^\d+$/.test(id ?? '')) {
      navigate('/browse', { replace: true });
      return;
    }
    try {
      const [entityData, pathData, attachmentData] = await Promise.all([
        entitiesApi.get(entityId),
        entitiesApi.getPath(entityId),
        attachmentsApi.list(entityId),
      ]);
      setEntity(entityData);
      setPath(pathData);
      setAttachments(attachmentData);
    } catch (err) {
      const code = err instanceof AxiosError ? err.response?.status : undefined;
      if (code === 404 || code === 422) {
        toast.warning('This entry no longer exists');
        navigate('/browse', { replace: true });
      } else {
        toast.error(apiErrorDetail(err, 'Failed to load entry'));
      }
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId, id]);

  // Without this, a file dropped outside the drop zone makes the browser
  // navigate away from the SPA to the local file.
  useEffect(() => {
    const prevent = (ev: DragEvent) => ev.preventDefault();
    window.addEventListener('dragover', prevent);
    window.addEventListener('drop', prevent);
    return () => {
      window.removeEventListener('dragover', prevent);
      window.removeEventListener('drop', prevent);
    };
  }, []);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  const photos = attachments.filter((a) => a.type === 'photo');
  const documents = attachments.filter((a) => a.type === 'document');

  // ── Uploads (sequential, with n-of-m progress) ────────────────────────────
  const uploadFiles = async (files: File[]) => {
    if (files.length === 0 || uploading) return;
    setUploading({ done: 0, total: files.length });
    let ok = 0;
    for (let i = 0; i < files.length; i++) {
      try {
        await attachmentsApi.upload(entityId, files[i]);
        ok++;
      } catch (err) {
        toast.error(apiErrorDetail(err, `Failed to upload “${files[i].name}”`));
      }
      setUploading({ done: i + 1, total: files.length });
    }
    setUploading(null);
    if (ok > 0) {
      toast.success(`Uploaded ${ok} file${ok === 1 ? '' : 's'}`);
      await load();
    }
  };

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ''; // allow re-picking the same file
    uploadFiles(files);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const all = Array.from(e.dataTransfer.files);
    const files = all.filter(isUploadable);
    const skipped = all.length - files.length;
    if (skipped > 0) {
      toast.warning(`Skipped ${skipped} unsupported file${skipped === 1 ? '' : 's'} (photos and PDFs only)`);
    }
    uploadFiles(files);
  };

  // ── Attachment actions ────────────────────────────────────────────────────
  const handleSetCover = async (att: Attachment) => {
    try {
      const updated = await attachmentsApi.setCover(entityId, att.id);
      setEntity(updated);
      setAttachments((prev) => prev.map((a) => ({ ...a, is_cover: a.id === att.id })));
      toast.success('Cover updated');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to set cover'));
    }
  };

  const handleSaveTitle = async (att: Attachment, title: string | null) => {
    try {
      const updated = await attachmentsApi.patchMeta(att.id, { title });
      setAttachments((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
      toast.success('Title saved');
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to save title'));
      throw err; // keep the editor open
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await attachmentsApi.remove(deleteTarget.id);
      toast.success('Attachment deleted');
      setDeleteTarget(null);
      setLightboxIndex(null);
      await load(); // cover may have cleared server-side
    } catch (err) {
      setDeleteTarget(null);
      toast.error(apiErrorDetail(err, 'Failed to delete attachment'));
    }
  };

  // ── Duplicate (kebab) ─────────────────────────────────────────────────────
  const handleDuplicate = async () => {
    if (duplicating) return;
    setKebabOpen(false);
    setDuplicating(true);
    try {
      const copy = await duplicateEntity(entityId);
      toast.success(`Duplicated as “${copy.name}”`);
      navigate(`/entity/${copy.id}`);
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to duplicate'));
    } finally {
      setDuplicating(false);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-sm py-16 justify-center">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading…
      </div>
    );
  }
  if (!entity) return null;

  const uploadBusy = uploading !== null;

  return (
    <div className="max-w-5xl mx-auto">
      {/* Hidden pickers. capture="environment" opens the iPhone rear camera directly. */}
      <input
        ref={photoInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        multiple
        hidden
        onChange={onFileInput}
      />
      <input
        ref={docInputRef}
        type="file"
        accept="application/pdf"
        multiple
        hidden
        onChange={onFileInput}
      />

      {/* Breadcrumb — each segment jumps back to that selection in Browse */}
      <nav className="flex items-center gap-1 text-sm overflow-x-auto whitespace-nowrap py-1 mb-3">
        <button
          onClick={() => navigate('/browse')}
          className="flex items-center gap-1.5 px-2 py-1 rounded-md text-gray-400 hover:text-white hover:bg-space-800 transition-colors"
        >
          <Home className="w-3.5 h-3.5" />
          All spaces
        </button>
        {path.map((seg, i) => (
          <span key={seg.id} className="flex items-center gap-1">
            <ChevronRight className="w-3.5 h-3.5 text-gray-600 shrink-0" />
            <button
              onClick={() => navigate(`/browse?sel=${seg.id}`)}
              className={`px-2 py-1 rounded-md transition-colors ${
                i === path.length - 1
                  ? 'text-white font-medium hover:bg-space-800'
                  : 'text-gray-400 hover:text-white hover:bg-space-800'
              }`}
            >
              {seg.name}
            </button>
          </span>
        ))}
      </nav>

      {/* Header */}
      <div className="flex flex-wrap items-center gap-2.5 mb-1">
        <EntityIcon entity={entity} className="w-6 h-6" />
        <h1 className="text-xl font-bold text-white truncate">{entity.name}</h1>
        <span className="text-xs text-gray-500">{KIND_META[entity.kind].label}</span>
        {entity.subtype && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-space-800 border border-space-700 text-gray-400">
            {entity.subtype}
          </span>
        )}
        {entity.archived && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-900/40 border border-yellow-700/40 text-yellow-500">
            archived
          </span>
        )}

        <div className="flex-1" />

        {/* Upload buttons */}
        <div className="flex items-center gap-2">
          {uploadBusy && (
            <span className="flex items-center gap-1.5 text-xs text-gray-400">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Uploading {uploading.done} of {uploading.total}…
            </span>
          )}
          <button
            onClick={() => photoInputRef.current?.click()}
            disabled={uploadBusy}
            className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors"
          >
            <Camera className="w-4 h-4" />
            <span className="hidden sm:inline">Add photo</span>
          </button>
          <button
            onClick={() => docInputRef.current?.click()}
            disabled={uploadBusy}
            className="flex items-center gap-1.5 px-3 py-2 bg-space-800 hover:bg-space-700 disabled:opacity-50 disabled:cursor-not-allowed text-gray-300 border border-space-600 rounded-lg text-sm transition-colors"
          >
            <FileUp className="w-4 h-4" />
            <span className="hidden sm:inline">Add document</span>
          </button>

          {/* Header kebab */}
          <div className="relative shrink-0" ref={kebabRef}>
            <button
              onClick={() => setKebabOpen((v) => !v)}
              aria-label="More actions"
              className={`p-2 rounded-lg text-gray-400 hover:text-white hover:bg-space-800 border border-space-700 transition-colors ${
                kebabOpen ? 'text-white bg-space-800' : ''
              }`}
            >
              <MoreVertical className="w-4 h-4" />
            </button>
            {kebabOpen && (
              <div className="absolute right-0 top-full mt-1 z-30 w-44 bg-space-900 border border-space-700 rounded-lg shadow-lg shadow-black/40 py-1 overflow-hidden">
                <button
                  onClick={handleDuplicate}
                  disabled={duplicating}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left text-gray-300 hover:bg-space-800 hover:text-white disabled:opacity-50 transition-colors"
                >
                  {duplicating ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                  Duplicate
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* M5: asset tag (QR sticker) block */}
      <AssetTagSection entity={entity} onEntityUpdate={setEntity} />

      {/* Read-only description / notes (editing lives in the Browse rename modal) */}
      {entity.description && (
        <p className="text-sm text-gray-500 mb-2">{entity.description}</p>
      )}
      {entity.notes && (
        <div className="mb-3 px-3 py-2 rounded-lg bg-space-900 border border-space-700">
          <p className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">Notes</p>
          <p className="text-sm text-gray-400 whitespace-pre-wrap">{entity.notes}</p>
        </div>
      )}

      {/* M4: tags editor */}
      <div className="mt-2 mb-4">
        <TagsEditor entity={entity} onEntityUpdate={setEntity} />
      </div>

      {/* M4: category + custom fields */}
      <CategoryFieldsSection entity={entity} onEntityUpdate={setEntity} />

      {/* Photo gallery */}
      <section className="mt-4">
        {photos.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center border border-dashed border-space-700 rounded-xl">
            <button
              onClick={() => photoInputRef.current?.click()}
              disabled={uploadBusy}
              className="flex flex-col items-center gap-3 group disabled:opacity-50"
            >
              <span className="w-16 h-16 rounded-full bg-blue-600 group-hover:bg-blue-500 flex items-center justify-center transition-colors">
                <Camera className="w-8 h-8 text-white" />
              </span>
              <span className="text-white font-semibold">Add the first photo</span>
              <span className="text-gray-500 text-sm">
                or drop photos / PDFs anywhere below
              </span>
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
            {photos.map((photo, i) => (
              <PhotoCard
                key={photo.id}
                photo={photo}
                isCover={entity.cover_attachment_id === photo.id}
                onOpen={() => setLightboxIndex(i)}
                onSetCover={() => handleSetCover(photo)}
                onSaveTitle={(title) => handleSaveTitle(photo, title)}
                onDelete={() => setDeleteTarget(photo)}
              />
            ))}
          </div>
        )}

        {/* Fat drop zone at the end of the gallery */}
        <div
          onClick={() => !uploadBusy && photoInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={`mt-3 flex items-center justify-center gap-3 py-8 rounded-xl border-2 border-dashed cursor-pointer transition-colors ${
            dragOver
              ? 'border-blue-500 bg-blue-500/10 text-blue-400'
              : 'border-space-700 text-gray-500 hover:border-space-600 hover:text-gray-400'
          }`}
        >
          <ImagePlus className="w-5 h-5" />
          <span className="text-sm">
            {dragOver ? 'Drop to upload' : 'Drop photos or PDFs here — or tap to add photos'}
          </span>
        </div>
      </section>

      {/* Documents */}
      {documents.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold text-white mb-2">Documents</h2>
          <div className="space-y-1">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-transparent hover:border-space-700 hover:bg-space-900 transition-colors"
              >
                <FileText className="w-5 h-5 text-red-400 shrink-0" />
                <span className="flex-1 min-w-0 text-sm text-white truncate">
                  {doc.title || 'PDF document'}
                </span>
                <span className="text-xs text-gray-500 shrink-0">
                  {formatBytes(doc.byte_size)}
                </span>
                <a
                  href={doc.urls.original}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Open PDF"
                  className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-400 hover:text-white hover:bg-space-700 transition-colors shrink-0"
                >
                  <ExternalLink className="w-3.5 h-3.5" /> open
                </a>
                <button
                  onClick={() => setDeleteTarget(doc)}
                  title="Delete document"
                  className="p-1.5 rounded-md text-gray-500 hover:text-red-400 hover:bg-space-700 transition-colors shrink-0"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Lightbox */}
      {lightboxIndex !== null && (
        <Lightbox
          photos={photos}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onNavigate={setLightboxIndex}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title={deleteTarget?.type === 'document' ? 'Delete document' : 'Delete photo'}
        message={`Permanently delete “${
          deleteTarget?.title || (deleteTarget?.type === 'document' ? 'PDF document' : 'this photo')
        }”? This cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
