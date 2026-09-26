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

export interface AnalyzeRequest {
  name: string;
  lat: number;
  lng: number;
  country_code: string | null;
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
  status: "queued" | "running" | "done" | "error";
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
