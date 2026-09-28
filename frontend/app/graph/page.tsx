import type { Metadata } from "next";
import { ShockGraphWorkspace } from "@/components/ShockGraphWorkspace";
export const metadata: Metadata = { title: "Graph" };
export default function Page() { return <ShockGraphWorkspace />; }
