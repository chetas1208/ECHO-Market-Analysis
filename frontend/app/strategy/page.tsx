import type { Metadata } from "next";
import { StrategyWorkspace } from "@/components/StrategyWorkspace";
export const metadata: Metadata = { title: "Strategy" };
export default function Page() { return <StrategyWorkspace />; }
