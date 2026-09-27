import type { Metadata } from "next";
import { SafeJourney } from "@/components/ride/SafeJourney";
import "./ride.css";

export const metadata: Metadata = {
  title: "Safe Journey — risk-aware Waymo rides",
  description: "Pick the fastest, balanced, or safest route using historical roadway risk.",
};

export default async function RidePage({ searchParams }: PageProps<"/ride">) {
  const city = (await searchParams).city;
  const initialSlug = typeof city === "string" ? city : city?.[0];

  return <SafeJourney initialSlug={initialSlug} />;
}
