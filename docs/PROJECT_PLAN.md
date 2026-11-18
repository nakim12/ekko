# Ekko: Is It Tilt, or Is It the Queue?

**Project plan v1 · Nathan Kim · November 2026**

> **Name: Ekko.** The champion who rewinds time, and it sounds like "echo": does your last game echo into your next one? Reads as a neutral word to non-players. Live at ekko.nakim.me when launched.

---

## 1. The one-sentence pitch

A data platform, causal study, and public app that answers the question every ranked player argues about: **when you go on a losing streak, is it you (tilt) or the matchmaker (loser's queue)?**

## 2. Why this project exists

| Goal | How Ekko delivers it |
|---|---|
| Give Version B personality and range | Real interest, real question, memorable in interviews |
| Prove the BI / data engineering stack | Warehouse (DuckDB + MotherDuck), dbt star schema with tests, Power BI, Tableau Public |
| Back up "Causal Inference" in the Version B headline | Within-player fixed effects, pre-registered hypotheses, selection-bias handling, BH correction |
| Show product and AI skill (Romus / Scalpal / Juno style) | Public app: enter a Riot ID, get a personal report, written by an AI coach that's checked against the numbers |
| Feed the brand track | At least 3 LinkedIn posts: the question, the findings, the app launch |

## 3. Research questions and pre-registered hypotheses

**Pre-registration rule:** write `analysis/PREREGISTRATION.md` and commit it **before** running any outcome analysis. The commit timestamp is your proof that you didn't go fishing. Interviewers who know statistics will notice this.

### Q1. Tilt (player side)

> After a ranked loss, does a player perform worse in their next game than their own baseline, holding everything else fixed?

- **H1 (primary):** A loss in the previous game (same session) lowers early-game performance in the next game.
- **H1a:** The effect grows with consecutive losses (1, 2, 3+).
- **H1b:** The effect shrinks with longer breaks between games ("cooldown").
- **H1c:** The effect differs by tier (Iron–Silver vs. Gold–Platinum vs. Emerald+).

### Q2. Loser's queue (system side)

> After a streak, does matchmaking give a player weaker teammates relative to their opponents than their own rank would predict?

- **H2 (primary):** The team strength gap (allies minus enemies, excluding the focal player) is the same after win streaks and loss streaks, conditional on the focal player's rank. (A real loser's queue would show a negative gap after win streaks.)
- **H2a:** The rate of autofilled teammates doesn't depend on the focal player's streak.

**Important nuance to state clearly in the write-up:** after a win streak, facing *stronger opponents* is normal skill-based matchmaking, not rigging. Loser's queue only exists if the *gap between your team and theirs* shifts against you. Getting this distinction right is what separates a serious analysis from a Reddit thread.

### Q3. Streak structure

> Are win/loss streaks longer or shorter than chance predicts?

- **H3:** After accounting for each player's win rate and slowly drifting skill, streak lengths match what independent games would produce. Test with a runs test per player against a simulated null.

## 4. Data

### 4.1 Source: Riot Games API

Confirm every endpoint, routing value, and rate limit in the Riot Developer Portal before coding. They change.

| Need | Endpoint (family) | Routing |
|---|---|---|
| Riot ID → PUUID | `account-v1` by Riot ID | regional (`americas`) |
| Sample players by tier | `league-v4` entries by queue/tier/division, plus Challenger/Grandmaster/Master lists | platform (`na1`) |
| Current rank for a player | `league-v4` entries by PUUID | platform (`na1`) |
| Match ID list | `match-v5` by PUUID, `queue=420` (ranked solo/duo), with `startTime`/`endTime` | regional (`americas`) |
| Match details | `match-v5` match by ID | regional |
| Per-minute gold, CS, XP | `match-v5` timeline | regional |
| Champion experience (optional control) | `champion-mastery-v4` by PUUID | platform |

### 4.2 API keys

| Key | Use | Notes |
|---|---|---|
| Development key | Days 1–3 only | Expires every 24 hours |
| **Personal key** | All research crawling | Apply in week 1. Doesn't expire. Low rate limits |
| **Production key** | Required for the public app | Apply once the app prototype works. Riot reviews the product. Read the developer policies first, and add Riot's required legal notice ("not endorsed by Riot Games…") to the app footer |

