"""The gate deciding whether a model's predictions are shown at all.

This exists because the first version of the gate was wrong in a way that is
easy to repeat: it required the model to beat a naive baseline on *accuracy*,
which is impossible for a rare event and rejected a genuinely good spike model
(AUC 0.70, 3.4x lift) while looking perfectly reasonable.
"""

import pytest

from app.services.modeling import _passes_gate


class TestRareEvents:
    """Base rate ~0.85%: accuracy edge is meaningless, ranking is everything."""

    def test_strong_rare_event_model_passes_despite_negative_accuracy_edge(self):
        # The real spike_2atr gradient-boosting result.
        assert _passes_gate(roc_auc=0.701, lift=3.42, edge_pp=-0.0, base_rate=0.85)

    def test_even_a_large_negative_accuracy_edge_does_not_block_a_rare_event(self):
        # The real spike_2atr logistic result: class_weight="balanced" makes it
        # predict positive often, wrecking accuracy while ranking stays good.
        assert _passes_gate(roc_auc=0.679, lift=2.64, edge_pp=-32.2, base_rate=0.85)

    def test_rare_event_still_needs_ranking_quality(self):
        assert not _passes_gate(roc_auc=0.52, lift=3.0, base_rate=0.85, edge_pp=0.0)

    def test_rare_event_still_needs_lift(self):
        assert not _passes_gate(roc_auc=0.70, lift=1.05, base_rate=0.85, edge_pp=0.0)


class TestBalancedTargets:
    """Base rate ~54%: the accuracy edge is a real, applicable hurdle."""

    def test_directional_model_with_no_edge_is_rejected(self):
        # The real up_5d result.
        assert not _passes_gate(roc_auc=0.525, lift=1.10, edge_pp=-0.235, base_rate=53.6)

    def test_balanced_target_needs_positive_edge_even_with_good_auc(self):
        assert not _passes_gate(roc_auc=0.62, lift=1.4, edge_pp=-0.1, base_rate=53.6)

    def test_balanced_target_passes_when_it_genuinely_beats_the_baseline(self):
        assert _passes_gate(roc_auc=0.62, lift=1.4, edge_pp=2.5, base_rate=53.6)


def test_nan_metrics_never_pass():
    assert not _passes_gate(roc_auc=float("nan"), lift=3.0, edge_pp=1.0, base_rate=1.0)
    assert not _passes_gate(roc_auc=0.7, lift=float("nan"), edge_pp=1.0, base_rate=1.0)
