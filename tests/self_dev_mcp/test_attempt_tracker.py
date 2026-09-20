import threading

from fleetmcp.self_dev_mcp.attempt_tracker import AttemptTracker


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


def test_try_record_attempt_returns_true_up_to_cap():
    tracker = AttemptTracker(max_attempts=3)
    assert tracker.try_record_attempt("issue-1") is True
    assert tracker.try_record_attempt("issue-1") is True
    assert tracker.try_record_attempt("issue-1") is True
    assert tracker.try_record_attempt("issue-1") is False


def test_try_record_attempt_concurrency():
    """Test that exactly max_attempts threads succeed when calling try_record_attempt concurrently."""
    tracker = AttemptTracker(max_attempts=5)
    results = []
    threads = []
    lock = threading.Lock()

    def attempt():
        result = tracker.try_record_attempt("issue-1")
        with lock:
            results.append(result)

    # Start 20 threads
    for _ in range(20):
        t = threading.Thread(target=attempt)
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Exactly 5 should have succeeded
    assert results.count(True) == 5
    assert results.count(False) == 15
