import argparse
import asyncio
import csv
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.models.schemas.verification import Candidate, ModelId  # noqa: E402
from app.services.evidence_service import REJECTED, EvidenceService  # noqa: E402
from app.services.openrouter_service import OpenRouterService  # noqa: E402


@dataclass
class Tally:
    correct: int = 0
    wrong: int = 0
    none: int = 0
    errors: int = 0
    wrong_addresses: int = 0
    wrong_rejected: int = 0
    correct_rejected: int = 0
    verdicts: dict[str, int] = field(default_factory=dict)


class DryLookup:
    async def find_candidates(self, names, model, shared_context=""):
        row_id, name = names[0]
        known, source = DRY_ROWS[row_id]
        if int(row_id) % 3 == 2:
            return {row_id: []}
        guess = Candidate(
            email=f"info@{known.split('@', 1)[1]}",
            confidence="low",
            source_url=source,
        )
        if int(row_id) % 3 == 1:
            return {row_id: [guess]}
        right = Candidate(email=known, confidence="high", source_url=source)
        return {row_id: [right, guess]}


class DryEvidence:
    async def assess(self, name, context, candidates):
        return [
            candidate.model_copy(
                update={
                    "verdict": "Rejected"
                    if candidate.email.startswith("info@")
                    else "Confirmed",
                    "verdict_reason": "dry run",
                }
            )
            for candidate in candidates
        ]


DRY_ROWS: dict[str, tuple[str, str]] = {}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]
    return [row for row in rows if row.get("name") and row.get("known_email")]


async def run_model(model, rows, lookup, evidence, use_evidence, verbose, limit):
    tally = Tally()
    semaphore = asyncio.Semaphore(limit)

    async def one(index, row):
        async with semaphore:
            row_id = str(index)
            try:
                found = await lookup.find_candidates(
                    [(row_id, row["name"])], model, row.get("context", "")
                )
                candidates = found.get(row_id, [])
                if use_evidence and candidates:
                    candidates = await evidence.assess(
                        row["name"], row.get("context", ""), candidates
                    )
            except Exception as exc:
                return row, None, type(exc).__name__
            return row, candidates, None

    outcomes = await asyncio.gather(*(one(i, row) for i, row in enumerate(rows)))
    for row, candidates, error in outcomes:
        known = row["known_email"].lower()
        if error:
            tally.errors += 1
            if verbose:
                print(f"  {row['name']}: error {error}")
            continue
        emails = [candidate.email for candidate in candidates]
        if not candidates:
            tally.none += 1
        elif known in emails:
            tally.correct += 1
        else:
            tally.wrong += 1
        for candidate in candidates:
            verdict = candidate.verdict or "none"
            tally.verdicts[verdict] = tally.verdicts.get(verdict, 0) + 1
            if candidate.email == known:
                tally.correct_rejected += verdict == REJECTED
            else:
                tally.wrong_addresses += 1
                tally.wrong_rejected += verdict == REJECTED
        if verbose:
            shown = ", ".join(
                f"{candidate.email} [{candidate.verdict or '-'}: "
                f"{candidate.verdict_reason or '-'}]"
                for candidate in candidates
            )
            print(f"  {row['name']} (known {known}): {shown or 'none'}")
    return tally


def report(model, tally, total, use_evidence):
    print(f"{model}")
    print(f"  people: {total}")
    print(f"  found correct: {tally.correct}")
    print(f"  found wrong: {tally.wrong}")
    print(f"  none: {tally.none}")
    if tally.errors:
        print(f"  errors: {tally.errors}")
    if use_evidence:
        print(
            f"  wrong addresses marked Rejected: {tally.wrong_rejected} "
            f"of {tally.wrong_addresses}"
        )
        print(f"  correct addresses marked Rejected: {tally.correct_rejected}")
        verdicts = ", ".join(f"{k} {v}" for k, v in sorted(tally.verdicts.items()))
        print(f"  verdicts: {verdicts or 'none'}")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure email discovery and the evidence step without Verifalia."
    )
    parser.add_argument(
        "csv", nargs="?", type=Path, default=ROOT / "samples" / "eval_people.csv"
    )
    parser.add_argument(
        "--model",
        action="append",
        choices=[model.value for model in ModelId],
        help="Repeat to compare models. Defaults to every model.",
    )
    parser.add_argument("--no-evidence", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    rows = read_rows(args.csv)
    if not rows:
        print(f"No usable rows in {args.csv}.")
        return 1
    models = [ModelId(value) for value in (args.model or [m.value for m in ModelId])]
    use_evidence = not args.no_evidence

    if args.dry_run:
        DRY_ROWS.update(
            {
                str(i): (row["known_email"].lower(), row.get("source", ""))
                for i, row in enumerate(rows)
            }
        )
        lookup, evidence = DryLookup(), DryEvidence()
        print("Dry run: no network calls.")
    else:
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            print("Set OPENROUTER_API_KEY to run the evaluation.")
            return 1
        settings = Settings(_env_file=None, openrouter_api_key=key)
        lookup, evidence = OpenRouterService(settings), EvidenceService(settings)

    for model in models:
        tally = await run_model(
            model,
            rows,
            lookup,
            evidence,
            use_evidence,
            args.verbose,
            max(1, args.concurrency),
        )
        report(model.value, tally, len(rows), use_evidence)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
