import pytest
from vyro_publishing_scheduler.store import QueueStore


def test_job_requires_approval_and_idempotency(tmp_path):
    store = QueueStore(tmp_path / "queue.db")
    args = ("vyro-1", "https://cdn.example/video.mp4", "caption", "2020-01-01T12:00:00+07:00", "key-1")
    job1 = store.add_job(*args)
    job2 = store.add_job(*args)
    assert job1 == job2
    assert store.claim_due() == []
    store.approve(job1)
    claimed = store.claim_due()
    assert len(claimed) == 1 and claimed[0]["status"] == "PROCESSING"
    store.complete(job1, "ig-123")
    assert store.list_due()[0]["status"] == "PUBLISHED"


def test_idempotency_key_rejects_changed_payload(tmp_path):
    store = QueueStore(tmp_path / "idempotency.db")
    store.add_job("vyro-2", "https://cdn.example/v.mp4", "caption", "2020-01-01T12:00:00+07:00", "key-2")
    with pytest.raises(ValueError):
        store.add_job("vyro-2", "https://cdn.example/other.mp4", "caption", "2020-01-01T12:00:00+07:00", "key-2")


def test_slot_scoring_without_metrics(tmp_path):
    store = QueueStore(tmp_path / "queue.db")
    assert store.recommend_slots()["status"] == "insufficient_data"


def test_fail_requeues_with_delay(tmp_path):
    store = QueueStore(tmp_path / "retry.db")
    job = store.add_job("vyro-3", "https://cdn.example/v.mp4", "caption", "2020-01-01T12:00:00+07:00", "key-3", max_attempts=2)
    store.approve(job)
    claimed = store.claim_due()
    assert claimed[0]["id"] == job
    store.fail(job, "temporary", retry_in=60)
    row = store.list_due()[0]
    assert row["status"] == "SCHEDULED"
    assert row["last_error"] == "temporary"


def test_rejects_naive_schedule_and_untrusted_url(tmp_path):
    store = QueueStore(tmp_path / "strict.db")
    with pytest.raises(ValueError):
        store.add_job("vyro-4", "http://cdn.example/v.mp4", "caption", "2026-11-24T10:00:00", "key-4")
    with pytest.raises(ValueError):
        store.add_job("vyro-4", "https://user:pass@cdn.example/v.mp4", "caption", "2026-11-24T10:00:00+07:00", "key-5")


def test_approval_can_be_revoked_before_claim(tmp_path):
    store = QueueStore(tmp_path / "approval.db")
    job = store.add_job("vyro-5", "https://cdn.example/v.mp4", "caption", "2020-01-01T12:00:00+07:00", "key-6")
    store.approve(job)
    store.revoke_approval(job)
    assert store.claim_due() == []


def test_new_job_starts_pending_approval(tmp_path):
    store = QueueStore(tmp_path / "pending.db")
    job = store.add_job("vyro-6", "https://cdn.example/v.mp4", "caption", "2020-01-01T12:00:00+07:00", "key-7")
    row = next(item for item in store.list_due() if item["id"] == job)
    assert row["status"] == "PENDING_APPROVAL"
    assert row["approved"] == 0
