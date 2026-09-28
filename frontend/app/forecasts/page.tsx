import type { Metadata } from "next";
import { ForecastWorkspace } from "@/components/ForecastWorkspace";
export const metadata: Metadata = { title: "Forecasts" };
export default function Page() { return <ForecastWorkspace />; }
