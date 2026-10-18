"use client";

// One PixiJS canvas over the stage draws every light effect: conversation arcs and comets,
// broadcast ripples, vote beams, build pulses with sparks, fading trails and the
// agreement/argument haze between seats. It reacts only to live events.

import { useEffect, useRef, useState, type RefObject } from "react";
import { Application, Container, Graphics } from "pixi.js";
import {
  Layout,
  Point,
  SeatSpot,
  buildCurve,
  distanceToPolyline,
  talkCurve,
  voteCurve,
} from "@/lib/chamber/geometry";
import { ChamberState, SeatView } from "@/lib/chamber/reducer";
import { CLIENT, ChamberEvent, MODERATOR, STANCE_COLOUR, STANCE_LABEL } from "@/lib/chamber/types";
import type { EffectListener } from "@/lib/chamber/useChamber";

const GREEN = "#4ade80";
const RED = "#f87171";

type Fx = {
  g: Graphics;
  age: number;
  /** Redraw for this frame; return false when finished. */
  draw: (g: Graphics, age: number) => boolean;
  hover?: { pts: Point[]; label: string; alpha: () => number };
};

type Props = {
  layout: Layout;
  seats: SeatView[];
  heat: ChamberState["heat"];
  subscribe: (fn: EffectListener) => () => void;
  onCoreHit: (added: number, removed: number) => void;
  reducedMotion: boolean;
  stageRef: RefObject<HTMLDivElement | null>;
};

// ---------------------------------------------------------------- drawing helpers

const clamp01 = (t: number) => Math.min(Math.max(t, 0), 1);
const ease = (t: number) => 1 - (1 - clamp01(t)) ** 3;
/** Slow in, slow out: motion that starts and lands softly. */
const easeInOut = (t: number) => {
  const x = clamp01(t);
  return x < 0.5 ? 4 * x ** 3 : 1 - (-2 * x + 2) ** 3 / 2;
};
const lerp = (a: number, b: number, t: number) => a + (b - a) * clamp01(t);

function path(g: Graphics, pts: Point[], from: number, to: number) {
  const n = pts.length - 1;
  const i0 = Math.max(0, Math.floor(from * n));
  const i1 = Math.min(n, Math.ceil(to * n));
  if (i1 <= i0) return false;
  g.moveTo(pts[i0].x, pts[i0].y);
  for (let i = i0 + 1; i <= i1; i++) g.lineTo(pts[i].x, pts[i].y);
  return true;
}

function pointAt(pts: Point[], f: number): Point {
  const n = pts.length - 1;
  const x = clamp01(f) * n;
  const i = Math.min(Math.floor(x), n - 1);
  const t = x - i;
  return { x: lerp(pts[i].x, pts[i + 1].x, t), y: lerp(pts[i].y, pts[i + 1].y, t) };
}

/** The stretch of a polyline between fractions `from` and `to`, with exact (interpolated) ends,
 * so a line grows smoothly instead of in sample-sized steps. */
function slice(pts: Point[], from: number, to: number): Point[] {
  if (to - from < 1e-4) return [];
  const n = pts.length - 1;
  const out = [pointAt(pts, from)];
  for (let i = Math.floor(from * n) + 1; i < to * n; i++) out.push(pts[i]);
  out.push(pointAt(pts, to));
  return out;
}

/**
 * A line of light whose brightness varies along it (`alphaAt(u)`, u = 0 at the start of `pts`,
 * 1 at the end): a wide soft halo, a mid glow and a fine bright core. The line is split into a
 * few runs of equal brightness; on the additive layer their butt ends meet without a seam.
 */
function ribbon(g: Graphics, pts: Point[], color: string, alphaAt: (u: number) => number, width = 1.5, halo = 1, runs = 14) {
  if (pts.length < 2) return;
  const n = pts.length - 1;
  const per = Math.max(1, Math.ceil(n / runs));
  const passes: [number, number][] = [
    [width * 7, 0.04 * halo],
    [width * 2.8, 0.12 * halo],
    [width, 0.92],
  ];
  for (const [w, k] of passes) {
    for (let i = 0; i < n; i += per) {
      const j = Math.min(n, i + per);
      const a = alphaAt((i + j) / 2 / n) * k;
      if (a < 0.003) continue;
      g.moveTo(pts[i].x, pts[i].y);
      for (let m = i + 1; m <= j; m++) g.lineTo(pts[m].x, pts[m].y);
      g.stroke({ width: w, color, alpha: a, cap: "butt", join: "round" });
    }
  }
}

