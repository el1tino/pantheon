"use client";

import { siteUrl } from "@/lib/api";
import { useRunInfo } from "@/lib/chamber/runInfo";
import { SeatView } from "@/lib/chamber/reducer";

type Img = { path: string; kind: string; prompt: string; consultant: string; seat: string };

/** Images the consultants made, with who asked for them and the prompt they got. */
export default function Gallery({ images, seats, version }: {
  images: Img[];
  seats: SeatView[];
  version: number;
}) {
  const { siteKey } = useRunInfo();
  const seat = (l: string) => seats.find((s) => s.letter === l);
  if (!images.length) return <p className="text-[13px] text-white/35">No images yet.</p>;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {images.map((img) => (
        <figure key={img.path} className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.02]">
          <div className="checkerboard flex aspect-[4/3] items-center justify-center p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={siteUrl(siteKey, img.path.replace(/^site\//, ""), version)}
              alt={img.prompt}
              className="max-h-full max-w-full object-contain"
            />
          </div>
          <figcaption className="space-y-1 p-3 text-[12px]">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-white/70">{img.path}</span>
              <span className="rounded bg-white/[0.06] px-1.5 text-[11.5px] text-white/45">{img.kind}</span>
            </div>
            <p className="italic text-white/50">“{img.prompt}”</p>
            <p className="text-white/35">
              by <span style={{ color: seat(img.seat)?.colour }}>{seat(img.seat)?.name ?? img.seat}</span>, made with {img.consultant}
            </p>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
