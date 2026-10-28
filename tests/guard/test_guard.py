"""Acceptance tests for issue #6 (Phase 04a): Agent Resource Guard.

Limits in TEST_POLICY are round numbers written here, not read from config/guard-policy.json,
so expected thresholds are independent of the code under test (warn_at_fraction 0.8).
"""

from __future__ import annotations

import copy
import json
import random
import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import guard.budget as guard_budget
from guard import (
    DEFAULT_POLICY_FILE,
    Guard,
    GuardStop,
    Level,
    Limit,
    ModelUsage,
    PolicyError,
    RequestResult,
    UnknownProfileError,
    UsageLogError,
    load_policy,
    parse_policy,
    warning_message_de,
)

TEST_POLICY = {
    "schema_version": "1",
    "global": {"session_budget_usd": 3.0, "daily_budget_usd": 5.0, "max_concurrent_requests": 1},
    "profiles": {
        "p": {
            "max_output_tokens": 1000,
            "max_model_calls": 5,
            "max_tool_calls": 5,
            "max_budget_usd": 1.0,
            "timeout_s": 100,
            "max_identical_tool_calls": 3,
            "max_files_written": 10,
            "max_live_writes": 5,
            "warn_at_fraction": 0.8,
        }
    },
}

BERLIN = timezone(timedelta(hours=1))


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class FakeNow:
    def __init__(self) -> None:
        self.dt = datetime(2026, 10, 28, 12, 0, tzinfo=BERLIN)

    def __call__(self) -> datetime:
        return self.dt


def policy(**changes):
    doc = copy.deepcopy(TEST_POLICY)
    for dotted, value in changes.items():
        section, key = dotted.split("__")
        target = doc["global"] if section == "g" else doc["profiles"]["p"]
        target[key] = value
    return parse_policy(doc)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def now():
    return FakeNow()


@pytest.fixture
def make_guard(tmp_path, clock, now):
    def make(pol=None, log_path=None):
        return Guard(
            pol or policy(), log_path=log_path or tmp_path / "usage.jsonl", clock=clock, now=now
        )

    return make


def model_call(req, est=0.0, cost=0.0, tokens=10):
    permit = req.before_model_call(estimated_cost_usd=est)
    return req.after_model_call(permit, ModelUsage(output_tokens=tokens, cost_usd=cost))


def tool_call(req, name="t", args=None, files=0, live=0, actual_files=None, actual_live=None):
    permit = req.before_tool(name, args if args is not None else {}, writes_files=files,
                             live_writes=live)
    return req.after_tool(permit, files_written=actual_files, live_writes=actual_live)


# --- policy -------------------------------------------------------------------------------


def test_default_policy_loads_and_has_both_profiles():
    pol = load_policy(DEFAULT_POLICY_FILE)
    assert pol.profile("kick_generation").max_model_calls == 8
    assert pol.profile("mentor_answer").max_live_writes == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["profiles"]["p"].pop("timeout_s"),
        lambda d: d["profiles"]["p"].update(max_tool_calls="5"),
        lambda d: d["profiles"]["p"].update(max_tool_calls=True),
        lambda d: d["profiles"]["p"].update(warn_at_fraction=1.0),
        lambda d: d["profiles"]["p"].update(extra=1),
        lambda d: d["global"].update(session_budget_usd=0),
        lambda d: d.update(profiles={}),
    ],
    ids=["missing", "string", "bool", "warn=1", "unknown-key", "zero-budget", "no-profiles"],
)
def test_malformed_policy_is_rejected(mutate):
    doc = copy.deepcopy(TEST_POLICY)
    mutate(doc)
    with pytest.raises(PolicyError):
        parse_policy(doc)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_in_policy_file_are_rejected(tmp_path, token):
    text = json.dumps(TEST_POLICY).replace('"max_budget_usd": 1.0', f'"max_budget_usd": {token}')
    assert token in text
    path = tmp_path / "pol.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(path)


