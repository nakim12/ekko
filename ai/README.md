# ai

AI coach report (Phase 7): prompts, deterministic verifier, 150-profile eval set and eval runner.

The model only sees structured stats JSON. The verifier checks every number against the JSON, blocks effect claims when an interval includes zero, and limits recommendations to approved actions.
