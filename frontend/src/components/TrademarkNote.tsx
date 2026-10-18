/** Shown wherever provider logos appear on a page of their own. */
export default function TrademarkNote({ className = "" }: { className?: string }) {
  return (
    <p className={`text-center text-[10.5px] text-white/25 ${className}`}>
      Model logos are trademarks of their owners, shown only to identify each model. No affiliation or endorsement.
    </p>
  );
}