**Apply for the production key as early as the policy allows.** The review can take a while, and it's the main dependency for launching the app.

### 4.3 Sampling plan

- **Region:** NA only (`na1`). Clean, and one region is enough.
- **Players:** stratified random sample from `league-v4` tier lists. Target **~250 players per tier** from Iron through Diamond, plus all reachable Master+ players up to 250 → about **2,000 focal players**.
- **Games:** each focal player's last **100–150 ranked solo games** → roughly **200k–300k player-games**.
- **Timelines:** fetch for all focal-player matches if the rate budget allows. Otherwise a random 50% subset.
- **Loser's queue subsample:** **10,000 recent matches** (last 7 days only) where you look up the current rank of **all 10 players**. Using only recent matches keeps "current rank" close to "rank at match time."
- **Rank snapshots:** start a **daily rank snapshot job on day 1** for all focal players. Over the project this builds a real LP history, which strengthens Q2 and lets you check how biased the 7-day approach is.

### 4.4 Rate budget (personal key)

At roughly 100 requests per 2 minutes, you get about **70,000 requests per day**. Rough budget:

| Job | Requests | Days |
|---|---|---|
| Tier sampling + PUUIDs | ~3k | <1 |
| Match ID lists | ~4k | <1 |
| Match details (de-duplicated) | ~200k | ~3 |
| Timelines | ~200k | ~3 |
| Loser's queue rank lookups | ~90k | ~1.5 |
| **Total** | **~500k** | **~8–9 days of continuous crawling** |

This is why the crawler must run on a server (Fly.io), not your laptop, and why you **start crawling in week 1** while building everything else.

### 4.5 Known data limitations (say these out loud in the write-up)

1. **Hidden MMR isn't available.** Riot matches on a hidden rating. Rank and LP are the best available stand-ins. Q2 measures whether teams are imbalanced *by visible rank*, which is still the claim players actually make.
2. **Rank at match time isn't in match data.** Handled with the 7-day window and daily snapshots.
3. **No autofill flag.** Infer it: a player is "likely autofilled" if their assigned role differs from the role they played in at least 60% of their own recent games (requires their history, so only for the Q2 subsample).
4. **Duo queue.** Players queued with a friend aren't flagged. Sensitivity check: drop focal games where any teammate appears in 3+ of the focal player's other games.

## 5. Architecture

```
Riot API
   │  (async Python crawler, token-bucket rate limiter, Retry-After handling, resumable)
   ▼
Raw landing zone: Parquet files (partitioned by date), immutable
   │
   ▼
MotherDuck (DuckDB in the cloud)
   │  dbt-duckdb: staging → intermediate → marts, with tests
   ▼
Marts ──► Analysis (Python: pyfixest, statsmodels, PyMC)
      ──► Power BI Desktop (.pbix in repo) and Tableau Public (live link)
      ──► FastAPI backend ──► Next.js app (Riot ID lookup + AI coach report)
```

| Layer | Tool | Notes |
|---|---|---|
| Crawler | Python, `httpx` async, `tenacity` | Runs as a Fly.io machine. Resumable by checkpointing match IDs already fetched |
| Scheduling | GitHub Actions cron | Daily rank snapshots and incremental match pulls. Long crawls stay on Fly.io (Actions jobs time out after 6 hours) |
| Warehouse | DuckDB locally, MotherDuck in the cloud | Same SQL everywhere |
| Transformations | dbt Core with `dbt-duckdb` | Tests, docs site, lineage graph |
| Analysis | Python: `pyfixest`, `statsmodels`, `PyMC` | Optional cross-check of the main model in R `fixest` |
| BI | Power BI Desktop + Tableau Public | Power BI for the skill and the .pbix; Tableau Public for the shareable link |
| App backend | FastAPI | Job queue for lookups, SSE progress updates |
| App frontend | Next.js, TypeScript, Tailwind | Deployed on Vercel |
| AI | Claude API | Structured input, verified output |
| CI | GitHub Actions | dbt build + tests, Python unit tests, app tests |

