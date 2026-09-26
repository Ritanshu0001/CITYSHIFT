export type Band = "green" | "yellow" | "red";
export type JobStep = "roads" | "infrastructure" | "weather" | "scoring" | "scenarios";

export interface TopFeature {
  name: string;
  value: number;
  ref_median: number;
  z: number;
  pct: number;
}

export interface CityHex {
  h3: string;
  shift_score: number;
  band: Band;
  top_features: TopFeature[];
  novel: string[];
}

export interface Center {
  lat: number;
  lng: number;
}

export interface Climate {
  rain_days_per_year: number;
  heavy_rain_days_per_year: number;
  snow_days_per_year: number;
}

export interface FeatureComparison {
  name: string;
  target: number;
  reference: number;
}

export interface Summary {
  city: string;
  slug: string;
  center: Center;
  radius_km: number;
  n_hexes: number;
  pct_red: number;
  climate: {
    target: Climate;
    reference: Climate;
  };
  driving_side: "left" | "right";
  feature_comparison: FeatureComparison[];
  osm_completeness: number;
  novel_city: Array<"snow" | "left_hand_traffic">;
}

export interface Scenario {
  id: string;
  priority: number;
  title: string;
  description: string;
  triggered_by: string[];
  hex_ids: string[];
  scope: "hex" | "city";
}

export interface CityResult {
  hexes: CityHex[];
  summary: Summary;
  scenarios: Scenario[];
}

export interface CrashPoint {
  lat: number;
  lng: number;
  year: number;
  month: number;
  hour: number | null;
  fatalities: number;
  pedestrian: boolean;
  cyclist: boolean;
  dark: boolean;
  h3: string;
}

export interface AvailableCrashesResponse {
  slug: string;
  available: true;
  source: "NHTSA FARS";
  years: number[];
  preliminary_years: number[];
  note: "Fatal crashes only";
  total: number;
  points: CrashPoint[];
  by_hex: Record<string, { count: number; pct: number }>;
}

export interface UnavailableCrashesResponse {
  slug: string;
  available: false;
  reason: string;
}

export type CrashesResponse = AvailableCrashesResponse | UnavailableCrashesResponse;

export interface ChatMessage {
  role: "user" | "model";
  text: string;
}

export interface UiState {
  selected_hex: string | null;
  open_panel: "why" | "comparison" | "scenarios" | null;
  crashes_on: boolean;
}

export type ChatAction =
  | { type: "select_hex"; h3: string }
  | { type: "highlight_scenario"; id: string }
  | { type: "open_panel"; panel: "why" | "comparison" | "scenarios" }
  | { type: "toggle_crashes"; on: boolean }
  | { type: "fly_to"; lat: number; lng: number; zoom: number }
  | { type: "open_city"; slug: string }
  | { type: "download_briefing"; format: "md" | "json" };

export interface ChatResponse {
  reply: string;
  actions: ChatAction[];
  model: string;
  fallback: boolean;
}

export interface AnalyzeRequest {
  name: string;
  lat: number;
  lng: number;
  country_code: string | null;
  supersedes_job_id?: string;
}

export interface AnalyzeResponse {
  job_id: string;
  slug: string;
  status: "queued" | "running" | "done";
  cached: boolean;
}

export interface JobStatus {
  job_id: string;
  slug: string;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  step: JobStep | null;
  steps_done: JobStep[];
  message: string | null;
  error: string | null;
}

export interface CityListItem {
  slug: string;
  name: string;
  center: Center;
  n_hexes: number;
  pct_red: number;
  created_at: string;
}

export interface CitiesResponse {
  cities: CityListItem[];
}
