"use client";

import { ArrowUpRight, Database, MapPin, Radar, Route } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { BrandMark } from "@/components/BrandMark";
import { HexFingerprint } from "@/components/HexFingerprint";
import { SearchBox } from "@/components/SearchBox";
import { getCities } from "@/lib/api";
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
        <div className="nav-status">
          <span className="status-pulse" />
          Public data pipeline online
        </div>
        <a className="nav-link" href="#method">Method <ArrowUpRight size={14} /></a>
      </nav>

      <section className="hero-section">
        <div className="hero-copy">
          <p className="eyebrow"><span>01</span> City intelligence for simulation teams</p>
          <h1>Every city has a different <em>driving fingerprint.</em></h1>
          <p className="hero-lede">
            Enter any city. CityShift finds where its roads, weather, and street life depart from Phoenix—then turns the gaps into candidate test scenarios.
          </p>
          <SearchBox hero />
          <div className="hero-note">
            <Database size={15} />
            OpenStreetMap + Open-Meteo · 8 km study area · H3 resolution 8
          </div>
        </div>
        <HexFingerprint />
      </section>

      <section className="proof-strip" aria-label="How CityShift works">
        <div><span>01</span><MapPin /><p><b>Pick a city</b>Anywhere public data reaches.</p></div>
        <div><span>02</span><Radar /><p><b>Find the shift</b>Every area scored against Phoenix.</p></div>
        <div><span>03</span><Route /><p><b>Prioritize tests</b>Evidence-backed scenarios, ranked.</p></div>
        <blockquote>“Waymax tests the scenario.<br /><strong>CityShift finds the scenario worth testing.</strong>”</blockquote>
      </section>

      <section className="cached-section" id="method">
        <div className="section-heading">
          <p className="eyebrow"><span>02</span> Ready now</p>
          <h2>Cities we’ve already mapped</h2>
          <p>Open a cached analysis instantly—the reliable path when live data is still processing.</p>
        </div>
        <div className="city-list">
          {cities.map((city, index) => (
            <Link href={`/city/${city.slug}`} className="city-row" key={city.slug}>
              <span className="city-index">{String(index + 1).padStart(2, "0")}</span>
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
        <BrandMark compact />
        <p>Public signals. Comparable cities. Testable scenarios.</p>
        <span>Reference city · Phoenix, AZ</span>
      </footer>
    </main>
  );
}