## 6. Data model (dbt star schema)

### 6.1 Layers

- **staging:** one model per raw source, renamed and typed, no logic. `stg_matches`, `stg_participants`, `stg_timeline_frames`, `stg_rank_snapshots`.
- **intermediate:** business logic. `int_sessions` (session assignment), `int_lane_opponents`, `int_streaks`, `int_performance_scores`.
- **marts:** the star schema below plus analysis-ready tables.

### 6.2 Star schema

**Fact table: `fct_player_games`** (grain: one row per player per match)

| Column group | Examples |
|---|---|
| Keys | `player_key`, `match_key`, `champion_key`, `date_key`, `role_key` |
| Outcome | `win`, `early_surrender`, `remake` |
| Performance | `kills`, `deaths`, `assists`, `cs_per_min`, `damage_share`, `vision_per_min`, `gold_diff_at_14`, `cs_diff_at_14`, `xp_diff_at_14`, `deaths_before_14` |
| Context | `session_id`, `game_number_in_session`, `minutes_since_last_game`, `prev_game_won`, `consecutive_losses_before`, `consecutive_wins_before` |
| Standardized | `perf_index` (z-score within tier × role × patch) |

**Dimensions**

| Dimension | Grain | Key attributes |
|---|---|---|
| `dim_player` | player | PUUID (hashed for anything public), sampled tier, main role |
| `dim_match` | match | patch, duration, start time, queue |
| `dim_champion` | champion | name, class |
| `dim_role` | role | top / jungle / mid / bot / support |
| `dim_date` | date | day of week, hour bucket (local time) |
| `dim_rank_snapshot` | player × day | tier, division, LP, numeric ladder position |

**Second fact table for Q2: `fct_match_team_strength`** (grain: one row per focal player per match)
`ally_strength_mean` (excluding focal), `enemy_strength_mean`, `strength_gap`, `ally_autofill_count`, `enemy_autofill_count`, focal player's streak state.

### 6.3 dbt tests (minimum set)

- `unique` + `not_null` on every key; `relationships` from facts to dimensions
- `accepted_values` for role, queue, tier
- Custom: every match has exactly 10 participants; 5 per team; exactly one winning team
- Custom: `gold_diff_at_14` is null only when game length < 14 minutes
- Custom: session assignment never puts games more than the gap threshold apart in one session
- Freshness check on the raw rank snapshots (fails CI if the daily job stops)

## 7. Analysis design

### 7.1 Definitions (fix these in the pre-registration)

- **Session:** consecutive ranked games with gaps under **60 minutes**. Sensitivity runs at 30, 90, and 120.
- **Exclude:** remakes (under 5 minutes), games where the focal player was AFK (near-zero gold and damage), and the first game of each session (no previous game in session).
- **Primary outcome:** `gold_diff_at_14` against the lane opponent, standardized within tier × role × patch.
  - Why: it's measured early, before most of the current game's result is decided, so it's less contaminated by "winning makes stats look good." It's also comparable across roles once standardized.
- **Secondary outcomes:** `deaths_before_14`, `cs_diff_at_14`, composite `perf_index`, win.

### 7.2 Q1 model: within-player fixed effects

```
perf_{i,t} = β · lost_{i,t-1}
           + γ · perf_{i,t-1}
           + controls(champion, role, patch, hour, game number in session, minutes since last game)
           + α_i (player fixed effect)
           + ε_{i,t}
```

- **Player fixed effects** compare each player to their own average, so "bad players lose more" can't explain the result.
- **Controlling for last game's performance** separates "you lost because you played badly, and you're still playing badly" from "losing itself made you worse." Without this, a lot of apparent tilt is just a bad day.
- Standard errors clustered by player.
- Long panels (100+ games per player) keep the bias from combining fixed effects with a lagged outcome small. Mention this in the write-up; it's a detail that signals depth.

### 7.3 The selection problem (the most important section to get right)

Players **choose** whether to keep playing after a loss. The ones who queue again might be the ones who feel fine, which would hide tilt. Address it three ways:

