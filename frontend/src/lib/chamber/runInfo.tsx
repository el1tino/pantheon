"use client";

import { createContext, useContext } from "react";

/** What the Chamber knows about the run it shows, beyond its events. */
export type RunContext = {
  runId: string;
  siteKey: string;
  canChange: boolean; // false for someone else's public run and in Replay
  replay: boolean;
};

const Ctx = createContext<RunContext>({ runId: "", siteKey: "", canChange: false, replay: false });

export const RunInfoProvider = Ctx.Provider;
export const useRunInfo = () => useContext(Ctx);
