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


def test_training_cycle_ingests_before_building_features():
    """Regression guard for a first-run failure.

    training_cycle used to build the feature frame before ingesting, so on a
    fresh database it found no bars and returned {"error": "no bars"} while
    reporting success. CI starts with an empty database every run, so this was
    invisible locally and fatal there.
    """
    import inspect

    from app import worker

    src = inspect.getsource(worker.training_cycle)
    ingest_at = src.index("ingest_bars")
    build_at = src.index("build_frame")
    assert ingest_at < build_at, "training_cycle must ingest before building features"


class TestTrainingIsDue:
    """Regression guard: the worker used to retrain on every restart."""

    from datetime import datetime, timedelta, timezone

    NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)

    def test_never_trained_is_due(self):
        from app.services.modeling import training_is_due
        assert training_is_due(None, self.NOW, 86400)

    def test_fresh_models_are_not_due_after_a_restart(self):
        from app.services.modeling import training_is_due
        two_hours_ago = self.NOW - self.timedelta(hours=2)
        assert not training_is_due(two_hours_ago, self.NOW, 86400)

    def test_stale_models_are_due(self):
        from app.services.modeling import training_is_due
        two_days_ago = self.NOW - self.timedelta(days=2)
        assert training_is_due(two_days_ago, self.NOW, 86400)

    def test_boundary_is_inclusive(self):
        from app.services.modeling import training_is_due
        exactly = self.NOW - self.timedelta(seconds=86400)
        assert training_is_due(exactly, self.NOW, 86400)


class TestTargetsAreWiredEverywhere:
    """Adding a target once broke three places that each listed targets by hand:
    the /predictions route pattern (422), the export payload (missing key) and
    the frontend fetch. These pin the single-source-of-truth wiring."""

    def test_route_pattern_accepts_every_target(self):
        import re
        from app.routers.market import TARGET_PATTERN
        from app.services.modeling import TARGETS
        for t in TARGETS:
            assert re.match(TARGET_PATTERN, t), f"{t} rejected by route pattern"

    def test_route_pattern_rejects_garbage(self):
        import re
        from app.routers.market import TARGET_PATTERN
        assert not re.match(TARGET_PATTERN, "spike_2atr; DROP TABLE")
        assert not re.match(TARGET_PATTERN, "")

    def test_export_iterates_the_canonical_target_list(self):
        import inspect
        from app import export
        src = inspect.getsource(export.build_payload)
        assert "modeling.TARGETS" in src
        assert '"spike_2atr": queries.predictions' not in src  # no hand-written keys


def test_prediction_history_round_trips_through_json(tmp_path):
    """export -> import must restore the exact rows; the CI track record
    depends on this file format surviving a stateless rebuild."""
    import json
    from datetime import date
    from app import prediction_history as ph

    payload = {"as_of": "2026-09-04", "rows": [
        {"s": "AAPL", "t": "spike_2atr", "m": "gradient_boosting", "p": 0.0123, "q": 98.5},
        {"s": "MSFT", "t": "spike_2atr", "m": "gradient_boosting", "p": 0.0045, "q": 61.0},
    ]}
    (tmp_path / "2026-09-04.json").write_text(json.dumps(payload))

    written = []
    class FakeDB:
        def execute(self, stmt): written.append(stmt)
        def commit(self): pass
    counts = ph.import_dir(FakeDB(), tmp_path)
    assert counts == {"2026-09-04": 2}
    assert len(written) == 1
    # The statement carries an ON CONFLICT DO NOTHING clause: history is
    # append-only and a rerun must never overwrite what was published.
    sql = str(written[0].compile(dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect()))
    assert "ON CONFLICT" in sql and "DO NOTHING" in sql
    assert date.fromisoformat(payload["as_of"]) == date(2026, 9, 4)


def test_prediction_history_never_overwrites_a_published_day(tmp_path):
    """A retrain or a fallback build must not replace the picks that were
    actually shown; the track record scores those and only those."""
    from datetime import date
    from app import prediction_history as ph

    original = tmp_path / "2026-09-04.json"
    original.write_text('{"as_of":"2026-09-04","rows":[{"s":"OLD","t":"x","m":"y","p":0.1,"q":1.0}]}')

    class FakeDB:
        def execute(self, stmt):
            class R:  # one row from a "new" model
                def __iter__(self): return iter([("NEW", "x", "y", 0.9, 99.0)])
                def all(self): return [("NEW", "x", "y", 0.9, 99.0)]
            return R()
    assert ph.export_day(FakeDB(), date(2026, 9, 4), tmp_path) == 0
    assert '"OLD"' in original.read_text() and '"NEW"' not in original.read_text()