1. **Model the continuation decision:** estimate the probability of playing another game within 60 minutes after a loss vs. a win, and report it. ("Players are X% more likely to stop after a loss.") That's an interesting finding on its own.
2. **Inverse probability weighting:** weight continuation games by the inverse of their predicted probability, then rerun the main model.
3. **Bounds:** report how large the selection effect would need to be to erase the result.

### 7.4 Q2 model: team strength gap

```
strength_gap_{i,m} = δ · streak_state_{i,m}
                   + f(focal player's ladder position)
                   + controls(hour, day of week, patch, tier)
                   + ε
```

- `streak_state`: categories from 3+ losses through 3+ wins, with no streak as the baseline.
- **Placebo test:** replace the focal player with a random other player in the same match. If the "effect" shows up for random players too, it's an artifact.
- Same model with `ally_autofill_count − enemy_autofill_count` as the outcome (H2a).

### 7.5 Q3: runs test

- For each player, compare observed streak lengths with 10,000 simulated sequences that use the same win rate with slow drift (rolling 20-game win rate).
- Aggregate across players and report the share of players whose streaks are more extreme than chance.

### 7.6 Rigor checklist

- [ ] Pre-registration committed before outcome analysis
- [ ] Power analysis: with ~200k player-games, what's the smallest effect detectable? Report it.
- [ ] Benjamini-Hochberg correction across all secondary tests (tiers × outcomes × streak lengths)
- [ ] Every main result with 95% confidence intervals, not just p-values
- [ ] Effect sizes translated into game terms ("about X gold at 14 minutes, roughly Y CS")
- [ ] Sensitivity: session thresholds, duo-queue exclusion, timeline subset vs. full
- [ ] Null results reported as findings, not hidden. "Loser's queue isn't real" is a great result.

## 8. Public app

### 8.1 User flow

1. User enters a Riot ID (`name#tag`).
2. Backend checks the cache. If stale or missing, it queues a job that fetches their last 100 ranked games and timelines.
3. The page shows live progress over SSE ("fetched 40 of 100 games").
4. The report appears:
   - **Your tilt score:** how much your early-game performance drops after a loss, with an interval, compared with the average player at your rank.
   - **Your cooldown:** how long a break erases the drop, if the data supports it.
   - **Your stop rule:** "After 2 losses in a row, your win rate drops to X%. Consider stopping." Only shown when the interval supports it.
   - **Your matchmaking check:** whether your recent teams were weaker or stronger than your opponents' (with the honest caveat that one player's 100 games can't prove anything about the matchmaker; link to the full study).
   - **AI coach summary** (Section 9).

### 8.2 The statistics behind personal reports: partial pooling

100 games isn't enough to estimate one person's tilt reliably on its own. Use **empirical Bayes shrinkage**: each player's estimate is pulled toward the average for their tier, more strongly when their data is noisy.

- Fit the population model per tier once (from the research data). Store the prior mean and variance.
- At lookup time, compute the player's raw estimate and standard error, then the shrunken estimate. This is fast enough for a live app.
- Optional upgrade: a full hierarchical model in PyMC, used to validate that the empirical Bayes shortcut agrees.

This is the same idea teams use to rank sellers with few reviews or estimate small-region rates, so it's a strong interview talking point.

### 8.3 Engineering details

- **Job queue with leases** (the Scalpal pattern): one worker per lookup, stale jobs rejected, duplicate lookups for the same Riot ID collapse into one job.
- **Caching:** a player's report is cached for 6 hours; their match data is stored, so refreshes only fetch new games.
- **Rate-limit sharing:** one global rate limiter shared by research crawling and app lookups. App lookups get priority.
- **Privacy:** only show reports for the Riot ID entered. Hash PUUIDs in anything public. No leaderboards of named players.
- **Footer:** Riot's required legal notice.

## 9. AI coach report

### 9.1 Design