def test_unreadable_or_broken_policy_file(tmp_path):
    with pytest.raises(PolicyError):
        load_policy(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(bad)


def test_unknown_profile_is_rejected(make_guard):
    with pytest.raises(UnknownProfileError, match="Known profiles: p"):
        make_guard().request("nope")


# --- one warn and one stop test per limit -------------------------------------------------


def test_model_calls_warn_and_stop(make_guard):
    with make_guard().request("p") as req:
        assert [model_call(req) for _ in range(3)] == [Level.OK] * 3
        assert model_call(req) == Level.WARN  # 4 >= 0.8 * 5
        assert model_call(req) == Level.WARN  # the 5th of 5 still runs
        with pytest.raises(GuardStop) as info:
            req.before_model_call(estimated_cost_usd=0.0)
    assert info.value.reason is Limit.MODEL_CALLS


def test_tool_calls_warn_and_stop(make_guard):
    with make_guard().request("p") as req:
        assert [tool_call(req, args={"i": i}) for i in range(3)] == [Level.OK] * 3
        assert tool_call(req, args={"i": 3}) == Level.WARN
        assert tool_call(req, args={"i": 4}) == Level.WARN
        with pytest.raises(GuardStop) as info:
            req.before_tool("t", {"i": 5})
    assert info.value.reason is Limit.TOOL_CALLS


def test_output_tokens_warn_and_stop(make_guard):
    with make_guard().request("p") as req:
        assert model_call(req, tokens=799) == Level.OK
        assert model_call(req, tokens=800) == Level.WARN
        with pytest.raises(GuardStop) as info:
            model_call(req, tokens=1001)
    assert info.value.reason is Limit.OUTPUT_TOKENS


def test_asking_for_more_output_tokens_than_the_profile_is_a_bug(make_guard):
    with make_guard().request("p") as req:
        assert req.before_model_call(estimated_cost_usd=0).max_output_tokens == 1000
        with pytest.raises(ValueError):
            req.before_model_call(estimated_cost_usd=0, max_output_tokens=1001)


def test_request_budget_warn_and_stop_before_the_call(make_guard):
    with make_guard().request("p") as req:
        assert model_call(req, est=0.5, cost=0.5) == Level.OK
        assert model_call(req, est=0.3, cost=0.3) == Level.WARN  # 0.8 of 1.0
        with pytest.raises(GuardStop) as info:
            req.before_model_call(estimated_cost_usd=0.3)  # 0.8 + 0.3 > 1.0
    assert info.value.reason is Limit.REQUEST_BUDGET


def test_request_budget_overshoot_by_a_finished_call_stops(make_guard):
    with make_guard().request("p") as req:
        with pytest.raises(GuardStop) as info:
            model_call(req, est=0.1, cost=1.2)
    assert info.value.reason is Limit.REQUEST_BUDGET


def test_session_total_stops_a_request_whose_own_profile_has_room(make_guard):
    guard = make_guard(policy(g__session_budget_usd=1.5))
    with guard.request("p") as req:
        model_call(req, est=1.0, cost=1.0)
        req.finish()
    with guard.request("p") as req:
        assert model_call(req, est=0.3, cost=0.3) == Level.WARN  # session 1.3 >= 1.2
        assert Limit.SESSION_BUDGET in req.warnings
        with pytest.raises(GuardStop) as info:
            req.before_model_call(estimated_cost_usd=0.3)  # request has 0.7 left
    assert info.value.reason is Limit.SESSION_BUDGET


def test_daily_total_survives_a_restart_and_stops(tmp_path, make_guard, now):
    log = tmp_path / "usage.jsonl"
    big = policy(p__max_budget_usd=4.5, g__session_budget_usd=4.5)
    with make_guard(big, log_path=log).request("p") as req:
        model_call(req, est=4.5, cost=4.5)
        req.finish()
    with make_guard(log_path=log).request("p") as req:  # new session, same day
        model_call(req, est=0.0, cost=0.0)
        assert Limit.DAILY_BUDGET in req.warnings  # 4.5 >= 0.8 * 5.0
        with pytest.raises(GuardStop) as info:
            req.before_model_call(estimated_cost_usd=0.6)
    assert info.value.reason is Limit.DAILY_BUDGET
    now.dt += timedelta(days=1)
    with make_guard(log_path=log).request("p") as req:
        assert model_call(req, est=0.6, cost=0.6) == Level.OK


def test_timeout_warns_and_stops_with_injected_clock(make_guard, clock):
    with make_guard().request("p") as req:
        clock.t += 79.9
        assert tool_call(req, args={"i": 0}) == Level.OK
        clock.t += 0.1  # 80 s = 0.8 * 100
        assert tool_call(req, args={"i": 1}) == Level.WARN
        assert req.remaining_s() == pytest.approx(20.0)
        clock.t += 20.0
        with pytest.raises(GuardStop) as info:
            req.before_tool("t", {"i": 2})
    assert info.value.reason is Limit.TIMEOUT


def test_timeout_reached_during_a_model_call_stops_after_it(make_guard, clock):
    with make_guard().request("p") as req:
        permit = req.before_model_call(estimated_cost_usd=0.0)
        clock.t += 150
        with pytest.raises(GuardStop) as info:
            req.after_model_call(permit, ModelUsage(output_tokens=1, cost_usd=0.0))
    assert info.value.reason is Limit.TIMEOUT


def test_loop_same_tool_same_args_stops(make_guard):
    with make_guard().request("p") as req:
        args = {"bpm": 136, "tone": -0.5}
        assert tool_call(req, args=args) == Level.OK
        assert tool_call(req, args=args) == Level.OK  # 2 < 0.8 * 3
        assert tool_call(req, args=args) == Level.WARN
        with pytest.raises(GuardStop) as info:
            req.before_tool("t", {"tone": -0.5, "bpm": 136.0})  # same call, other spelling
    assert info.value.reason is Limit.LOOP


def test_loop_same_tool_different_args_does_not_stop(make_guard):
    pol = policy(p__max_tool_calls=50)
    with make_guard(pol).request("p") as req:
        for i in range(40):
            tool_call(req, args={"seed": i})
        assert Limit.LOOP not in req.warnings


def test_loop_keeps_bool_and_int_apart(make_guard):
    with make_guard(policy(p__max_identical_tool_calls=1)).request("p") as req:
        tool_call(req, args={"x": 1})
        tool_call(req, args={"x": True})
        tool_call(req, args={"x": "1"})
        with pytest.raises(GuardStop):
            req.before_tool("t", {"x": 1.0})


def test_files_written_warn_and_stop(make_guard):
    with make_guard().request("p") as req:
        assert tool_call(req, args={"i": 0}, files=7) == Level.OK
        assert tool_call(req, args={"i": 1}, files=1) == Level.WARN  # 8 >= 0.8 * 10
        with pytest.raises(GuardStop) as info:
            req.before_tool("t", {"i": 2}, writes_files=3)  # 8 + 3 > 10
    assert info.value.reason is Limit.FILES


def test_files_actual_above_declared_stops(make_guard):
    with make_guard().request("p") as req:
        with pytest.raises(GuardStop) as info:
            tool_call(req, files=2, actual_files=11)
    assert info.value.reason is Limit.FILES


def test_files_actual_below_declared_frees_room(make_guard):
    with make_guard().request("p") as req:
        tool_call(req, args={"i": 0}, files=10, actual_files=2)
        assert tool_call(req, args={"i": 1}, files=8) == Level.WARN  # 2 + 8 = 10


def test_live_writes_warn_and_stop(make_guard):
    with make_guard().request("p") as req:
        assert tool_call(req, args={"i": 0}, live=3) == Level.OK
        assert tool_call(req, args={"i": 1}, live=1) == Level.WARN  # 4 >= 0.8 * 5
        with pytest.raises(GuardStop) as info:
            req.before_tool("t", {"i": 2}, live_writes=2)
    assert info.value.reason is Limit.LIVE_WRITES


def test_mentor_profile_cannot_write(tmp_path, clock, now):
    guard = Guard(load_policy(), log_path=tmp_path / "u.jsonl", clock=clock, now=now)
    with guard.request("mentor_answer") as req:
        tool_call(req, name="list_tracks")  # reading is fine
        with pytest.raises(GuardStop) as info:
            req.before_tool("import_sample", {}, live_writes=1)
    assert info.value.reason is Limit.LIVE_WRITES


def test_concurrent_request_limit(make_guard):
    guard = make_guard()
    with guard.request("p"):
        with pytest.raises(GuardStop) as info:
            with guard.request("p"):
                pass
        assert info.value.reason is Limit.CONCURRENCY
    with guard.request("p") as req:  # the slot is free again
        assert req.level is Level.OK


# --- conservative counting ----------------------------------------------------------------


def test_missing_usage_counts_the_reserved_amount(make_guard):
    guard = make_guard()
    with guard.request("p") as req:
        permit = req.before_model_call(estimated_cost_usd=0.4)
        req.after_model_call(permit, None)
        assert guard.session_spent_usd == pytest.approx(0.4)
        assert Limit.OUTPUT_TOKENS in req.warnings  # unknown tokens count as 1000


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, True, "0.1"])
def test_unreadable_reported_cost_counts_the_reservation_and_stops(make_guard, bad):
    guard = make_guard()
    with guard.request("p") as req:
        permit = req.before_model_call(estimated_cost_usd=0.25)
        with pytest.raises(GuardStop) as info:
            req.after_model_call(permit, ModelUsage(output_tokens=5, cost_usd=bad))
    assert info.value.reason is Limit.UNREADABLE_USAGE
    assert guard.session_spent_usd == pytest.approx(0.25)