/** Evenly spaced dots, for questions. */
function dotted(g: Graphics, pts: Point[], color: string, alphaAt: (u: number) => number) {
  const n = pts.length - 1;
  for (let i = 0; i <= n; i += 3) {
    const a = alphaAt(i / Math.max(n, 1));
    if (a < 0.003) continue;
    g.circle(pts[i].x, pts[i].y, 3.6).fill({ color, alpha: a * 0.1 });
    g.circle(pts[i].x, pts[i].y, 1.4).fill({ color, alpha: a * 0.9 });
  }
}

/** The bright head of a travelling line. */
function comet(g: Graphics, at: Point, color: string, alpha = 1) {
  if (alpha <= 0.01) return;
  g.circle(at.x, at.y, 9).fill({ color, alpha: 0.12 * alpha });
  g.circle(at.x, at.y, 4.2).fill({ color, alpha: 0.38 * alpha });
  g.circle(at.x, at.y, 1.9).fill({ color: "#ffffff", alpha: 0.95 * alpha });
}

/** A soft ring that settles around a disc when a line lands on it. */
function landing(g: Graphics, disc: { x: number; y: number; r: number }, color: string, k: number) {
  if (k <= 0 || k >= 1) return;
  const fade = 1 - ease(k);
  g.circle(disc.x, disc.y, disc.r + 2 + 9 * ease(k)).stroke({ width: 1.2, color, alpha: 0.4 * fade });
  g.circle(disc.x, disc.y, disc.r + 6).fill({ color, alpha: 0.06 * fade });
}

// ---------------------------------------------------------------- effects

// A line travels from speaker to listener with its comet at the tip, rests, then draws itself
// into the listener and leaves a faint trail that fades out.
const TRAVEL = 0.95;
const HOLD = 0.55;
const RETRACT = 1.25;
const TRAIL_ALPHA = 0.08;
const TRAIL_END = 14;
const GONE = 17;

function talkFx(pts: Point[], target: SeatSpot, stance: string, speakerColour: string, label: string, reduced: boolean): Fx {
  const colour = STANCE_COLOUR[stance] ?? STANCE_COLOUR.propose;
  const halo = stance === "agree" ? 1.6 : stance === "challenge" ? 1.3 : 1;
  const arrive = TRAVEL + HOLD;
  let alphaNow = 1;
  return {
    g: new Graphics(),
    age: 0,
    hover: { pts, label, alpha: () => alphaNow },
    draw(g, t) {
      if (t > GONE) return false;
      // The faint trail that stays once the line has landed.
      const trail = t < arrive ? 0
        : t < TRAIL_END ? TRAIL_ALPHA * ease((t - arrive) / RETRACT)
          : lerp(TRAIL_ALPHA, 0, (t - TRAIL_END) / (GONE - TRAIL_END));
      const draw = stance === "question" ? dotted : (gg: Graphics, p: Point[], c: string, f: (u: number) => number) => ribbon(gg, p, c, f, 1.5, halo);

      if (reduced) {
        const a = t < 0.4 ? t / 0.4 : t < arrive ? 1 : Math.max(trail, lerp(1, 0, (t - arrive) / RETRACT));
        alphaNow = a;
        draw(g, pts, colour, () => a);
        return true;
      }

      const head = easeInOut(t / TRAVEL);
      const tail = t < arrive ? 0 : easeInOut((t - arrive) / RETRACT);
      // A challenge breathes while it is live; nothing flickers.
      const pulse = stance === "challenge" && t < arrive ? 0.86 + 0.14 * Math.sin(t * 9) : 1;
      // While travelling, the line brightens towards its head; once landed it evens out.
      const settle = clamp01((t - TRAVEL) / HOLD);
      const along = (u: number) => pulse * lerp(0.18 + 0.82 * u ** 1.6, 1, settle);

      if (trail > 0.002 && tail > 0) draw(g, pts, colour, () => trail);
      if (tail < 1) {
        const part = slice(pts, tail, head);
        draw(g, part, colour, (u) => along(lerp(tail, head, u) / Math.max(head, 1e-3)));
      }
      alphaNow = tail < 1 ? 1 : trail;

      if (t < TRAVEL + 0.15) comet(g, pointAt(pts, head), speakerColour, t < TRAVEL ? 1 : 1 - (t - TRAVEL) / 0.15);
      landing(g, target.disc, speakerColour, (t - TRAVEL) / 0.8);
      return true;
    },
  };
}

