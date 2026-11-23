import io
import math
import re
from collections import Counter
from collections.abc import Callable
from copy import copy
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zipfile import ZipFile, BadZipFile

import pandas as pd

from app.core.config import Settings
from app.exceptions.handlers import ServiceError
from app.models.schemas.verification import (
    BatchResponse,
    BatchSummary,
    Candidate,
    ModelId,
    Quality,
    VerificationResult,
)
from app.repositories.batch_repository import BatchRepository
from app.services.evidence_service import REJECTED, EvidenceService
from app.services.openrouter_service import OpenRouterService
from app.services.verifalia_service import VerifaliaService


EMAIL_SEPARATOR = re.compile(r"[,;\n]+")
RESULT_COLUMNS = [
    "result",
    "verifalia_classification",
    "verifalia_status",
    "normalized_email",
    "is_disposable",
    "is_role_account",
    "is_free_address",
    "suggestions",
    "candidate_confidence",
    "candidate_source_url",
    "candidate_rationale",
    "verdict",
    "verdict_reason",
]

NOT_PROCESSED_LABEL = "Not processed"
NOT_PROCESSED = object()
RETRY_RESULTS = {"", "No email found", NOT_PROCESSED_LABEL}


@dataclass
class _Table:
    frame: pd.DataFrame
    email_column: object | None
    previous: dict[str, object]
    done: set[int]
    names: list[tuple[str, str]]
    direct_emails: list[str]