@pytest.mark.parametrize("tokens", [5000.0, np.int64(5000)])
def test_whole_number_reports_of_other_types_still_count(make_guard, tokens):
    with make_guard().request("p") as req:
        permit = req.before_model_call(estimated_cost_usd=0.1)
        with pytest.raises(GuardStop) as info:
            req.after_model_call(
                permit, ModelUsage(output_tokens=tokens, cost_usd=np.float32(0.1))
            )
    assert info.value.reason is Limit.OUTPUT_TOKENS


@pytest.mark.parametrize("files", [20.0, np.int64(20)])
def test_files_reported_as_float_or_numpy_still_count(make_guard, files):
    with make_guard().request("p") as req:
        with pytest.raises(GuardStop) as info:
            tool_call(req, files=1, actual_files=files)
    assert info.value.reason is Limit.FILES


@pytest.mark.parametrize("bad", [2.5, -1, "3", float("nan")])
def test_unreadable_tool_counts_stop(make_guard, bad):
    with make_guard().request("p") as req:
        with pytest.raises(GuardStop) as info:
            tool_call(req, files=1, actual_files=bad)
    assert info.value.reason is Limit.UNREADABLE_USAGE


def test_no_estimate_reserves_everything_left(make_guard):
    guard = make_guard()
    with guard.request("p") as req:
        permit = req.before_model_call()
        assert permit.reserved_cost_usd == pytest.approx(1.0)
        with pytest.raises(GuardStop) as info:
            req.before_model_call(estimated_cost_usd=0.0)  # nothing left while in flight
        assert info.value.reason is Limit.REQUEST_BUDGET


