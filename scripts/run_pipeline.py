"""Batch-run the full agent pipeline over Azure Document Intelligence JSON results.

Each extracted document is inserted as a Claim row and driven through Claim Intake -> Document ->
Coverage -> Fraud -> Settlement -> Communication using real LLM calls.

Usage:
    python -m scripts.run_pipeline [--input data/extracted] [--limit N]
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.orchestrator import run_pipeline
from app.db import SessionLocal
from app.models import Claim
from app.security import new_claim_number


@dataclass(frozen=True)
class ExtractedDocument:
    source_file: str
    relative_path: str
    text: str


def load_extracted_documents(input_path: Path, limit: int | None = None) -> list[ExtractedDocument]:
    if limit is not None and limit < 1:
        raise ValueError("--limit must be a positive integer")
    if input_path.is_file():
        if input_path.suffix.lower() != ".json":
            raise ValueError(f"Expected an Azure extraction .json file: {input_path}")
        files = [input_path]
        base_directory = input_path.parent
    elif input_path.is_dir():
        files = sorted(path for path in input_path.rglob("*.json") if path.is_file())
        base_directory = input_path
    else:
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    if not files:
        raise FileNotFoundError(
            f"No Azure Document Intelligence JSON files found in {input_path}. "
            "Extract the PDFs first with scripts.extract_documents."
        )

    documents: list[ExtractedDocument] = []
    for path in files[:limit]:
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read extraction result {path}: {exc}") from exc

        service_result = payload.get("content") if isinstance(payload, dict) else None
        text = service_result.get("content") if isinstance(service_result, dict) else None
        source_file = payload.get("source_file") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Extraction result has no text at content.content: {path}")
        if not isinstance(source_file, str) or not source_file.strip():
            raise ValueError(f"Extraction result has no source_file: {path}")

        documents.append(
            ExtractedDocument(
                source_file=Path(source_file.replace("\\", "/")).name,
                relative_path=path.relative_to(base_directory).as_posix(),
                text=text,
            )
        )
    return documents


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/extracted"),
        help="Azure Document Intelligence JSON file or directory (default: data/extracted)",
    )
    args = parser.parse_args()

    input_path = args.input
    if not input_path.is_absolute():
        input_path = Path(__file__).resolve().parents[1] / input_path
    try:
        documents = load_extracted_documents(input_path, args.limit)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Running pipeline for {len(documents)} extracted documents against live LLM...")

    stats = {
        "total": 0,
        "by_status": {},
        "by_claim_type": {},
        "by_decision": {},
        "straight_through": 0,
        "exceptions": 0,
        "classification_confidences": [],
        "extraction_confidences": [],
        "fraud_scores": [],
    }

    started = time.time()
    for i, document in enumerate(documents, 1):
        db = SessionLocal()
        try:
            claim = Claim(
                claim_number=new_claim_number(),
                channel="document",
                source=f"azure-document-intelligence:{document.relative_path}",
                raw_subject=document.source_file,
                raw_body=document.text,
                attachments_text="",
            )
            db.add(claim)
            db.commit()
            db.refresh(claim)

            claim = run_pipeline(db, claim)

            stats["total"] += 1
            stats["by_status"][claim.status] = stats["by_status"].get(claim.status, 0) + 1
            stats["by_claim_type"][claim.claim_type] = stats["by_claim_type"].get(claim.claim_type, 0) + 1
            stats["by_decision"][claim.recommended_decision] = stats["by_decision"].get(claim.recommended_decision, 0) + 1
            if claim.straight_through:
                stats["straight_through"] += 1
            if claim.status == "exception":
                stats["exceptions"] += 1
            stats["classification_confidences"].append(claim.classification_confidence)
            stats["extraction_confidences"].append(claim.extraction_confidence)
            stats["fraud_scores"].append(claim.fraud_score)

            print(
                f"[{i}/{len(documents)}] {claim.claim_number} type={claim.claim_type} "
                f"decision={claim.recommended_decision} status={claim.status} stp={claim.straight_through}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(documents)}] FAILED: {exc}")
            db.rollback()
        finally:
            db.close()

    elapsed = time.time() - started

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    print("\n=== Batch Summary ===")
    print(f"Total claims run: {stats['total']}")
    print(f"Elapsed: {elapsed:.1f}s ({elapsed / max(1, stats['total']):.2f}s/claim)")
    print(f"By status: {stats['by_status']}")
    print(f"By claim_type: {stats['by_claim_type']}")
    print(f"By decision: {stats['by_decision']}")
    print(f"Straight-through: {stats['straight_through']} ({100 * stats['straight_through'] / max(1, stats['total']):.1f}%)")
    print(f"Exceptions: {stats['exceptions']} ({100 * stats['exceptions'] / max(1, stats['total']):.1f}%)")
    print(f"Avg classification confidence: {avg(stats['classification_confidences']):.3f}")
    print(f"Avg extraction confidence: {avg(stats['extraction_confidences']):.3f}")
    print(f"Avg fraud score: {avg(stats['fraud_scores']):.3f}")


if __name__ == "__main__":
    main()
