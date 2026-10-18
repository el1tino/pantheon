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

const ease = (t: number) => 1 - (1 - Math.min(Math.max(t, 0), 1)) ** 3;
const lerp = (a: number, b: number, t: number) => a + (b - a) * Math.min(Math.max(t, 0), 1);

function path(g: Graphics, pts: Point[], from: number, to: number) {
  const n = pts.length - 1;
  const i0 = Math.max(0, Math.floor(from * n));
  const i1 = Math.min(n, Math.ceil(to * n));
  if (i1 <= i0) return false;
  g.moveTo(pts[i0].x, pts[i0].y);
  for (let i = i0 + 1; i <= i1; i++) g.lineTo(pts[i].x, pts[i].y);
  return true;
}

function glow(g: Graphics, pts: Point[], from: number, to: number, color: string, alpha: number, width = 1.6, strength = 1) {
  if (alpha <= 0.002) return;
  const passes: [number, number][] = [
    [width * 7, 0.05 * strength],
    [width * 3.2, 0.14 * strength],
    [width, 0.95],
  ];
  for (const [w, a] of passes) {
    if (path(g, pts, from, to)) g.stroke({ width: w, color, alpha: alpha * a, cap: "round", join: "round" });
  }
}

function dots(g: Graphics, pts: Point[], to: number, color: string, alpha: number) {
  const n = Math.floor(to * (pts.length - 1));
  for (let i = 0; i <= n; i += 2) {
    g.circle(pts[i].x, pts[i].y, 4.5).fill({ color, alpha: alpha * 0.12 });
    g.circle(pts[i].x, pts[i].y, 1.7).fill({ color, alpha: alpha * 0.95 });
  }
}

function pointAt(pts: Point[], f: number): Point {
  const n = pts.length - 1;
  const x = Math.min(Math.max(f, 0), 1) * n;
  const i = Math.min(Math.floor(x), n - 1);
  const t = x - i;
  return { x: lerp(pts[i].x, pts[i + 1].x, t), y: lerp(pts[i].y, pts[i + 1].y, t) };
}

function comet(g: Graphics, pts: Point[], f: number, color: string, alpha = 1) {
  if (f <= 0) return;
  glow(g, pts, Math.max(0, f - 0.16), f, color, 0.55 * alpha, 2.2);
  const head = pointAt(pts, f);
  g.circle(head.x, head.y, 11).fill({ color, alpha: 0.16 * alpha });
  g.circle(head.x, head.y, 5).fill({ color, alpha: 0.45 * alpha });
  g.circle(head.x, head.y, 2.4).fill({ color: "#ffffff", alpha: 0.95 * alpha });
}

// ---------------------------------------------------------------- effects

// Lines draw in, the comet travels, then the line fades to a faint trail and goes.
const DRAW_S = 0.55;
const COMET_S = 0.95;
const FADE_FROM = 1.1;
const FADE_TO = 3.6; // "lines fade over about 3 seconds"
const TRAIL_ALPHA = 0.09;
const TRAIL_END = 16;
const GONE = 19;