def test_unsettled_calls_are_counted_on_exit(make_guard):
    guard = make_guard()
    with guard.request("p") as req:
        req.before_model_call(estimated_cost_usd=0.7)
    assert guard.session_spent_usd == pytest.approx(0.7)


def test_invalid_estimate_and_counts_are_rejected(make_guard):
    with make_guard().request("p") as req:
        for bad in (float("nan"), -1, True):
            with pytest.raises(ValueError):
                req.before_model_call(estimated_cost_usd=bad)
        for bad in (-1, 1.5, True):
            with pytest.raises(ValueError):
                req.before_tool("t", {}, writes_files=bad)


# --- a stopped request is never a success -------------------------------------------------


def test_stop_is_sticky_and_finish_cannot_succeed(make_guard):
    with make_guard().request("p") as req:
        req.add_open("kick 2")
        tool_call(req, args={"i": 0})
        try:
            req.before_tool("t", {"i": 1}, live_writes=6)
        except GuardStop:
            pass  # an orchestrator that swallows the stop …
        with pytest.raises(GuardStop):
            req.finish("done")  # … still cannot report success
        with pytest.raises(GuardStop):
            req.before_model_call(estimated_cost_usd=0)
        assert req.level is Level.STOP
    stop = info_of(req)
    assert stop.result.success is False
    assert stop.done == ("Werkzeug t",)
    assert stop.open == ("kick 2", "Werkzeug t")
    assert "Abgebrochen" in stop.user_message_de and "kick 2" in stop.user_message_de


def info_of(req):
    with pytest.raises(GuardStop) as info:
        req.finish()
    return info.value


def test_result_object_refuses_success_with_stop_or_open_items():
    with pytest.raises(ValueError):
        RequestResult(True, "p", "r", (), (), Limit.TIMEOUT, None)
    with pytest.raises(ValueError):
        RequestResult(True, "p", "r", (), ("x",), None, None)
    with pytest.raises(ValueError):
        RequestResult(False, "p", "r", (), (), None, None)


