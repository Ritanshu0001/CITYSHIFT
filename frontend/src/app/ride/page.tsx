import type { Metadata } from "next";
import { SafeJourney } from "@/components/ride/SafeJourney";
import "./ride.css";

export const metadata: Metadata = {
  title: "Safe Journey — risk-aware Waymo rides",
  description: "Choose how much travel time to trade for a route with lower historical fatal-crash exposure.",
};

export default function RidePage() {
  return <SafeJourney />;
}
