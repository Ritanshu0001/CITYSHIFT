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
      <div className="fingerprint-glow" aria-hidden="true" />
      <svg className="fingerprint-maplines" viewBox="0 0 720 720" aria-hidden="true">
        <path className="map-water" d="M-20 556 C104 477 187 490 278 536 C380 587 492 580 741 447 L741 741 L-20 741 Z" />
        <g className="map-minor-roads">
          <path d="M-18 108 C157 73 231 157 385 131 S610 38 754 94" />
          <path d="M-28 208 C142 178 285 253 455 206 S626 154 753 191" />
          <path d="M-20 354 C151 302 258 378 405 343 S628 273 748 322" />
          <path d="M25 489 C157 436 322 504 441 467 S633 398 749 417" />
          <path d="M112 -20 C93 130 179 224 137 365 S84 589 124 742" />
          <path d="M287 -18 C318 132 248 250 298 391 S351 611 319 741" />
          <path d="M504 -18 C449 132 557 223 519 363 S465 577 499 741" />
          <path d="M650 -18 C621 146 690 237 642 385 S601 589 628 741" />
        </g>
        <g className="map-major-roads">
          <path d="M-30 615 C140 514 275 630 433 523 S606 350 756 388" />
          <path d="M35 -24 C205 119 202 261 373 376 S591 527 724 738" />
          <path d="M-15 290 C168 250 336 322 516 238 S659 144 750 129" />
        </g>
      </svg>
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
      <div className="fingerprint-axis axis-x"><span>SHIFT SURFACE</span><b>00</b><b>100</b></div>
      <div className="fingerprint-callout callout-a"><span />Road mix</div>
      <div className="fingerprint-callout callout-b"><span />Novel conditions</div>
      <div className="fingerprint-stamp">
        <small>SHIFT</small>
        <b>97.4</b>
        <span>NYC · PHX</span>
      </div>
    </div>
  );
}