def test_finish_requires_settled_calls_and_no_open_items(make_guard):
    with make_guard().request("p") as req:
        req.add_open("kick 1")
        permit = req.before_model_call(estimated_cost_usd=0)
        with pytest.raises(ValueError):
            req.finish()
        req.after_model_call(permit, ModelUsage(output_tokens=1, cost_usd=0))
        with pytest.raises(ValueError):
            req.finish()
        req.mark_done("kick 1")
        result = req.finish("ok")
    assert result.success and result.done == ("kick 1",)
    with pytest.raises(RuntimeError):
        req.before_tool("t", {})


def test_failed_tool_is_listed_as_open(make_guard):
    with make_guard().request("p") as req:
        permit = req.before_tool("import_sample", {})
        req.after_tool(permit, ok=False, label="Import Kick 1")
        assert req.open == ("Import Kick 1",)


# --- threads ------------------------------------------------------------------------------


def test_concurrent_reservations_never_exceed_the_session_budget(make_guard, monkeypatch):
    # Widen the gap between "does it fit?" and "reserve" so a missing lock shows up reliably;
    # without the sleep the GIL hides the race (fault-injection run, see PR).
    original_fits = guard_budget.Counter.fits

    def slow_fits(self, amount, *, needs_room=False):
        result = original_fits(self, amount, needs_room=needs_room)
        time.sleep(0.0002)
        return result

    monkeypatch.setattr(guard_budget.Counter, "fits", slow_fits)
    guard = make_guard(policy(g__max_concurrent_requests=8, g__session_budget_usd=1.0,
                              p__max_model_calls=100))
    barrier = threading.Barrier(8)
    granted = []

    def worker():
        with guard.request("p") as req:
            barrier.wait()
            permits = []
            try:
                while True:
                    permits.append(req.before_model_call(estimated_cost_usd=0.03))
            except GuardStop:
                pass
            granted.append(len(permits))
            for p in permits:
                try:
                    req.after_model_call(p, ModelUsage(output_tokens=1, cost_usd=0.03))
                except GuardStop:
                    pass  # settling after a stop records the call, then re-raises the stop

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(granted) == 33  # floor(1.0 / 0.03), checked by hand
    assert guard.session_spent_usd <= 1.0 + 1e-9


def test_concurrent_tool_calls_in_one_request_hit_the_limit_exactly(make_guard, monkeypatch):
    original_fits = guard_budget.Counter.fits

    def slow_fits(self, amount, *, needs_room=False):
        result = original_fits(self, amount, needs_room=needs_room)
        time.sleep(0.0002)  # widen the check-then-act gap, as in the session test
        return result

    monkeypatch.setattr(guard_budget.Counter, "fits", slow_fits)
    guard = make_guard(policy(p__max_tool_calls=50, p__max_files_written=500))
    barrier = threading.Barrier(16)
    ok = []
    with guard.request("p") as req:

        def worker(n):
            barrier.wait()
            for i in range(10):
                try:
                    req.before_tool("t", {"n": n, "i": i}, writes_files=1)
                    ok.append(1)
                except GuardStop:
                    return

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert len(ok) == 50


# --- usage log ----------------------------------------------------------------------------


def test_usage_log_records_estimated_and_actual(tmp_path, make_guard):
    log = tmp_path / "usage.jsonl"
    with make_guard(log_path=log).request("p") as req:
        model_call(req, est=0.2, cost=0.15, tokens=42)
        tool_call(req, name="generate_kick", files=2)
        req.finish()
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [x["kind"] for x in lines] == ["model", "tool", "request_end"]
    m = lines[0]
    costs = (m["estimated_cost_usd"], m["actual_cost_usd"], m["counted_cost_usd"])
    assert costs == (0.2, 0.15, 0.15)
    assert m["actual_output_tokens"] == 42 and m["date"] == "2026-10-28"
    assert lines[2]["outcome"] == "success"


def test_corrupt_log_lines_are_skipped(tmp_path, make_guard):
    log = tmp_path / "usage.jsonl"
    good = {"kind": "model", "date": "2026-10-28", "counted_cost_usd": 4.9}
    log.write_text(
        json.dumps(good) + "\n{cut off\n"
        + '{"kind": "model", "date": "2026-10-28", "counted_cost_usd": NaN}\n',
        encoding="utf-8",
    )
    guard = make_guard(log_path=log)
    assert guard.daily_spent_usd == pytest.approx(4.9)
    assert guard._log.skipped_lines == 2


