"use client";

import { ArrowUpRight, Database, MapPin, Radar, Route } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { BrandMark } from "@/components/BrandMark";
import { HexFingerprint } from "@/components/HexFingerprint";
import { SearchBox } from "@/components/SearchBox";
import { getCities } from "@/lib/api";
import { REFERENCE_LABEL } from "@/lib/constants";
import type { CityListItem } from "@/lib/types";

export default function Home() {
  const [cities, setCities] = useState<CityListItem[]>([]);
  const [activeSlide, setActiveSlide] = useState(0);
  const [maxSlide, setMaxSlide] = useState(0);
  const carouselRef = useRef<HTMLDivElement | null>(null);

  const getCarouselMetrics = (carousel: HTMLDivElement) => {
    const slides = carousel.querySelectorAll<HTMLElement>(".city-slide");
    const firstSlide = slides[0];
    const secondSlide = slides[1];
    const step = secondSlide && firstSlide
      ? secondSlide.offsetLeft - firstSlide.offsetLeft
      : firstSlide?.offsetWidth ?? carousel.clientWidth;
    const lastIndex = Math.max(0, Math.round((carousel.scrollWidth - carousel.clientWidth) / Math.max(step, 1)));

    return { slides, step, lastIndex };
  };

  useEffect(() => {
    let active = true;
    getCities()
      .then((response) => active && setCities(response.cities))
      .catch(() => active && setCities([]));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const carousel = carouselRef.current;
    if (!carousel) return;

    const updateCarousel = () => {
      const { step, lastIndex } = getCarouselMetrics(carousel);
      const nextIndex = Math.round(carousel.scrollLeft / Math.max(step, 1));
      setMaxSlide(lastIndex);
      setActiveSlide(Math.min(Math.max(nextIndex, 0), lastIndex));
    };

    updateCarousel();
    const resizeObserver = new ResizeObserver(updateCarousel);
    resizeObserver.observe(carousel);
    carousel.addEventListener("scroll", updateCarousel, { passive: true });
    return () => {
      resizeObserver.disconnect();
      carousel.removeEventListener("scroll", updateCarousel);
    };
  }, [cities.length]);

  useEffect(() => {
    const carousel = carouselRef.current;
    if (!carousel || cities.length < 2) return;

    let gestureActive = false;
    let gestureTimer: number | undefined;

    const handleWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return;

      const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
      if (Math.abs(delta) < 2) return;

      window.clearTimeout(gestureTimer);
      gestureTimer = window.setTimeout(() => {
        gestureActive = false;
      }, 180);

      if (gestureActive) {
        event.preventDefault();
        return;
      }

      const { step, lastIndex } = getCarouselMetrics(carousel);
      const currentIndex = Math.round(carousel.scrollLeft / Math.max(step, 1));
      const nextIndex = Math.min(Math.max(currentIndex + (delta > 0 ? 1 : -1), 0), lastIndex);

      if (nextIndex === currentIndex) return;

      event.preventDefault();
      gestureActive = true;
      carousel.scrollTo({ left: step * nextIndex, behavior: "smooth" });
      setActiveSlide(nextIndex);
    };

    carousel.addEventListener("wheel", handleWheel, { passive: false });
    return () => {
      window.clearTimeout(gestureTimer);
      carousel.removeEventListener("wheel", handleWheel);
    };
  }, [cities.length]);

  const scrollToSlide = (index: number) => {
    const carousel = carouselRef.current;
    if (!carousel) return;

    const { step, lastIndex } = getCarouselMetrics(carousel);
    const nextIndex = Math.min(Math.max(index, 0), lastIndex);
    const nextLeft = step * nextIndex;
    carousel.scrollTo({ left: nextLeft, behavior: "smooth" });
    setActiveSlide(nextIndex);
  };

  return (
    <main className="landing-page">
      <nav className="site-nav">
        <BrandMark descriptor="Waymo Support system" />
        <a className="nav-link" href="#saved-cities">Saved cities <ArrowUpRight size={14} /></a>
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
        <div><span className="proof-icon"><MapPin /></span><p><b>Pick a city</b>Anywhere public data reaches.</p></div>
        <div><span className="proof-icon"><Radar /></span><p><b>Find the shift</b>Every area scored against {REFERENCE_LABEL}.</p></div>
        <div><span className="proof-icon"><Route /></span><p><b>Prioritize tests</b>Evidence-backed scenarios, ranked.</p></div>
      </section>

      <section className="grid-explainer" aria-labelledby="grid-explainer-title">
        <div className="grid-explainer-visual">
          <Image
            src="/san-francisco-grid-map.jpg"
            alt="San Francisco covered by CityShift’s hexagonal analysis grid"
            width={1300}
            height={1000}
            sizes="(max-width: 980px) calc(100vw - 40px), 48vw"
          />
        </div>
        <div className="grid-explainer-copy">
          <p className="grid-explainer-kicker">How the grid is made</p>
          <h2 id="grid-explainer-title">One city, divided into comparable areas.</h2>
          <p>
            CityShift lays a hexagonal grid over the city so every area is measured at the same scale. Each cell gathers road layout, terrain, weather, and crash context, then compares those signals with {REFERENCE_LABEL}. Hexagons keep neighboring areas evenly connected, making local shifts easy to see without relying on changing neighborhood boundaries.
          </p>
        </div>
      </section>

      <section className="cached-section" id="saved-cities">
        <div className="section-heading">
          <h2>Cities we’ve already mapped</h2>
          <p>Open a cached analysis instantly—the reliable path when live data is still processing.</p>
        </div>

        {cities.length > 0 ? (
          <>
            <div
              className="city-carousel"
              ref={carouselRef}
              aria-label="Mapped cities carousel"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "ArrowRight") {
                  event.preventDefault();
                  scrollToSlide(Math.min(activeSlide + 1, maxSlide));
                } else if (event.key === "ArrowLeft") {
                  event.preventDefault();
                  scrollToSlide(Math.max(activeSlide - 1, 0));
                }
              }}
            >
              {cities.map((city, index) => (
                <div className="city-slide" key={city.slug}>
                  <Link
                    href={`/city/${city.slug}`}
                    className="city-row"
                    style={{ "--city-share": `${city.pct_red}%`, "--city-delay": `${Math.min(index * 35, 280)}ms` } as CSSProperties}
                  >
                    <span className="city-row-heading">
                      <span className="city-name"><b>{city.name}</b><small>{city.n_hexes} mapped areas</small></span>
                      <span className="city-open" aria-hidden="true"><ArrowUpRight size={30} /></span>
                    </span>
                    <span className="city-shift-summary">
                      <span className="city-share" aria-label={`${city.pct_red.toFixed(1)}% of mapped areas show a strong shift`}>
                        <b>{city.pct_red.toFixed(1)}%</b>
                      </span>
                      <span className="city-score"><b>Strong-shift areas</b><small>Share of mapped areas</small></span>
                    </span>
                  </Link>
                </div>
              ))}
            </div>

            <div className="city-dots" aria-label="City slide navigation">
              {cities.slice(0, maxSlide + 1).map((city, index) => (
                <button
                  key={city.slug}
                  type="button"
                  className={index === activeSlide ? "is-active" : ""}
                  aria-label={`Show ${city.name}`}
                  aria-current={index === activeSlide ? "true" : undefined}
                  onClick={() => scrollToSlide(index)}
                />
              ))}
            </div>
          </>
        ) : (
          <div className="city-empty">No cached cities yet. Start with the search above.</div>
        )}
      </section>

      <footer className="site-footer">
        <BrandMark />
        <p>Public signals. Comparable cities. Testable scenarios.</p>
        <span>Reference · {REFERENCE_LABEL}<br />Crash data: NHTSA FARS 2020-2024 (2024 preliminary)</span>
      </footer>
    </main>
  );
}