class BatchService:
    def __init__(
        self,
        settings: Settings,
        repository: BatchRepository,
        openrouter: OpenRouterService,
        verifalia: VerifaliaService,
        evidence: EvidenceService | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._openrouter = openrouter
        self._verifalia = verifalia
        self._evidence = evidence

    async def process(
        self,
        content: bytes,
        filename: str,
        model: ModelId,
        quality: Quality,
        generate_missing: bool,
        context: str,
        on_progress: Callable[[dict[str, object]], None] | None = None,
    ) -> BatchResponse:
        table = self._prepare(content, filename, generate_missing)
        candidate_map: dict[str, list[Candidate]] = {}
        verified: dict[str, VerificationResult] = {}

        def report() -> None:
            if on_progress is not None:
                on_progress(self._checkpoint(candidate_map, verified))

        async def verify(emails: list[str]) -> None:
            pending = list(
                dict.fromkeys(email for email in emails if email not in verified)
            )
            size = self._settings.verifalia_chunk_size
            for offset in range(0, len(pending), size):
                verified.update(
                    await self._verifalia.verify_many(
                        pending[offset : offset + size], quality
                    )
                )
                report()

        await verify(table.direct_emails)
        names = dict(table.names)
        size = self._settings.lookup_chunk_size_for(model.value)
        for offset in range(0, len(table.names), size):
            found = await self._openrouter.find_candidates(
                table.names[offset : offset + size], model, context
            )
            if self._evidence is not None:
                rows = list(found)
                assessed = await self._evidence.assess_many(
                    context, [(names.get(row, ""), found[row]) for row in rows]
                )
                found = dict(zip(rows, assessed))
            candidate_map.update(found)
            report()
            await verify(
                [
                    candidate.email
                    for items in found.values()
                    for candidate in items
                    if candidate.verdict != REJECTED
                ]
            )

        response, _ = self._build(table, filename, candidate_map, verified)
        return response

    def partial(
        self,
        content: bytes,
        filename: str,
        generate_missing: bool,
        checkpoint: dict[str, object],
    ) -> tuple[BatchResponse, list[int]]:
        table = self._prepare(content, filename, generate_missing)
        candidates = checkpoint.get("candidates") or {}
        results = checkpoint.get("verified") or {}
        candidate_map = {
            str(position): [Candidate(**item) for item in items]
            for position, items in candidates.items()
        }
        verified = {
            str(email): VerificationResult(**item) for email, item in results.items()
        }
        return self._build(table, filename, candidate_map, verified)

    @staticmethod
    def has_progress(checkpoint: dict[str, object] | None) -> bool:
        return bool(
            checkpoint and (checkpoint.get("candidates") or checkpoint.get("verified"))
        )

    @staticmethod
    def describe_rows(rows: list[int], limit: int = 20) -> str:
        ranges: list[str] = []
        for row in rows:
            if ranges and ranges[-1].split("-")[-1] == str(row - 1):
                ranges[-1] = ranges[-1].split("-")[0] + f"-{row}"
            else:
                ranges.append(str(row))
        text = ", ".join(ranges[:limit])
        if len(ranges) > limit:
            text += f" and {len(ranges) - limit} more ranges"
        return text

    @staticmethod
    def _checkpoint(
        candidate_map: dict[str, list[Candidate]],
        verified: dict[str, VerificationResult],
    ) -> dict[str, object]:
        return {
            "candidates": {
                position: [item.model_dump(mode="json") for item in items]
                for position, items in candidate_map.items()
            },
            "verified": {
                email: result.model_dump(mode="json")
                for email, result in verified.items()
            },
        }

    def _prepare(self, content: bytes, filename: str, generate_missing: bool) -> _Table:
        frame = self._read_file(content, filename)
        previous: dict[str, object] = {}
        # Preserve input result columns when a user checks a previously exported workbook.
        for column in list(frame.columns):
            key = str(column).strip().lower()
            if key in RESULT_COLUMNS:
                replacement = f"input_{column}"
                while replacement in frame.columns:
                    replacement = "input_" + replacement
                frame = frame.rename(columns={column: replacement})
                previous[key] = replacement
        if len(frame) > self._settings.max_batch_rows:
            raise ServiceError(
                f"Files can contain up to {self._settings.max_batch_rows:,} rows.",
                status_code=413,
            )

        email_column = self._find_column(frame, "email")
        name_column = self._find_column(frame, "name")
        if email_column is None and not (generate_missing and name_column is not None):
            raise ServiceError(
                'The file needs an "email" column, or a "name" column with email generation enabled.',
                status_code=422,
            )

        done: set[int] = set()
        names: list[tuple[str, str]] = []
        direct_emails: list[str] = []
        for position, (_, row) in enumerate(frame.iterrows()):
            if (
                "result" in previous
                and self._clean_cell(row.get(previous["result"])) not in RETRY_RESULTS
            ):
                done.add(position)
                continue
            emails = (
                self._split_emails(row.get(email_column))
                if email_column is not None
                else []
            )
            direct_emails.extend(emails)
            name = (
                self._clean_cell(row.get(name_column))
                if name_column is not None
                else ""
            )
            if generate_missing and not emails and name:
                names.append((str(position), name))
        return _Table(
            frame,
            email_column,
            previous,
            done,
            names,
            list(dict.fromkeys(direct_emails)),
        )

    def _build(
        self,
        table: _Table,
        filename: str,
        candidate_map: dict[str, list[Candidate]],
        verified: dict[str, VerificationResult],
    ) -> tuple[BatchResponse, list[int]]:
        frame, email_column = table.frame, table.email_column
        output_rows: list[dict[str, object]] = []
        unprocessed: list[int] = []
        generated_count = 0
        lookup_rows = {row_id for row_id, _ in table.names}
        for position, (_, source_row) in enumerate(frame.iterrows()):
            original = {
                column: self._json_value(source_row.get(column))
                for column in frame.columns
            }
            if position in table.done:
                original["email"] = (
                    self._clean_cell(source_row.get(email_column))
                    if email_column is not None
                    else ""
                )
                for column in RESULT_COLUMNS:
                    original[column] = original.get(table.previous.get(column), "")
                output_rows.append(original)
                continue
            raw_emails = (
                self._split_emails(source_row.get(email_column))
                if email_column is not None
                else []
            )
            if raw_emails:
                pairs = [(email, None) for email in raw_emails]
            elif str(position) in candidate_map:
                pairs = [
                    (candidate.email, candidate)
                    for candidate in candidate_map[str(position)]
                ] or [("", None)]
                generated_count += sum(1 for _, candidate in pairs if candidate)
            elif str(position) in lookup_rows:
                pairs = [("", NOT_PROCESSED)]
            else:
                pairs = [("", None)]
            row_missing = False
            for email, candidate in pairs:
                row = original.copy()
                row["email"] = email
                if isinstance(candidate, Candidate) and candidate.verdict == REJECTED:
                    row.update(
                        self._result_columns(
                            VerificationResult(
                                email=email,
                                result="Unverified",
                                classification="Unknown",
                                status="SkippedRejected",
                            ),
                            candidate,
                        )
                    )
                elif candidate is NOT_PROCESSED or (email and email not in verified):
                    row_missing = True
                    row.update(
                        self._not_processed_columns(
                            candidate if isinstance(candidate, Candidate) else None
                        )
                    )
                else:
                    row.update(
                        self._result_columns(
                            verified.get(email) if email else None, candidate
                        )
                    )
                output_rows.append(row)
            if row_missing:
                unprocessed.append(position + 2)

        emails = [
            str(row["email"])
            for row in output_rows
            if row["email"] and str(row["email"]) in verified
        ]
        output_frame = pd.DataFrame(output_rows)
        output_bytes = self._write_excel(output_frame)
        source_stem = Path(filename).stem or "email-check"
        output_filename = f"{source_stem}-verified.xlsx"
        batch_id = self._repository.put(output_filename, output_bytes)
        counts = Counter(str(row["result"]) for row in output_rows)
        response = BatchResponse(
            batch_id=batch_id,
            filename=output_filename,
            preview=output_rows[:50],
            columns=[str(column) for column in output_frame.columns],
            summary=BatchSummary(
                total_rows=len(frame),
                output_rows=len(output_rows),
                emails_checked=len(set(emails)),
                generated_candidates=generated_count,
                counts=dict(counts),
            ),
        )
        return response, unprocessed

    def download(self, batch_id: str) -> tuple[str, bytes]:
        stored = self._repository.get(batch_id)
        if stored is None:
            raise ServiceError(
                "This download has expired or does not exist.", status_code=404
            )
        return stored.filename, stored.content

    @staticmethod
    def _find_column(frame: pd.DataFrame, target: str) -> object | None:
        for column in frame.columns:
            if str(column).strip().lower() == target:
                return column
        return None

    @staticmethod
    def _read_file(content: bytes, filename: str) -> pd.DataFrame:
        if not content:
            raise ServiceError("The uploaded file is empty.", status_code=422)
        extension = Path(filename).suffix.lower()
        if extension == ".xlsx":
            try:
                with ZipFile(io.BytesIO(content)) as archive:
                    if (
                        sum(item.file_size for item in archive.infolist())
                        > 50 * 1024 * 1024
                    ):
                        raise ServiceError(
                            "The expanded workbook exceeds 50 MB.", status_code=413
                        )
            except BadZipFile as exc:
                raise ServiceError("Invalid Excel workbook.", status_code=422) from exc
        try:
            if extension == ".csv":
                frame = pd.read_csv(io.BytesIO(content), dtype=object, nrows=25_001)
            elif extension in {".xlsx", ".xls"}:
                frame = pd.read_excel(io.BytesIO(content), dtype=object, nrows=25_001)
            else:
                raise ServiceError(
                    "Upload an .xlsx, .xls, or .csv file.", status_code=415
                )
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(
                "The spreadsheet could not be read. Check that it is a valid, unprotected file.",
                status_code=422,
            ) from exc
        if len(frame.columns) > 200:
            raise ServiceError(
                "Spreadsheets can contain at most 200 columns.", status_code=413
            )
        if frame.empty:
            raise ServiceError("The spreadsheet has no data rows.", status_code=422)
        return frame

    @staticmethod
    def _split_emails(value: object) -> list[str]:
        cleaned = BatchService._clean_cell(value)
        if not cleaned:
            return []
        return list(
            dict.fromkeys(
                candidate.strip().lower()
                for candidate in EMAIL_SEPARATOR.split(cleaned)
                if candidate.strip()
            )
        )

    @staticmethod
    def _clean_cell(value: object) -> str:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        return str(value).strip()

    @staticmethod
    def _json_value(value: object) -> object:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        if isinstance(value, (pd.Timestamp, date, datetime)):
            return value.isoformat()
        if hasattr(value, "item"):
            try:
                return value.item()
            except (ValueError, AttributeError):
                pass
        return value

    @staticmethod
    def _result_columns(
        result: VerificationResult | None,
        candidate: Candidate | None,
    ) -> dict[str, object]:
        if result is None:
            return {
                "result": "No email found",
                "verifalia_classification": "Unknown",
                "verifalia_status": "CandidateNotFound",
                "normalized_email": "",
                "is_disposable": "",
                "is_role_account": "",
                "is_free_address": "",
                "suggestions": "",
                "candidate_confidence": "",
                "candidate_source_url": "",
                "candidate_rationale": "",
                "verdict": "",
                "verdict_reason": "",
            }
        return {
            "result": result.result,
            "verifalia_classification": result.classification,
            "verifalia_status": result.status,
            "normalized_email": result.normalized_email or "",
            "is_disposable": result.is_disposable
            if result.is_disposable is not None
            else "",
            "is_role_account": result.is_role_account
            if result.is_role_account is not None
            else "",
            "is_free_address": result.is_free_address
            if result.is_free_address is not None
            else "",
            "suggestions": ", ".join(result.suggestions),
            "candidate_confidence": candidate.confidence if candidate else "",
            "candidate_source_url": candidate.source_url or "" if candidate else "",
            "candidate_rationale": candidate.rationale or "" if candidate else "",
            "verdict": candidate.verdict or "" if candidate else "",
            "verdict_reason": candidate.verdict_reason or "" if candidate else "",
        }

    @staticmethod
    def _not_processed_columns(candidate: Candidate | None) -> dict[str, object]:
        columns = BatchService._result_columns(None, candidate)
        columns.update(
            result=NOT_PROCESSED_LABEL,
            verifalia_classification="",
            verifalia_status="NotProcessed",
        )
        if candidate is not None:
            columns.update(
                candidate_confidence=candidate.confidence,
                candidate_source_url=candidate.source_url or "",
                candidate_rationale=candidate.rationale or "",
                verdict=candidate.verdict or "",
                verdict_reason=candidate.verdict_reason or "",
            )
        return columns

    @staticmethod
    def _write_excel(frame: pd.DataFrame) -> bytes:
        buffer = io.BytesIO()
        safe_frame = frame.map(BatchService._safe_excel_value)
        safe_frame.columns = [
            BatchService._safe_excel_value(str(column)) for column in frame.columns
        ]
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            safe_frame.to_excel(writer, sheet_name="Verified", index=False)
            worksheet = writer.book["Verified"]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for cell in worksheet[1]:
                header_font = copy(cell.font)
                header_font.bold = True
                cell.font = header_font
            for column_cells in worksheet.columns:
                width = min(
                    max(len(str(cell.value or "")) for cell in column_cells) + 2,
                    48,
                )
                worksheet.column_dimensions[column_cells[0].column_letter].width = max(
                    width, 12
                )
        return buffer.getvalue()

    @staticmethod
    def _safe_excel_value(value: object) -> object:
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
            return f"'{value}"
        return value