function rippleFx(centre: Point, colour: string, maxR: number, reduced: boolean): Fx {
  return {
    g: new Graphics(),
    age: 0,
    draw(g, t) {
      if (reduced) {
        if (t > 1.2) return false;
        g.circle(centre.x, centre.y, 46).fill({ color: colour, alpha: 0.14 * (1 - t / 1.2) });
        return true;
      }
      if (t > 1.9) return false;
      // Two soft waves: a broad faint band with a fine bright edge, easing out as they spread.
      for (const delay of [0, 0.22]) {
        const k = (t - delay) / 1.6;
        if (k <= 0 || k >= 1) continue;
        const r = 8 + ease(k) * maxR;
        const fade = (1 - k) ** 2;
        g.circle(centre.x, centre.y, r).stroke({ width: 26, color: colour, alpha: 0.025 * fade });
        g.circle(centre.x, centre.y, r).stroke({ width: 7, color: colour, alpha: 0.06 * fade });
        g.circle(centre.x, centre.y, r).stroke({ width: 1, color: colour, alpha: 0.38 * fade });
      }
      return true;
    },
  };
}

function beamFx(pts: Point[], target: SeatSpot, colour: string, label: string, reduced: boolean): Fx {
  const travel = 0.45;
  let alphaNow = 1;
  return {
    g: new Graphics(),
    age: 0,
    hover: { pts, label, alpha: () => alphaNow },
    draw(g, t) {
      if (t > 1.7) return false;
      const head = reduced ? 1 : easeInOut(t / travel);
      alphaNow = t < 0.6 ? 1 : lerp(1, 0, (t - 0.6) / 1.1);
      const part = slice(pts, 0, head);
      ribbon(g, part, colour, (u) => alphaNow * (0.25 + 0.75 * u), 1.6, 1.4, 10);
      if (!reduced) {
        if (t < travel + 0.1) comet(g, pointAt(pts, head), colour, t < travel ? 1 : 1 - (t - travel) / 0.1);
        landing(g, target.disc, colour, (t - travel) / 0.7);
      }
      return true;
    },
  };
}

type Spark = { x: number; y: number; vx: number; vy: number; colour: string };

function sparksFx(at: Point, added: number, removed: number): Fx {
  const total = Math.min(26, 8 + Math.round(Math.sqrt(added + removed) * 3));
  const greenShare = added + removed === 0 ? 1 : added / (added + removed);
  const sparks: Spark[] = Array.from({ length: total }, (_, i) => {
    const angle = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 1.15;
    const speed = 60 + Math.random() * 130;
    return {
      x: at.x, y: at.y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
      colour: i / total < greenShare ? GREEN : RED,
    };
  });
  let last = 0;
  return {
    g: new Graphics(),
    age: 0,
    draw(g, t) {
      if (t > 0.85) return false;
      const dt = t - last;
      last = t;
      const a = 1 - t / 0.85;
      for (const s of sparks) {
        s.vy += 260 * dt;
        s.x += s.vx * dt;
        s.y += s.vy * dt;
        g.circle(s.x, s.y, 3.2).fill({ color: s.colour, alpha: 0.18 * a });
        g.circle(s.x, s.y, 1.3).fill({ color: s.colour, alpha: 0.95 * a });
      }
      return true;
    },
  };
}

function pulseFx(pts: Point[], colour: string, onArrive: () => void, reduced: boolean): Fx {
  let arrived = false;
  const travel = reduced ? 0.01 : 0.9;
  return {
    g: new Graphics(),
    age: 0,
    draw(g, t) {
      if (!arrived && t >= travel) {
        arrived = true;
        onArrive();
      }
      if (reduced || t > travel + 0.2) return false;
      const head = easeInOut(t / travel);
      const tail = Math.max(0, head - 0.3);
      const fade = t < travel ? 1 : 1 - (t - travel) / 0.2;
      ribbon(g, slice(pts, tail, head), colour, (u) => fade * 0.75 * u ** 1.4, 1.4, 1.2, 8);
      if (t < travel) comet(g, pointAt(pts, head), colour);
      return true;
    },
  };
}

function benchFlashFx(spots: SeatSpot[], colour: string, reduced: boolean): Fx {
  const pts = spots.map((s) => ({ x: s.x, y: s.top.y - 6 }));
  return {
    g: new Graphics(),
    age: 0,
    draw(g, t) {
      if (t > 2.6 || pts.length < 2) return false;
      const a = t < 0.5 ? (reduced ? t / 0.5 : ease(t / 0.5)) : lerp(1, 0, (t - 0.5) / 2.1);
      ribbon(g, pts, colour, () => a * 0.9, 2.4, 2, 6);
      for (const p of pts) g.circle(p.x, p.y + 30, 54).fill({ color: colour, alpha: 0.07 * a });
      return true;
    },
  };
}

