import { AlertTriangle } from "lucide-react";
import { BAND_COLORS, CRASH_COUNT_COLORS, REFERENCE_LABEL } from "@/lib/constants";

export function Legend({ showCrashes = false }: { showCrashes?: boolean }) {
  return (
    <div className="map-legend">
      <div className="legend-title"><span>Shift score</span></div>
      <div className="legend-scale">
        <span style={{ background: BAND_COLORS.green.hex }} /><span style={{ background: BAND_COLORS.yellow.hex }} /><span style={{ background: BAND_COLORS.red.hex }} />
      </div>
      <div className="legend-labels"><span>&lt; 80</span><span>80–95</span><span>≥ 95</span></div>
      <p>Area percentile relative to {REFERENCE_LABEL}.</p>
      <div className="legend-novel"><AlertTriangle size={13} /> Novel feature present</div>
      {showCrashes && (
        <div className="legend-crashes">
          <b>Fatal crashes · area count</b>
          <span><i style={{ background: CRASH_COUNT_COLORS.one.hex }} /> 1</span>
          <span><i style={{ background: CRASH_COUNT_COLORS.few.hex }} /> 2–3</span>
          <span><i style={{ background: CRASH_COUNT_COLORS.many.hex }} /> 4+</span>
          <small>Within this city only · white/aqua ring marks pedestrian/cyclist</small>
        </div>
      )}
    </div>
  );
}
