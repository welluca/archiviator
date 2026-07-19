import { useCallback, useEffect } from 'react';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import type { Attachment } from '../../types';
import { formatBytes } from '../../utils/format';

interface LightboxProps {
  photos: Attachment[];
  index: number;
  onClose: () => void;
  onNavigate: (index: number) => void;
}

/** Fullscreen overlay showing the 1600px display image with prev/next,
 * Escape/backdrop close and a caption row. */
export function Lightbox({ photos, index, onClose, onNavigate }: LightboxProps) {
  const photo = photos[index];
  const hasPrev = index > 0;
  const hasNext = index < photos.length - 1;

  const prev = useCallback(() => {
    if (index > 0) onNavigate(index - 1);
  }, [index, onNavigate]);

  const next = useCallback(() => {
    if (index < photos.length - 1) onNavigate(index + 1);
  }, [index, photos.length, onNavigate]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowLeft') prev();
      else if (e.key === 'ArrowRight') next();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, prev, next]);

  if (!photo) return null;

  const navBtn =
    'absolute top-1/2 -translate-y-1/2 p-2 rounded-full bg-black/50 text-gray-300 hover:text-white hover:bg-black/70 transition-colors disabled:opacity-30 disabled:cursor-not-allowed';

  return (
    <div
      className="fixed inset-0 z-[90] bg-black/90 flex flex-col"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <button
        onClick={onClose}
        aria-label="Close"
        className="absolute top-3 right-3 z-10 p-2 rounded-full bg-black/50 text-gray-300 hover:text-white hover:bg-black/70 transition-colors"
      >
        <X className="w-5 h-5" />
      </button>

      <div
        className="flex-1 min-h-0 flex items-center justify-center p-4 sm:p-10"
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        <img
          key={photo.id}
          src={photo.urls.display ?? photo.urls.original}
          alt={photo.title ?? 'Photo'}
          className="max-w-full max-h-full object-contain rounded-lg shadow-2xl shadow-black"
        />
      </div>

      {photos.length > 1 && (
        <>
          <button onClick={prev} disabled={!hasPrev} aria-label="Previous photo" className={`${navBtn} left-3`}>
            <ChevronLeft className="w-6 h-6" />
          </button>
          <button onClick={next} disabled={!hasNext} aria-label="Next photo" className={`${navBtn} right-3`}>
            <ChevronRight className="w-6 h-6" />
          </button>
        </>
      )}

      {/* Caption row */}
      <div className="shrink-0 flex items-center justify-center gap-3 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] text-sm">
        <span className="text-gray-200 truncate max-w-[60vw]">
          {photo.title ?? 'Untitled'}
        </span>
        <span className="text-gray-500">·</span>
        <span className="text-gray-500">{formatBytes(photo.byte_size)}</span>
        {photos.length > 1 && (
          <>
            <span className="text-gray-500">·</span>
            <span className="text-gray-500">
              {index + 1} / {photos.length}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

export default Lightbox;
