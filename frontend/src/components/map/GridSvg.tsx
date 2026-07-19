import type { FurnitureGrid, GridCell } from '../../types';

interface GridSvgProps {
  grid: FurnitureGrid;
  selectedCellId?: number | null;
  onCellClick?: (cell: GridCell) => void;
  /** Mini read-only preview: decorations only, no text, no interaction. */
  compact?: boolean;
  className?: string;
}

// Cell geometry in viewBox units — the svg scales to its container.
const CW = 150;
const CH = 112;
const GAP = 10;
const PAD = 16;

const truncate = (s: string, max: number): string =>
  s.length > max ? `${s.slice(0, Math.max(1, max - 1))}…` : s;

/** Type-specific face decoration, drawn inside the cell rect. */
function CellDecoration({ cell, x, y, w, h }: { cell: GridCell; x: number; y: number; w: number; h: number }) {
  switch (cell.cell_type) {
    case 'drawer':
      // Horizontal handle bar, upper middle of the face.
      return (
        <rect
          x={x + w / 2 - w * 0.18}
          y={y + h * 0.26}
          width={w * 0.36}
          height={7}
          rx={3.5}
          className="fill-space-600"
        />
      );
    case 'door':
      // Hinge-side line + knob dot on the opposite side.
      return (
        <>
          <line
            x1={x + 10}
            y1={y + 8}
            x2={x + 10}
            y2={y + h - 8}
            strokeWidth={2.5}
            className="stroke-space-600"
          />
          <circle cx={x + w - 16} cy={y + h / 2} r={5} className="fill-space-500" />
        </>
      );
    case 'shelf':
      // Open slot: a thicker board along the bottom edge.
      return (
        <rect x={x + 4} y={y + h - 8} width={w - 8} height={5} rx={2} className="fill-space-700" />
      );
    case 'box':
      // Lid line with a small tape mark.
      return (
        <>
          <line
            x1={x + 6}
            y1={y + h * 0.28}
            x2={x + w - 6}
            y2={y + h * 0.28}
            strokeWidth={2}
            className="stroke-space-600"
          />
          <rect
            x={x + w / 2 - 8}
            y={y + h * 0.28 - 6}
            width={16}
            height={12}
            rx={2}
            className="fill-space-700"
          />
        </>
      );
    default:
      return null;
  }
}

/** Pure SVG front-view of a furniture grid — drawers, shelves, doors, boxes.
 * All coordinates are in viewBox units so the same renderer serves the full
 * editor and the mini preview on the entity detail page. */
export function GridSvg({ grid, selectedCellId = null, onCellClick, compact = false, className = '' }: GridSvgProps) {
  const vw = PAD * 2 + grid.cols * CW + (grid.cols - 1) * GAP;
  const vh = PAD * 2 + grid.rows * CH + (grid.rows - 1) * GAP;

  return (
    <svg viewBox={`0 0 ${vw} ${vh}`} className={`block w-full h-auto ${className}`}>
      {/* Cabinet frame */}
      <rect
        x={2}
        y={2}
        width={vw - 4}
        height={vh - 4}
        rx={14}
        strokeWidth={3}
        className="fill-space-900 stroke-space-600"
      />

      {grid.cells.map((cell) => {
        const x = PAD + cell.col * (CW + GAP);
        const y = PAD + cell.row * (CH + GAP);
        const w = cell.col_span * CW + (cell.col_span - 1) * GAP;
        const h = cell.row_span * CH + (cell.row_span - 1) * GAP;
        const isVoid = cell.cell_type === 'void';
        const selected = cell.id === selectedCellId;
        const bound = cell.entity !== null;
        // Unbound voids are holes — nothing to open, nothing to bind (the
        // backend refuses binding them), so they render non-interactive.
        const interactive = Boolean(onCellClick) && !(isVoid && !bound);
        const cx = x + w / 2;

        // Rough per-span character budget for the centered name.
        const maxChars = Math.floor(w / 9.5);

        return (
          <g
            key={cell.id}
            onClick={interactive ? () => onCellClick!(cell) : undefined}
            className={interactive ? 'cursor-pointer' : undefined}
          >
            {/* Face */}
            <rect
              x={x}
              y={y}
              width={w}
              height={h}
              rx={8}
              strokeWidth={selected ? 3.5 : 2}
              strokeDasharray={isVoid ? '7 6' : undefined}
              className={
                selected
                  ? `stroke-blue-400 ${isVoid ? 'fill-transparent' : bound ? 'fill-space-800' : 'fill-space-950'}`
                  : isVoid
                    ? 'fill-transparent stroke-space-700/70'
                    : bound
                      ? `fill-space-800 stroke-space-600 ${interactive ? 'hover:stroke-blue-500/70' : ''}`
                      : `fill-space-950 stroke-space-700 ${interactive ? 'hover:stroke-blue-500/70' : ''}`
              }
            />
            {!isVoid && <CellDecoration cell={cell} x={x} y={y} w={w} h={h} />}

            {!compact && (
              <>
                {/* Custom label, top-left */}
                {cell.label && (
                  <text
                    x={x + 10}
                    y={y + 18}
                    fontSize={11}
                    className="fill-gray-500 select-none pointer-events-none"
                  >
                    {truncate(cell.label, maxChars + 4)}
                  </text>
                )}

                {bound && cell.entity ? (
                  <>
                    {/* Bound entity name, centered */}
                    <text
                      x={cx}
                      y={y + h / 2 + (cell.cell_type === 'drawer' || cell.cell_type === 'box' ? 14 : 5)}
                      fontSize={14}
                      textAnchor="middle"
                      className="fill-white select-none pointer-events-none"
                    >
                      {truncate(cell.entity.name, maxChars)}
                    </text>
                    {/* Item-count pill, bottom center */}
                    <g className="pointer-events-none select-none">
                      <rect
                        x={cx - 22}
                        y={y + h - 26}
                        width={44}
                        height={17}
                        rx={8.5}
                        className="fill-space-950/90"
                      />
                      <text
                        x={cx}
                        y={y + h - 13.5}
                        fontSize={10.5}
                        textAnchor="middle"
                        className="fill-gray-400"
                      >
                        {cell.entity.item_count} it.
                      </text>
                    </g>
                  </>
                ) : (
                  !isVoid && (
                    // Unbound affordance
                    <text
                      x={cx}
                      y={y + h / 2 + 7}
                      fontSize={20}
                      textAnchor="middle"
                      className="fill-gray-600 select-none pointer-events-none"
                    >
                      +
                    </text>
                  )
                )}
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export default GridSvg;
