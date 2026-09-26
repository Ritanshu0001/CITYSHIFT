import type { Band, JobStep } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
export const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === "1";
export const MAPS_API_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY ?? "";

export const POLL_MS = 1500;
export const BAND_YELLOW = 80;
export const BAND_RED = 95;
export const REFERENCE_SLUG = "phoenix-az-usa";

export const JOB_STEPS: JobStep[] = [
  "roads",
  "infrastructure",
  "weather",
  "scoring",
  "scenarios",
];

export const JOB_STEP_LABELS: Record<JobStep, string> = {
  roads: "Pulling road network",
  infrastructure: "Reading infrastructure and places",
  weather: "Pulling five years of weather",
  scoring: "Scoring against Phoenix",
  scenarios: "Building candidate scenarios",
};

export const BAND_COLORS: Record<Band, { hex: string; rgb: [number, number, number] }> = {
  green: { hex: "#18C6A3", rgb: [24, 198, 163] },
  yellow: { hex: "#F8BF47", rgb: [248, 191, 71] },
  red: { hex: "#FF5262", rgb: [255, 82, 98] },
};

export const FEATURE_LABELS: Record<string, string> = {
  intersection_density: "Intersections / km²",
  road_density: "Road km / km²",
  arterial_share: "Arterial road share",
  motorway_share: "Motorway share",
  oneway_share: "One-way road share",
  signal_density: "Signals / km²",
  crosswalk_density: "Crossings / km²",
  bike_lane_density: "Bike lanes / km²",
  transit_stop_density: "Transit stops / km²",
  school_density: "Schools / km²",
  nightlife_density: "Nightlife venues / km²",
  tourism_density: "Tourism places / km²",
  bridge_count: "Bridges",
  movable_bridge_count: "Movable bridges",
  tunnel_count: "Tunnels",
  roundabout_count: "Roundabouts",
  stadium_count: "Stadiums",
};

export function featureLabel(name: string) {
  return FEATURE_LABELS[name] ?? name.replaceAll("_", " ");
}

export function bandLabel(band: Band) {
  if (band === "red") return "Strong shift";
  if (band === "yellow") return "Notable shift";
  return "Within baseline";
}

export function compactNumber(value: number) {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  return value.toFixed(2);
}
