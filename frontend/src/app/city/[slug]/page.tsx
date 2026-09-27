"use client";

import { ArrowLeft, CircleHelp, GitCompareArrows, Layers3, ListChecks, Route, Search } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BrandMark } from "@/components/BrandMark";
import { BriefingViewer } from "@/components/BriefingViewer";
import { ChatPanel } from "@/components/ChatPanel";
import { ComparisonView } from "@/components/ComparisonView";
import { HexMap } from "@/components/HexMap";
import { ProgressScreen } from "@/components/ProgressScreen";
import { ScenarioCards } from "@/components/ScenarioCards";
import { WhyPanel } from "@/components/WhyPanel";
import { ApiError, briefingUrl, clearActiveJob, getCity, getCrashes, getJob } from "@/lib/api";
import { MAPS_API_KEY, POLL_MS, REFERENCE_LABEL } from "@/lib/constants";
import { getLiveTerrain, type LiveTerrain } from "@/lib/terrain";
import type { ChatAction, CityHex, CityResult, CrashesResponse, JobStatus, Scenario, UiState } from "@/lib/types";

type PanelTab = "why" | "compare" | "scenarios";
type Phase = "loading" | "progress" | "result" | "missing" | "error";
type CityPageContentProps = {
  slug: string;
  jobId: string | null;
};

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const NO_HIGHLIGHT: string[] = []; // stable identity, so the map doesn't rebuild its layers each render

/** Chat may only move the map inside this city's study area (mirrors the backend's fly_to check). */
function withinCity(summary: CityResult["summary"], lat: number, lng: number) {
  const dLat = (lat - summary.center.lat) * 110.54;
  const dLng = (lng - summary.center.lng) * 111.32 * Math.cos((summary.center.lat * Math.PI) / 180);
  return Math.hypot(dLat, dLng) <= summary.radius_km * 1.5;
}

export default function CityPage() {
  const { slug } = useParams<{ slug: string }>();
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");

  return <CityPageContent key={`${slug}:${jobId ?? "cached"}`} slug={slug} jobId={jobId} />;
}

