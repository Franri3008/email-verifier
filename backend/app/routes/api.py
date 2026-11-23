from pathlib import Path
from urllib.parse import quote
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import session
from app.core.security import authenticate, cipher, user_settings
from app.models.persistence import Job
from app.models.schemas.verification import ModelId, Quality, SimpleCheckRequest
from app.services.job_service import describe, enqueue, owned_job
from app.services.usage_service import provider_usage

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    with session() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/configuration")
def configuration(user=Depends(authenticate)):
    settings = user_settings(user.id)
    return {
        "status": "ok",
        "openrouter_configured": bool(settings.openrouter_api_key),
        "verifalia_configured": settings.has_verifalia_credentials,
    }


@router.get("/usage")
async def usage(user=Depends(authenticate)):
    return await provider_usage(user_settings(user.id))


@router.get("/models")
def models(user=Depends(authenticate)):
    return [
        dict(id=key.value, label=label, note="")
        for key, label in [
            (ModelId.GPT_LUNA, "GPT-6 Luna"),
            (ModelId.GPT_TERRA, "GPT-5.6 Terra"),
            (ModelId.CLAUDE_HAIKU, "Claude Haiku 5.5"),
            (ModelId.CLAUDE_SONNET, "Claude Sonnet 5.5"),
            (ModelId.CLAUDE_OPUS, "Claude Opus 5.5"),
        ]
    ]


@router.post("/check", status_code=202)
def check(body: SimpleCheckRequest, user=Depends(authenticate)):
    return enqueue(user, "simple", body.model_dump(mode="json"))


@router.post("/batch", status_code=202)
async def batch(
    file: UploadFile = File(...),
    model: ModelId = Form(ModelId.GPT_LUNA),
    quality: Quality = Form(Quality.STANDARD),
    generate_missing: bool = Form(False),
    context: str = Form("", max_length=500),
    user=Depends(authenticate),
):
    filename = Path(file.filename or "upload.xlsx").name[:200]
    if Path(filename).suffix.lower() not in {".xls", ".xlsx", ".csv"}:
        raise HTTPException(415, "Upload an .xlsx, .xls, or .csv file.")
    try:
        content = await file.read(get_settings().max_upload_bytes + 1)
    finally:
        await file.close()
    if not content:
        raise HTTPException(422, "The uploaded file is empty.")
    if len(content) > get_settings().max_upload_bytes:
        raise HTTPException(413, "File is too large (maximum 5 MB).")
    return enqueue(
        user,
        "batch",
        dict(
            model=model.value,
            quality=quality.value,
            generate_missing=generate_missing,
            context=context,
        ),
        filename,
        content,
    )


@router.get("/jobs")
def jobs(user=Depends(authenticate)):
    with session() as db:
        return [
            describe(job)
            for job in db.scalars(
                select(Job)
                .where(Job.user_id == user.id, Job.expires > time.time())
                .order_by(Job.created.desc())
                .limit(100)
            )
        ]


@router.get("/jobs/{job_id}")
def job(job_id: str, user=Depends(authenticate)):
    with session() as db:
        return describe(owned_job(db, user.id, job_id), include_result=True)


@router.delete("/jobs/{job_id}")
def remove_job(job_id: str, user=Depends(authenticate)):
    with session() as db, db.begin():
        current = owned_job(db, user.id, job_id)
        if current.status == "running":
            raise HTTPException(409, "Wait for the running job to finish.")
        db.delete(current)
    return {"ok": True}


@router.get("/batch/{job_id}/download")
def download(job_id: str, user=Depends(authenticate)):
    with session() as db:
        current = owned_job(db, user.id, job_id)
        if current.status != "completed" or not current.download:
            raise HTTPException(409, "Download is not ready.")
        content = cipher().decrypt(current.download)
        filename = Path(current.filename).stem + "-verified.xlsx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename),
            "Cache-Control": "no-store",
        },
    )
