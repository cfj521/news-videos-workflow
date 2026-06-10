from app.services import scoring_constants as C


def test_constants_present_and_sane():
    assert isinstance(C.SOURCE_TIERS, list) and C.SOURCE_TIERS
    assert all(isinstance(p, str) and 0 < w <= 1 for p, w in C.SOURCE_TIERS)
    assert 0 < C.DEFAULT_SOURCE_WEIGHT <= 1
    assert "anthropic" in " ".join(p for p, _ in C.SOURCE_TIERS).lower()
    assert "openai" in C.POSITIVE_ENTITIES
    assert "中国" in C.CHINA_TERMS
    assert "crypto" in C.NEGATIVE_TERMS
    assert abs(C.W_FINAL_LLM + C.W_FINAL_RULE - 1.0) < 1e-9
    assert C.LLM_CONCURRENCY == 5 and C.LLM_CANDIDATE_CAP == 25
    assert C.FRESH_FLOOR < C.FRESH_WEEK_END <= 1.0
