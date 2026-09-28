import type { Metadata } from "next";
import { EventDetailView } from "@/components/EventDetailView";

export const metadata: Metadata = { title: "Event Detail" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EventDetailView id={id} />;
}
