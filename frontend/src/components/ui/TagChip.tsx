import { X } from 'lucide-react';
import type { TagLite } from '../../types';

/** Dot color used when a tag has no color assigned. */
const FALLBACK_DOT = '#64748b';

interface TagChipProps {
  tag: TagLite;
  /** Renders a small × that calls this (tags editor). */
  onRemove?: () => void;
  /** Makes the whole chip a toggle button (search filter rail). */
  onClick?: () => void;
  selected?: boolean;
}

/** Compact tag pill: color dot + name. Presentation-only unless given handlers. */
export function TagChip({ tag, onRemove, onClick, selected = false }: TagChipProps) {
  const base = `inline-flex items-center gap-1.5 text-[10px] px-1.5 py-0.5 rounded-full border max-w-[10rem] ${
    selected
      ? 'bg-blue-500/20 border-blue-500/50 text-blue-300'
      : 'bg-space-800 border-space-700 text-gray-300'
  }`;

  const inner = (
    <>
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{ backgroundColor: tag.color || FALLBACK_DOT }}
      />
      <span className="truncate">{tag.name}</span>
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="text-gray-500 hover:text-red-400 transition-colors shrink-0"
          aria-label={`Remove tag ${tag.name}`}
        >
          <X className="w-3 h-3" />
        </button>
      )}
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={`${base} hover:border-space-500 transition-colors cursor-pointer`}
      >
        {inner}
      </button>
    );
  }
  return <span className={base}>{inner}</span>;
}

export default TagChip;
