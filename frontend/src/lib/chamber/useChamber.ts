"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { BACKEND_WS_URL } from "@/lib/config";
import { ChamberState, initialState, reduce } from "./reducer";
import { ChamberEvent } from "./types";

export type EffectListener = (ev: ChamberEvent, state: ChamberState) => void;

/**
 * Connects to a run's event stream. History arrives first and only updates state;
 * events after the `caught_up` marker also fire effects (lines, comets, pulses).
 */
export function useChamber(runId: string) {
  const [state, dispatch] = useReducer(reduce, initialState);
  const [connection, setConnection] = useState<"connecting" | "open" | "closed">("connecting");
  const listeners = useRef(new Set<EffectListener>());
  const liveRef = useRef(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    let local = initialState;

    const connect = () => {
      setConnection("connecting");
      ws = new WebSocket(`${BACKEND_WS_URL}/api/runs/${runId}/ws`);
      ws.onopen = () => setConnection("open");
      ws.onmessage = (msg) => {
        const ev = JSON.parse(msg.data) as ChamberEvent;
        const fresh = ev.type === "caught_up" || ev.seq > local.lastSeq;
        local = reduce(local, ev);
        dispatch(ev);
        if (ev.type === "caught_up") liveRef.current = true;
        else if (liveRef.current && fresh) listeners.current.forEach((fn) => fn(ev, local));
      };
      ws.onclose = () => {
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
  }, [runId]);

  const subscribe = useCallback((fn: EffectListener) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  return { state, connection, subscribe };
}
