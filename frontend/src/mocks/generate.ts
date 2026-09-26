import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const outputDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(outputDir, "../../..");

// Keep the offline demo byte-for-byte aligned with the latest committed backend result.
const result = JSON.parse(
  readFileSync(join(repoRoot, "cache/new-york-ny-usa/result.json"), "utf8"),
);
const city = JSON.parse(
  readFileSync(join(repoRoot, "cache/new-york-ny-usa/city.json"), "utf8"),
);

const cities = {
  cities: [
    {
      slug: result.summary.slug,
      name: result.summary.city,
      center: result.summary.center,
      n_hexes: result.summary.n_hexes,
      pct_red: result.summary.pct_red,
      created_at: city.created_at,
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
