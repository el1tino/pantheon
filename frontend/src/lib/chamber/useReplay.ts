"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StoredEvent, runEvents } from "@/lib/api";
import { ChamberState, initialState, reduce } from "./reducer";
import { ChamberEvent } from "./types";
import type { EffectListener } from "./useChamber";

// Long pauses (a model thinking, the client at a checkpoint) are cut down so the replay keeps moving.
const MAX_GAP_S = 1.5;
const SNAPSHOT_EVERY = 200;
export const SPEEDS = [1, 2, 4, 8] as const;

export type Marker = { at: number; kind: "phase" | "checkpoint"; label: string };

// History is applied as if already caught up, so the result opens when the replay reaches the end.
const START = reduce(initialState, { seq: 0, type: "caught_up", payload: {} });

/**
 * Plays a finished run's stored events back through the same reducer as the live Chamber.
 * Effects (lines, comets, pulses) fire only for events reached while playing, not when seeking.
 */
export function useReplay(runId: string, enabled = true) {
  const [events, setEvents] = useState<ChamberEvent[]>([]);
  const [times, setTimes] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<ChamberState>(START);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(1);
  const [clock, setClock] = useState(0);

  const listeners = useRef(new Set<EffectListener>());
  const stateRef = useRef<ChamberState>(START);
  const cursor = useRef(0); // number of events applied
  const clockRef = useRef(0);
  const snapshots = useRef(new Map<number, ChamberState>([[0, START]]));

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    runEvents(runId)
      .then((rows: StoredEvent[]) => {
        if (cancelled) return;
        const t: number[] = [];
        rows.forEach((r, i) => t.push(i === 0 ? 0 : t[i - 1] + Math.min(Math.max(r.at - rows[i - 1].at, 0), MAX_GAP_S)));
        setEvents(rows.map(({ seq, type, payload }) => ({ seq, type, payload })));
        setTimes(t);
        setPlaying(true);
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [runId, enabled]);

  const duration = times.length ? times[times.length - 1] : 0;

  /** Applies events up to (not including) index `to`; `effects` fires listeners for each. */
  const advance = useCallback(
    (to: number, effects: boolean) => {
      let s = stateRef.current;
      for (let i = cursor.current; i < to; i++) {
        s = reduce(s, events[i]);
        if ((i + 1) % SNAPSHOT_EVERY === 0) snapshots.current.set(i + 1, s);
        if (effects) {
          const ev = events[i];
          const now = s;
          listeners.current.forEach((fn) => fn(ev, now));
        }
      }
      cursor.current = Math.max(cursor.current, to);
      stateRef.current = s;
    },
    [events],
  );

  const indexAt = useCallback(
    (t: number) => {
      let lo = 0;
      let hi = times.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (times[mid] <= t) lo = mid + 1;
        else hi = mid;
      }
      return lo; // events [0, lo) happen at or before t
    },
    [times],
  );

  const seek = useCallback(
    (t: number) => {
      const target = Math.min(Math.max(t, 0), duration);
      const idx = indexAt(target);
      if (idx < cursor.current) {
        const base = Math.floor(idx / SNAPSHOT_EVERY) * SNAPSHOT_EVERY;
        let from = base;
        while (!snapshots.current.has(from)) from -= SNAPSHOT_EVERY;
        stateRef.current = snapshots.current.get(from)!;
        cursor.current = from;
      }
      advance(idx, false);
      clockRef.current = target;
      setClock(target);
      setState(stateRef.current);
    },
    [advance, duration, indexAt],
  );

  // The playback clock.
  useEffect(() => {
    if (!playing || !events.length) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.25);
      last = now;
      clockRef.current = Math.min(clockRef.current + dt * speed, duration);
      const idx = indexAt(clockRef.current);
      if (idx > cursor.current) {
        advance(idx, true);
        setState(stateRef.current);
      }
      setClock(clockRef.current);
      if (clockRef.current >= duration) {
        setPlaying(false);
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, events, duration, advance, indexAt]);

  const toggle = useCallback(() => {
    if (!playing && clockRef.current >= duration) seek(0);
    setPlaying((p) => !p);
  }, [playing, duration, seek]);

  const markers = useMemo(() => {
    const out: Marker[] = [];
    let phase = "";
    events.forEach((ev, i) => {
      if (ev.type === "phase_changed" && ev.payload.phase && ev.payload.phase !== phase) {
        phase = String(ev.payload.phase);
        out.push({ at: times[i], kind: "phase", label: phase });
      } else if (ev.type === "checkpoint_opened") {
        out.push({ at: times[i], kind: "checkpoint", label: String(ev.payload.kind ?? "checkpoint") });
      }
    });
    return out;
  }, [events, times]);

  const subscribe = useCallback((fn: EffectListener) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  return {
    state,
    subscribe,
    loaded: events.length > 0,
    error,
    playing,
    toggle,
    speed,
    setSpeed,
    clock,
    duration,
    seek,
    markers,
  };
}

export type Replay = ReturnType<typeof useReplay>;
