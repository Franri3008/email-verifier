import io
import math
import re
from collections import Counter
from copy import copy
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
]


class BatchService:
    def __init__(
        self,
        settings: Settings,
        repository: BatchRepository,
        openrouter: OpenRouterService,
        verifalia: VerifaliaService,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._openrouter = openrouter
        self._verifalia = verifalia

    async def process(
        self,
        content: bytes,
        filename: str,
        model: ModelId,
        quality: Quality,
        generate_missing: bool,
        context: str,
    ) -> BatchResponse:
        frame = self._read_file(content, filename)
        # Preserve input result columns when a user checks a previously exported workbook.
        for column in list(frame.columns):
            if str(column).strip().lower() in RESULT_COLUMNS:
                replacement = f"input_{column}"
                while replacement in frame.columns:
                    replacement = "input_" + replacement
                frame = frame.rename(columns={column: replacement})
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

        candidate_map: dict[str, list[Candidate]] = {}
        names_to_find: list[tuple[str, str]] = []
        if generate_missing and name_column is not None:
            for position, (_, row) in enumerate(frame.iterrows()):
                has_email = bool(
                    email_column is not None and self._clean_cell(row.get(email_column))
                )
                name = self._clean_cell(row.get(name_column))
                if not has_email and name:
                    names_to_find.append((str(position), name))

        for offset in range(0, len(names_to_find), 25):
            chunk = names_to_find[offset : offset + 25]
            candidate_map.update(
                await self._openrouter.find_candidates(chunk, model, context)
            )

        expanded: list[tuple[dict[str, object], str, Candidate | None]] = []
        generated_count = 0
        for position, (_, source_row) in enumerate(frame.iterrows()):
            original = {
                column: self._json_value(source_row.get(column))
                for column in frame.columns
            }
            raw_emails = (
                self._split_emails(source_row.get(email_column))
                if email_column is not None
                else []
            )
            if raw_emails:
                for email in raw_emails:
                    expanded.append((original.copy(), email, None))
                continue
            candidates = candidate_map.get(str(position), [])
            if candidates:
                for candidate in candidates:
                    generated_count += 1
                    expanded.append((original.copy(), candidate.email, candidate))
            else:
                expanded.append((original.copy(), "", None))

        emails = [email for _, email, _ in expanded if email]
        verified = await self._verifalia.verify_many(emails, quality)
        output_rows: list[dict[str, object]] = []
        for original, email, candidate in expanded:
            original["email"] = email
            result = verified.get(email) if email else None
            original.update(self._result_columns(result, candidate))
            output_rows.append(original)

        output_frame = pd.DataFrame(output_rows)
        output_bytes = self._write_excel(output_frame)
        source_stem = Path(filename).stem or "email-check"
        output_filename = f"{source_stem}-verified.xlsx"
        batch_id = self._repository.put(output_filename, output_bytes)
        counts = Counter(str(row["result"]) for row in output_rows)
        return BatchResponse(
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
        }

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
