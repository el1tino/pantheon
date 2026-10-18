/* eslint-disable @next/next/no-img-element */

type SeatLike = { letter: string; name: string; colour: string; logo?: string };

/** A seat's provider logo, or its letter in its colour for runs recorded before logos. */
export default function SeatLogo({ seat, size, dim = false, className = "" }: {
  seat: SeatLike;
  size: number;
  dim?: boolean; // absent: greyed out
  className?: string;
}) {
  const style = { width: size, height: size, filter: dim ? "grayscale(1) opacity(0.45)" : undefined };
  if (seat.logo) {
    return <img src={`/logos/${seat.logo}.svg`} alt={seat.name} draggable={false} className={`select-none ${className}`} style={style} />;
  }
  return (
    <span
      className={`inline-flex select-none items-center justify-center font-semibold leading-none ${className}`}
      style={{ ...style, color: dim ? "#5b5f66" : seat.colour, fontSize: size * 0.9 }}
      aria-label={seat.name}
    >
      {seat.letter}
    </span>
  );
}
