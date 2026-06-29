from ara.pricing import estimate_cost_usd, model_is_priced


def test_known_anthropic_model_is_priced() -> None:
    assert model_is_priced("claude-haiku-4-5") is True
    assert estimate_cost_usd("claude-haiku-4-5", 1_000_000, 0) == 0.80


def test_known_openai_model_is_priced() -> None:
    assert model_is_priced("gpt-4o-mini") is True
    assert estimate_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000) == 0.15 + 0.60


def test_unknown_model_is_unpriced_and_costs_zero() -> None:
    assert model_is_priced("some/unknown-model") is False
    assert estimate_cost_usd("some/unknown-model", 9_999, 9_999) == 0.0