function CityPageContent({ slug, jobId }: CityPageContentProps) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("loading");
  const [result, setResult] = useState<CityResult | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [message, setMessage] = useState("");
  const [selectedHex, setSelectedHex] = useState<CityHex | null>(null);
  const [activeTab, setActiveTab] = useState<PanelTab>("compare");
  const [activeScenario, setActiveScenario] = useState<string | null>(null);
  const [highlightedIds, setHighlightedIds] = useState<string[]>([]);
  const [terrainByH3, setTerrainByH3] = useState<Record<string, LiveTerrain | null>>({});
  const [crashes, setCrashes] = useState<CrashesResponse | null>(null);
  const [showCrashes, setShowCrashes] = useState(false);
  const [flyTo, setFlyTo] = useState<{ lat: number; lng: number; zoom: number; key: number } | null>(null);
  const terrainRequests = useRef(new Set<string>());
  const flyCommandId = useRef(0);

  useEffect(() => {
    let active = true;

    async function load() {
      if (jobId) {
        if (active) setPhase("progress");
        while (active) {
          try {
            const nextJob = await getJob(jobId);
            if (!active) return;
            setJob(nextJob);
            if (nextJob.status === "error" || nextJob.status === "cancelled") {
              clearActiveJob(nextJob.job_id);
              return;
            }
            if (nextJob.status === "done") {
              clearActiveJob(nextJob.job_id);
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
        return;
      }

      try {
        const city = await getCity(slug);
        if (!active) return;
        setResult(city);
        setPhase("result");
      } catch (caught) {
        if (!active) return;
        if (caught instanceof ApiError && caught.status === 404) {
          setPhase("missing");
          return;
        }
        setMessage(caught instanceof Error ? caught.message : "Could not load this city.");
        setPhase("error");
      }
    }

    load();
    return () => {
      active = false;
    };
  }, [jobId, slug]);

  useEffect(() => {
    if (phase !== "result" || result?.summary.slug !== slug) return;

    let active = true;
    void getCrashes(slug).then(
      (nextCrashes) => {
        if (!active) return;
        setCrashes(nextCrashes);
        setShowCrashes(false);
      },
      () => active && setCrashes(null),
    );
    return () => {
      active = false;
    };
  }, [phase, result?.summary.slug, slug]);

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

  const downloadBriefing = useCallback((format: "md" | "json") => {
    const link = document.createElement("a");
    link.href = briefingUrl(slug, format);
    link.download = `cityshift-${slug}-briefing.${format}`;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, [slug]);

  const dispatchChatActions = useCallback((actions: ChatAction[]) => {
    for (const action of actions) {
      try {
        switch (action.type) {
          case "select_hex": {
            if (typeof action.h3 !== "string") break;
            const hex = result?.hexes.find((candidate) => candidate.h3 === action.h3);
            if (!hex) break;
            setSelectedHex(hex);
            setActiveTab("why");
            break;
          }
          case "highlight_scenario": {
            if (typeof action.id !== "string") break;
            const scenario = result?.scenarios.find((candidate) => candidate.id === action.id);
            if (!scenario) break;
            setActiveScenario(scenario.id);
            setHighlightedIds(scenario.hex_ids);
            setActiveTab("scenarios");
            break;
          }
          case "open_panel":
            if (action.panel === "comparison") setActiveTab("compare");
            else if (action.panel === "why" || action.panel === "scenarios") setActiveTab(action.panel);
            break;
          case "toggle_crashes":
            if (typeof action.on === "boolean" && crashes?.slug === slug && crashes.available) setShowCrashes(action.on);
            break;
          case "fly_to":
            if (
              Number.isFinite(action.lat) && action.lat >= -90 && action.lat <= 90
              && Number.isFinite(action.lng) && action.lng >= -180 && action.lng <= 180
              && Number.isFinite(action.zoom) && action.zoom >= 3 && action.zoom <= 20
              && result && withinCity(result.summary, action.lat, action.lng)
            ) {
              flyCommandId.current += 1;
              setFlyTo({ lat: action.lat, lng: action.lng, zoom: action.zoom, key: flyCommandId.current });
            }
            break;
          case "open_city":
            if (typeof action.slug === "string" && /^[a-z0-9-]+$/.test(action.slug)) router.push(`/city/${action.slug}`);
            break;
          case "download_briefing":
            if (action.format === "md" || action.format === "json") downloadBriefing(action.format);
            break;
          default:
            break;
        }
      } catch {
        // A malformed model action must never interrupt the core city page.
      }
    }
  }, [crashes, downloadBriefing, result, router, slug]);

  // Scenario areas are a Scenarios-tab view: leaving the tab clears the blue (cards unmount without blurring).
  const mapHighlightIds = activeTab === "scenarios" ? highlightedIds : NO_HIGHLIGHT;
  const cityLabel = useMemo(() => slug.replaceAll("-", " "), [slug]);
  const cityCrashes = crashes?.slug === slug ? crashes : null;
  const chatUiState = useMemo<UiState>(() => ({
    selected_hex: selectedHex?.h3 ?? null,
    open_panel: activeTab === "compare" ? "comparison" : activeTab,
    crashes_on: showCrashes,
  }), [activeTab, selectedHex?.h3, showCrashes]);

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
        <BrandMark />
        <div className="analysis-actions">
          <Link href="/ride" className="ride-access"><Route size={16} /> Plan a ride</Link>
          <Link href="/" className="new-search"><Search size={15} /> <span>New city</span></Link>
        </div>
      </header>

      <section className="summary-strip">
        <div className="summary-title">
          <p className="summary-context">Compared with {REFERENCE_LABEL}</p>
          <h1>{summary.city}</h1>
        </div>
        <div className="summary-metric"><small>Study area</small><b>{summary.radius_km} km</b></div>
        <div className="summary-metric"><small>Mapped areas</small><b>{summary.n_hexes}</b></div>
        <div className="summary-metric summary-alert"><small>Strong shift</small><b>{summary.pct_red.toFixed(1)}%</b><span>of mapped areas</span></div>
        <div className="summary-actions">
          <div className="report-callout">
            <span>Train your own model? <b aria-hidden="true">→</b></span>
            <BriefingViewer cityName={summary.city} slug={slug} onDownload={downloadBriefing} />
          </div>
        </div>
      </section>

      <div className="analysis-workspace">
        <section className="map-column">
          <div className="map-toolbar">
            <div><Layers3 size={15} /><b>Shift surface</b><span>{mapHighlightIds.length ? `${mapHighlightIds.length} scenario areas highlighted` : "Select an area for evidence"}</span></div>
          </div>
          <HexMap
            center={summary.center}
            hexes={hexes}
            selectedHex={selectedHex}
            highlightedIds={mapHighlightIds}
            crashes={cityCrashes}
            showCrashes={showCrashes}
            flyTo={flyTo}
            onToggleCrashes={() => setShowCrashes((current) => !current)}
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
                crashes={cityCrashes}
                onClear={() => { setSelectedHex(null); setActiveTab("compare"); }}
              />
            )}
            {activeTab === "compare" && <ComparisonView summary={summary} />}
            {activeTab === "scenarios" && (
              <ScenarioCards scenarios={scenarios} activeScenario={activeScenario} onHighlight={handleScenarioHighlight} />
            )}
          </div>
          <ChatPanel key={slug} cityName={summary.city} slug={slug} uiState={chatUiState} onActions={dispatchChatActions} />
        </aside>
      </div>
    </main>
  );
}
