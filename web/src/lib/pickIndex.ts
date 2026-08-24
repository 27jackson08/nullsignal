/** Offscreen colour-index buffer for hit testing.
 *
 *  Each tract is filled with a colour encoding its array index, so finding the
 *  tract under the cursor is a single pixel read rather than a point-in-polygon
 *  scan over 2,300 shapes. Cost is constant in the number of tracts. */

const INDEX_OFFSET = 1; // 0 is reserved for "nothing here"

export function indexToColour(index: number): string {
  const value = index + INDEX_OFFSET;
  const r = value & 0xff;
  const g = (value >> 8) & 0xff;
  const b = (value >> 16) & 0xff;
  return `rgb(${r},${g},${b})`;
}

export function colourToIndex(r: number, g: number, b: number, a: number): number | null {
  if (a === 0) return null;
  const value = r | (g << 8) | (b << 16);
  return value === 0 ? null : value - INDEX_OFFSET;
}
