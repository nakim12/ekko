import type { Interval, Report } from "@/lib/api";
import styles from "./report.module.css";

const gold = (n: number) => `${Math.abs(Math.round(n)).toLocaleString("en-US")} gold`;
const pct = (x: number) => `${Math.round(x * 100)}%`;
const lp = (n: number) => `${Math.abs(Math.round(n))} LP`;
const MIN_STOP_RULE_GAMES = 10; // same threshold as stats.stop_rule in the API

export default function ReportView({ report }: { report: Report }) {
  const { rank } = report;
  const rankLabel = rank.tier
    ? `${rank.tier[0]}${rank.tier.slice(1).toLowerCase()}${rank.division && !["MASTER", "GRANDMASTER", "CHALLENGER"].includes(rank.tier) ? ` ${rank.division}` : ""}`
    : "Unranked";
  return (
    <section className={styles.report}>
      <header className={styles.reportHead}>
        <h2 className={styles.riotId}>{report.riot_id}</h2>
        <p className={styles.meta}>
          {rankLabel} · {report.games_analyzed} ranked games · {new Date(report.generated_at).toLocaleDateString()}
        </p>
      </header>

      {report.priors_are_placeholders && (
        <p className={styles.notice}>
          Preview. Comparisons with players at your rank use placeholder averages until the study&apos;s results
          are in, so treat them as rough.
        </p>
      )}

      {report.coach && <Coach coach={report.coach} />}

      <History history={report.history} />

      <div className={styles.cards}>
        <Tilt report={report} />
        <Cooldown report={report} />
        <StopRule report={report} />
        <Matchmaking report={report} />
      </div>
    </section>
  );
}

function Card({ eyebrow, title, children }: { eyebrow: string; title: React.ReactNode; children: React.ReactNode }) {
  return (
    <article className={styles.card}>
      <div className={styles.eyebrow}>{eyebrow}</div>
      <h3 className={styles.cardTitle}>{title}</h3>
      {children}
    </article>
  );
}

/** An interval on a symmetric axis around zero, in the units given by `format`. */
function IntervalLine({
  iv,
  scale,
  format,
  marker,
  highlight,
  ends = ["worse", "better"],
}: {
  iv: Interval;
  scale: number;
  format: (n: number) => string;
  marker?: { value: number; label: string };
  highlight?: boolean;
  /** Words after the axis end values, e.g. ["worse", "better"]. */
  ends?: [string, string];
}) {
  const pos = (v: number) => `${50 + (Math.max(-scale, Math.min(scale, v)) / scale) * 50}%`;
  return (
    <div className={styles.interval} aria-label={`${format(iv.estimate)}, interval ${format(iv.low)} to ${format(iv.high)}`}>
      <div className={styles.axis} />
      <div className={styles.zero} style={{ left: "50%" }} />
      {marker && <div className={styles.marker} style={{ left: pos(marker.value) }} title={marker.label} />}
      <div
        className={highlight ? styles.rangeGold : styles.range}
        style={{ left: pos(iv.low), width: `calc(${pos(iv.high)} - ${pos(iv.low)})` }}
      />
      <div className={highlight ? styles.pointGold : styles.point} style={{ left: pos(iv.estimate) }} />
      <div className={styles.axisLabels}>
        <span>
          {format(-scale)} {ends[0]}
        </span>
        <span>even</span>
        <span>
          {format(scale)} {ends[1]}
        </span>
      </div>
    </div>
  );
}

function Tilt({ report }: { report: Report }) {
  const t = report.tilt;
  const g = t.gold_per_sd;
  if (!t.shrunk) {
    return (
      <Card eyebrow="Tilt" title="Not enough games to say">
        <p className={styles.body}>You need more games played back to back, after both wins and losses.</p>
      </Card>
    );
  }
  const s = t.shrunk;
  const title = !t.supported ? (
    <>No clear drop after a loss</>
  ) : s.estimate < 0 ? (
    <>
      After a loss, you start about <em>{gold(s.estimate * g)}</em> behind
    </>
  ) : (
    <>
      After a loss, you start about <em>{gold(s.estimate * g)}</em> ahead
    </>
  );
  return (
    <Card eyebrow="Tilt" title={title}>
      <IntervalLine
        iv={{ ...s, estimate: s.estimate * g, low: s.low * g, high: s.high * g }}
        scale={Math.max(600, Math.ceil(Math.max(Math.abs(s.low), Math.abs(s.high)) * g / 100) * 100)}
        format={gold}
        marker={{ value: t.tier_average * g, label: "players at your rank" }}
        highlight={t.supported}
      />
      <p className={styles.body}>
        Gold lead over your lane opponent at 14 minutes, in the game right after a loss compared with your usual,
        from {t.games_used} back-to-back games.{" "}
        {t.supported
          ? "The whole range sits on one side of zero."
          : "The range includes zero, so there's no reliable difference."}{" "}
        Small samples are pulled toward the average for your rank.
      </p>
    </Card>
  );
}

