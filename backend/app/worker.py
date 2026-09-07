"""Durable database queue. Never automatically repeat ambiguous paid requests."""

import asyncio
import logging
import time

from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.database import initialize, session
from app.core.logging import setup_logging
from app.core.security import cipher, seal, unseal, user_settings
from app.models.persistence import Invite, Job, LoginSession, RateBucket
from app.repositories.batch_repository import BatchRepository
from app.services.batch_service import BatchService
from app.services.check_service import CheckService
from app.services.openrouter_service import OpenRouterService
from app.services.verifalia_service import VerifaliaService
from app.models.schemas.verification import ModelId, Quality

logger = logging.getLogger(__name__)


def cleanup():
    now = time.time()
    with session() as db, db.begin():
        db.execute(delete(Job).where(Job.expires < now))
        for model in (Invite, LoginSession, RateBucket):
            db.execute(delete(model).where(model.expires < now))
        db.execute(
            update(Job)
            .where(Job.status == "running", Job.updated < now - 90)
            .values(
                status="interrupted",
                payload=None,
                upload=None,
                error="Worker was interrupted. Provider credits may already have been used. Review before starting a new job.",
            )
        )


def claim():
    with session() as db, db.begin():
        job = db.scalar(
            select(Job)
            .where(Job.status == "queued", Job.expires > time.time())
            .order_by(Job.created)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        # Compare-and-swap also protects SQLite local development.
        claimed = db.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == "queued")
            .values(status="running", updated=time.time())
        )
        return job if claimed.rowcount else None


async def heartbeat(job_id):
    while True:
        await asyncio.sleep(15)
        with session() as db, db.begin():
            db.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(updated=time.time())
            )


async def execute(job):
    values = unseal(job.payload)
    settings = user_settings(job.user_id)
    lookup = OpenRouterService(settings)
    verifier = VerifaliaService(settings)
    model, quality = ModelId(values["model"]), Quality(values["quality"])
    download = None
    if job.kind == "simple":
        result = await CheckService(lookup, verifier).check(
            values["query"], values["context"], model, quality
        )
        result = result.model_dump(mode="json")
    else:
        repository = BatchRepository(3600)
        service = BatchService(settings, repository, lookup, verifier)
        result = await service.process(
            cipher().decrypt(job.upload),
            job.filename,
            model,
            quality,
            values["generate_missing"],
            values["context"],
        )
        _, download = service.download(result.batch_id)
        result.batch_id = job.id
        result = result.model_dump(mode="json")
    # Recheck revocation before publishing private results.
    user_settings(job.user_id)
    with session() as db, db.begin():
        db.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == "running")
            .values(
                status="completed",
                result=seal(result),
                download=cipher().encrypt(download) if download else None,
                upload=None,
                payload=None,
                updated=time.time(),
            )
        )


async def run_once():
    cleanup()
    job = claim()
    if job is None:
        return False
    pulse = asyncio.create_task(heartbeat(job.id))
    try:
        await asyncio.wait_for(execute(job), timeout=get_settings().job_timeout_seconds)
    except Exception as exc:
        # Never store/log raw provider responses or secrets.
        logger.warning("Job %s failed (%s)", job.id, type(exc).__name__)
        message = "The job failed. Check credentials and provider balances before starting another job; credits may have been used."
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            message = "Job exceeded its time limit. Provider credits may have been used; check before retrying."
        with session() as db, db.begin():
            db.execute(
                update(Job)
                .where(Job.id == job.id, Job.status == "running")
                .values(
                    status="failed",
                    error=message,
                    upload=None,
                    payload=None,
                    updated=time.time(),
                )
            )
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
    return True


async def loop():
    """Poll for work forever. Hosted by the web app, or run standalone via main()."""
    while True:
        try:
            worked = await run_once()
            if not worked:
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("Worker database operation failed; retrying in five seconds.")
            await asyncio.sleep(5)


async def main():
    setup_logging()
    cipher()  # Fail at startup if encryption is misconfigured.
    initialize()
    await loop()


if __name__ == "__main__":
    asyncio.run(main())
