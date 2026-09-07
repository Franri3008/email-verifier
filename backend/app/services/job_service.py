import time

from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import session
from app.core.security import cipher, rate_limit, seal, unseal, user_settings
from app.models.persistence import Job, User


def enqueue(user, kind, payload, filename="", upload=None):
    settings = get_settings()
    provider = user_settings(user.id)
    if not provider.has_verifalia_credentials:
        raise HTTPException(422, "Add your Verifalia credentials in Settings first.")
    needs_lookup = (kind == "simple" and "@" not in payload["query"]) or payload.get(
        "generate_missing"
    )
    if needs_lookup and not provider.openrouter_api_key:
        raise HTTPException(422, "Add your OpenRouter key in Settings first.")
    rate_limit("jobs:" + user.id, settings.max_jobs_per_hour, 3600)
    with session() as db, db.begin():
        # Serializes enqueue operations for this user across web instances.
        current = db.scalar(select(User).where(User.id == user.id).with_for_update())
        if not current or not current.active:
            raise HTTPException(401, "Account is disabled.")
        count = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == user.id, Job.status.in_(["queued", "running"]))
        )
        if count >= settings.max_active_jobs:
            raise HTTPException(
                429, "You already have active jobs. Wait for one to finish."
            )
        job = Job(
            user_id=user.id,
            kind=kind,
            payload=seal(payload),
            filename=filename,
            upload=cipher().encrypt(upload) if upload else None,
            expires=time.time() + settings.retention_hours * 3600,
        )
        db.add(job)
        db.flush()
        return describe(job)


def owned_job(db, user_id, job_id):
    job = db.scalar(
        select(Job).where(
            Job.id == job_id, Job.user_id == user_id, Job.expires > time.time()
        )
    )
    if not job:
        raise HTTPException(404, "Job not found or expired.")
    return job


def describe(job, include_result=False):
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "filename": job.filename,
        "created": job.created,
        "expires": job.expires,
        "error": job.error,
        "result": unseal(job.result) if include_result and job.result else None,
    }
