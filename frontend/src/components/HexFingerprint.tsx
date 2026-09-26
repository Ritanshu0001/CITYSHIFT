"use client";

import { ArrowUpRight, Crosshair, MapPin } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getCity } from "@/lib/api";
import type { CityHex, CityResult } from "@/lib/types";
import { HexMap } from "./HexMap";

const DEFAULT_CITY_SLUG = "new-york-ny-usa";

export function HexFingerprint() {
  const [result, setResult] = useState<CityResult | null>(null);
  const [selectedHex, setSelectedHex] = useState<CityHex | null>(null);

  useEffect(() => {
    let active = true;
    getCity(DEFAULT_CITY_SLUG)
      .then((city) => active && setResult(city))
      .catch(() => active && setResult(null));
    return () => {
      active = false;
    };
  }, []);

  const topScenario = result?.scenarios[0];

  return (
    <section className="city-preview" aria-label="New York city shift preview">
      <header className="city-preview-header">
        <div>
          <span className="city-preview-kicker"><MapPin size={13} /> Default city</span>
          <h2>{result?.summary.city ?? "New York, NY, USA"}</h2>
        </div>
        <Link href={`/city/${DEFAULT_CITY_SLUG}`}>Open analysis <ArrowUpRight size={15} /></Link>
      </header>

      <div className="city-preview-map">
        {result ? (
          <HexMap
            center={result.summary.center}
            hexes={result.hexes}
            selectedHex={selectedHex}
            highlightedIds={selectedHex ? [] : (topScenario?.hex_ids ?? [])}
            onSelect={setSelectedHex}
          />
        ) : (
          <div className="city-preview-loading"><Crosshair size={24} /><span>Loading the cached New York analysis…</span></div>
        )}
      </div>

      <footer className="city-preview-footer">
        <div><small>{selectedHex ? "Selected area" : "Strong shift"}</small><b>{selectedHex ? selectedHex.shift_score.toFixed(1) : `${result?.summary.pct_red.toFixed(1) ?? "30.4"}%`}</b></div>
        <div><small>Mapped areas</small><b>{result?.summary.n_hexes ?? "—"}</b></div>
        <p>{selectedHex ? "Area percentile against the pooled reference." : (topScenario?.title ?? "Real cached data—not an illustration.")}</p>
      </footer>
    </section>
  );
}
