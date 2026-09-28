import type { Metadata } from "next";
import { LiveEvents } from "@/components/LiveEvents";

export const metadata: Metadata = { title: "Events" };

export default async function Page({ searchParams }: { searchParams: Promise<{ q?: string | string[]; page?: string | string[] }> }) {
  const params = await searchParams;
  const rawQuery = params.q;
  const query = Array.isArray(rawQuery) ? rawQuery[0] ?? "" : rawQuery ?? "";
  const rawPage = params.page;
  const parsedPage = Number(Array.isArray(rawPage) ? rawPage[0] : rawPage);
  const page = Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1;
  return <LiveEvents initialQuery={query} initialOffset={(page - 1) * 20} />;
}
