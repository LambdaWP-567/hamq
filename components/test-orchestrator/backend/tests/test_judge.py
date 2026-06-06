import pytest
from app.judge import Judge


def test_no_gaps():
    j = Judge(max_val=10)
    for i in range(1, 11):
        j.record(i)
    assert j.missing() == []
    assert j.completion_pct() == 100.0


def test_detects_gaps():
    j = Judge(max_val=10)
    for i in [1, 2, 4, 5, 7]:
        j.record(i)
    missing = j.missing()
    assert 3 in missing
    assert 6 in missing


def test_cycle_increments():
    j = Judge(max_val=5)
    for i in range(1, 6):
        j.record(i)
    assert j.cycle == 0
    j.record(1)  # new cycle
    assert j.cycle == 1
    assert 1 in j.received
    assert len(j.received) == 1


def test_reset():
    j = Judge(max_val=5)
    for i in range(1, 6):
        j.record(i)
    j.record(1)
    j.reset()
    assert j.cycle == 0
    assert len(j.received) == 0
    assert j.missing() == []


def test_completion_pct_partial():
    j = Judge(max_val=10)
    for i in [1, 2, 3, 4, 5]:
        j.record(i)
    assert j.completion_pct() == 100.0
    j.record(7)
    assert j.completion_pct() < 100.0


def test_empty_judge():
    j = Judge(max_val=10)
    assert j.missing() == []
    assert j.completion_pct() == 0.0
    assert j.missing_count() == 0
