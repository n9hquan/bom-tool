import uuid
from app.models import Job

_jobs: dict[str, Job] = {}


def create_job() -> Job:
    job_id = str(uuid.uuid4())
    job = Job(job_id=job_id)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def delete_old_jobs(keep_latest: int = 50) -> None:
    if len(_jobs) > keep_latest:
        oldest = list(_jobs.keys())[: len(_jobs) - keep_latest]
        for jid in oldest:
            _jobs.pop(jid, None)
