"""Opt-in browser smoke test with disposable users/database and fake providers.

Run from repo root using a Python with Playwright installed. Requires .venv and a
same-origin frontend export, so build it with NEXT_PUBLIC_API_URL empty:
`cd frontend && NEXT_PUBLIC_API_URL= npx next build`. A build that kept the
development localhost:8000 value fails every request here with a CORS error.
Uses system Chrome; no provider credits are spent.
"""

import asyncio
import base64
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def serve():
    sys.path.insert(0, str(ROOT / "backend"))
    import uvicorn
    from app.core.database import initialize, session
    from app.core.security import password_hash
    from app.models.persistence import User
    from app.main import app
    from app.models.schemas.verification import Candidate, VerificationResult
    from app.services.openrouter_service import OpenRouterService
    from app.services.verifalia_service import VerifaliaService
    from app.worker import run_once
    from contextlib import asynccontextmanager

    initialize()
    with session() as db, db.begin():
        db.add(
            User(
                email="admin@example.org",
                password=password_hash("demo-password-only"),
                admin=True,
            )
        )

    async def lookup(self, names, model, context):
        return {
            row_id: [
                Candidate(email="demo@institution.example"),
                Candidate(email="demo@second.example"),
            ]
            for row_id, _ in names
        }

    async def verify(self, emails, quality):
        return {
            email: VerificationResult(
                email=email,
                result="Exists",
                classification="Deliverable",
                status="Success",
            )
            for email in emails
        }

    OpenRouterService.find_candidates = lookup
    VerifaliaService.verify_many = verify
    original = app.router.lifespan_context

    async def work():
        while True:
            await run_once()
            await asyncio.sleep(0.2)

    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            worker = asyncio.create_task(work())
            try:
                yield
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="127.0.0.1", port=8769, log_level="error")


def smoke():
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(prefix="email-checker-browser-") as directory:
        environment = os.environ | {
            "DATABASE_URL": "sqlite:///" + directory + "/browser.db",
            "ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
            "PUBLIC_URL": "http://127.0.0.1:8769",
            "ALLOWED_ORIGINS": "http://127.0.0.1:8769",
            "STATIC_DIR": str(ROOT / "frontend/out"),
            "SECURE_COOKIES": "false",
            "PRODUCTION": "false",
        }
        server = subprocess.Popen(
            [str(ROOT / ".venv/bin/python"), __file__, "--serve"], env=environment
        )
        try:
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", 8769), timeout=0.2):
                        break
                except OSError:
                    if server.poll() is not None:
                        raise RuntimeError("Smoke server failed")
                    time.sleep(0.1)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    headless=True,
                )
                admin = browser.new_context()
                page = admin.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto("http://127.0.0.1:8769")
                page.get_by_label("Email", exact=True).fill("admin@example.org")
                page.get_by_label("Password", exact=True).fill("demo-password-only")
                page.get_by_role("button", name="Sign in", exact=True).click()
                page.get_by_role("button", name="People", exact=True).click()
                page.get_by_label("Email", exact=True).fill("invited@example.org")
                page.get_by_role("button", name="Create invitation", exact=True).click()
                link = page.locator("input[readonly]")
                link.wait_for()
                invitation = link.input_value()

                person = browser.new_context(viewport={"width": 390, "height": 844})
                member = person.new_page()
                member.on("pageerror", lambda error: errors.append(str(error)))
                member.goto(invitation)
                member.get_by_label("Password", exact=True).fill(
                    "another-demo-password"
                )
                member.get_by_role("button", name="Save and sign in").click()
                member.get_by_role("button", name="Settings", exact=True).click()
                member.get_by_label("API key", exact=True).fill("synthetic-key")
                member.get_by_label("Username", exact=True).fill("synthetic-user")
                member.get_by_label("Password", exact=True).fill("synthetic-password")
                member.get_by_role("button", name="Save credentials").click()
                member.locator('input[placeholder="set"]').first.wait_for()
                member.get_by_role("button", name="Close", exact=True).click()
                member.get_by_label("Person or email to verify").fill("Demo Person")
                member.get_by_role("button", name="Run check", exact=True).click()
                member.get_by_text("2 addresses checked", exact=True).wait_for()
                member.reload()
                member.get_by_role("button", name="Jobs", exact=True).click()
                member.get_by_role("button", name="View", exact=True).click()
                member.get_by_text("demo@institution.example", exact=True).wait_for()
                member.get_by_role("button", name="Close", exact=True).click()
                member.get_by_role("tab", name="Advanced", exact=True).click()
                member.locator('input[type="file"]').set_input_files(
                    str(ROOT / "samples/ceps-email-demo.xlsx")
                )
                member.get_by_role("checkbox").check(force=True)
                member.get_by_role("button", name="Run batch verification").click()
                member.get_by_role("link", name="Download Excel").wait_for()
                with member.expect_download() as downloaded:
                    member.get_by_role("link", name="Download Excel").click()
                assert downloaded.value.suggested_filename.endswith("-verified.xlsx")
                assert member.locator("body").evaluate(
                    "e => e.scrollWidth <= window.innerWidth"
                )
                member.screenshot(
                    path="/private/tmp/email-checker-account-mobile.png", full_page=True
                )
                assert not errors, errors
                browser.close()
                print(
                    "Browser smoke passed: invite, login, private credentials, multi-email check, reload recovery, batch download, mobile layout."
                )
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else smoke()
