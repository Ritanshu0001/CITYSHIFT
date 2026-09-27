"use client";

import { ArrowUpRight, ChevronLeft, ChevronRight, Database, MapPin, Radar, Route } from "lucide-react";
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
  const pageRef = useRef<HTMLElement | null>(null);
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
    const page = pageRef.current;
    if (!page || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const targets = Array.from(page.querySelectorAll<HTMLElement>(".landing-reveal"));
    page.classList.add("has-reveal-motion");
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.14 });

    targets.forEach((target) => observer.observe(target));
    return () => observer.disconnect();
  }, [cities.length]);

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

  // Mouse drag-to-scroll. Touch and trackpads already scroll natively, and the vertical wheel is
  // left alone so it scrolls the page instead of being captured by the carousel.
  useEffect(() => {
    const carousel = carouselRef.current;
    if (!carousel || cities.length < 2) return;

    let pointerId: number | null = null;
    let startX = 0;
    let startLeft = 0;
    let lastX = 0;
    let lastT = 0;
    let velocity = 0; // px per ms, positive = pointer moving right
    let dragged = false;
    let settleTimer: number | undefined;

    const onDown = (event: PointerEvent) => {
      if (event.pointerType !== "mouse" || event.button !== 0) return;
      pointerId = event.pointerId;
      startX = lastX = event.clientX;
      startLeft = carousel.scrollLeft;
      lastT = event.timeStamp;
      velocity = 0;
      dragged = false;
    };

    const onMove = (event: PointerEvent) => {
      if (event.pointerId !== pointerId) return;
      const dx = event.clientX - startX;
      if (!dragged) {
        if (Math.abs(dx) < 6) return; // a click, not a drag
        dragged = true;
        window.clearTimeout(settleTimer);
        carousel.setPointerCapture(event.pointerId);
        carousel.classList.add("is-dragging");
      }
      carousel.scrollLeft = startLeft - dx;
      const dt = event.timeStamp - lastT;
      if (dt > 0) velocity = 0.8 * ((event.clientX - lastX) / dt) + 0.2 * velocity;
      lastX = event.clientX;
      lastT = event.timeStamp;
    };

    const onUp = (event: PointerEvent) => {
      if (event.pointerId !== pointerId) return;
      pointerId = null;
      if (!dragged) return;
      // Carry the fling ~250 ms forward, then settle on the nearest card.
      const { step, lastIndex } = getCarouselMetrics(carousel);
      const projected = carousel.scrollLeft - velocity * 250;
      const index = Math.min(Math.max(Math.round(projected / Math.max(step, 1)), 0), lastIndex);
      carousel.scrollTo({ left: index * step, behavior: "smooth" });
      setActiveSlide(index);
      // Snapping stays off until the settle animation lands, or it would fight it.
      settleTimer = window.setTimeout(() => carousel.classList.remove("is-dragging"), 450);
    };

    // A drag that ends over a card must not also open that city.
    const onClick = (event: MouseEvent) => {
      if (!dragged) return;
      event.preventDefault();
      event.stopPropagation();
      dragged = false;
    };
    const onDragStart = (event: DragEvent) => event.preventDefault(); // no ghost-image link drags

    carousel.addEventListener("pointerdown", onDown);
    carousel.addEventListener("pointermove", onMove);
    carousel.addEventListener("pointerup", onUp);
    carousel.addEventListener("pointercancel", onUp);
    carousel.addEventListener("click", onClick, true);
    carousel.addEventListener("dragstart", onDragStart);
    return () => {
      window.clearTimeout(settleTimer);
      carousel.removeEventListener("pointerdown", onDown);
      carousel.removeEventListener("pointermove", onMove);
      carousel.removeEventListener("pointerup", onUp);
      carousel.removeEventListener("pointercancel", onUp);
      carousel.removeEventListener("click", onClick, true);
      carousel.removeEventListener("dragstart", onDragStart);
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
    <main className="landing-page" ref={pageRef}>
      <nav className="site-nav">
        <BrandMark descriptor="Waymo Support system" />
        <div className="nav-actions">
          <a className="nav-link nav-link-saved" href="#saved-cities">Saved cities <ArrowUpRight size={14} /></a>
          <Link className="ride-access" href="/ride"><Route size={16} /> Plan a ride</Link>
        </div>
      </nav>

      <section className="hero-section">
        <div className="hero-copy">
          <h1>Every city has a different <em>driving fingerprint.</em></h1>
          <p className="hero-lede">
            Enter any city. CityShift finds where its roads, weather, and street life depart from {REFERENCE_LABEL}—then turns the gaps into candidate test scenarios.
            {" "}CityShift can help Waymo understand local driving patterns and prioritize testing before launching in a new city.
          </p>
          <SearchBox hero />
          <div className="hero-note">
            <Database size={15} />
            Data from OpenStreetMap and Open-Meteo.
          </div>
        </div>
        <HexFingerprint />
      </section>

      <section className="proof-strip landing-reveal" aria-label="How CityShift works">
        <div><span className="proof-icon"><MapPin /></span><p><b>Pick a city</b>Anywhere public data reaches.</p></div>
        <div><span className="proof-icon"><Radar /></span><p><b>Find the shift</b>Every area scored against {REFERENCE_LABEL}.</p></div>
        <div><span className="proof-icon"><Route /></span><p><b>Prioritize tests</b>Evidence-backed scenarios, ranked.</p></div>
      </section>

      <section className="grid-explainer" aria-labelledby="grid-explainer-title">
        <div className="grid-explainer-visual landing-reveal reveal-left">
          <Image
            src="/san-francisco-grid-map.jpg"
            alt="San Francisco covered by CityShift’s hexagonal analysis grid"
            width={1300}
            height={1000}
            sizes="(max-width: 980px) calc(100vw - 40px), 48vw"
          />
        </div>
        <div className="grid-explainer-copy landing-reveal reveal-right">
          <p className="grid-explainer-kicker">How the grid is made</p>
          <h2 id="grid-explainer-title">One city, divided into comparable areas.</h2>
          <p>
            CityShift lays a hexagonal grid over the city so every area is measured at the same scale. Each cell gathers road layout, terrain, weather, and crash context, then compares those signals with {REFERENCE_LABEL}. Hexagons keep neighboring areas evenly connected, making local shifts easy to see without relying on changing neighborhood boundaries.
          </p>
        </div>
      </section>

      <section className="cached-section" id="saved-cities">
        <div className="section-heading landing-reveal">
          <h2>Cities we’ve already mapped</h2>
          <p>Open a cached analysis instantly—the reliable path when live data is still processing.</p>
        </div>

        {cities.length > 0 ? (
          <>
            <div
              className="city-carousel landing-reveal"
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

            <div className="city-carousel-nav">
              <button type="button" className="city-step" aria-label="Previous cities"
                disabled={activeSlide === 0} onClick={() => scrollToSlide(activeSlide - 1)}>
                <ChevronLeft size={18} />
              </button>
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
              <button type="button" className="city-step" aria-label="Next cities"
                disabled={activeSlide >= maxSlide} onClick={() => scrollToSlide(activeSlide + 1)}>
                <ChevronRight size={18} />
              </button>
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
