import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gridDisk, latLngToCell } from "h3-js";

const outputDir = dirname(fileURLToPath(import.meta.url));
const center = { lat: 40.7128, lng: -74.006 };
const cells = gridDisk(latLngToCell(center.lat, center.lng, 8), 4);

const featureTemplates: Array<[string, number, number]> = [
  ["intersection_density", 88.1, 31.2],
  ["signal_density", 14.9, 4.1],
  ["crosswalk_density", 21.3, 6.8],
  ["transit_stop_density", 9.4, 1.9],
  ["nightlife_density", 5.8, 0.7],
  ["arterial_share", 0.42, 0.21],
];

const hexes = cells.map((h3, index) => {
  const isRed = index % 13 === 0 || index === 17;
  const isYellow = !isRed && (index % 5 === 0 || index % 8 === 0);
  const band = isRed ? "red" : isYellow ? "yellow" : "green";
  const score = isRed ? 95.2 + (index % 4) : isYellow ? 81.4 + (index % 11) : 34 + ((index * 7) % 44);
  const start = index % featureTemplates.length;
  const topFeatures = [0, 1, 2].map((offset) => {
    const [name, base, ref] = featureTemplates[(start + offset) % featureTemplates.length];
    const multiplier = 0.86 + ((index + offset) % 7) / 20;
    return {
      name,
      value: Number((base * multiplier).toFixed(2)),
      ref_median: ref,
      z: Number(((score / 34) - 0.35 - offset * 0.22).toFixed(2)),
      pct: Number(Math.min(99.8, score + 1.1 - offset * 2.7).toFixed(1)),
    };
  });

  return {
    h3,
    shift_score: Number(score.toFixed(1)),
    band,
    top_features: topFeatures,
    novel: index === 0 ? ["movable_bridge_count"] : index === 25 ? ["tunnel_count"] : [],
  };
});

const redHexes = hexes.filter((hex) => hex.band === "red").map((hex) => hex.h3);
const nightlifeHexes = hexes.filter((_, index) => index % 17 === 0).map((hex) => hex.h3);
const result = {
  hexes,
  summary: {
    city: "New York, NY, USA",
    slug: "new-york-ny-usa",
    center,
    radius_km: 8,
    n_hexes: hexes.length,
    pct_red: Number(((redHexes.length / hexes.length) * 100).toFixed(1)),
    climate: {
      target: { rain_days_per_year: 120.4, heavy_rain_days_per_year: 6.2, snow_days_per_year: 11 },
      reference: { rain_days_per_year: 33, heavy_rain_days_per_year: 0.6, snow_days_per_year: 0 },
    },
    driving_side: "right",
    feature_comparison: [
      ["intersection_density", 60.2, 31.2],
      ["road_density", 14.1, 8.9],
      ["arterial_share", 0.42, 0.21],
      ["motorway_share", 0.08, 0.17],
      ["oneway_share", 0.38, 0.16],
      ["signal_density", 12.4, 4.1],
      ["crosswalk_density", 18.6, 6.8],
      ["bike_lane_density", 4.8, 1.1],
      ["transit_stop_density", 8.2, 1.9],
      ["school_density", 2.4, 0.9],
      ["nightlife_density", 4.9, 0.7],
      ["tourism_density", 3.7, 0.6],
      ["bridge_count", 1.2, 0.1],
      ["movable_bridge_count", 0.04, 0],
      ["tunnel_count", 0.18, 0.01],
      ["roundabout_count", 0.06, 0.02],
      ["stadium_count", 0.03, 0],
    ].map(([name, target, reference]) => ({ name, target, reference })),
    osm_completeness: 0.72,
    novel_city: ["snow"],
  },
  scenarios: [
    {
      id: "rain_dense_intersection",
      priority: 87.3,
      title: "Heavy rain at a dense signalized intersection",
      description: "New York has 3.6× Phoenix’s rain days. Dense intersections concentrate pedestrians, signals, and turning conflicts.",
      triggered_by: ["heavy_rain_days_per_year 10.3× reference", "intersection_density z > 2 in 7 hexes"],
      hex_ids: redHexes.slice(0, 7),
      scope: "hex",
    },
    {
      id: "crosswalk_wide_arterial",
      priority: 64.8,
      title: "Pedestrian crossing a wide arterial",
      description: "High crosswalk density overlaps unusually arterial-heavy streets in the study area.",
      triggered_by: ["crosswalk_density z > 2", "arterial_share z > 1"],
      hex_ids: redHexes.slice(1, 5),
      scope: "hex",
    },
    {
      id: "snow_traction",
      priority: 51.2,
      title: "Reduced traction + hidden lane markings",
      description: "Recurring snow creates a city-wide operating condition absent from the Phoenix reference.",
      triggered_by: ["snow_days_per_year 11.0 vs Phoenix 0.0"],
      hex_ids: [],
      scope: "city",
    },
    {
      id: "late_night_pedestrians",
      priority: 38.1,
      title: "Late-night pedestrian activity",
      description: "Nightlife density indicates concentrated pedestrian activity during low-light hours.",
      triggered_by: ["nightlife_density z > 2 in 4 hexes"],
      hex_ids: nightlifeHexes,
      scope: "hex",
    },
    {
      id: "movable_bridge",
      priority: 24.6,
      title: "Queue at an opening bridge + adjacent lane change",
      description: "A movable bridge is novel relative to the Phoenix reference and creates a distinct queue-release pattern.",
      triggered_by: ["movable_bridge_count is novel"],
      hex_ids: [hexes[0].h3],
      scope: "hex",
    },
  ],
};

const cities = {
  cities: [
    {
      slug: result.summary.slug,
      name: result.summary.city,
      center,
      n_hexes: result.summary.n_hexes,
      pct_red: result.summary.pct_red,
      created_at: "2026-09-26T18:02:11Z",
    },
  ],
};

const job = {
  job_id: "demo-city-analysis",
  slug: result.summary.slug,
  status: "running",
  step: "roads",
  steps_done: [],
  message: "Pulling the drivable road network…",
  error: null,
};

writeFileSync(join(outputDir, "result.json"), `${JSON.stringify(result, null, 2)}\n`);
writeFileSync(join(outputDir, "cities.json"), `${JSON.stringify(cities, null, 2)}\n`);
writeFileSync(join(outputDir, "job.json"), `${JSON.stringify(job, null, 2)}\n`);
