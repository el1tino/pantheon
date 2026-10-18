// Where everything sits on the stage. Shared by the HTML seats and the PixiJS effects layer.

export type Point = { x: number; y: number };

export type SeatSpot = {
  letter: string;
  x: number;
  y: number; // centre of the letter
  size: number; // letter font size in px
  top: Point; // top of the seat's disc: ripples and the bench line start here
  disc: { x: number; y: number; r: number }; // the glass disc the logo sits on (see Seat.tsx)
  arrowStart: Point; // where the build arrow leaves, under the labels
  arrowEnd: Point; // where it lands on the core
  align: "start" | "center" | "end"; // which way the caption bubble opens, to stay on screen
};

export type Layout = {
  width: number;
  height: number;
  compact: boolean;
  seats: SeatSpot[];
  core: { x: number; y: number; w: number; h: number }; // centre x/y
};

export function computeLayout(width: number, height: number, letters: string[]): Layout {
  const n = Math.max(letters.length, 1);
  const compact = width < 640;
  const coreW = Math.min(520, Math.max(220, width * 0.38));
  const core = { x: width / 2, y: height * (compact ? 0.72 : 0.76), w: coreW, h: 14 };

  // On a phone every seat gets an equal slice of the width, so names and edges stay on screen.
  const span = compact ? (n - 1) / n : Math.min(0.8, 0.14 + 0.075 * (n - 1));
  const size = compact
    ? Math.min(44, (width * 0.86) / n / 1.25)
    : Math.min(92, Math.max(40, (width * span) / n / 1.35));
  const yTop = compact ? height * 0.2 : height * 0.25;
  const drop = compact ? 0 : height * 0.13;
  const labelDepth = compact ? 34 : 64;

  const seats = letters.map((letter, i) => {
    const t = n === 1 ? 0 : i / (n - 1) - 0.5; // -0.5 .. 0.5
    const x = width / 2 + t * span * width;
    const y = yTop + drop * (2 * t) ** 2;
    const landing = core.x + (n === 1 ? 0 : t * core.w * 0.82);
    return {
      letter,
      x,
      y,
      size,
      top: { x, y: y - size * 0.62 },
      disc: { x, y: y - size * 0.06, r: size * 0.54 },
      arrowStart: { x, y: y + size * 0.55 + labelDepth },
      arrowEnd: { x: landing, y: core.y - core.h / 2 - 6 },
      align: (x < width * 0.3 ? "start" : x > width * 0.7 ? "end" : "center") as SeatSpot["align"],
    };
  });
  return { width, height, compact, seats, core };
}

// Curve helpers -------------------------------------------------------------

export function quadPoint(p0: Point, c: Point, p1: Point, t: number): Point {
  const u = 1 - t;
  return { x: u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, y: u * u * p0.y + 2 * u * t * c.y + t * t * p1.y };
}

export function cubicPoint(p0: Point, c1: Point, c2: Point, p1: Point, t: number): Point {
  const u = 1 - t;
  return {
    x: u ** 3 * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t ** 3 * p1.x,
    y: u ** 3 * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t ** 3 * p1.y,
  };
}

export function sample(fn: (t: number) => Point, steps = 48): Point[] {
  return Array.from({ length: steps + 1 }, (_, i) => fn(i / steps));
}

/** Arc of light between two seats, bowing upwards over the bench. */
/** Where a line leaves (or meets) a disc: on its upper rim, leaning towards the other seat. */
function rimPoint(s: SeatSpot, towardX: number, lean = 0.62): Point {
  const side = towardX === s.x ? 0 : towardX > s.x ? 1 : -1;
  const r = s.disc.r + 3;
  return { x: s.disc.x + side * Math.sin(lean) * r, y: s.disc.y - Math.cos(lean) * r };
}

/** Arc of light between two seats, bowing upwards over the bench, rim to rim. */
export function talkCurve(a: SeatSpot, b: SeatSpot, compact: boolean): Point[] {
  const p0 = rimPoint(a, b.x);
  const p1 = rimPoint(b, a.x);
  const dist = Math.hypot(p1.x - p0.x, p1.y - p0.y);
  const lift = compact ? 18 + dist * 0.12 : 30 + dist * 0.32;
  // Two control points give a rounder, more even arc than a single quadratic one.
  const top = Math.min(p0.y, p1.y) - lift;
  const c1 = { x: lerpX(p0.x, p1.x, 0.18), y: top };
  const c2 = { x: lerpX(p0.x, p1.x, 0.82), y: top };
  return sample((t) => cubicPoint(p0, c1, c2, p1, t), 64);
}

/** A vote: a quick, low arc from voter to the voted-for seat. */
export function voteCurve(a: SeatSpot, b: SeatSpot): Point[] {
  const p0 = rimPoint(a, b.x, 0.35);
  const p1 = rimPoint(b, a.x, 0.35);
  const lift = 16 + Math.hypot(p1.x - p0.x, p1.y - p0.y) * 0.14;
  const c = { x: (p0.x + p1.x) / 2, y: Math.min(p0.y, p1.y) - lift };
  return sample((t) => quadPoint(p0, c, p1, t), 40);
}

const lerpX = (a: number, b: number, t: number) => a + (b - a) * t;

/** Build arrow from under a seat's labels into the core. */
export function buildCurve(s: SeatSpot): Point[] {
  const p0 = s.arrowStart;
  const p1 = s.arrowEnd;
  const midY = (p0.y + p1.y) / 2;
  return sample((t) => cubicPoint(p0, { x: p0.x, y: midY + (p1.y - p0.y) * 0.15 }, { x: p1.x, y: midY - (p1.y - p0.y) * 0.05 }, p1, t), 40);
}

export function distanceToPolyline(p: Point, pts: Point[]): number {
  let best = Infinity;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len2 = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
    best = Math.min(best, Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy)));
  }
  return best;
}
