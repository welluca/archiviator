import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ImagePlus, Loader2 } from 'lucide-react';
import Modal from '../browse/Modal';
import { mapApi } from '../../api/map';
import { apiErrorDetail } from '../../api/entities';
import { useToast } from '../ui/Toast';
import { formatBytes } from '../../utils/format';
import type { FloorPlan } from '../../types';

interface ReplaceFloorImageModalProps {
  open: boolean;
  floor: FloorPlan | null;
  onClose: () => void;
  onReplaced: () => void;
}

/** PATCH the floor image. Regions are intentionally KEPT server-side — warn
 * that their pixel coordinates only line up if the new image matches. */
export function ReplaceFloorImageModal({ open, floor, onClose, onReplaced }: ReplaceFloorImageModalProps) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setFile(null);
      setBusy(false);
    }
  }, [open]);

  if (!open || !floor) return null;

  // A blank-canvas floor has no image yet — this modal then ADDS the first one
  // (no "keep coordinates" warning, since nothing is being replaced).
  const isAdd = floor.image_url === null;

  const replace = async () => {
    if (!file || busy) return;
    setBusy(true);
    try {
      await mapApi.replaceFloorImage(floor.id, file);
      toast.success(isAdd ? 'Background image added' : 'Floor image replaced');
      onReplaced();
      onClose();
    } catch (err) {
      toast.error(apiErrorDetail(err, `Failed to ${isAdd ? 'add' : 'replace'} the image`));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title={`${isAdd ? 'Add image' : 'Replace image'} — ${floor.entity.name}`}
      onClose={onClose}
    >
      {isAdd ? (
        <p className="text-xs text-gray-500 mb-4">
          Add a background scan or photo to trace over. The canvas keeps its current
          size, so anything you've already drawn stays exactly in place.
        </p>
      ) : (
        <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg bg-yellow-900/20 border border-yellow-700/40 mb-4">
          <AlertTriangle className="w-4 h-4 text-yellow-500 shrink-0 mt-0.5" />
          <p className="text-xs text-yellow-500/90">
            Rooms and furniture keep their canvas coordinates. If the new image is a
            different scan, crop or scale, the shapes may not line up — adjust them
            afterwards.
          </p>
        </div>
      )}

      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <button
        onClick={() => fileRef.current?.click()}
        className="w-full flex items-center justify-center gap-3 py-6 rounded-xl border-2 border-dashed border-space-700 hover:border-space-600 text-gray-500 hover:text-gray-400 transition-colors"
      >
        <ImagePlus className="w-5 h-5" />
        <span className="text-sm">{file ? `${file.name} · ${formatBytes(file.size)}` : 'Choose the new image…'}</span>
      </button>

      <div className="flex justify-end gap-2 mt-5">
        <button
          onClick={onClose}
          className="px-4 py-2 bg-space-800 hover:bg-space-700 text-gray-300 rounded-lg text-sm border border-space-600 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={replace}
          disabled={!file || busy}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm transition-colors"
        >
          {busy && <Loader2 className="w-4 h-4 animate-spin" />}
          {isAdd ? 'Add image' : 'Replace image'}
        </button>
      </div>
    </Modal>
  );
}

export default ReplaceFloorImageModal;
