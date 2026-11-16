"""Extract PDFs in data/raw_documents with Azure Document Intelligence."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from app.document_intelligence import DocumentIntelligenceSettings, extract_directory


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=project_root / "data" / "raw_documents",
        help="Folder containing PDFs (default: data/raw_documents)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "data" / "extracted",
        help="Folder for Markdown and JSON results (default: data/extracted)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-submit documents that already have both output files",
    )
    args = parser.parse_args()

    try:
        settings = DocumentIntelligenceSettings()
    except ValidationError:
        print(
            "Add AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and "
            "AZURE_DOCUMENT_INTELLIGENCE_KEY to .env. "
            "AZURE_DOCUMENT_INTELLIGENCE_MODEL is optional (default: prebuilt-layout).",
            file=sys.stderr,
        )
        return 2

    try:
        extract_directory(args.input_dir, args.output_dir, settings, overwrite=args.overwrite)
    except (FileNotFoundError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
