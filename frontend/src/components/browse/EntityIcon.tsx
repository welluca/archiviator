import { Inbox } from 'lucide-react';
import type { Entity } from '../../types';
import { KIND_META, isInboxRoot } from '../../types';

const kindColors: Record<Entity['kind'], string> = {
  space: 'text-blue-400',
  furniture: 'text-amber-400',
  container: 'text-emerald-400',
  item: 'text-gray-400',
};

interface EntityIconProps {
  entity: Entity;
  className?: string;
}

/** Kind icon with per-kind accent color; the Inbox root gets an inbox icon. */
export function EntityIcon({ entity, className = 'w-4 h-4' }: EntityIconProps) {
  const Icon = isInboxRoot(entity) ? Inbox : KIND_META[entity.kind].icon;
  return <Icon className={`${className} ${kindColors[entity.kind]} shrink-0`} />;
}

export default EntityIcon;
