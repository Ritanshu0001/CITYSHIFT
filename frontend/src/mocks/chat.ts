import type { ChatAction, ChatMessage, ChatResponse, UiState } from "@/lib/types";

const CITY_FIXTURES: Record<string, {
  name: string;
  pctRed: number;
  nHexes: number;
  redH3: string;
  redCenter: [number, number];
  topScenario: string;
  topScenarioTitle: string;
  movableBridge?: { h3: string; center: [number, number] };
}> = {
  "new-york-ny-usa": {
    name: "New York, NY, USA", pctRed: 30.4, nHexes: 227,
    redH3: "882a100d63fffff", redCenter: [40.7529686, -73.9708647],
    topScenario: "snow_traction", topScenarioTitle: "Reduced traction + hidden lane markings",
  },
  "miami-fl-usa": {
    name: "Miami, FL, USA", pctRed: 18.0, nHexes: 172,
    redH3: "8844a11287fffff", redCenter: [25.7656331, -80.1943584],
    topScenario: "roundabout_or_tunnel",
    topScenarioTitle: "Multi-lane roundabout entry; GPS loss and lighting change in a tunnel",
    movableBridge: { h3: "8844a110ddfffff", center: [25.7934726, -80.1836908] },
  },
  "london-uk": {
    name: "London, UK", pctRed: 46.3, nHexes: 300,
    redH3: "88194ad143fffff", redCenter: [51.4843603, -0.1175504],
    topScenario: "left_hand_traffic",
    topScenarioTitle: "Mirrored turn logic; turns across oncoming traffic",
  },
};

const FALLBACK_CITY = CITY_FIXTURES["new-york-ny-usa"];

function response(reply: string, actions: ChatAction[] = []): ChatResponse {
  return { reply, actions, model: "mock-cityshift", fallback: false };
}

export async function mockChat(slug: string, messages: ChatMessage[], _uiState: UiState): Promise<ChatResponse> {
  void _uiState;
  await new Promise((resolve) => window.setTimeout(resolve, 520));
  const city = CITY_FIXTURES[slug] ?? FALLBACK_CITY;
  const prompt = messages.at(-1)?.text.toLowerCase() ?? "";

  if (prompt.includes("train") || prompt.includes("waymo's model") || prompt.includes("waymo model")) {
    return response("No. CityShift does **not** train Waymo’s models and does not use Waymo’s internal systems. It turns public city data into candidate test plans; red means unfamiliar to the car, not dangerous.");
  }
  if (prompt.includes("download") || prompt.includes("briefing")) {
    return response("I’m downloading the Markdown city readiness briefing. It contains the public-data evidence, candidate scenarios, and limitations.", [
      { type: "download_briefing", format: "md" },
    ]);
  }
  if ((prompt.includes("drawbridge") || prompt.includes("movable bridge")) && city.movableBridge) {
    const [lat, lng] = city.movableBridge.center;
    return response("I selected a Miami area with a recorded movable bridge and moved the map there. The Why panel shows the evidence for that area.", [
      { type: "select_hex", h3: city.movableBridge.h3 },
      { type: "fly_to", lat, lng, zoom: 14 },
    ]);
  }
  if (prompt.includes("crash")) {
    if (slug === "london-uk") {
      return response("NHTSA FARS covers US cities only, so fatal-crash dots are not available for London.", [
        { type: "open_panel", panel: "why" },
      ]);
    }
    return response("I turned on the fatal-crash context layer. These dots show recorded fatal crashes from NHTSA FARS 2020–24 and are not part of the shift score.", [
      { type: "toggle_crashes", on: true },
    ]);
  }
  if (prompt.includes("top scenario") || (prompt.includes("show") && prompt.includes("scenario"))) {
    return response(`The highest-priority candidate is **${city.topScenarioTitle}**. I opened and highlighted its mapped areas.`, [
      { type: "highlight_scenario", id: city.topScenario },
    ]);
  }
  if (prompt.includes("open") && prompt.includes("scenario")) {
    return response("I opened the candidate scenarios panel.", [
      { type: "open_panel", panel: "scenarios" },
    ]);
  }
  if (prompt.includes("why") || prompt.includes("reddest") || prompt.includes("red area")) {
    const [lat, lng] = city.redCenter;
    return response("I selected the highest-shift area and opened its evidence. Its score reflects how unusual its top public-data features are relative to Waymo’s established cities.", [
      { type: "select_hex", h3: city.redH3 },
      { type: "fly_to", lat, lng, zoom: 14 },
    ]);
  }

  return response(`**${city.name}** has **${city.pctRed.toFixed(1)}%** strong-shift areas across **${city.nHexes} mapped areas**. The map ranks unfamiliar public-road conditions relative to Waymo’s established cities; it does not measure danger.`, [
    { type: "open_panel", panel: "comparison" },
  ]);
}