function talkFx(pts: Point[], stance: string, speakerColour: string, label: string, reduced: boolean): Fx {
  const colour = STANCE_COLOUR[stance] ?? STANCE_COLOUR.propose;
  const strength = stance === "agree" ? 1.8 : 1;
  let alphaNow = 1;
  return {
    g: new Graphics(),
    age: 0,
    hover: { pts, label, alpha: () => alphaNow },
    draw(g, t) {
      if (t > GONE) return false;
      let a =
        t < FADE_FROM ? 1 : t < FADE_TO ? lerp(1, TRAIL_ALPHA, (t - FADE_FROM) / (FADE_TO - FADE_FROM))
          : t < TRAIL_END ? TRAIL_ALPHA : lerp(TRAIL_ALPHA, 0, (t - TRAIL_END) / (GONE - TRAIL_END));
      if (reduced) a *= Math.min(1, t / 0.4);
      if (stance === "challenge" && t < FADE_TO && !reduced) {
        a *= 0.62 + 0.38 * Math.abs(Math.sin(t * 31) * Math.sin(t * 17 + 1));
      }
      alphaNow = a;
      const drawn = reduced ? 1 : ease(t / DRAW_S);
      if (stance === "question") dots(g, pts, drawn, colour, a);
      else glow(g, pts, 0, drawn, colour, a, 1.5, strength);
      if (!reduced && t < COMET_S + 0.3) {
        const f = ease(t / COMET_S);
        comet(g, pts, f, speakerColour, t < COMET_S ? 1 : lerp(1, 0, (t - COMET_S) / 0.3));
      }
      if (!reduced && t > COMET_S && t < COMET_S + 0.5) {
        const end = pts[pts.length - 1];
        const k = (t - COMET_S) / 0.5;
        g.circle(end.x, end.y, 6 + 18 * k).stroke({ width: 1.5, color: speakerColour, alpha: 0.6 * (1 - k) });
      }
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
        g.circle(centre.x, centre.y, 46).fill({ color: colour, alpha: 0.16 * (1 - t / 1.2) });
        return true;
      }
      if (t > 2.1) return false;
      for (const delay of [0, 0.28]) {
        const k = (t - delay) / 1.8;
        if (k <= 0 || k >= 1) continue;
        const r = ease(k) * maxR;
        g.circle(centre.x, centre.y, r).stroke({ width: 10, color: colour, alpha: 0.035 * (1 - k) });
        g.circle(centre.x, centre.y, r).stroke({ width: 1.2, color: colour, alpha: 0.32 * (1 - k) });
      }
      return true;
    },
  };
}

function beamFx(from: Point, to: Point, colour: string, label: string, reduced: boolean): Fx {
  const pts = [from, to];
  let alphaNow = 1;
  return {
    g: new Graphics(),
    age: 0,
    hover: { pts, label, alpha: () => alphaNow },
    draw(g, t) {
      if (t > 1.6) return false;
      const head = reduced ? 1 : ease(t / 0.32);
      alphaNow = t < 0.5 ? 1 : lerp(1, 0, (t - 0.5) / 1.1);
      const line = [from, { x: lerp(from.x, to.x, head), y: lerp(from.y, to.y, head) }];
      glow(g, line, 0, 1, colour, alphaNow, 2, 1.6);
      if (!reduced && t > 0.3 && t < 0.9) {
        const k = (t - 0.3) / 0.6;
        g.circle(to.x, to.y, 8 + 22 * k).fill({ color: colour, alpha: 0.25 * (1 - k) });
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
  return {
    g: new Graphics(),
    age: 0,
    draw(g, t) {
      const travel = reduced ? 0.01 : 0.9;
      if (!arrived && t >= travel) {
        arrived = true;
        onArrive();
      }
      if (reduced) return false;
      if (t > travel + 0.25) return false;
      const f = ease(t / travel);
      glow(g, pts, 0, Math.min(1, f), colour, 0.22 * (t < travel ? 1 : 1 - (t - travel) / 0.25), 1.4);
      if (t < travel) comet(g, pts, f, colour);
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
      glow(g, pts, 0, 1, colour, a * 0.9, 3, 2.2);
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
      const alpha = seat.status === "absent" ? 0.06 : 0.17;
      if (path(g, pts, 0, 1)) g.stroke({ width: 1.2, color: seat.colour, alpha, cap: "round" });
      const end = pts[pts.length - 1];
      const prev = pts[pts.length - 4];
      const ang = Math.atan2(end.y - prev.y, end.x - prev.x);
      for (const side of [-1, 1]) {
        g.moveTo(end.x, end.y);
        g.lineTo(end.x - 7 * Math.cos(ang + side * 0.45), end.y - 7 * Math.sin(ang + side * 0.45));
      }
      g.stroke({ width: 1.2, color: seat.colour, alpha: alpha * 1.3, cap: "round" });
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
          add(rippleFx(from.top, colourOf(p.from), Math.max(lay.width, lay.height) * 0.75, reduced));
          return;
        }
        const to = spot(p.to);
        if (!to) return;
        const label = `${nameOf(p.from)} ${(STANCE_LABEL[p.stance] ?? p.stance).toLowerCase()} → ${nameOf(p.to)}\n${snippet}`;
        if (p.stance === "vote") {
          add(beamFx(from.top, to.top, colourOf(p.from), label, reduced));
        } else {
          add(talkFx(talkCurve(from, to, lay.compact), p.stance, colourOf(p.from), label, reduced));
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