def test_unwritable_usage_log_stops_the_request(tmp_path, make_guard):
    log = tmp_path / "usage.jsonl"
    guard = make_guard(log_path=log)
    with guard.request("p") as req:
        permit = req.before_model_call(estimated_cost_usd=0.1)
        log.mkdir()  # the log path becomes unwritable while the call runs
        with pytest.raises(GuardStop) as info:
            req.after_model_call(permit, ModelUsage(output_tokens=1, cost_usd=0.1))
    assert info.value.reason is Limit.USAGE_LOG
    assert guard.session_spent_usd == pytest.approx(0.1)  # still counted in memory
    assert req.log_errors  # the request_end line could not be written either


def test_unreadable_usage_log_stops_before_the_next_model_call(tmp_path, make_guard):
    log = tmp_path / "usage.jsonl"
    guard = make_guard(log_path=log)
    log.mkdir()
    with guard.request("p") as req:
        with pytest.raises(GuardStop) as info:
            req.before_model_call(estimated_cost_usd=0.1)
    assert info.value.reason is Limit.USAGE_LOG


def test_unreadable_usage_log_refuses_to_start(tmp_path, make_guard):
    log = tmp_path / "usage.jsonl"
    log.mkdir()
    with pytest.raises(UsageLogError):
        make_guard(log_path=log)


# --- helpers for 04b ----------------------------------------------------------------------


def test_sdk_limits_follow_the_tightest_budget(make_guard):
    guard = make_guard(policy(g__session_budget_usd=1.5))
    with guard.request("p") as req:
        model_call(req, est=1.0, cost=1.0)
        req.finish()
    with guard.request("p") as req:
        model_call(req, est=0.1, cost=0.1)
        assert req.sdk_limits() == {"max_turns": 4, "max_budget_usd": pytest.approx(0.4)}


def test_warning_message_is_german():
    assert warning_message_de([]) == ""
    assert "Hinweis" in warning_message_de([Limit.TOOL_CALLS])


# --- property test: random operation sequences over the full limit range ------------------


@pytest.mark.parametrize("seed", range(40))
def test_random_sequences_never_breach_count_limits(tmp_path, clock, now, seed):
    rng = random.Random(seed)
    doc = copy.deepcopy(TEST_POLICY)
    doc["global"]["max_concurrent_requests"] = 1
    doc["global"]["session_budget_usd"] = rng.uniform(0.05, 5)
    doc["global"]["daily_budget_usd"] = rng.uniform(0.05, 10)
    prof = doc["profiles"]["p"]
    prof.update(
        max_output_tokens=rng.randint(64, 32000),
        max_model_calls=rng.randint(1, 100),
        max_tool_calls=rng.randint(0, 200),
        max_budget_usd=rng.uniform(0.01, 3),
        timeout_s=rng.uniform(5, 3600),
        max_identical_tool_calls=rng.randint(1, 20),
        max_files_written=rng.randint(0, 500),
        max_live_writes=rng.randint(0, 100),
        warn_at_fraction=rng.uniform(0.05, 0.95),
    )
    guard = Guard(parse_policy(doc), log_path=tmp_path / "u.jsonl", clock=clock, now=now)
    stop = None
    with guard.request("p") as req:
        for _ in range(300):
            clock.t += rng.uniform(0, prof["timeout_s"] / 100)
            try:
                if rng.random() < 0.4:
                    p = req.before_model_call(
                        estimated_cost_usd=rng.uniform(0, prof["max_budget_usd"] / 5)
                    )
                    req.after_model_call(p, ModelUsage(
                        output_tokens=rng.randint(0, prof["max_output_tokens"]),
                        cost_usd=p.reserved_cost_usd * rng.uniform(0.5, 1.0)))
                else:
                    p = req.before_tool("t", {"a": rng.randint(0, 3)},
                                        writes_files=rng.randint(0, 3),
                                        live_writes=rng.randint(0, 2))
                    req.after_tool(p)
            except GuardStop as exc:
                stop = exc
                break
        usage = req._usage()
    assert usage["model_calls"] <= prof["max_model_calls"]
    assert usage["tool_calls"] <= prof["max_tool_calls"]
    assert usage["files_written"] <= prof["max_files_written"]
    assert usage["live_writes"] <= prof["max_live_writes"]
    # Actual cost is never above the estimate here, so money never overshoots.
    assert usage["cost_usd"] <= prof["max_budget_usd"] + 1e-9
    assert guard.session_spent_usd <= doc["global"]["session_budget_usd"] + 1e-9
    assert guard.daily_spent_usd <= doc["global"]["daily_budget_usd"] + 1e-9
    if stop is not None:
        assert stop.result.success is False
        assert usage["elapsed_s"] < prof["timeout_s"] or stop.reason is Limit.TIMEOUT


