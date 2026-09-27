import { ArrowDownRight, ArrowUpRight, CloudRain, Compass, Database, Snowflake } from "lucide-react";
import { compactNumber, featureLabel } from "@/lib/constants";
import type { Summary } from "@/lib/types";

const climateRows = [
  { key: "rain_days_per_year", label: "Rainy days per year", icon: CloudRain },
  { key: "heavy_rain_days_per_year", label: "Heavy-rain days per year", icon: CloudRain },
  { key: "snow_days_per_year", label: "Snow days / year", icon: Snowflake },
] as const;

export function ComparisonView({ summary }: { summary: Summary }) {
  const shifts = summary.feature_comparison
    .filter((row) => row.name !== "terrain_slope_pct" && row.reference > 0)
    .map((row) => ({ ...row, ratio: row.target / row.reference }))
    .sort((a, b) => Math.abs(Math.log(b.ratio)) - Math.abs(Math.log(a.ratio)))
    .slice(0, 6);

  return (
    <div className="comparison-view">
      <section className="comparison-section">
        <div className="mini-heading"><span>Climate profile</span><small>Typical year</small></div>
        <div className="climate-list">
          {climateRows.map(({ key, label, icon: Icon }) => {
            const target = summary.climate.target[key];
            const reference = summary.climate.reference[key];
            const max = Math.max(target, reference, 1);
            return (
              <div className="climate-row" key={key}>
                <div className="climate-label"><Icon size={15} /><span>{label}</span></div>
                <div className="paired-bar">
                  <div><span style={{ width: `${(target / max) * 100}%` }} /><b>{compactNumber(target)}</b></div>
                  <div><span style={{ width: `${(reference / max) * 100}%` }} /><b>{compactNumber(reference)}</b></div>
                </div>
                <div className="pair-key"><span>This city</span><span>Waymo benchmark</span></div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="context-grid">
        <div><Compass size={17} /><small>Driving side</small><b>{summary.driving_side === "left" ? "Left-hand" : "Right-hand"}</b></div>
        <div><Database size={17} /><small>OpenStreetMap coverage</small><b>{Math.round(summary.osm_completeness * 100)}%</b></div>
      </section>

      {summary.novel_city.length > 0 && (
        <div className="novel-city-row">
          <span>Rare city conditions</span>
          {summary.novel_city.map((flag) => <b key={flag}>{flag === "snow" ? "Snow" : "Left-hand traffic"}</b>)}
        </div>
      )}

      <section className="comparison-section shift-section">
        <div className="mini-heading"><span>Biggest shifts</span><small>City compared with benchmark</small></div>
        <div className="shift-list">
          {shifts.map((row) => {
            const isUp = row.ratio >= 1;
            return (
              <div className="shift-row" key={row.name}>
                <div><b>{featureLabel(row.name)}</b><small>{compactNumber(row.target)} city · {compactNumber(row.reference)} reference</small></div>
                <span className={isUp ? "ratio-up" : "ratio-down"}>
                  {isUp ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}{row.ratio.toFixed(1)}×
                </span>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
