import type { Metadata } from "next";
import { SafeJourney } from "@/components/ride/SafeJourney";
import "./ride.css";

export const metadata: Metadata = {
  title: "Safe Journey — risk-aware Waymo rides",
  description: "Pick the fastest, balanced, or safest route using historical roadway risk.",
};

export default function RidePage() {
  return <SafeJourney />;
}
