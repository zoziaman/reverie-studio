from utils.batch_queue import BatchQueue


def test_retry_job_preserves_resume_from_checkpoint_flag(tmp_path):
    queue = BatchQueue(str(tmp_path))
    job_id = queue.add_job(
        channel="senior",
        mode="life_saguk",
        resume_from_checkpoint=False,
    )
    assert queue.fail_job(job_id, "boom") is True

    retry_id = queue.retry_job(job_id)

    assert retry_id is not None
    retry_job = queue.get_job(retry_id)
    assert retry_job is not None
    assert retry_job["resume_from_checkpoint"] is False
