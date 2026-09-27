// Rider-facing Safe Journey API (/ride/* on the backend). Kept apart from lib/api.ts, which serves the admin views.
import { API_BASE } from "./constants";

export interface LatLng {
  lat: number;
  lng: number;
}

export interface Place extends LatLng {
  label: string;
  detail?: string;
}

export type RoutingState = "idle" | "building" | "ready" | "error";

export interface RideCity {
  slug: string;
  name: string;
  center: LatLng;
  radius_km: number;
  routing: RoutingState;
}

export interface RouteStep {
  instruction: string;
  street: string | null;
  distance_m: number;
}

export type AreaBand = "green" | "yellow" | "red";

export interface RideRoute {
  id: string;
  label: "Fastest" | "Balanced" | "Safest" | "Fastest & safest";
  lam: number;
  duration_s: number;
  distance_m: number;
  /** Route risk in units of one intersection in a strong-shift area: the hex layer plus the crash layer. */
  risk: number;
  risk_reduction_pct: number;
  risk_parts: { intersections: number; distance: number; crashes: number };
  intersections: number;
  /** Percent of the distance driven in each shift band. */
  area_mix: Record<AreaBand, number>;
  /** Scored H3 cells the route passes through (keys of RoutePlan.areas). */
  hexes: string[];
  extra_s: number;
  crash_sites: number[];
  avoided_sites: number[];
  path: [number, number][];
  steps: RouteStep[];
}

export interface RouteArea {
  shift_score: number;
  band: AreaBand;
}

export interface CrashSite extends LatLng {
  year: number;
  month: number;
  hour: number | null;
  fatalities: number;
  pedestrian: boolean;
  cyclist: boolean;
  dark: boolean;
  street: string | null;
}

export interface RoutePlan {
  slug: string;
  origin_street: string | null;
  destination_street: string | null;
  routes: RideRoute[];
  fastest_id: string;
  safest_id: string;
  recommended_id: string;
  crashes: Record<string, CrashSite>;
  areas: Record<string, RouteArea>;
  method: {
    area_source: string;
    crash_source: string;
    intersection_risk: number;
    area_risk_per_100m: number;
    crash_weight: number;
    kernel_sigma_m: number;
    near_route_m: number;
    intersection_delay_s: number;
  };
}

export class RideError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "RideError";
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}/ride${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      message = ((await response.json()) as { detail?: string }).detail ?? message;
    } catch {
      // Keep the status message when there's no JSON body.
    }
    throw new RideError(response.status, message);
  }
  return (await response.json()) as T;
}

export const getRideCities = () => call<{ cities: RideCity[] }>("/cities").then((r) => r.cities);

export const prepareCity = (slug: string) =>
  call<{ status: RoutingState; error: string | null }>(`/${encodeURIComponent(slug)}/prepare`, { method: "POST" });

export const cityStatus = (slug: string) =>
  call<{ status: RoutingState; error: string | null }>(`/${encodeURIComponent(slug)}/status`);

export const planRoutes = (slug: string, origin: LatLng, destination: LatLng) =>
  call<RoutePlan>(`/${encodeURIComponent(slug)}/routes`, {
    method: "POST",
    body: JSON.stringify({ origin: { lat: origin.lat, lng: origin.lng }, destination: { lat: destination.lat, lng: destination.lng } }),
  });

// Curated trips inside each city's service radius, for a one-tap demo.
export const PRESET_TRIPS: Record<string, { name: string; from: Place; to: Place }[]> = {
  "new-york-ny-usa": [
    {
      name: "Battery Park → Upper West Side",
      from: { label: "Battery Park", detail: "Lower Manhattan", lat: 40.7033, lng: -74.017 },
      to: { label: "Upper West Side", detail: "W 72nd St & Amsterdam Ave", lat: 40.7794, lng: -73.98 },
    },
    {
      name: "Downtown Brooklyn → Times Square",
      from: { label: "Downtown Brooklyn", detail: "Court St & Joralemon St", lat: 40.6928, lng: -73.9903 },
      to: { label: "Times Square", detail: "Midtown Manhattan", lat: 40.758, lng: -73.9855 },
    },
    {
      name: "Williamsburg → Hudson Yards",
      from: { label: "Williamsburg", detail: "Brooklyn", lat: 40.7081, lng: -73.9571 },
      to: { label: "Hudson Yards", detail: "Manhattan West Side", lat: 40.7536, lng: -74.0017 },
    },
  ],
};

