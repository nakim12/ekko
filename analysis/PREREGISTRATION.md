# Ekko pre-registration

**Is it tilt, or is it the queue?** A study of ranked League of Legends losing streaks.

- Author: Nathan Kim
- Registered: the timestamp of the commit that adds this file to `main`. Nothing in this document may change after that commit without an entry under [Deviations](#11-deviations).
- Plan of record: `docs/PROJECT_PLAN.md` (sections 3, 4 and 7). Where this document and the plan differ, this document governs.

## 1. What has been seen before registration

Being specific about what was already looked at is the point of pre-registering, so here it is in full.

- **Phase 0 sample** (2026-11-18): 20 players (2 per tier, Iron to Challenger) and 1,836 ranked solo games with timelines. Used only for a data-availability check (`docs/phase0-field-check.md`): field presence, match structure, the share of games 14+ minutes long, the distribution of gaps between consecutive games, and the overall mean and SD of gold difference at 14 minutes (mean 39, SD 1,428, n = 1,762). No outcome was computed against any exposure: nothing was split by previous result, streak, session position, team strength or tier.
- **Landing page demo**: the win/loss sequences of the last 30 games of 8 randomly chosen Phase 0 players appear on the site. Their longest streaks were seen. No statistic was computed across them.
- **Phase 0 data is excluded from every confirmatory analysis.** Phase 0 players are not eligible for the Phase 1 sample.

"Outcome analysis" means any computation that relates an outcome (performance, win, team strength gap, streak statistics) to an exposure (previous result, streak state, break length, tier). None will be run before this file is committed, except on simulated data (section 9).

## 2. Questions and hypotheses

Three confirmatory hypotheses (H1, H2, H3) and five secondary ones. Directions are stated in advance, but all tests are two-sided.

### Q1. Tilt (player side)

> After a ranked loss, does a player perform worse in their next game than their own baseline?

- **H1 (primary):** Losing the previous game in the same session lowers standardized gold difference at 14 minutes in the next game. Prediction: β < 0.
- **H1a:** The effect grows with consecutive losses within the session (1, 2, 3+).
- **H1b:** The effect shrinks as the break between games gets longer.
- **H1c:** The effect differs across tier groups (Iron–Silver, Gold–Platinum, Emerald+).

### Q2. Loser's queue (system side)

> After a streak, does matchmaking give a player weaker teammates relative to their opponents than their rank predicts?

- **H2 (primary):** The team strength gap is the same after 3+ win streaks as after 3+ loss streaks, conditional on the focal player's rank. This is a hypothesis of *no difference*, tested for equivalence (section 7.2). A loser's queue would show a lower gap after win streaks than after loss streaks.
- **H2a:** The difference in likely-autofilled players (allies minus enemies) does not depend on the focal player's streak state.

Facing stronger *opponents* after a win streak is ordinary skill-based matchmaking. Only a shift in the *gap* between the two teams counts as a loser's queue.

### Q3. Streak structure

> Are win and loss streaks longer than chance predicts?

- **H3 (primary):** After allowing for each player's win rate and slow drift in skill, the number of runs in players' win/loss sequences matches what independent games would produce.

## 3. Data and sample

- **Source:** Riot Games API, NA (`na1` / `americas`), ranked solo/duo only (queue 420).
- **Players:** stratified random sample from `league-v4` tier lists: target 250 per tier, Iron through Diamond (random divisions and random pages within each tier), plus a random 250 from Master, Grandmaster and Challenger combined. About 2,000 focal players. The tier a player was sampled from is their **sampled tier** for every analysis.
- **Minimum history:** a sampled player is kept only if they have at least 30 ranked solo games available; otherwise they are replaced by another random draw from the same tier. (Phase 0 found players with as few as 11.)
- **Games:** each focal player's most recent 150 ranked solo games, or all available if fewer, with timelines.
- **Q2 sample:** see section 7.2.
- **Stopping rule:** the crawl stops when the targets above are met. The outcome analysis runs once, on the completed crawl. No interim looks.

## 4. Definitions

### 4.1 Games and sequences

- **Remake:** `gameEndedInEarlySurrender` is true or the game lasted under 5 minutes. Remakes are dropped from everything, including win/loss sequences (they don't count as a win or a loss).
- **Previous game:** the focal player's previous non-remake ranked solo game in the crawled history.
- **Break:** minutes from the end of the previous game to the start of this one.
- **Session:** a run of games in which each break is under **60 minutes**. Sensitivity thresholds: 30, 90 and 120 minutes.
- **AFK game:** the focal player or their lane opponent has under 1,500 XP at the minute-14 frame. AFK games are dropped as outcomes; they still count in win/loss sequences.
- **Lane opponent:** the enemy participant with the same `teamPosition`. Games without a unique match are dropped as outcomes.
- **Patch:** `gameVersion` major.minor.

### 4.2 Outcomes (Q1)

- **Primary: `gold_diff_14`.** Focal `totalGold` minus lane opponent `totalGold` at the minute-14 timeline frame, then z-scored within sampled tier × role × patch. Games shorter than 14 minutes have no value and are dropped as outcomes.
- **Secondary:**
  - `cs_diff_14`: (minions + jungle minions) at minute 14, focal minus opponent.
  - `xp_diff_14`: XP at minute 14, focal minus opponent.
  - `deaths_before_14`: the number of `CHAMPION_KILL` events with the focal player as victim before 14:00.
  - `perf_index`: the mean of the z-scores of `gold_diff_14`, `cs_diff_14`, `xp_diff_14` and −`deaths_before_14`.
  - `win`.

  The first four secondary outcomes are z-scored like the primary outcome; `win` is 0/1.

### 4.3 Exposures

- **`lost_prev`** (H1): 1 if the previous game in the same session was a loss.
- **`loss_run`** (H1a): consecutive losses immediately before this game within the session, as 1, 2 or 3+ (0 = previous game won).
- **Break bucket** (H1b): under 15 min, 15–60 min, 1–6 h, 6–24 h.
- **Tier group** (H1c): Iron–Silver, Gold–Platinum, Emerald+.
- **Streak state** (Q2): consecutive identical results immediately before the match, across sessions: L3+, L2, then a baseline of a streak of 1 (the last two results differ), then W2, W3+.

### 4.4 Team strength (Q2)

- **Ladder position:** a continuous LP scale. Iron IV 0 LP = 0, each division adds 100 and each tier 400, so Diamond I 100 LP = 2,800. Master, Grandmaster and Challenger are all 2,800 + LP, since they share one LP scale.
- **Rank at match time:** each participant's current solo rank is looked up within 24 hours of the match ending. That lookup already includes the result of the match itself, so the matched game is removed: 20 LP is subtracted from every winner and added to every loser. Rank lookups for apex tiers and promotions aren't exact, and section 8 checks the effect of this adjustment.
- **`strength_gap`:** the mean ladder position of the focal player's 4 teammates minus the mean of the 5 enemies. Unranked participants are left out of the means. The match is dropped if fewer than 3 teammates or 4 enemies have a rank.
- **Likely autofilled** (H2a): a participant whose role in this match differs from the role they played in at least 60% of their previous 20 ranked solo games. A player with no role at 60% or more is never counted as autofilled.

## 5. Q1 model (H1, H1a–c)

Sample: focal games whose previous game is in the same session, excluding remakes, AFK games, games under 14 minutes and games without a lane opponent. (This automatically drops the first game of every session and of every player's history.)

```
gold_diff_14[i,t] = β · lost_prev[i,t]
                  + γ · gold_diff_14[i,t-1]
                  + champion FE + role FE + patch FE + hour-of-day FE
                  + game-number-in-session FE (1..6, 7+) + log(break minutes)
                  + α_i (player FE) + ε[i,t]
```

- **H1:** test β = 0. Standard errors clustered by player.
- If the previous game has no `gold_diff_14` (under 14 minutes or AFK), its lagged value is set to 0 and an indicator for "lag missing" is added.
- Hour-of-day uses the match start in US Central time. Because it enters as fixed effects, the choice of time zone only matters through daylight saving time.
- With 100+ games per player, the bias from a lagged outcome alongside player fixed effects (Nickell bias) is of order 1/T and small. A robustness run drops the lagged outcome (section 8).
- **H1a:** replace `lost_prev` with `loss_run` categories (0 as baseline). Test a linear trend across 1, 2 and 3+.
- **H1b:** the sample is all focal games whose previous game ended within 24 hours (not only same-session games). Interact `lost_prev` with the break bucket and test whether the interaction terms are jointly zero. Under H1b the predicted ordering is: largest effect under 15 min, smallest at 6–24 h.
- **H1c:** interact `lost_prev` with tier group and test whether the interaction terms are jointly zero.
- **Secondary outcomes:** rerun the H1 model with each secondary outcome. For `win` this is a linear probability model with the same fixed effects.

### 5.1 Selection: who keeps playing after a loss

Players choose whether to queue again, and those who continue after a loss may be the ones who feel fine. Three steps:

1. **Continuation model.** For every focal game, model the probability that another game starts within 60 minutes of it ending. Use a linear probability model with player FE: `lost`, the game's own `gold_diff_14`, game number in session, hour FE, and day of week. Report the difference in continuation after a loss vs. a win, with a 95% CI.
2. **Inverse probability weighting.** Fit a logistic version of the continuation model (player mean continuation rate in place of the FE). Weight each H1-sample game by 1 / P(continue), trim the weights at the 1st and 99th percentiles, and rerun H1.
3. **Bounds.** A pattern-mixture sensitivity analysis: assume players who stopped after a loss would have played δ SD worse (or better) than those who continued. Report the δ at which the 95% CI for β would first include 0.

## 6. Q3 model (H3)

- **Sequence:** each focal player's full win/loss sequence in time order, across sessions, remakes removed.
- **Statistic:** the number of runs (Wald–Wolfowitz). Fewer runs than expected means streakier.
- **Null:** 10,000 simulated sequences per player. Game t is a Bernoulli draw with p_t equal to the player's win rate over the 20 surrounding games (10 before, 10 after, excluding game t). This allows slow drift in skill without letting game t predict itself.
- **Per player:** z = (observed runs − mean of simulated runs) / SD of simulated runs. Also a two-sided simulation p-value.
- **H3 test:** the mean z across players, with a 95% CI from a bootstrap over players (10,000 resamples). H3 is supported if the CI includes 0. Also report the share of players whose own p-value is below 0.05 in the streaky direction, against the 2.5% expected by chance.
- **Caveat:** a local win rate absorbs part of any real streakiness, so this null is conservative. Sensitivity runs: a constant win rate per player and a 50-game window (section 8).

## 7. Q2 model (H2, H2a)

### 7.1 Q2 sample

- Matches played by focal players in which all 10 participants' current ranks are looked up within 24 hours of the match ending (section 4.4). Collected daily from the focal players' newest games until **10,000 matches** qualify. When a match contains several focal players, one is chosen at random.
- The focal player's streak state comes from their own history.
- This replaces the plan's 7-day window, which would let a week of later games contaminate everyone's rank. The 7-day version is a sensitivity analysis if the data exist.

### 7.2 Model and test

```
strength_gap[i,m] = Σ δ_s · streak_state_s[i,m]          (baseline: streak of 1)
                  + spline(focal ladder position, 4 df)
                  + hour FE + day-of-week FE + patch FE + sampled tier FE + ε
```

- Standard errors clustered by focal player.
- **H2 contrast:** Δ = δ(W3+) − δ(L3+). A loser's queue predicts Δ < 0.
- **Equivalence test (TOST):** the smallest effect size of interest is **±25 LP**, about one game's worth of LP. H2 is supported if the 90% CI for Δ lies inside ±25 LP. Also report the usual two-sided test of Δ = 0 and the 95% CI.
- **Placebo:** for each Q2 match, pick one random non-focal participant, build their streak state from their 5 previous ranked games, and rerun the model with them as the "focal" player. An effect that also appears for random players is an artifact of the method.
- **H2a:** the outcome is (likely-autofilled teammates) − (likely-autofilled enemies). This needs each participant's previous 20 games, which costs about 180 requests per match, so H2a runs on a random subsample of **1,000** Q2 matches. Same model; test whether all δ are jointly zero.

## 8. Sensitivity and robustness (reported, not counted as new hypothesis tests)

- Session threshold at 30, 90 and 120 minutes (H1, H1a).
- H1 without the lagged outcome.
- H1 on games 15+ minutes only, and with outcome z-scores computed within tier × role only (ignoring patch).
- **Duo queue:** drop focal games where any teammate appears in 3 or more of the focal player's other crawled games.
- Timeline subset vs. full (only if timelines end up being fetched for a subset).
- Q2:
  - Without the ±20 LP adjustment.
  - With this match's result as a covariate.
  - Using the 7-day window, if available.
  - Using daily rank snapshots where they cover the match date.
- Q3: a constant win rate per player; a 50-game window.

## 9. Inference rules

- **Primary family (H1, H2, H3):** Holm correction across the three at α = 0.05. For H2, the equivalence test is the confirmatory one.
- **Secondary family:**
  - Members: H1a, H1b, H1c, H2a, the H1 model on each secondary outcome, and the continuation difference (5.1.1).
  - Correction: Benjamini–Hochberg at q = 0.05.
- Every main result gets a 95% CI and is translated into game terms (gold at 14 minutes, CS, LP).
- **Null results are findings and will be reported as such.**
- **Code validation before real data:** every model is run first on simulated data with a known planted effect (and on real data with outcomes shuffled within player), to confirm it recovers the effect and holds its false positive rate. Only then is it run once on the real outcomes.
- Anything not listed in this document is labeled **exploratory** wherever it appears.

## 10. Power

- **H1:** about 2,000 players × ~125 games ≈ 250,000 player-games. Same-session games are about 58% of games (Phase 0), and about 6% are lost to remakes and games under 14 minutes. That leaves about 135,000 games for the H1 model. With `lost_prev` near 50/50 and a standardized outcome, SE(β) ≈ 1 / √(135,000 × 0.25) ≈ 0.0054. The minimum detectable effect at 80% power is about 0.015 SD, or roughly **22 gold at 14 minutes** (Phase 0 SD 1,428). This ignores residual correlation within player, so it is a lower bound.
- **H2:** with 10,000 matches and about 12% of them in each of W3+ and L3+, and an assumed gap SD of 150 LP, SE(Δ) ≈ 6 LP. That gives high power for the ±25 LP equivalence bound.
- Both numbers will be recomputed by simulation on the realized sample (with outcomes shuffled) before the outcome run, and reported.

## 11. Deviations

Any change after registration is listed here with its date, what changed and why, in a separate commit. Results from changed analyses are reported next to the registered version, never in place of it.

### Deviation 1: H1 drops games whose previous game has no score (2026-11-18)

- **Applies to:** H1, H1a–c, the secondary outcomes and the IPW rerun (sections 5 and 5.1).
- **Registered:** if the previous game has no `gold_diff_14` (under 14 minutes, AFK, or no lane opponent), set the lag to 0 and add a "lag missing" indicator.
- **Change:** drop those games from the H1 sample instead. Expected cost: about 5% of the sample.
- **Why:** the code-validation step (section 9) found that filling biases β toward tilt. When the previous game's performance is unmeasured, its result stands in for it. In simulation with a true β = 0, performance persistence of 0.2 between games, 5% missing lags and a per-session form shock, the registered model averaged β̂ = −0.012 to −0.020 SD. That is 2–4 times the expected standard error (0.0054), so it would likely report tilt that isn't there. Dropping the rows brought the bias to +0.001 and recovered a planted β = −0.10 as −0.099.
- **Checked and not adopted:** a split-panel jackknife for the lagged-outcome (Nickell) bias made no measurable difference at about 120 games per player.
- **Evidence:** `tests/analysis/test_q1.py`, `python -m ekko_analysis.validate`.
- **Reporting:** the registered model (`lag="fill"`) is reported alongside.

### Deviation 2: H3 uses a within-block permutation null (2026-11-18)

- **Applies to:** H3 and its sensitivity runs (section 6).
- **Registered:** simulate each game as a Bernoulli draw with p_t equal to the player's win rate over the 20 surrounding games.
- **Change:** the null shuffles each player's own results within consecutive blocks of 20 games, 10,000 times. Slow skill drift is kept between blocks, and the null is exactly calibrated when games are independent. The test statistic, per-player p-values, bootstrap and decision rule are unchanged. The registered sensitivity runs map to a whole-sequence shuffle (constant win rate) and 50-game blocks.
- **Why:** the registered null estimates drift from the same noisy games, so its simulated sequences are streakier than independent play. In simulation, independent sequences averaged z = +0.49 with a 95% CI excluding 0, so H3 would be rejected when it is true. On shuffled Phase 0 sequences it gave +0.55 (CI excluding 0). With the block null:
  - independent sequences averaged z = −0.04 (SE 0.06), and drifting-skill sequences −0.07;
  - real streakiness gives a stronger signal: −1.05 vs. −0.45 when the previous result repeats with probability 0.55.
- **Evidence:** `tests/analysis/test_q3.py`, `python -m ekko_analysis.validate`.
- **Reporting:** the registered null (`null="drift"`) is reported alongside.
