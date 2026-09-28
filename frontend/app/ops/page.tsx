import type { Metadata } from "next";
import { OpsWorkspace } from "@/components/OpsWorkspace";

export const metadata: Metadata = { title: "Operations" };

export default function Page() {
  return <OpsWorkspace />;
}
