import { AlertTriangle } from "lucide-react";
import { BAND_COLORS } from "@/lib/constants";

export function Legend() {
  return (
    <div className="map-legend">
      <div className="legend-title"><span>Shift score</span><small>vs Phoenix</small></div>
      <div className="legend-scale">
        <span style={{ background: BAND_COLORS.green.hex }} /><span style={{ background: BAND_COLORS.yellow.hex }} /><span style={{ background: BAND_COLORS.red.hex }} />
      </div>
      <div className="legend-labels"><span>&lt; 80</span><span>80–95</span><span>≥ 95</span></div>
      <p>More unusual than X% of Phoenix areas</p>
      <div className="legend-novel"><AlertTriangle size={13} /> Novel feature present</div>
    </div>
  );
}
