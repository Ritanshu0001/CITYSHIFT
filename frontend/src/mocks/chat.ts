import { cellToLatLng } from "h3-js";
import { compactNumber, featureLabel, REFERENCE_LABEL } from "@/lib/constants";
import type { ChatAction, ChatMessage, ChatResponse, CityHex, CityResult, UiState } from "@/lib/types";

// Facts come from the active city's own result, so every answer and map action stays in that
// city. (A fixed New York fallback used to fly other cities' maps to Manhattan.)
interface CityFacts {
  name: string;
  shortName: string;
  pctRed: number;
  nHexes: number;
  hexes: Map<string, CityHex>;
  reddest: { h3: string; center: [number, number] } | null;
  topScenario: { id: string; title: string } | null;
  movableBridge: { h3: string; center: [number, number] } | null;
  usCrashData: boolean;
}

const factsCache = new Map<string, Promise<CityFacts>>();

function toFacts(result: CityResult): CityFacts {
  const { summary, hexes, scenarios } = result;
  const reddest = hexes.reduce<CityResult["hexes"][number] | null>(
    (best, hex) => (!best || hex.shift_score > best.shift_score ? hex : best), null);
  const top = scenarios.reduce<CityResult["scenarios"][number] | null>(
    (best, s) => (!best || s.priority > best.priority ? s : best), null);
  const bridge = hexes.find((hex) => hex.novel.includes("movable_bridge_count")
    || hex.top_features.some((f) => f.name === "movable_bridge_count" && f.value > 0));
  return {
    name: summary.city,
    shortName: summary.city.split(",")[0],
    pctRed: summary.pct_red,
    nHexes: summary.n_hexes,
    hexes: new Map(hexes.map((hex) => [hex.h3, hex])),
    reddest: reddest ? { h3: reddest.h3, center: cellToLatLng(reddest.h3) } : null,
    topScenario: top ? { id: top.id, title: top.title } : null,
    movableBridge: bridge ? { h3: bridge.h3, center: cellToLatLng(bridge.h3) } : null,
    usCrashData: /,\s*USA$/.test(summary.city),
  };
}

function cityFacts(slug: string): Promise<CityFacts> {
  let facts = factsCache.get(slug);
  if (!facts) {
    // Imported lazily: lib/api imports this module, so a static import would be circular.
    facts = import("@/lib/api").then(({ getCity }) => getCity(slug)).then(toFacts);
    facts.catch(() => factsCache.delete(slug));
    factsCache.set(slug, facts);
  }
  return facts;
}

function response(reply: string, actions: ChatAction[] = []): ChatResponse {
  return { reply, actions, model: "mock-cityshift", fallback: false };
}

/** The evidence behind one area's score, in words: its strongest signals and any novel features. */
function explainHex(hex: CityHex, lead: string) {
  const signals = hex.top_features.map((f) => {
    const direction = f.z >= 0 ? "high" : "low";
    const reference = f.ref_median > 0 ? `reference ${compactNumber(f.ref_median)}` : "most reference areas have none";
    return `- **${featureLabel(f.name)}: ${compactNumber(f.value)}** is unusually ${direction}. It sits at the ${f.pct.toFixed(1)}th percentile; ${reference}.`;
  });
  const novel = hex.novel.length
    ? `\n\nIt also has **${hex.novel.map(featureLabel).join(", ")}**, which are rare across ${REFERENCE_LABEL}.`
    : "";
  return [
    `${lead} It scores **${hex.shift_score.toFixed(1)}/100**, meaning it is more unusual than ${hex.shift_score.toFixed(1)}% of areas across ${REFERENCE_LABEL}. The strongest signals:`,
    "",
    ...signals,
    novel,
    "",
    "Red means unfamiliar to the car, not dangerous.",
  ].join("\n");
}

export async function mockChat(slug: string, messages: ChatMessage[], uiState: UiState): Promise<ChatResponse> {
  const [city] = await Promise.all([cityFacts(slug), new Promise((resolve) => window.setTimeout(resolve, 520))]);
  const prompt = messages.at(-1)?.text.toLowerCase() ?? "";

  // "Why is this area red?" with an area already selected explains that area, not the reddest one.
  const selected = uiState.selected_hex ? city.hexes.get(uiState.selected_hex) : undefined;
  if (selected && prompt.includes("why") && /\b(this|selected|here)\b/.test(prompt)) {
    return response(explainHex(selected, "Here’s why the selected area stands out."), [
      { type: "open_panel", panel: "why" },
    ]);
  }

  if (prompt.includes("train") || prompt.includes("waymo's model") || prompt.includes("waymo model")) {
    return response("No. CityShift does **not** train Waymo’s models and does not use Waymo’s internal systems. It turns public city data into candidate test plans; red means unfamiliar to the car, not dangerous.");
  }
  if (prompt.includes("download") || prompt.includes("briefing")) {
    return response("I’m downloading the Markdown city readiness briefing. It contains the public-data evidence, candidate scenarios, and limitations.", [
      { type: "download_briefing", format: "md" },
    ]);
  }
  if (prompt.includes("drawbridge") || prompt.includes("movable bridge")) {
    if (!city.movableBridge) {
      return response(`OpenStreetMap records no movable bridges in the mapped ${city.shortName} area.`);
    }
    const [lat, lng] = city.movableBridge.center;
    return response(`I selected a ${city.shortName} area with a recorded movable bridge and moved the map there. The Why panel shows the evidence for that area.`, [
      { type: "select_hex", h3: city.movableBridge.h3 },
      { type: "fly_to", lat, lng, zoom: 14 },
    ]);
  }
  if (prompt.includes("crash")) {
    if (!city.usCrashData) {
      return response(`NHTSA FARS covers US cities only, so fatal-crash dots are not available for ${city.shortName}.`, [
        { type: "open_panel", panel: "why" },
      ]);
    }
    return response("I turned on the fatal-crash context layer. These dots show recorded fatal crashes from NHTSA FARS 2020–24 and are not part of the shift score.", [
      { type: "toggle_crashes", on: true },
    ]);
  }
  if ((prompt.includes("top scenario") || (prompt.includes("show") && prompt.includes("scenario"))) && city.topScenario) {
    return response(`The highest-priority candidate is **${city.topScenario.title}**. I opened and highlighted its mapped areas.`, [
      { type: "highlight_scenario", id: city.topScenario.id },
    ]);
  }
  if (prompt.includes("open") && prompt.includes("scenario")) {
    return response("I opened the candidate scenarios panel.", [
      { type: "open_panel", panel: "scenarios" },
    ]);
  }
  const reddestHex = city.reddest ? city.hexes.get(city.reddest.h3) : undefined;
  if ((prompt.includes("why") || prompt.includes("reddest") || prompt.includes("red area")) && city.reddest && reddestHex) {
    const [lat, lng] = city.reddest.center;
    return response(explainHex(reddestHex, `I’ve selected ${city.shortName}’s highest-shift area on the map.`), [
      { type: "select_hex", h3: city.reddest.h3 },
      { type: "fly_to", lat, lng, zoom: 14 },
    ]);
  }

  return response(`**${city.name}** has **${city.pctRed.toFixed(1)}%** strong-shift areas across **${city.nHexes} mapped areas**. The map ranks unfamiliar public-road conditions relative to Waymo’s established cities; it does not measure danger.`, [
    { type: "open_panel", panel: "comparison" },
  ]);
}
