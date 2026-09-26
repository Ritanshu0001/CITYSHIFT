"use client";

import { ArrowLeft, CircleHelp, GitCompareArrows, Layers3, ListChecks, Search, Sparkles } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BrandMark } from "@/components/BrandMark";
import { ComparisonView } from "@/components/ComparisonView";
import { HexMap } from "@/components/HexMap";
import { ProgressScreen } from "@/components/ProgressScreen";
import { ScenarioCards } from "@/components/ScenarioCards";
import { WhyPanel } from "@/components/WhyPanel";
import { ApiError, getCity, getJob } from "@/lib/api";
import { MAPS_API_KEY, POLL_MS, REFERENCE_LABEL, REFERENCE_SLUGS } from "@/lib/constants";
import { getLiveTerrain, type LiveTerrain } from "@/lib/terrain";
import type { CityHex, CityResult, JobStatus, Scenario } from "@/lib/types";

type PanelTab = "why" | "compare" | "scenarios";
type Phase = "loading" | "progress" | "result" | "missing" | "error";

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function CityPage() {
  const { slug } = useParams<{ slug: string }>();
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const [phase, setPhase] = useState<Phase>("loading");
  const [result, setResult] = useState<CityResult | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [message, setMessage] = useState("");
  const [selectedHex, setSelectedHex] = useState<CityHex | null>(null);
  const [activeTab, setActiveTab] = useState<PanelTab>("compare");
  const [activeScenario, setActiveScenario] = useState<string | null>(null);
  const [highlightedIds, setHighlightedIds] = useState<string[]>([]);
  const [terrainByH3, setTerrainByH3] = useState<Record<string, LiveTerrain | null>>({});
  const terrainRequests = useRef(new Set<string>());

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const city = await getCity(slug);
        if (!active) return;
        setResult(city);
        setPhase("result");
      } catch (caught) {
        if (!(caught instanceof ApiError) || caught.status !== 404) {
          if (active) {
            setMessage(caught instanceof Error ? caught.message : "Could not load this city.");
            setPhase("error");
          }
          return;
        }

        if (!jobId) {
          if (active) setPhase("missing");
          return;
        }

        if (active) setPhase("progress");
        while (active) {
          try {
            const nextJob = await getJob(jobId);
            if (!active) return;
            setJob(nextJob);
            if (nextJob.status === "error") return;
            if (nextJob.status === "done") {
              const city = await getCity(slug);
              if (!active) return;
              setResult(city);
              setPhase("result");
              return;
            }
          } catch (pollError) {
            if (active) {
              setMessage(pollError instanceof Error ? pollError.message : "Lost contact with the analysis job.");
              setPhase("error");
            }
            return;
          }
          await wait(POLL_MS);
        }
      }
    }

    load();
    return () => {
      active = false;
    };
  }, [jobId, slug]);

  useEffect(() => {
    const h3 = selectedHex?.h3;
    if (!h3 || !MAPS_API_KEY || terrainRequests.current.has(h3)) return;

    terrainRequests.current.add(h3);
    void getLiveTerrain(h3).then(
      (terrain) => setTerrainByH3((current) => ({ ...current, [h3]: terrain })),
      () => setTerrainByH3((current) => ({ ...current, [h3]: null })),
    );
  }, [selectedHex]);

  const handleSelectHex = useCallback((hex: CityHex) => {
    setSelectedHex(hex);
    setActiveTab("why");
  }, []);

  const handleScenarioHighlight = useCallback((scenario: Scenario | null) => {
    setActiveScenario(scenario?.id ?? null);
    setHighlightedIds(scenario?.hex_ids ?? []);
  }, []);

  const cityLabel = useMemo(() => slug.replaceAll("-", " "), [slug]);

  if (phase === "loading") return <ProgressScreen cityName={cityLabel} job={null} />;
  if (phase === "progress") return <ProgressScreen cityName={cityLabel} job={job} />;
  if (job?.status === "error") return <ProgressScreen cityName={cityLabel} job={job} />;

  if (phase === "missing") {
    return (
      <main className="state-page">
        <CircleHelp size={36} />
        <p className="eyebrow"><span>404</span> Not analyzed</p>
        <h1>This city isn’t in the atlas yet.</h1>
        <p>Start from search so CityShift can create a job and build the city’s driving fingerprint.</p>
        <Link href="/"><Search size={17} /> Search for a city</Link>
      </main>
    );
  }

  if (phase === "error" || !result) {
    return (
      <main className="state-page">
        <CircleHelp size={36} />
        <p className="eyebrow"><span>!</span> Connection error</p>
        <h1>We couldn’t open this analysis.</h1>
        <p>{message || "The city data is not available right now."}</p>
        <Link href="/"><ArrowLeft size={17} /> Back to search</Link>
      </main>
    );
  }

  const { summary, hexes, scenarios } = result;

  return (
    <main className="analysis-page">
      <header className="analysis-nav">
        <BrandMark compact />
        <div className="analysis-breadcrumb"><span>City atlas</span><b>/</b><strong>{summary.city}</strong></div>
        <Link href="/" className="new-search"><Search size={15} /> New city</Link>
      </header>

      <section className="summary-strip">
        <div className="summary-title">
          <p className="eyebrow"><span>LIVE</span> Compared with {REFERENCE_LABEL}</p>
          <h1>{summary.city}</h1>
        </div>
        <div className="summary-metric"><small>Study area</small><b>{summary.radius_km} km</b><span>fixed radius</span></div>
        <div className="summary-metric"><small>Mapped areas</small><b>{summary.n_hexes}</b><span>road-bearing H3 cells</span></div>
        <div className="summary-metric summary-alert"><small>Strong shift</small><b>{summary.pct_red.toFixed(1)}%</b><span>of areas differ strongly</span></div>
        <div className="summary-reference"><Sparkles size={16} /><span><b>{REFERENCE_LABEL}</b>{REFERENCE_SLUGS.length}-city pooled baseline</span></div>
      </section>

      <div className="analysis-workspace">
        <section className="map-column">
          <div className="map-toolbar">
            <div><Layers3 size={15} /><b>Shift surface</b><span>{highlightedIds.length ? `${highlightedIds.length} scenario areas highlighted` : "Select an area for evidence"}</span></div>
            <span className="map-coordinate">{summary.center.lat.toFixed(4)}° N · {Math.abs(summary.center.lng).toFixed(4)}° W</span>
          </div>
          <HexMap
            center={summary.center}
            hexes={hexes}
            selectedHex={selectedHex}
            highlightedIds={highlightedIds}
            onSelect={handleSelectHex}
          />
        </section>

        <aside className="evidence-panel">
          <div className="panel-tabs" role="tablist" aria-label="City analysis panels">
            <button className={activeTab === "why" ? "is-active" : ""} onClick={() => setActiveTab("why")} role="tab" aria-selected={activeTab === "why"}>
              <CircleHelp size={15} /> Why
              {selectedHex && <span />}
            </button>
            <button className={activeTab === "compare" ? "is-active" : ""} onClick={() => setActiveTab("compare")} role="tab" aria-selected={activeTab === "compare"}>
              <GitCompareArrows size={15} /> Compare
            </button>
            <button className={activeTab === "scenarios" ? "is-active" : ""} onClick={() => setActiveTab("scenarios")} role="tab" aria-selected={activeTab === "scenarios"}>
              <ListChecks size={15} /> Scenarios <b>{scenarios.length}</b>
            </button>
          </div>
          <div className="panel-scroll">
            {activeTab === "why" && (
              <WhyPanel
                hex={selectedHex}
                terrain={selectedHex ? terrainByH3[selectedHex.h3] : undefined}
                onClear={() => { setSelectedHex(null); setActiveTab("compare"); }}
              />
            )}
            {activeTab === "compare" && <ComparisonView summary={summary} />}
            {activeTab === "scenarios" && (
              <ScenarioCards scenarios={scenarios} activeScenario={activeScenario} onHighlight={handleScenarioHighlight} />
            )}
          </div>
        </aside>
      </div>
    </main>
  );
}
