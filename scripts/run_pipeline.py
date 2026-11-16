"""Batch-run the full agent pipeline over the generated claims (data/generated/claims.jsonl),
inserting each as a Claim row and driving it through Claim Intake -> Document -> Coverage ->
Fraud -> Settlement -> Communication using real LLM calls.

Usage:
    python scripts/run_pipeline.py [--limit N]
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.orchestrator import run_pipeline
from app.db import SessionLocal
from app.models import Claim
from app.security import new_claim_number


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--input", type=str, default="data/generated/claims.jsonl")
    args = parser.parse_args()

    path = Path(__file__).resolve().parents[1] / args.input
    lines = path.read_text().splitlines()
    if args.limit:
        lines = lines[: args.limit]

    print(f"Running pipeline for {len(lines)} claims against live LLM...")

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
    for i, line in enumerate(lines, 1):
        raw = json.loads(line)
        db = SessionLocal()
        try:
            claim = Claim(
                claim_number=new_claim_number(),
                channel=raw["channel"],
                source=raw["source"],
                raw_subject=raw["raw_subject"],
                raw_body=raw["raw_body"],
                attachments_text=raw.get("attachments_text", ""),
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
                f"[{i}/{len(lines)}] {claim.claim_number} type={claim.claim_type} "
                f"decision={claim.recommended_decision} status={claim.status} stp={claim.straight_through}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(lines)}] FAILED: {exc}")
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
