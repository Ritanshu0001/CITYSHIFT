import { JOB_STEPS, JOB_STEP_LABELS } from "./constants";
import type { JobLogLine, JobStatus } from "./types";

const TAG_STYLE = "color:#fff;background:#1f6fff;border-radius:3px;padding:1px 5px;font-weight:600";
const STALL_NOTICE_S = 15;

function say(method: "log" | "warn" | "error", text: string, ...extra: unknown[]) {
  console[method](`%cCityShift%c ${text}`, TAG_STYLE, "", ...extra);
}

/**
 * Mirrors a city analysis job into the browser console (CR-019): every backend log line
 * with its time since submit, a notice when a step goes quiet, and a per-step timing
 * table when the job ends.
 */
export function createJobConsole(slug: string, jobId: string) {
  let lastSeq = 0;
  let announced = false;
  let finished = false;
  let quietSince = Date.now();
  let lastNotice = 0;

  // The job's own id and "[slug]" prefixes help in the server terminal, not here.
  const tidy = (message: string) =>
    message.replace(/^job [0-9a-f]+: /, "").replace(`[${slug}] `, "");

  function print(line: JobLogLine) {
    const text = `+${line.t.toFixed(1)}s ${line.source}: ${tidy(line.message)}`;
    if (line.level === "ERROR" || line.level === "CRITICAL") say("error", text);
    else if (line.level === "WARNING") say("warn", text);
    else say("log", text);
  }

  function summarize(job: JobStatus) {
    const total = job.elapsed_s != null ? ` after ${job.elapsed_s.toFixed(1)}s` : "";
    const step = job.step ? JOB_STEP_LABELS[job.step] : null;
    if (job.status === "done") say("log", `${slug} ready${total}`);
    else if (job.status === "cancelled") say("warn", `${slug} cancelled${total}: ${job.message ?? "replaced by a newer search"}`);
    else say("error", `${slug} failed${step ? ` during "${step}"` : ""}${total}: ${job.error ?? "unknown error"}`);

    const rows: Record<string, { seconds: number }> = {};
    for (const s of JOB_STEPS) {
      const seconds = job.step_elapsed_s?.[s];
      if (seconds != null) rows[JOB_STEP_LABELS[s]] = { seconds: Math.round(seconds * 10) / 10 };
    }
    if (Object.keys(rows).length) {
      say("log", "Step times (wall clock; roads, infrastructure and weather download in parallel, "
        + "so each download's own time is in its \"done in\" line above):");
      console.table(rows);
    }
  }

  return {
    update(job: JobStatus) {
      if (!announced) {
        announced = true;
        say("log", `Analyzing ${slug} (job ${jobId}). Backend log follows; times are since the search started.`);
      }

      const fresh = (job.logs ?? []).filter((line) => line.seq > lastSeq);
      if (fresh.length) {
        fresh.forEach(print);
        lastSeq = fresh[fresh.length - 1].seq;
        quietSince = Date.now();
      }

      const now = Date.now();
      if ((job.status === "running" || job.status === "queued")
        && now - quietSince >= STALL_NOTICE_S * 1000 && now - lastNotice >= STALL_NOTICE_S * 1000) {
        lastNotice = now;
        const where = job.status === "queued" ? "Still queued behind another city"
          : job.step ? `Still on "${JOB_STEP_LABELS[job.step]}" (${(job.step_elapsed_s?.[job.step] ?? 0).toFixed(0)}s in this step)`
            : "Still running";
        say("log", `${where}, ${(job.elapsed_s ?? 0).toFixed(0)}s total; `
          + `no backend output for ${Math.round((now - quietSince) / 1000)}s`);
      }

      if (!finished && (job.status === "done" || job.status === "error" || job.status === "cancelled")) {
        finished = true;
        summarize(job);
      }
    },

    pollFailed(error: unknown) {
      say("warn", `Lost contact with the backend while polling job ${jobId}`, error);
    },
  };
}