# --- review round 1 (findings P1-P8) --------------------------------------------------------


def test_two_guards_on_one_log_share_the_daily_budget(tmp_path, make_guard):
    log = tmp_path / "usage.jsonl"
    big = policy(p__max_budget_usd=4.9, g__session_budget_usd=5.0)
    a, b = make_guard(big, log_path=log), make_guard(big, log_path=log)
    with a.request("p") as req:
        model_call(req, est=4.9, cost=4.9)
        req.finish()
    with b.request("p") as req:  # b was created before a spent anything
        with pytest.raises(GuardStop) as info:
            req.before_model_call(estimated_cost_usd=0.2)
    assert info.value.reason is Limit.DAILY_BUDGET


def test_call_open_at_midnight_is_charged_to_the_day_it_started(tmp_path, make_guard, now):
    log = tmp_path / "usage.jsonl"
    big = policy(p__max_budget_usd=4.9, g__session_budget_usd=5.0)
    now.dt = datetime(2026, 10, 28, 23, 59, 59, tzinfo=BERLIN)
    with make_guard(big, log_path=log).request("p") as req:
        permit = req.before_model_call(estimated_cost_usd=4.9)
        now.dt = datetime(2026, 10, 29, 0, 0, 1, tzinfo=BERLIN)
        req.after_model_call(permit, ModelUsage(output_tokens=1, cost_usd=4.9))
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert entry["date"] == "2026-10-28"
    fresh = make_guard(big, log_path=log)
    assert fresh.daily_spent_usd == 0.0  # 29th: nothing spent yet


def test_permit_from_another_request_is_rejected(make_guard):
    guard = make_guard(policy(g__max_concurrent_requests=2))
    with guard.request("p") as ra, guard.request("p") as rb:
        pa = ra.before_model_call(estimated_cost_usd=0.1)
        rb.before_model_call(estimated_cost_usd=0.9)
        with pytest.raises(ValueError):
            rb.after_model_call(pa, ModelUsage(output_tokens=1, cost_usd=0.0))
        ta = ra.before_tool("t", {})
        with pytest.raises(ValueError):
            rb.after_tool(ta)
    assert guard.session_spent_usd == pytest.approx(1.0)


def test_failure_on_exit_keeps_the_original_error_and_frees_the_slot(make_guard, now):
    guard = make_guard()

    def broken_now():
        raise OSError("clock")

    with pytest.raises(KeyError):
        with guard.request("p") as req:
            req.before_model_call(estimated_cost_usd=0.1)
            now_backup = guard._now
            guard._now = broken_now
            raise KeyError("original")
    guard._now = now_backup
    assert req.log_errors
    with guard.request("p") as req2:  # the concurrency slot was released
        assert req2.level is Level.OK


def test_parse_policy_rejects_nan():
    doc = copy.deepcopy(TEST_POLICY)
    doc["global"]["session_budget_usd"] = float("nan")
    with pytest.raises(PolicyError, match="session_budget_usd"):
        parse_policy(doc)


def test_ok_must_be_a_bool(make_guard):
    with make_guard().request("p") as req:
        permit = req.before_tool("t", {})
        with pytest.raises(TypeError):
            req.after_tool(permit, ok="False")


def test_exception_after_finish_is_not_logged_as_success(tmp_path, make_guard):
    log = tmp_path / "usage.jsonl"
    with pytest.raises(RuntimeError):
        with make_guard(log_path=log).request("p") as req:
            req.finish()
            raise RuntimeError("after finish")
    end = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert end["outcome"] == "error"
