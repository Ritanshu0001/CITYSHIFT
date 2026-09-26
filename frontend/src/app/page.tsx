"use client";

import { ArrowUpRight, Database, MapPin, Radar, Route } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { BrandMark } from "@/components/BrandMark";
import { HexFingerprint } from "@/components/HexFingerprint";
import { SearchBox } from "@/components/SearchBox";
import { getCities } from "@/lib/api";
import { REFERENCE_LABEL } from "@/lib/constants";
import type { CityListItem } from "@/lib/types";

export default function Home() {
  const [cities, setCities] = useState<CityListItem[]>([]);

  useEffect(() => {
    let active = true;
    getCities()
      .then((response) => active && setCities(response.cities))
      .catch(() => active && setCities([]));
    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="landing-page">
      <nav className="site-nav">
        <BrandMark />
        <a className="nav-link" href="#method">Method <ArrowUpRight size={14} /></a>
      </nav>

      <section className="hero-section">
        <div className="hero-copy">
          <h1>Every city has a different <em>driving fingerprint.</em></h1>
          <p className="hero-lede">
            Enter any city. CityShift finds where its roads, weather, and street life depart from {REFERENCE_LABEL}—then turns the gaps into candidate test scenarios.
          </p>
          <SearchBox hero />
          <div className="hero-note">
            <Database size={15} />
            Data from OpenStreetMap, Open-Meteo, and Copernicus DEM.
          </div>
        </div>
        <HexFingerprint />
      </section>

      <section className="proof-strip" aria-label="How CityShift works">
        <div><MapPin /><p><b>Pick a city</b>Anywhere public data reaches.</p></div>
        <div><Radar /><p><b>Find the shift</b>Every area scored against {REFERENCE_LABEL}.</p></div>
        <div><Route /><p><b>Prioritize tests</b>Evidence-backed scenarios, ranked.</p></div>
      </section>

      <section className="cached-section" id="method">
        <div className="section-heading">
          <h2>Cities we’ve already mapped</h2>
          <p>Open a cached analysis instantly—the reliable path when live data is still processing.</p>
        </div>
        <div className="city-list">
          {cities.map((city) => (
            <Link href={`/city/${city.slug}`} className="city-row" key={city.slug}>
              <span className="city-name"><b>{city.name}</b><small>{city.n_hexes} mapped areas</small></span>
              <span className="city-meter" aria-label={`${city.pct_red}% strongly different`}>
                <span style={{ width: `${Math.max(5, city.pct_red)}%` }} />
              </span>
              <span className="city-score"><b>{city.pct_red.toFixed(1)}%</b><small>strong shift</small></span>
              <ArrowUpRight size={20} />
            </Link>
          ))}
          {cities.length === 0 && <div className="city-empty">No cached cities yet. Start with the search above.</div>}
        </div>
      </section>

      <footer className="site-footer">
        <BrandMark />
        <p>Public signals. Comparable cities. Testable scenarios.</p>
        <span>Reference · {REFERENCE_LABEL}<br />Crash data: NHTSA FARS 2020-2024 (2024 preliminary)</span>
      </footer>
    </main>
  );
}
