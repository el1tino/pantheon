import ChamberView from "@/components/chamber/ChamberView";

export default async function ReplayPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <ChamberView runId={runId} mode="replay" />;
}