// ---- path geometry (for the ride animation) ----------------------------------------------

function haversine(a: [number, number], b: [number, number]) {
  const rad = Math.PI / 180;
  const dLat = (b[0] - a[0]) * rad;
  const dLng = (b[1] - a[1]) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(h));
}

/** Cumulative metres at each vertex of a [lat, lng] path. */
export function cumulative(path: [number, number][]) {
  const cum = [0];
  for (let i = 1; i < path.length; i += 1) cum.push(cum[i - 1] + haversine(path[i - 1], path[i]));
  return cum;
}

/** Position and heading (degrees, 0 = north) at `meters` along the path. */
export function pointAlong(path: [number, number][], cum: number[], meters: number) {
  const d = Math.min(Math.max(meters, 0), cum.at(-1) ?? 0);
  let i = 1;
  while (i < cum.length - 1 && cum[i] < d) i += 1;
  const [a, b] = [path[i - 1], path[i] ?? path[i - 1]];
  const span = cum[i] - cum[i - 1] || 1;
  const t = Math.min(1, Math.max(0, (d - cum[i - 1]) / span));
  const heading = (Math.atan2((b[1] - a[1]) * Math.cos((a[0] * Math.PI) / 180), b[0] - a[0]) * 180) / Math.PI;
  return { lat: a[0] + (b[0] - a[0]) * t, lng: a[1] + (b[1] - a[1]) * t, heading, index: i };
}

/** Metres along the path to the vertex nearest `point`. */
export function distanceAlong(path: [number, number][], cum: number[], point: LatLng) {
  let best = 0;
  let bestD = Infinity;
  path.forEach((p, i) => {
    const d = haversine(p, [point.lat, point.lng]);
    if (d < bestD) [best, bestD] = [i, d];
  });
  return cum[best];
}

export function formatMinutes(seconds: number) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export function formatExtra(seconds: number) {
  if (seconds < 30) return "No extra time";
  return `+${formatMinutes(seconds)}`;
}

export function formatDistance(meters: number) {
  return meters < 1000 ? `${Math.round(meters / 10) * 10} m` : `${(meters / 1000).toFixed(1)} km`;
}

export function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "crosses 52 intersections, 64% of the way in strong-shift areas": the hex layer in words. */
export function areaSummary(route: RideRoute) {
  return `crosses ${plural(route.intersections, "intersection")}, ${Math.round(route.area_mix.red)}% of the way in strong-shift areas`;
}

/** "FDR Drive ×7 · South Street" from a list of risk-site indices. */
export function streetsSummary(plan: RoutePlan, sites: number[], limit = 3) {
  const counts = new Map<string, number>();
  for (const i of sites) {
    const street = plan.crashes[String(i)]?.street ?? "an unnamed road";
    counts.set(street, (counts.get(street) ?? 0) + 1);
  }
  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const shown = ranked.slice(0, limit).map(([street, n]) => (n > 1 ? `${street} ×${n}` : street));
  const rest = ranked.slice(limit).reduce((sum, [, n]) => sum + n, 0);
  return rest ? [...shown, `${rest} more`] : shown;
}

export function describeRisk(site: CrashSite) {
  const month = new Date(2000, site.month - 1, 1).toLocaleString("en-US", { month: "short" });
  const who = site.pedestrian ? "pedestrian" : site.cyclist ? "cyclist" : "vehicle";
  return `${month} ${site.year} · ${who} record`;
}
