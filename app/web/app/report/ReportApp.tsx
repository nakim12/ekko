"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { followLookup, getReport, startLookup, type Job, type Report } from "@/lib/api";
import ReportView from "./ReportView";
import styles from "./report.module.css";

type State =
  | { kind: "idle" }
  | { kind: "working"; job: Job | null }
  | { kind: "report"; report: Report }
  | { kind: "error"; message: string };

const STAGES: Record<string, string> = {
  queued: "Waiting for a free worker",
  account: "Finding your account",
  rank: "Checking your rank",
  "match list": "Listing your ranked games",
  games: "Reading your games",
  matchmaking: "Looking up the players in your last 10 games",
  report: "Writing your report",
};

export default function ReportApp() {
  const params = useSearchParams();
  const router = useRouter();
  const [riotId, setRiotId] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });
  const stop = useRef<(() => void) | null>(null);

  // The URL is the source of truth for which report is shown (?r=<report id>), so a finished
  // lookup and a shared link take the same path.
  const linked = params.get("r");
  useEffect(() => {
    if (!linked) return;
    let cancelled = false;
    getReport(linked).then(
      (report) => !cancelled && setState({ kind: "report", report }),
      (e: Error) => !cancelled && setState({ kind: "error", message: e.message }),
    );
    return () => {
      cancelled = true;
    };
  }, [linked]);

  useEffect(() => () => stop.current?.(), []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    stop.current?.();
    setState({ kind: "working", job: null });
    try {
      const job = await startLookup(riotId.trim());
      setState({ kind: "working", job });
      stop.current = followLookup(
        job.id,
        (j) => {
          if (j.status === "done" && j.report_id) {
            const id = j.report_id;
            if (id === linked) {
              // Same (cached) report as the URL already names: the effect won't rerun, so load it here.
              getReport(id).then(
                (report) => setState({ kind: "report", report }),
                (e: Error) => setState({ kind: "error", message: e.message }),
              );
            } else {
              router.replace(`/report?r=${id}`, { scroll: false });
            }
          }
          else if (j.status === "failed") setState({ kind: "error", message: j.message ?? "The lookup failed." });
          else setState({ kind: "working", job: j });
        },
        () => setState({ kind: "error", message: "Lost the connection to the server. Try again." }),
      );
    } catch (err) {
      setState({ kind: "error", message: (err as Error).message });
    }
  }

  const busy = state.kind === "working";
  return (
    <>
      <section className={styles.lookup}>
        <div className={styles.eyebrow}>Your tilt report</div>
        <h1 className={styles.title}>
          Does your last game <em>ripple</em> into your next?
        </h1>
        <form className={styles.form} onSubmit={submit}>
          <label htmlFor="riot-id" className={styles.srOnly}>Riot ID</label>
          <input
            id="riot-id"
            className={styles.input}
            placeholder="name#tag"
            value={riotId}
            onChange={(e) => setRiotId(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            required
            pattern=".{3,16}#[^#]{2,5}"
            title="Riot IDs look like name#tag"
          />
          <button className={styles.button} type="submit" disabled={busy}>
            {busy ? "Looking…" : "Look up"}
          </button>
        </form>
        <p className={styles.hint}>NA ranked solo queue. Reads your last 100 games; takes a few minutes the first time.</p>
      </section>

      {state.kind === "working" && <Progress job={state.job} />}
      {state.kind === "error" && (
        <p className={styles.error} role="alert">
          {state.message}
        </p>
      )}
      {state.kind === "report" && <ReportView report={state.report} />}
    </>
  );
}

function Progress({ job }: { job: Job | null }) {
  const stage = job?.stage ?? "queued";
  const share = job && job.total ? job.done / job.total : null;
  return (
    <section className={styles.progress} aria-live="polite">
      <div className={styles.progressLabel}>
        <span>{STAGES[stage] ?? stage}</span>
        {job && job.total > 0 && (
          <span className={styles.progressCount}>
            {job.done} of {job.total}
          </span>
        )}
      </div>
      <div className={styles.track}>
        <div
          className={share === null ? styles.trackIndeterminate : styles.trackFill}
          style={share === null ? undefined : { transform: `scaleX(${share})` }}
        />
      </div>
    </section>
  );
}
