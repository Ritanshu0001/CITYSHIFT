import type { CSSProperties } from "react";

const cells = [
  [2, 0, "quiet"], [3, 0, "quiet"], [4, 0, "warm"],
  [1, 1, "quiet"], [2, 1, "base"], [3, 1, "base"], [4, 1, "hot"], [5, 1, "quiet"],
  [0, 2, "quiet"], [1, 2, "base"], [2, 2, "warm"], [3, 2, "hot"], [4, 2, "hot"], [5, 2, "base"],
  [1, 3, "quiet"], [2, 3, "base"], [3, 3, "warm"], [4, 3, "base"], [5, 3, "quiet"],
  [2, 4, "quiet"], [3, 4, "base"], [4, 4, "quiet"],
] as const;

export function HexFingerprint() {
  return (
    <div className="fingerprint" aria-label="Illustration of a city analyzed as hexagonal areas">
      <div className="fingerprint-grid" aria-hidden="true">
        {cells.map(([x, y, level], index) => (
          <span
            key={`${x}-${y}-${index}`}
            className={`fingerprint-cell is-${level}`}
            style={{ "--x": x, "--y": y } as CSSProperties}
          />
        ))}
      </div>
      <div className="fingerprint-axis axis-y"><span>8 KM</span></div>
      <div className="fingerprint-axis axis-x"><span>SHIFT SCORE</span><b>00</b><b>100</b></div>
      <div className="fingerprint-callout callout-a"><span />Different road mix</div>
      <div className="fingerprint-callout callout-b"><span />Novel infrastructure</div>
      <div className="fingerprint-stamp">
        <b>NYC</b>
        <span>VS PHX</span>
      </div>
    </div>
  );
}