- **Input:** a structured JSON of the player's computed stats (estimates, intervals, sample sizes, comparisons). The model never sees raw match data, so it can't compute its own numbers.
- **Output:** a structured response: a short summary, 2–3 specific findings, and 1–2 recommendations. Each finding cites the JSON field it's based on.
- **Verification layer (deterministic, runs on every report):**
  - Every number in the text must match a JSON value (after rounding rules). Any mismatch → regenerate, then fall back to a template.
  - If a finding's interval includes zero, the text must not claim an effect. A rule checks for words like "you tilt" against interval flags.
  - Recommendations can only use approved actions (take a break, stop after N losses, play fewer games late at night) tied to supported findings.

### 9.2 Evaluation (the Juno move, improved)

- **Test set:** 150 player profiles: 100 real (from research data, anonymized) and 50 synthetic edge cases (tiny samples, intervals crossing zero, extreme values, contradictory signals).
- **Rule-based metrics** (computed exactly):
  - Numeric accuracy: share of numbers that match the source
  - Unsupported claim rate: claims made when the interval includes zero
  - Coverage: share of significant findings the report mentions
- **LLM-judge metrics** (calibrated against your own grading on a 40-report sample; report agreement as Cohen's κ):
  - Clarity, actionability, appropriate certainty, tone
- **Ablation:** compare reports with and without the verification layer. The difference in unsupported claim rate is your headline AI result.

## 10. Dashboards

### 10.1 Power BI (in the repo as a .pbix, with screenshots and a 60-second video)

| Page | Contents |
|---|---|
| Overview | Sample size, tiers, games, date range, data freshness |
| Tilt | Effect of a previous loss by tier, by consecutive losses, by break length |
| Selection | Probability of continuing after a win vs. a loss, by tier and hour |
| Loser's queue | Team strength gap by streak state, with placebo comparison |
| Streaks | Observed vs. simulated streak length distributions |

Include at least 5 real DAX measures (for example: win rate, win rate after N losses, average gold diff at 14, continuation rate, strength gap), so you can honestly say you've written DAX.

### 10.2 Tableau Public

Rebuild the 2–3 strongest views (tilt by break length, the loser's queue gap chart, streak simulation) and publish them. This is the link for nakim.me, LinkedIn, and the resume.

## 11. Repository structure

```
ekko/
├── README.md               # question, findings, screenshots, app link, how to run
├── crawler/                # async Riot API client, rate limiter, jobs
├── dbt/                    # models/staging, intermediate, marts; tests; docs
├── analysis/
│   ├── PREREGISTRATION.md
│   ├── notebooks/          # exploration only
│   ├── src/                # models as importable, tested functions
│   └── results/            # tables and figures generated by scripts
├── app/
│   ├── api/                # FastAPI
│   └── web/                # Next.js
├── ai/                     # prompts, verifier, eval set, eval runner
├── bi/                     # .pbix, Tableau workbook, screenshots
└── .github/workflows/      # dbt build + tests, Python tests, daily snapshot cron
```

## 12. Phases and definitions of done

Applications and outreach still come first every weekday. This project gets the remaining time.

| Phase | Work | Done when |
|---|---|---|
| **0. Setup and data check** (days 1–3) | Riot account, dev key, pull 20 players' histories; confirm timeline fields; apply for personal key | 20 players' last 100 games and timelines load into DuckDB; fields in Section 6.2 confirmed |
| **1. Crawler** (week 1) | Async crawler with rate limiter, checkpointing, Parquet landing zone; deploy on Fly.io; daily rank snapshot cron | Crawler runs unattended for 24 hours without errors; snapshot job runs daily |
| **2. Warehouse and dbt** (weeks 2–3, while crawling) | Staging, intermediate, marts; all tests in 6.3; dbt docs | `dbt build` passes in CI; lineage graph generated; you can query time-ordered games per session |
| **3. Pre-registration** (end of week 3) | Write hypotheses, definitions, models, exclusions | `PREREGISTRATION.md` committed before any outcome analysis |
| **4. Analysis** (weeks 4–5) | Q1 with selection handling, Q2 with placebo, Q3 simulation, sensitivity, BH | `analysis/results/` regenerates from one command; findings memo written |
| **5. Dashboards** (week 6) | Power BI pages, DAX measures, Tableau Public views | .pbix in repo, Tableau link live, video recorded |
| **6. App** (weeks 6–8) | FastAPI job queue, SSE, empirical Bayes per-player estimates, Next.js UI; apply for production key | A real Riot ID returns a full report in under 2 minutes (with cache, instantly) |
| **7. AI coach and eval** (week 8) | Prompt, verifier, 150-profile eval, κ calibration, ablation | Eval results table in README; verifier blocks every injected bad report in tests |
| **8. Launch** (week 9) | README, nakim.me card, resume bullets, LinkedIn posts | Everything in Section 14 is published |

## 13. Testing

- **Crawler:** unit tests for the rate limiter, retry logic on 429 and 5xx, checkpoint resume (kill mid-run, restart, no duplicates).
- **dbt:** Section 6.3 tests in CI on every push.
- **Analysis:** unit tests for session assignment, streak counting, lane-opponent matching, and a **known-effect simulation**: generate synthetic games with a planted tilt effect of known size and confirm the model recovers it. (This is the BlueAlpha parameter-recovery idea applied here, and worth a sentence on the resume.)
- **App:** API tests for the job lifecycle (queued → running → done, stale lease rejected); a frontend test for the report page.
- **AI:** verifier tests with injected wrong numbers and overclaims; all must be caught.

## 14. Deliverables and how to use them

### 14.1 Resume (Version B), drafts with placeholders

Fill in brackets with real numbers only.

- *Built a Riot API data platform (async Python crawler, MotherDuck, dbt star schema with [N] tests) covering [N]k ranked games across [N] players; served findings in Power BI and Tableau Public.*
- *Tested whether losing streaks come from player tilt or matchmaking with pre-registered within-player fixed effects models, selection correction, and BH-adjusted tests: [main finding in one clause].*
- *Shipped a public app that gives players a personal tilt report using empirical Bayes estimates and an AI coach verified against the stats ([X]% unsupported claims without verification vs. [Y]% with).*

### 14.2 LinkedIn posts (brand track)

1. **The question** (week 1–2): what you're testing and why it's harder than comparing win rates. Invite people to guess.
2. **The findings** (week 5–6): one chart, one surprising result, one honest limitation.
3. **The app launch** (week 9): demo video, link, and the AI verification result.

### 14.3 nakim.me

A card with the question, the headline finding, links to the app, Tableau Public, and the repo.

## 15. Interview questions to be ready for

- Why not just compare win rates after wins and losses?
- How do you know the drop isn't just a bad day carrying over?
- What about players who stop after a loss?
- Riot uses hidden MMR. Doesn't that break your loser's queue test?
- Why gold difference at 14 minutes instead of KDA or win?
- Why fixed effects instead of a random effects model?
- Why shrink individual estimates in the app? What does that cost?
- How do you stop the AI coach from making things up?
- How would you scale the crawler with a higher rate limit?
- Walk me through your star schema. Why is the grain one row per player per game?

Write a short answer to each in `docs/INTERVIEW_NOTES.md` as you go.

## 16. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Personal key rate limits slow crawling | Start crawling in week 1 on Fly.io; build dbt and analysis on partial data while it runs |
| Production key delayed or denied | Ship the app with a "research mode" that works for players in the dataset, plus a waitlist; the analysis and dashboards don't depend on it |
| API fields or endpoints change | Raw JSON stored immutably; staging models isolate schema changes |
| Effects are tiny or null | That's still a finding. "Loser's queue isn't real, and tilt is smaller than people think" is a strong post |
| Scope creep | Phases 0–5 are the core. The app and AI coach build on top; don't start them until Phase 4 results exist |
| Policy issues with Riot | Read the developer policies before applying for the production key; no named leaderboards; legal notice in footer |

## 17. First three actions

1. **Today:** sign in to the Riot Developer Portal, get a development key, and apply for a personal key.
2. **Within 2 days:** pull 20 players' last 100 ranked games and timelines into DuckDB. Confirm `teamPosition`, timeline gold per minute, and game timestamps all exist.
3. **This weekend:** start the crawler on Fly.io and the daily rank snapshot job, then start the dbt project while it runs.
