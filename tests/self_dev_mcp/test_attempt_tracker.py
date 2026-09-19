from services.self_dev_mcp.attempt_tracker import AttemptTracker


def test_attempts_remaining_decreases_with_each_record():
    tracker = AttemptTracker(max_attempts=3)
    assert tracker.attempts_remaining("issue-1") == 3
    tracker.record_attempt("issue-1")
    assert tracker.attempts_remaining("issue-1") == 2


def test_is_exhausted_after_max_attempts():
    tracker = AttemptTracker(max_attempts=2)
    tracker.record_attempt("issue-1")
    assert not tracker.is_exhausted("issue-1")
    tracker.record_attempt("issue-1")
    assert tracker.is_exhausted("issue-1")


def test_attempts_are_scoped_per_issue():
    tracker = AttemptTracker(max_attempts=1)
    tracker.record_attempt("issue-1")
    assert tracker.is_exhausted("issue-1")
    assert not tracker.is_exhausted("issue-2")
