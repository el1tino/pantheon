"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { goToLogin } from "@/lib/api";
import { backendWsUrl } from "@/lib/config";
import { ChamberState, initialState, reduce } from "./reducer";
import { ChamberEvent } from "./types";

export type EffectListener = (ev: ChamberEvent, state: ChamberState) => void;

/**
 * Connects to a run's event stream. History arrives first and only updates state;
 * events after the `caught_up` marker also fire effects (lines, comets, pulses).
 */
export function useChamber(runId: string, enabled = true) {
  const [state, dispatch] = useReducer(reduce, initialState);
  const [connection, setConnection] = useState<"connecting" | "open" | "closed" | "denied">("connecting");
  const listeners = useRef(new Set<EffectListener>());
  const liveRef = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    let local = initialState;

    const connect = () => {
      setConnection("connecting");
      ws = new WebSocket(`${backendWsUrl()}/api/runs/${runId}/ws`);
      ws.onopen = () => setConnection("open");
      ws.onmessage = (msg) => {
        const ev = JSON.parse(msg.data) as ChamberEvent;
        const fresh = ev.type === "caught_up" || ev.seq > local.lastSeq;
        local = reduce(local, ev);
        dispatch(ev);
        if (ev.type === "caught_up") liveRef.current = true;
        else if (liveRef.current && fresh) listeners.current.forEach((fn) => fn(ev, local));
      };
      ws.onclose = (e) => {
        if (e.code === 4401) return goToLogin();
        if (e.code === 4404 || e.code === 1008) return setConnection("denied");
        setConnection("closed");
        liveRef.current = false;
        const st = local.status;
        if (!stopped && !["done", "stopped", "failed"].includes(st)) {
          retry = setTimeout(connect, 1500); // reconnect; history dedupes by seq
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, [runId, enabled]);

  const subscribe = useCallback((fn: EffectListener) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  return { state, connection, subscribe };
}
