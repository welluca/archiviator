import type { MapRegion, PolygonPoint } from '../../types';

/** Area-weighted polygon centroid with a vertex-mean fallback for degenerate
 * (zero-area / collinear) polygons. Image-pixel in, image-pixel out. */
export function polygonCentroid(pts: PolygonPoint[]): { x: number; y: number } {
  if (pts.length === 0) return { x: 0, y: 0 };
  let area = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[(i + 1) % pts.length];
    const cross = x1 * y2 - x2 * y1;
    area += cross;
    cx += (x1 + x2) * cross;
    cy += (y1 + y2) * cross;
  }
  if (Math.abs(area) < 1e-6) {
    const sx = pts.reduce((s, p) => s + p[0], 0);
    const sy = pts.reduce((s, p) => s + p[1], 0);
    return { x: sx / pts.length, y: sy / pts.length };
  }
  area *= 3;
  return { x: cx / area, y: cy / area };
}

/** Label anchor of a region: explicit label position, else the centroid. */
export const regionLabelPos = (r: MapRegion): { x: number; y: number } =>
  r.label_x !== null && r.label_y !== null
    ? { x: r.label_x, y: r.label_y }
    : polygonCentroid(r.polygon);

export const pointsAttr = (pts: PolygonPoint[]): string =>
  pts.map(([x, y]) => `${x},${y}`).join(' ');

export const clamp = (v: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, v));

/** Convert a client (screen) coordinate into the svg's viewBox space —
 * i.e. image-pixel coordinates — via the inverse screen CTM. */
export function clientToImage(
  svg: SVGSVGElement,
  clientX: number,
  clientY: number
): { x: number; y: number } | null {
  const ctm = svg.getScreenCTM();
  if (!ctm) return null;
  const pt = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
  return { x: pt.x, y: pt.y };
}
