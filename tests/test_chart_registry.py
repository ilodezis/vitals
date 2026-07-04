"""Unit tests for the cross-domain chart metric registry (pure logic, no DB)."""
from __future__ import annotations

import pytest

from vitals.services.analytics import chart_registry
from vitals.services.analytics.chart_registry import REGISTRY


def test_registry_keys_are_unique():
    keys = [m.key for m in REGISTRY.values()]
    assert len(keys) == len(set(keys))


def test_metrics_for_domain_matches_registry():
    weight_metrics = chart_registry.metrics_for_domain("weight")
    assert {m.key for m in weight_metrics} == {
        k for k, m in REGISTRY.items() if m.domain == "weight"
    }
    assert all(m.domain == "weight" for m in weight_metrics)


def test_all_domains_covers_every_registry_domain():
    domains = chart_registry.all_domains()
    assert set(domains) == {m.domain for m in REGISTRY.values()}
    # No duplicates.
    assert len(domains) == len(set(domains))


def test_get_returns_field_by_key():
    field = chart_registry.get("weight.weight_kg")
    assert field.domain == "weight"
    assert field.model is not None
    assert field.column == "weight_kg"


def test_get_unknown_key_raises_keyerror():
    with pytest.raises(KeyError):
        chart_registry.get("does.not_exist")


def test_parametrized_metrics_carry_no_model_or_column():
    for m in REGISTRY.values():
        if m.param_kind != "none":
            assert m.model is None
            assert m.column is None


def test_simple_metrics_carry_model_and_column():
    for m in REGISTRY.values():
        if m.param_kind == "none":
            assert m.model is not None
            assert m.column is not None


def test_domain_labels_cover_every_domain():
    for domain in chart_registry.all_domains():
        assert domain in chart_registry.DOMAIN_LABELS
        ru, en = chart_registry.DOMAIN_LABELS[domain]
        assert ru and en


def test_genetics_and_supplements_excluded():
    domains = set(chart_registry.all_domains())
    assert "genetics" not in domains
    assert "supplements" not in domains
