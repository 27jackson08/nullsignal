/** Diagonal hatch marking low-sufficiency zones -- the visual signature of
 *  missing signal, and the reason the product is called what it is.
 *
 *  Built as a repeating vertical stripe that the pattern matrix then rotates
 *  45 degrees. Drawing diagonals into the tile directly is the obvious
 *  approach and the wrong one: the strokes do not meet across tile edges and
 *  the result reads as a field of dashes rather than continuous lines. */

const SPACING = 6;
const LINE_WIDTH = 1.2;
/* Ink on paper. Finer than a screen hatch would be, because the reference is
   an engraved survey plate rather than a UI texture. */
const LINE_COLOUR = "rgba(20, 22, 26, 0.62)";
const ROTATION_DEGREES = 45;

export function createHatchPattern(
  ctx: CanvasRenderingContext2D,
  scale = 1,
): CanvasPattern | null {
  const spacing = SPACING * scale;
  const tile = document.createElement("canvas");
  tile.width = spacing;
  tile.height = spacing;

  const tileCtx = tile.getContext("2d");
  if (!tileCtx) return null;

  tileCtx.fillStyle = LINE_COLOUR;
  tileCtx.fillRect(0, 0, LINE_WIDTH * scale, spacing);

  const pattern = ctx.createPattern(tile, "repeat");
  if (!pattern) return null;

  // Rotating the whole pattern keeps every line unbroken across tile seams.
  if (typeof DOMMatrix !== "undefined" && pattern.setTransform) {
    pattern.setTransform(new DOMMatrix().rotate(ROTATION_DEGREES));
  }
  return pattern;
}
