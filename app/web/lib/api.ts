// Client for the FastAPI backend (app/api), proxied at /api by next.config.ts.

export type JobStatus = "queued" | "running" | "done" | "failed";

export type Job = {
  id: string;
  display_riot_id: string;
  status: JobStatus;
  stage: string | null;
  done: number;
  total: number;
  message: string | null;
  report_id: string | null;
};

export type Interval = { estimate: number; low: number; high: number; n: number };

export type Report = {
  report_id: string;
  riot_id: string;
  generated_at: string;
  rank: { tier: string | null; division: string | null; league_points: number | null };
  tier_group: string | null;
  games_analyzed: number;
  priors_are_placeholders: boolean;
  tilt: {
    games_used: number;
    tier_average: number;
    gold_per_sd: number;
    prior_is_placeholder: boolean;
    raw: Interval | null;
    shrunk: Interval | null;
    gold_equivalent: number | null;
    supported: boolean;
    direction?: string;
    reason?: string;
  };
  cooldown: {
    quick_requeue: Interval | null;
    after_a_break: Interval | null;
    supported: boolean;
  };
  stop_rule: {
    after_losses_in_a_row: number;
    games: number;
    win_rate: number | null;
    low: number;
    high: number;
    overall_win_rate: number;
    supported: boolean;
  };
  matchmaking: {
    games: number;
    mean_gap_lp: number | null;
    low: number | null;
    high: number | null;
    caveat: string;
    supported: boolean;
  };
  history: { start_ms: number; win: boolean; session: boolean; z: number | null }[];
  coach?: {
    summary: string;
    findings: { text: string; fact_ids: string[] }[];
    recommendations: { action: string; text: string; fact_ids: string[] }[];
    source: "model" | "template";
  };
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status}).`);
  }
  return res.json() as Promise<T>;
}

export async function startLookup(riotId: string): Promise<Job> {
  return json<Job>(
    await fetch("/api/lookups", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ riot_id: riotId }),
    }),
  );
}

export async function getReport(reportId: string): Promise<Report> {
  return json<Report>(await fetch(`/api/reports/${encodeURIComponent(reportId)}`));
}

/** Server-sent progress until the job is done or failed. Returns a function that stops listening. */
export function followLookup(jobId: string, onJob: (job: Job) => void, onError: () => void): () => void {
  const source = new EventSource(`/api/lookups/${encodeURIComponent(jobId)}/events`);
  source.onmessage = (e) => {
    const job = JSON.parse(e.data) as Job;
    onJob(job);
    if (job.status === "done" || job.status === "failed") source.close();
  };
  source.onerror = () => {
    source.close();
    onError();
  };
  return () => source.close();
}
