import { DemoReplay } from "@/components/demo-replay";

export default async function DemoPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <DemoReplay slug={slug} />;
}
