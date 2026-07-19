import { useEffect, useRef, useState } from 'react';
import { ImagePlus, LayoutGrid, Loader2 } from 'lucide-react';
import Modal from '../browse/Modal';
import EntityIcon from '../browse/EntityIcon';
import { mapApi } from '../../api/map';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { formatBytes } from '../../utils/format';
import type { Entity, FloorPlan } from '../../types';

interface AddFloorModalProps {
  open: boolean;
  roots: Entity[];
  childrenOf: Map<number, Entity[]>;
  /** Space entity ids that already have a plan (one plan per entity — disabled). */
  existingEntityIds: Set<number>;
  onClose: () => void;
  onCreated: (floor: FloorPlan) => void;
}

/** Add-floor flow: pick the SPACE the plan belongs to (spaces only — same
 * tree pattern as LocationPickerModal) + upload its image. */
export function AddFloorModal({
  open,
  roots,
  childrenOf,
  existingEntityIds,
  onClose,
  onCreated,
}: AddFloorModalProps) {
  const toast = useToast();
  const [entityId, setEntityId] = useState<number | null>(null);
  const [mode, setMode] = useState<'blank' | 'image'>('blank');
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Reset on open; revoke the preview URL on change/unmount.
  useEffect(() => {
    if (open) {
      setEntityId(null);
      setMode('blank');
      setFile(null);
      setPreviewUrl(null);
      setUploading(false);
    }
  }, [open]);
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  if (!open) return null;

  const pickFile = (f: File | null) => {
    setFile(f);
    setPreviewUrl(f ? URL.createObjectURL(f) : null);
  };

  const canSubmit = entityId !== null && (mode === 'blank' || file !== null) && !uploading;

  const submit = async () => {
    if (!canSubmit || entityId === null) return;
    setUploading(true);
    try {
      const floor = await mapApi.createFloor(entityId, mode === 'blank' ? null : file);
      toast.success(`Floor plan added for “${floor.entity.name}”`);
      onCreated(floor);
      onClose();
    } catch (err) {
      toast.error(apiErrorDetail(err, 'Failed to create the floor plan'));
    } finally {
      setUploading(false);
    }
  };

  const renderNode = (node: Entity): React.ReactNode => {
    if (node.kind !== 'space') return null;
    const children = childrenOf.get(node.id) ?? [];
    const taken = existingEntityIds.has(node.id);
    return (
      <div key={node.id}>
        <button
          type="button"
          disabled={taken}
          onClick={() => setEntityId(node.id)}
          style={{ paddingLeft: `${node.depth * 14 + 8}px` }}
          className={`w-full flex items-center gap-2 pr-2 py-1.5 rounded-md text-sm text-left transition-colors ${
            entityId === node.id
              ? 'bg-blue-500/20 text-blue-300'
              : taken
                ? 'text-gray-600 cursor-not-allowed'
                : 'text-gray-300 hover:bg-space-800 hover:text-white'
          }`}
        >
          <EntityIcon entity={node} />
          <span className="truncate flex-1">{node.name}</span>
          {taken && <span className="text-[10px] text-gray-600 shrink-0">has a plan</span>}
        </button>
        {children.map(renderNode)}
      </div>
    );
  };

  return (
    <Modal open={open} title="Add floor" onClose={onClose} maxWidth="max-w-lg">
      <p className="text-xs text-gray-500 mb-3">
        Pick the space this plan shows (a floor, the whole house, the garage…), then
        lay it out graphically on a blank canvas — or upload a scan, sketch or photo
        to trace over.
      </p>

      <p className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Space</p>
      <div className="border border-space-700 rounded-lg bg-space-950 max-h-52 overflow-y-auto p-1.5 mb-4">
        {roots.filter((r) => r.kind === 'space').length === 0 ? (
          <p className="text-xs text-gray-500 p-2">No spaces yet — create one in Browse first.</p>
        ) : (
          roots.map(renderNode)
        )}
      </div>

      <p className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Background</p>
      <div className="grid grid-cols-2 gap-2 mb-4">
        <button
          type="button"
          onClick={() => setMode('blank')}
          className={`flex items-center gap-2 px-3 py-2.5 rounded-lg border text-sm transition-colors ${
            mode === 'blank'
              ? 'bg-blue-500/20 text-blue-300 border-blue-500/40'
              : 'text-gray-400 hover:text-white hover:bg-space-800 border-space-700'
          }`}
        >
          <LayoutGrid className="w-4 h-4 shrink-0" />
          Blank canvas
        </button>
        <button
          type="button"
          onClick={() => setMode('image')}
          className={`flex items-center gap-2 px-3 py-2.5 rounded-lg border text-sm transition-colors ${
            mode === 'image'
              ? 'bg-blue-500/20 text-blue-300 border-blue-500/40'
              : 'text-gray-400 hover:text-white hover:bg-space-800 border-space-700'
          }`}
        >
          <ImagePlus className="w-4 h-4 shrink-0" />
          Upload image
        </button>
      </div>

      {mode === 'image' && (
        <>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
          />
          <button
            onClick={() => fileRef.current?.click()}
            className={`w-full flex items-center justify-center gap-3 rounded-xl border-2 border-dashed transition-colors overflow-hidden ${
              previewUrl
                ? 'border-space-600 p-0'
                : 'border-space-700 hover:border-space-600 text-gray-500 hover:text-gray-400 py-8'
            }`}
          >
            {previewUrl ? (
              <img src={previewUrl} alt="Floor plan preview" className="max-h-48 w-full object-contain bg-space-950" />
            ) : (
              <>
                <ImagePlus className="w-5 h-5" />
                <span className="text-sm">Choose an image…</span>
              </>
            )}
          </button>
          {file && (
            <p className="text-xs text-gray-500 mt-1.5 truncate">
              {file.name} · {formatBytes(file.size)}
            </p>
          )}
        </>
      )}
      {mode === 'blank' && (
        <p className="text-xs text-gray-500">
          You'll get an empty grid to draw rooms and place furniture on. You can add a
          background image later from the floor toolbar.
        </p>
      )}

      <div className="flex justify-end gap-2 mt-5">
        <button
          onClick={onClose}
          className="px-4 py-2 bg-space-800 hover:bg-space-700 text-gray-300 rounded-lg text-sm border border-space-600 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={!canSubmit}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors"
        >
          {uploading && <Loader2 className="w-4 h-4 animate-spin" />}
          {uploading ? 'Creating…' : 'Add floor'}
        </button>
      </div>
    </Modal>
  );
}

export default AddFloorModal;
