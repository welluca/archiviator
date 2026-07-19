import { useState } from 'react';
import type { FloorPlanDetail } from '../../types';
import { pointsAttr, regionLabelPos } from './geometry';

interface FloorCanvasProps {
  floor: FloorPlanDetail;
  /** Entity id of the highlighted room region, or null. */
  selectedEntityId: number | null;
  onSelectRegion: (entityId: number | null) => void;
}

/** View-mode floor plan: <svg viewBox> with the image + region polygons.
 * Everything is drawn in image-pixel coordinates, so the svg scales freely
 * with the container; the name/count pills are HTML overlays anchored by
 * percentage so text stays crisp and constant-size at any zoom. */
export function FloorCanvas({ floor, selectedEntityId, onSelectRegion }: FloorCanvasProps) {
  const [hoverId, setHoverId] = useState<number | null>(null);

  const w = floor.image_w || 1600;
  const h = floor.image_h || 1200;
  // Stroke widths live in image units — scale them with the image size so
  // they look the same on a 800px scan and a 4000px scan.
  const stroke = Math.max(2, w * 0.002);

  return (
    <div className="relative select-none">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="block w-full h-auto rounded-xl border border-space-700 bg-space-950"
        onClick={() => onSelectRegion(null)}
      >
        <image href={floor.image_url} x={0} y={0} width={w} height={h} />
        {floor.regions.map((r) => {
          const selected = r.entity.id === selectedEntityId;
          const hovered = r.entity.id === hoverId;
          return (
            <polygon
              key={r.id}
              points={pointsAttr(r.polygon)}
              onClick={(e) => {
                e.stopPropagation();
                onSelectRegion(selected ? null : r.entity.id);
              }}
              onMouseEnter={() => setHoverId(r.entity.id)}
              onMouseLeave={() => setHoverId((prev) => (prev === r.entity.id ? null : prev))}
              strokeWidth={selected ? stroke * 1.6 : stroke}
              strokeLinejoin="round"
              className={`cursor-pointer transition-colors ${
                selected
                  ? 'fill-blue-500/40 stroke-blue-400'
                  : hovered
                    ? 'fill-blue-500/30 stroke-blue-400/90'
                    : 'fill-blue-500/15 stroke-blue-500/60'
              }`}
            />
          );
        })}
      </svg>

      {/* Name + item-count pills (HTML so text does not scale with the image) */}
      {floor.regions.map((r) => {
        const p = regionLabelPos(r);
        const selected = r.entity.id === selectedEntityId;
        return (
          <button
            key={r.id}
            onClick={() => onSelectRegion(selected ? null : r.entity.id)}
            onMouseEnter={() => setHoverId(r.entity.id)}
            onMouseLeave={() => setHoverId((prev) => (prev === r.entity.id ? null : prev))}
            style={{ left: `${(p.x / w) * 100}%`, top: `${(p.y / h) * 100}%` }}
            className={`absolute -translate-x-1/2 -translate-y-1/2 flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-full border text-xs whitespace-nowrap shadow-md shadow-black/40 transition-colors ${
              selected
                ? 'bg-blue-600 border-blue-400 text-white'
                : 'bg-space-900/90 border-space-600 text-gray-200 hover:border-blue-400 hover:text-white'
            }`}
          >
            <span className="font-medium">{r.entity.name}</span>
            <span
              className={`px-1.5 py-px rounded-full text-[10px] ${
                selected ? 'bg-blue-500/60 text-white' : 'bg-space-800 text-gray-400'
              }`}
            >
              {r.entity.item_count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export default FloorCanvas;