// ---------------------------------------------------------------- component

export default function EffectsLayer({
  layout, seats, heat, subscribe, onCoreHit, reducedMotion, stageRef,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<Application | null>(null);
  const baseRef = useRef<Graphics | null>(null);
  const fxLayerRef = useRef<Container | null>(null);
  const fxRef = useRef<Fx[]>([]);
  const [ready, setReady] = useState(false);
  const [hover, setHover] = useState<{ x: number; y: number; label: string } | null>(null);

  // Latest props for event callbacks, without re-subscribing on every render.
  const live = useRef({ layout, seats, reducedMotion, onCoreHit });
  live.current = { layout, seats, reducedMotion, onCoreHit };

  // Create the Pixi app once.
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    const app = new Application();
    app
      .init({
        backgroundAlpha: 0,
        antialias: true,
        resizeTo: host,
        autoDensity: true,
        resolution: Math.min(window.devicePixelRatio || 1, 2),
      })
      .then(() => {
        if (cancelled) {
          app.destroy(true, { children: true });
          return;
        }
        app.canvas.style.position = "absolute";
        app.canvas.style.inset = "0";
        host.appendChild(app.canvas);
        const base = new Graphics();
        const fxLayer = new Container();
        fxLayer.blendMode = "add";
        app.stage.addChild(base, fxLayer);
        baseRef.current = base;
        fxLayerRef.current = fxLayer;
        appRef.current = app;
        app.ticker.add((ticker) => {
          const dt = Math.min(ticker.deltaMS / 1000, 0.1);
          fxRef.current = fxRef.current.filter((fx) => {
            fx.age += dt;
            fx.g.clear();
            const alive = fx.draw(fx.g, fx.age);
            if (!alive) fx.g.destroy();
            return alive;
          });
        });
        setReady(true);
      });
    return () => {
      cancelled = true;
      if (appRef.current) {
        appRef.current.destroy(true, { children: true });
        appRef.current = null;
      }
      fxRef.current = [];
    };
  }, []);

  // Static layer: build arrows and the agree/argue haze. Redrawn when they change.
  useEffect(() => {
    const g = baseRef.current;
    if (!g || !ready) return;
    g.clear();
    const spots = new Map(layout.seats.map((s) => [s.letter, s]));
    for (const [key, h] of Object.entries(heat)) {
      const [a, b] = key.split("|");
      const sa = spots.get(a);
      const sb = spots.get(b);
      if (!sa || !sb) continue;
      const total = h.agree + h.challenge;
      const colour = h.agree >= h.challenge ? GREEN : RED;
      const alpha = Math.min(0.11, 0.022 * total);
      const pts = talkCurve(sa, sb, layout.compact);
      for (const [w, k] of [[30, 0.45], [14, 1]] as const) {
        if (path(g, pts, 0, 1)) g.stroke({ width: w, color: colour, alpha: alpha * k, cap: "round" });
      }
    }
    for (const seat of seats) {
      const spot = spots.get(seat.letter);
      if (!spot) continue;
      const pts = buildCurve(spot);
      const strength = seat.status === "absent" ? 0.35 : 1;
      const n = pts.length - 1;
      for (let i = 0; i < n; i += 4) {
        const j = Math.min(n, i + 4);
        const u = (i + j) / 2 / n;
        g.moveTo(pts[i].x, pts[i].y);
        for (let m = i + 1; m <= j; m++) g.lineTo(pts[m].x, pts[m].y);
        g.stroke({ width: 1.1, color: seat.colour, alpha: strength * (0.03 + 0.17 * u ** 1.3), cap: "butt" });
      }
      const end = pts[n];
      g.circle(end.x, end.y, 4).fill({ color: seat.colour, alpha: 0.05 * strength });
      g.circle(end.x, end.y, 1.6).fill({ color: seat.colour, alpha: 0.35 * strength });
    }
  }, [ready, layout, seats, heat]);

  // Live events -> effects.
  useEffect(() => {
    const add = (fx: Fx) => {
      fxLayerRef.current?.addChild(fx.g);
      fxRef.current.push(fx);
    };
    return subscribe((ev: ChamberEvent, state: ChamberState) => {
      if (!fxLayerRef.current) return;
      const { layout: lay, seats: seatViews, reducedMotion: reduced, onCoreHit: hit } = live.current;
      const spot = (letter: string) => lay.seats.find((s) => s.letter === letter);
      const colourOf = (letter: string) => seatViews.find((s) => s.letter === letter)?.colour ?? "#ffffff";
      const nameOf = (letter: string) => seatViews.find((s) => s.letter === letter)?.name ?? letter;
      const p = ev.payload;

      if (ev.type === "message_routed" && p.from === CLIENT) {
        // The client speaks: a white ripple rises from the bottom to every letter.
        add(rippleFx({ x: lay.width / 2, y: lay.height + 40 }, "#ffffff", lay.height * 1.15, reduced));
      } else if (ev.type === "checkpoint_resolved" && (p.action === "pick" || p.action === "accept")) {
        // Gavel: the bench flashes and a ring strikes out from the core.
        add(benchFlashFx(lay.seats, "#fde68a", reduced));
        add(rippleFx({ x: lay.core.x, y: lay.core.y }, "#fde68a", Math.max(lay.width, lay.height) * 0.6, reduced));
        hit(1, 0);
      } else if (ev.type === "artifact_created" && p.kind === "check") {
        // The site was run in Docker: the core rings out green when it passes, red when it fails.
        const colour = p.status === "passed" ? GREEN : p.status === "failed" ? RED : "#fcd34d";
        add(rippleFx({ x: lay.core.x, y: lay.core.y }, colour, Math.max(lay.width, lay.height) * 0.55, reduced));
        hit(p.status === "passed" ? 1 : 0, p.status === "failed" ? 1 : 0);
      } else if (ev.type === "message_routed" && p.from !== MODERATOR) {
        const from = spot(p.from);
        if (!from) return;
        const msg = state.messages.find((m) => m.id === p.message_id);
        const snippet = msg ? msg.content.slice(0, 140) + (msg.content.length > 140 ? "…" : "") : "";
        if (p.to === "all") {
          add(rippleFx(from.disc, colourOf(p.from), Math.min(lay.width * 0.42, 520), reduced));
          return;
        }
        const to = spot(p.to);
        if (!to) return;
        const label = `${nameOf(p.from)} ${(STANCE_LABEL[p.stance] ?? p.stance).toLowerCase()} → ${nameOf(p.to)}\n${snippet}`;
        if (p.stance === "vote") {
          add(beamFx(voteCurve(from, to), to, colourOf(p.from), label, reduced));
        } else {
          add(talkFx(talkCurve(from, to, lay.compact), to, p.stance, colourOf(p.from), label, reduced));
        }
      } else if (ev.type === "diff_applied") {
        const s = spot(p.seat);
        const landing = s ? s.arrowEnd : { x: lay.core.x, y: lay.core.y - lay.core.h / 2 };
        const arrive = () => {
          hit(p.lines_added, p.lines_removed);
          if (!reduced) add(sparksFx(landing, p.lines_added, p.lines_removed));
        };
        if (s) add(pulseFx(buildCurve(s), colourOf(p.seat), arrive, reduced));
        else arrive();
      } else if (ev.type === "phase_changed" && p.status === "done" && p.decision) {
        const winner = state.messages.find((m) => m.id === p.decision);
        if (!winner) return;
        const colour = colourOf(winner.seat);
        add(benchFlashFx(lay.seats, colour, reduced));
        const ws = spot(winner.seat);
        if (ws) add(rippleFx(ws.top, colour, Math.max(lay.width, lay.height) * 0.8, reduced));
      }
    });
  }, [subscribe]);

  // Hovering a line shows the message it carried.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const onMove = (e: PointerEvent) => {
      const rect = stage.getBoundingClientRect();
      const pt = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      let best: { d: number; label: string } | null = null;
      for (const fx of fxRef.current) {
        if (!fx.hover || fx.hover.alpha() < 0.05) continue;
        const d = distanceToPolyline(pt, fx.hover.pts);
        if (d < 10 && (!best || d < best.d)) best = { d, label: fx.hover.label };
      }
      setHover(best ? { x: pt.x, y: pt.y, label: best.label } : null);
    };
    const onLeave = () => setHover(null);
    stage.addEventListener("pointermove", onMove);
    stage.addEventListener("pointerleave", onLeave);
    return () => {
      stage.removeEventListener("pointermove", onMove);
      stage.removeEventListener("pointerleave", onLeave);
    };
  }, [stageRef]);

  return (
    <div ref={hostRef} className="pointer-events-none absolute inset-0 z-20">
      {hover && (
        <div
          className="absolute z-30 max-w-xs whitespace-pre-line glass-chip rounded-xl px-3 py-2 text-xs leading-relaxed text-white/85"
          style={{ left: Math.min(hover.x + 14, layout.width - 260), top: hover.y + 14 }}
        >
          {hover.label}
        </div>
      )}
    </div>
  );
}

