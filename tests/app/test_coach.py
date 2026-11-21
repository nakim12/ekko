"""The coach's verification layer, retry and template fallback (no real model calls)."""

import itertools
from types import SimpleNamespace

import pytest
from ekko_api import coach
from ekko_api.coach import CoachOutput, Finding, Recommendation


def _report(tilt=False, stop=False, cool=False, tilt_sign=-1):
    iv = lambda e: {"estimate": e, "low": e - 0.1, "high": e + 0.1, "n": 40}  # noqa: E731
    return {
        "games_analyzed": 97,
        "rank": {"tier": "GOLD", "division": "II", "league_points": 40},
        "priors_are_placeholders": True,
        "tilt": {
            "games_used": 52,
            "gold_per_sd": 1400.0,
            "shrunk": iv(0.2 * tilt_sign if tilt else 0.02),
            "supported": tilt,
        },
        "cooldown": {"quick_requeue": iv(-0.2), "after_a_break": iv(0.0), "supported": cool},
        "stop_rule": {
            "after_losses_in_a_row": 2,
            "games": 18,
            "win_rate": 0.33 if stop else 0.5,
            "low": 0.16,
            "high": 0.48 if stop else 0.7,
            "overall_win_rate": 0.55,
            "supported": stop,
        },
        "matchmaking": {
            "games": 10,
            "mean_gap_lp": -24.4,
            "low": -60,
            "high": 12,
            "supported": False,
        },
    }


def _out(findings, recs=(), summary="Here is what your games show."):
    return CoachOutput(summary=summary, findings=list(findings), recommendations=list(recs))


# --- verify ---


def test_facts_are_rounded_like_the_page():
    fs = coach.facts(_report(tilt=True))
    assert fs["tilt.gold_after_loss"] == -280 and fs["stop_rule.win_pct"] == 50
    assert fs["matchmaking.mean_gap_lp"] == -24 and fs["minute_mark"] == 14


def test_numbers_must_come_from_the_facts():
    fs = coach.facts(_report(tilt=True))
    good = Finding(
        text="After a loss you start about 280 gold behind at minute 14.",
        fact_ids=["tilt.gold_after_loss"],
    )
    bad = Finding(
        text="After a loss you start about 300 gold behind.", fact_ids=["tilt.gold_after_loss"]
    )
    other = Finding(text="You won 55% of your games.", fact_ids=["stop_rule.overall_win_pct"])
    assert coach.verify(_out([good, other]), fs).ok
    v = coach.verify(_out([bad, other]), fs)
    assert any("300" in x for x in v.violations)


def test_no_effect_claims_without_support():
    fs = coach.facts(_report(tilt=False))
    other = Finding(text="You won 55% of your games.", fact_ids=["stop_rule.overall_win_pct"])
    claim = Finding(text="You tilt a little after losses.", fact_ids=["tilt.supported"])
    hedged = Finding(
        text="There's no clear sign that losing makes your next game worse.",
        fact_ids=["tilt.supported"],
    )
    assert not coach.verify(_out([claim, other]), fs).ok
    assert coach.verify(_out([hedged, other]), fs).ok


def test_matchmaker_claims_and_unknown_facts_are_rejected():
    fs = coach.facts(_report())
    rigged = Finding(
        text="Your games look rigged against you.", fact_ids=["matchmaking.mean_gap_lp"]
    )
    ghost = Finding(text="Your tilt is low.", fact_ids=["tilt.made_up"])
    v = coach.verify(_out([rigged, ghost]), fs)
    assert any("matchmaker" in x for x in v.violations)
    assert any("unknown fact" in x for x in v.violations)


def test_recommendations_need_their_evidence():
    ok_finding = Finding(
        text="Losing streaks show no clear effect.", fact_ids=["stop_rule.supported"]
    )
    other = Finding(text="You won 55% of your games.", fact_ids=["stop_rule.overall_win_pct"])
    stop = Recommendation(
        action="stop_after_losses_in_a_row",
        text="Stop after 2 losses in a row.",
        fact_ids=["stop_rule.supported"],
    )
    assert not coach.verify(_out([ok_finding, other], [stop]), coach.facts(_report(stop=False))).ok
    assert coach.verify(_out([ok_finding, other], [stop]), coach.facts(_report(stop=True))).ok


