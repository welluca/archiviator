import { useState } from 'react';
import type { FloorPlanDetail, Placement } from '../../types';
import { pointsAttr, regionLabelPos } from './geometry';
import CanvasBackground from './CanvasBackground';

interface FloorCanvasProps {
  floor: FloorPlanDetail;
  /** Entity id of the highlighted room region, or null. */
  selectedEntityId: number | null;
  onSelectRegion: (entityId: number | null) => void;
  /** Click a furniture footprint → open its front-view grid. */
  onOpenPlacement: (entityId: number) => void;
}

/** Placement label anchor: explicit override, else the box centre. */
const placementLabelPos = (p: Placement): { x: number; y: number } =>
  p.label_x !== null && p.label_y !== null
    ? { x: p.label_x, y: p.label_y }
    : { x: p.x + p.w / 2, y: p.y + p.h / 2 };

/** View-mode floor plan: <svg viewBox> with the background (image or blank grid)
 * + room polygons + furniture footprints. Everything is drawn in canvas
 * coordinates, so the svg scales freely with the container; the name/count
 * pills are HTML overlays anchored by percentage so text stays crisp. */
export function FloorCanvas({
  floor,
  selectedEntityId,
  onSelectRegion,
  onOpenPlacement,
}: FloorCanvasProps) {
  const [hoverId, setHoverId] = useState<number | null>(null);

  const w = floor.image_w || 1600;
  const h = floor.image_h || 1200;
  // Stroke widths live in canvas units — scale them with the canvas size so
  // they look the same on a 800px scan and a 4000px scan.
  const stroke = Math.max(2, w * 0.002);

  return (
    <div className="relative select-none">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="block w-full h-auto rounded-xl border border-space-700 bg-space-950"
        onClick={() => onSelectRegion(null)}
      >
        <CanvasBackground imageUrl={floor.image_url} w={w} h={h} idSuffix={floor.id} />
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

        {/* Furniture footprints — solid boxes ON TOP of the rooms, so clicking
            a footprint opens its front view without selecting the room under it. */}
        {floor.placements.map((p) => {
          const hovered = p.entity.id === hoverId;
          const cx = p.x + p.w / 2;
          const cy = p.y + p.h / 2;
          return (
            <g
              key={p.id}
              transform={p.rotation ? `rotate(${p.rotation} ${cx} ${cy})` : undefined}
            >
              <rect
                x={p.x}
                y={p.y}
                width={p.w}
                height={p.h}
                rx={Math.min(p.w, p.h) * 0.06}
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenPlacement(p.entity.id);
                }}
                onMouseEnter={() => setHoverId(p.entity.id)}
                onMouseLeave={() => setHoverId((prev) => (prev === p.entity.id ? null : prev))}
                strokeWidth={stroke}
                strokeLinejoin="round"
                className={`cursor-pointer transition-colors ${
                  hovered
                    ? 'fill-amber-500/85 stroke-amber-200'
                    : 'fill-amber-500/70 stroke-amber-300'
                }`}
              />
            </g>
          );
        })}
      </svg>

      {/* Room name + item-count pills (HTML so text does not scale with the image) */}
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

      {/* Furniture name + item-count pills (amber, drill into the front view) */}
      {floor.placements.map((p) => {
        const pos = placementLabelPos(p);
        return (
          <button
            key={p.id}
            onClick={() => onOpenPlacement(p.entity.id)}
            onMouseEnter={() => setHoverId(p.entity.id)}
            onMouseLeave={() => setHoverId((prev) => (prev === p.entity.id ? null : prev))}
            style={{ left: `${(pos.x / w) * 100}%`, top: `${(pos.y / h) * 100}%` }}
            className="absolute -translate-x-1/2 -translate-y-1/2 flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-full border text-xs whitespace-nowrap shadow-md shadow-black/40 bg-amber-950/90 border-amber-700/70 text-amber-100 hover:border-amber-400 hover:text-white transition-colors"
          >
            <span className="font-medium">{p.entity.name}</span>
            <span className="px-1.5 py-px rounded-full text-[10px] bg-amber-900/70 text-amber-200">
              {p.entity.item_count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export default FloorCanvas;
