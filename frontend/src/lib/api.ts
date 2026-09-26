import mockCitiesJson from "@/mocks/cities.json";
import mockCrashesJson from "@/mocks/crashes.json";
import { mockChat } from "@/mocks/chat";
import mockJobJson from "@/mocks/job.json";
import mockResultJson from "@/mocks/result.json";
import { API_BASE, JOB_STEPS, USE_CHAT_MOCK, USE_MOCK } from "./constants";
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ChatMessage,
  ChatResponse,
  CitiesResponse,
  CityResult,
  CrashesResponse,
  JobStatus,
  UiState,
} from "./types";

const mockCities = mockCitiesJson as CitiesResponse;
const mockCrashes = mockCrashesJson as Record<string, CrashesResponse>;
const mockResult = mockResultJson as CityResult;
const mockJob = mockJobJson as JobStatus;
let mockPollCount = 0;
let mockInProgress = false;
const MOCK_JOB_KEY = "cityshift:mock-job";
const ACTIVE_JOB_KEY = "cityshift:active-job";

function activeJobId() {
  return typeof window === "undefined" ? null : window.sessionStorage.getItem(ACTIVE_JOB_KEY);
}

function rememberActiveJob(jobId: string) {
  if (typeof window !== "undefined") window.sessionStorage.setItem(ACTIVE_JOB_KEY, jobId);
}

export function clearActiveJob(jobId: string) {
  if (typeof window !== "undefined" && activeJobId() === jobId) {
    window.sessionStorage.removeItem(ACTIVE_JOB_KEY);
  }
}

function mockJobIsRunning() {
  if (typeof window === "undefined") return mockInProgress;
  return window.sessionStorage.getItem(MOCK_JOB_KEY) === "running";
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function pause(ms = 260) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      message = payload.detail ?? message;
    } catch {
      // Keep the status-based message when the server has no JSON body.
    }
    throw new ApiError(response.status, message);
  }

  return (await response.json()) as T;
}

export async function analyze(payload: AnalyzeRequest): Promise<AnalyzeResponse> {
  const supersedesJobId = activeJobId();
  const request = supersedesJobId ? { ...payload, supersedes_job_id: supersedesJobId } : payload;
  if (USE_MOCK) {
    await pause();
    mockPollCount = 0;
    mockInProgress = true;
    if (typeof window !== "undefined") window.sessionStorage.setItem(MOCK_JOB_KEY, "running");
    const response: AnalyzeResponse = {
      job_id: "demo-city-analysis",
      slug: mockResult.summary.slug,
      status: "queued",
      cached: false,
    };
    rememberActiveJob(response.job_id);
    return response;
  }

  const response = await fetchJson<AnalyzeResponse>("/analyze", {
    method: "POST",
    body: JSON.stringify(request),
  });
  rememberActiveJob(response.job_id);
  return response;
}

export async function getJob(jobId: string): Promise<JobStatus> {
  if (USE_MOCK) {
    await pause(380);
    mockPollCount += 1;
    const completed = JOB_STEPS.slice(0, Math.min(mockPollCount, JOB_STEPS.length));
    const isDone = mockPollCount >= JOB_STEPS.length;
    if (isDone) {
      mockInProgress = false;
      if (typeof window !== "undefined") window.sessionStorage.removeItem(MOCK_JOB_KEY);
    }
    return {
      ...mockJob,
      job_id: jobId,
      status: isDone ? "done" : "running",
      step: isDone ? null : JOB_STEPS[mockPollCount] ?? JOB_STEPS.at(-1)!,
      steps_done: completed,
      message: isDone ? "Analysis ready" : "Comparing public city signals…",
    };
  }

  return fetchJson<JobStatus>(`/jobs/${encodeURIComponent(jobId)}`);
}

export async function getCities(): Promise<CitiesResponse> {
  if (USE_MOCK) {
    await pause();
    if (mockJobIsRunning()) throw new ApiError(404, "not cached");
    return mockCities;
  }
  return fetchJson<CitiesResponse>("/cities");
}

export async function getCity(slug: string): Promise<CityResult> {
  if (USE_MOCK) {
    await pause();
    if (slug !== mockResult.summary.slug && !slug.startsWith("demo-")) {
      throw new ApiError(404, "not cached");
    }
    return mockResult;
  }
  return fetchJson<CityResult>(`/cities/${encodeURIComponent(slug)}`);
}

export async function getCrashes(slug: string): Promise<CrashesResponse> {
  if (USE_MOCK) {
    await pause(120);
    return mockCrashes[slug] ?? mockCrashes["london-uk"];
  }
  return fetchJson<CrashesResponse>(`/cities/${encodeURIComponent(slug)}/crashes`);
}

export async function postChat(slug: string, messages: ChatMessage[], uiState: UiState): Promise<ChatResponse> {
  if (USE_CHAT_MOCK) return mockChat(slug, messages, uiState);
  return fetchJson<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({ slug, messages, ui_state: uiState }),
  });
}

export function briefingUrl(slug: string, format: "md" | "json") {
  return `${API_BASE}/cities/${encodeURIComponent(slug)}/briefing.${format}`;
}
