interface CanvasBackgroundProps {
  /** Background image URL, or null for a blank-canvas grid. */
  imageUrl: string | null;
  /** Canvas dimensions (SVG viewBox units). */
  w: number;
  h: number;
  /** Unique suffix for the <pattern> id so two mounted SVGs never collide. */
  idSuffix: string | number;
}

/** Shared floor background: the uploaded plan image when present, otherwise a
 * subtle grid so a blank canvas still reads as a drawable surface. Rendered in
 * viewBox (canvas) space, so it scales freely with the container. */
export function CanvasBackground({ imageUrl, w, h, idSuffix }: CanvasBackgroundProps) {
  if (imageUrl) {
    return <image href={imageUrl} x={0} y={0} width={w} height={h} />;
  }
  // Grid step scales with the canvas so it looks the same at any size.
  const step = Math.max(20, Math.round(w / 40));
  const patternId = `floorGrid-${idSuffix}`;
  return (
    <>
      <defs>
        <pattern
          id={patternId}
          width={step}
          height={step}
          patternUnits="userSpaceOnUse"
        >
          <path
            d={`M ${step} 0 L 0 0 0 ${step}`}
            fill="none"
            className="stroke-space-800"
            strokeWidth={1}
          />
        </pattern>
      </defs>
      <rect x={0} y={0} width={w} height={h} className="fill-space-950" />
      <rect x={0} y={0} width={w} height={h} fill={`url(#${patternId})`} />
    </>
  );
}

export default CanvasBackground;
