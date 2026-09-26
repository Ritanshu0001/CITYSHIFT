import { AlertTriangle, Crosshair, X } from "lucide-react";
import { bandLabel, compactNumber, featureLabel, REFERENCE_LABEL } from "@/lib/constants";
import type { CityHex } from "@/lib/types";
import { StreetViewPanel } from "./StreetViewPanel";

export function WhyPanel({ hex, onClear }: { hex: CityHex | null; onClear: () => void }) {
  if (!hex) {
    return (
      <div className="panel-empty">
        <Crosshair size={28} strokeWidth={1.5} />
        <h3>Select an area on the map</h3>
        <p>Pick any hex to see the three strongest differences from {REFERENCE_LABEL} and the evidence behind its score.</p>
      </div>
    );
  }

  return (
    <div className="why-panel">
      <div className="panel-topline">
        <span className={`band-chip band-${hex.band}`}>{bandLabel(hex.band)}</span>
        <button className="icon-button" onClick={onClear} aria-label="Clear selected area"><X size={17} /></button>
      </div>
      <div className="score-lockup">
        <strong>{hex.shift_score.toFixed(1)}</strong>
        <span>/ 100</span>
      </div>
      <p className="score-explainer">More unusual than <b>{hex.shift_score.toFixed(1)}%</b> of areas across {REFERENCE_LABEL}.</p>
      <p className="hex-id">H3 · {hex.h3}</p>

      <div className="panel-rule" />
      <div className="mini-heading"><span>Strongest signals</span><small>Target vs reference</small></div>
      <div className="feature-table">
        {hex.top_features.map((feature, index) => (
          <div className="feature-row" key={feature.name}>
            <span className="feature-rank">0{index + 1}</span>
            <div className="feature-name"><b>{featureLabel(feature.name)}</b><small>{feature.pct.toFixed(1)}th percentile</small></div>
            <div className="feature-values"><b>{compactNumber(feature.value)}</b><small>REF {compactNumber(feature.ref_median)}</small></div>
            <span className={feature.z >= 0 ? "z-score positive" : "z-score negative"}>{feature.z >= 0 ? "+" : ""}{feature.z.toFixed(1)}σ</span>
          </div>
        ))}
      </div>

      {hex.novel.length > 0 && (
        <div className="novel-alert">
          <AlertTriangle size={18} />
          <div><b>Novel infrastructure</b><p>{hex.novel.map(featureLabel).join(", ")} are rarely present across {REFERENCE_LABEL}.</p></div>
        </div>
      )}

      <StreetViewPanel h3={hex.h3} />
    </div>
  );
}
