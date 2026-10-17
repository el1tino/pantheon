import ChamberView from "@/components/chamber/ChamberView";

export default async function ChamberPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <ChamberView runId={runId} />;
}
