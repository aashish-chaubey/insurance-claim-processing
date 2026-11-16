"""Batch extraction of PDF documents through Azure Document Intelligence."""

import json
import mimetypes
from pathlib import Path
from typing import Any

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DocumentIntelligenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_document_intelligence_endpoint: str | None = None
    azure_document_intelligence_key: str | None = None
    azure_document_intelligence_model: str = "prebuilt-layout"

    @model_validator(mode="after")
    def validate_credentials(self) -> "DocumentIntelligenceSettings":
        missing = [
            name
            for name, value in (
                ("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", self.azure_document_intelligence_endpoint),
                ("AZURE_DOCUMENT_INTELLIGENCE_KEY", self.azure_document_intelligence_key),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "Set the following Azure Document Intelligence settings in .env: "
                + ", ".join(missing)
            )
        return self


def create_document_intelligence_client(
    settings: DocumentIntelligenceSettings,
) -> DocumentIntelligenceClient:
    """Create a DocumentIntelligenceClient using the provided settings."""
    if not settings.azure_document_intelligence_endpoint or not settings.azure_document_intelligence_key:
        raise ValueError("Azure Document Intelligence endpoint and key are required")
    return DocumentIntelligenceClient(
        endpoint=settings.azure_document_intelligence_endpoint,
        credential=AzureKeyCredential(settings.azure_document_intelligence_key),
    )


def extract_pdf(
    client: DocumentIntelligenceClient,
    source: Path,
    source_directory: Path,
    output_directory: Path,
    *,
    model_id: str,
) -> tuple[Path, Path]:
    """Extract a single PDF document and save its content as Markdown and JSON files."""
    relative_source = source.relative_to(source_directory)
    markdown_path = output_directory / relative_source.with_suffix(".md")
    json_path = output_directory / relative_source.with_suffix(".json")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)

    content_type = mimetypes.guess_type(source.name)[0] or "application/pdf"
    with source.open("rb") as document:
        # Submit the document to Azure Document Intelligence for analysis
        poller = client.begin_analyze_document(
            model_id=model_id,
            body=document,
            content_type=content_type,
            output_content_format="markdown",
        )
    result = poller.result()

    markdown_path.write_text(result.content or "", encoding="utf-8")
    payload: dict[str, Any] = {
        "source_file": source.name,
        "model_id": model_id,
        "content": result.as_dict(),
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return markdown_path, json_path


def extract_directory(
    input_directory: Path,
    output_directory: Path,
    settings: DocumentIntelligenceSettings,
    *,
    overwrite: bool = False,
) -> tuple[int, int]:
    """Extract PDF documents from a directory and save their content as Markdown and JSON files."""
    if not input_directory.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_directory}")

    # Recursively find all PDF files in the input directory
    documents = sorted(
        path for path in input_directory.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"
    )
    if not documents:
        raise FileNotFoundError(f"No PDF documents found in {input_directory}")

    # Create document intelligence client
    client = create_document_intelligence_client(settings)
    
    extracted_count = 0
    skipped_count = 0
    failures: list[str] = []

    try:
        for source in documents:
            # Determine the relative path of the source file and the corresponding output paths
            relative_source = source.relative_to(input_directory)
            markdown_path = output_directory / relative_source.with_suffix(".md")
            json_path = output_directory / relative_source.with_suffix(".json")

            # If both output files already exist and overwrite is False, skip this document
            if not overwrite and markdown_path.is_file() and json_path.is_file():
                print(f"SKIP {relative_source} (already extracted)")
                skipped_count += 1
                continue

            try:
                # Extract the PDF document and save the results
                extract_pdf(
                    client,
                    source,
                    input_directory,
                    output_directory,
                    model_id=settings.azure_document_intelligence_model,
                )
                print(f"OK   {relative_source}")
                extracted_count += 1
            except Exception as exc:
                print(f"FAIL {relative_source}: {type(exc).__name__}: {exc}")
                failures.append(relative_source.as_posix())
    finally:
        client.close()

    print(
        f"Extraction complete: {extracted_count} extracted, {skipped_count} skipped, "
        f"{len(failures)} failed."
    )
    if failures:
        raise RuntimeError("Some documents failed: " + ", ".join(failures))
    return extracted_count, skipped_count
