import pytest
from vyro_publishing_scheduler.store import QueueStore

def test_idempotency_and_claim(tmp_path):
 store=QueueStore(tmp_path/"queue.db")
 job1=store.add_job("vyro-1","https://cdn.example/video.mp4","caption","2020-01-01T12:00:00+07:00","key-1")
 job2=store.add_job("vyro-1","https://cdn.example/video.mp4","caption","2020-01-01T12:00:00+07:00","key-1")
 assert job1==job2
 claimed=store.claim_due()
 assert len(claimed)==1 and claimed[0]["status"]=="PROCESSING"
 store.complete(job1,"ig-123")
 assert store.list_due()[0]["status"]=="PUBLISHED"

def test_slot_scoring_without_metrics(tmp_path):
 store=QueueStore(tmp_path/"queue.db")
 assert store.recommend_slots()["status"]=="insufficient_data"


def test_fail_requeues_with_delay(tmp_path):
 store=QueueStore(tmp_path/"retry.db")
 job=store.add_job("vyro-2","https://cdn.example/v.mp4","caption","2020-01-01T12:00:00+07:00","key-2",max_attempts=2)
 claimed=store.claim_due()
 assert claimed[0]["id"]==job
 store.fail(job,"temporary",retry_in=60)
 row=store.list_due()[0]
 assert row["status"]=="SCHEDULED"
 assert row["last_error"]=="temporary"


def test_rejects_naive_schedule_and_untrusted_url(tmp_path):
 store=QueueStore(tmp_path/"strict.db")
 with pytest.raises(ValueError):
  store.add_job("vyro-3","http://cdn.example/v.mp4","caption","2026-11-24T10:00:00","key-3")
 with pytest.raises(ValueError):
  store.add_job("vyro-3","https://user:pass@cdn.example/v.mp4","caption","2026-11-24T10:00:00+07:00","key-4")