function Cooldown({ report }: { report: Report }) {
  const c = report.cooldown;
  const g = report.tilt.gold_per_sd;
  const rows: [string, Interval | null][] = [
    ["Queued again within 15 minutes", c.quick_requeue],
    ["After a 15-minute to 6-hour break", c.after_a_break],
  ];
  return (
    <Card eyebrow="Cooldown" title={c.supported ? <>A short break <em>helps</em></> : <>Breaks: no clear pattern yet</>}>
      {rows.map(([label, iv]) => (
        <div key={label} className={styles.row}>
          <div className={styles.rowLabel}>{label}</div>
          {iv ? (
            <IntervalLine
              iv={{ ...iv, estimate: iv.estimate * g, low: iv.low * g, high: iv.high * g }}
              scale={1200}
              format={gold}
              highlight={c.supported}
            />
          ) : (
            <p className={styles.small}>Not enough games.</p>
          )}
        </div>
      ))}
      <p className={styles.body}>How a loss affects your next game, depending on how soon you queue again.</p>
    </Card>
  );
}

function StopRule({ report }: { report: Report }) {
  const r = report.stop_rule;
  if (r.games < MIN_STOP_RULE_GAMES || r.win_rate === null) {
    return (
      <Card eyebrow="Stop rule" title="Not enough losing streaks to say">
        <p className={styles.body}>
          You&apos;ve played {r.games} {r.games === 1 ? "game" : "games"} right after losing{" "}
          {r.after_losses_in_a_row} in a row in the same session. It takes at least {MIN_STOP_RULE_GAMES} to say
          anything about them.
        </p>
      </Card>
    );
  }
  return (
    <Card
      eyebrow="Stop rule"
      title={
        r.supported ? (
          <>
            Consider <em>stopping</em> after {r.after_losses_in_a_row} losses in a row
          </>
        ) : (
          <>No reason to stop after {r.after_losses_in_a_row} losses</>
        )
      }
    >
      <div className={styles.stat}>
        <span className={styles.statBig}>{pct(r.win_rate)}</span>
        <span className={styles.small}>
          won after {r.after_losses_in_a_row} losses in a row ({r.games} games, range {pct(r.low)} to {pct(r.high)}),
          against {pct(r.overall_win_rate)} overall
        </span>
      </div>
      <p className={styles.body}>
        {r.supported
          ? "Even the top of the range is below your usual win rate."
          : "The range overlaps your usual win rate, so these games aren't clearly worse."}
      </p>
    </Card>
  );
}

function Matchmaking({ report }: { report: Report }) {
  const m = report.matchmaking;
  return (
    <Card eyebrow="Matchmaking check" title={<>Your last {m.games} games</>}>
      {m.mean_gap_lp !== null && m.low !== null && m.high !== null ? (
        <>
          <IntervalLine
            iv={{ estimate: m.mean_gap_lp, low: m.low, high: m.high, n: m.games }}
            scale={Math.max(200, Math.ceil(Math.max(Math.abs(m.low), Math.abs(m.high)) / 100) * 100)}
            format={lp}
            ends={["weaker team", "stronger team"]}
          />
          <p className={styles.body}>
            Your teammates averaged {lp(m.mean_gap_lp)} {m.mean_gap_lp >= 0 ? "above" : "below"} your opponents,
            by their current rank.
          </p>
        </>
      ) : (
        <p className={styles.body}>Too few ranked players in your recent games to compare.</p>
      )}
      <p className={styles.small}>
        {m.caveat} <a href="/#questions">See the study</a>.
      </p>
    </Card>
  );
}

function Coach({ coach }: { coach: NonNullable<Report["coach"]> }) {
  return (
    <section className={styles.coach}>
      <div className={styles.eyebrow}>The short version</div>
      <p className={styles.coachSummary}>{coach.summary}</p>
      <ul className={styles.coachList}>
        {coach.findings.map((f) => (
          <li key={f.text}>{f.text}</li>
        ))}
      </ul>
      {coach.recommendations.length > 0 && (
        <div className={styles.coachRecs}>
          {coach.recommendations.map((r) => (
            <p key={r.text}>
              <span className={styles.coachArrow} aria-hidden="true">→</span> {r.text}
            </p>
          ))}
        </div>
      )}
      <p className={styles.small}>
        {coach.source === "model"
          ? "Written by Claude from your numbers, then checked: every number matches your report, and nothing is claimed that the data doesn't support."
          : "A standard summary of your numbers."}
      </p>
    </section>
  );
}

function History({ history }: { history: Report["history"] }) {
  const wins = history.filter((g) => g.win).length;
  return (
    <div className={styles.history}>
      <div className={styles.historyHead}>
        <span className={styles.eyebrow}>Your games, oldest first</span>
        <span className={styles.small}>
          {wins} wins, {history.length - wins} losses · gaps are breaks of an hour or more
        </span>
      </div>
      <div className={styles.pips}>
        {history.map((g, i) => (
          <span
            key={g.start_ms}
            className={`${styles.pip} ${g.win ? styles.win : styles.loss} ${g.session && i > 0 ? styles.newSession : ""}`}
            title={`${new Date(g.start_ms).toLocaleString()} · ${g.win ? "win" : "loss"}`}
          />
        ))}
      </div>
    </div>
  );
}