def test_finding_count_is_enforced():
    fs = coach.facts(_report())
    one = Finding(text="Losing streaks show no clear effect.", fact_ids=["stop_rule.supported"])
    assert not coach.verify(_out([one]), fs).ok


@pytest.mark.parametrize(
    "tilt,stop,cool,sign",
    list(itertools.product([False, True], [False, True], [False, True], [-1, 1])),
)
def test_template_always_passes_verification(tilt, stop, cool, sign):
    fs = coach.facts(_report(tilt=tilt, stop=stop, cool=cool, tilt_sign=sign))
    assert coach.verify(coach.template(fs), fs).violations == []


# --- generation with a fake client ---


class FakeClient:
    """Stands in for anthropic.Anthropic: beta.messages.parse returns scripted outputs."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []
        self.kwargs = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kw):
        self.kwargs.append(kw)
        self.prompts.append(kw["messages"][0]["content"])
        out = self.outputs.pop(0)
        if out == "refusal":
            return SimpleNamespace(stop_reason="refusal", parsed_output=None)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=out)


GOOD = _out(
    [
        Finding(
            text="Losing a game shows no clear effect on your next game.",
            fact_ids=["tilt.supported"],
        ),
        Finding(text="You won 55% of your games overall.", fact_ids=["stop_rule.overall_win_pct"]),
    ],
    [
        Recommendation(
            action="keep_playing_as_usual",
            text="Nothing here says you need to change how you queue.",
            fact_ids=[],
        )
    ],
)
BAD = _out([Finding(text="You lose 400 gold after every loss.", fact_ids=["tilt.supported"])])


def test_model_note_is_used_when_it_passes():
    client = FakeClient([GOOD])
    result = coach.coach(_report(), client)
    assert result.source == "model" and result.attempts == 1
    kw = client.kwargs[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["output_format"] is CoachOutput
    assert '"tilt.supported": false' in client.prompts[0]


def test_a_rejected_note_is_retried_with_the_violations():
    client = FakeClient([BAD, GOOD])
    result = coach.coach(_report(), client)
    assert result.source == "model" and result.attempts == 2
    assert "rejected by the checker" in client.prompts[1] and "400" in client.prompts[1]


def test_falls_back_to_the_template_after_repeated_failures_or_refusals():
    for outputs in ([BAD, BAD], ["refusal", "refusal"]):
        result = coach.coach(_report(stop=True), FakeClient(outputs))
        assert result.source == "template" and len(result.violations) == 2
        assert coach.verify(result.output, coach.facts(_report(stop=True))).ok


def test_no_client_means_template():
    assert coach.coach(_report()).source == "template"


# --- evaluation harness ---


def test_eval_profiles_cover_the_edge_cases_and_templates_score_clean():
    from ekko_api import coach_eval

    ps = coach_eval.profiles(50)
    assert len(ps) == 50
    assert any(p["tilt"]["shrunk"] is None for p in ps)  # tiny samples
    assert any(p["tilt"]["supported"] and p["stop_rule"]["supported"] for p in ps)  # contradictory
    for p in ps:
        fs = coach.facts(p)
        s = coach_eval.score(coach.template(fs), fs)
        assert s["numbers_correct"] == s["numbers"] and s["unsupported_findings"] == 0


def test_eval_separates_the_verified_and_unverified_arms():
    from ekko_api import coach_eval

    # A model that always overclaims: the unverified arm shows it, the verified arm falls back.
    overclaim = _out(
        [
            Finding(text="You tilt hard after losses.", fact_ids=["tilt.supported"]),
            Finding(text="Streaks hurt you.", fact_ids=["stop_rule.supported"]),
        ]
    )
    result = coach_eval.evaluate(FakeClient([overclaim] * 100), n=5)
    assert result["unverified"]["unsupported_claim_rate"] > 0
    assert result["verified"]["unsupported_claim_rate"] == 0
    assert result["verified"]["template_rate"] > 0
