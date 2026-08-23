"""Unit tests for JSONSplitter massive array partitioning and validation."""

import json
from pathlib import Path

from spansh.split_json import JSONSplitter


def test_validate_chunk_valid_ndjson_returns_true(tmp_path: Path) -> None:
    """Validates that a clean .ndjson chunk file with valid JSON records passes validation."""
    chunk_file = tmp_path / "valid_part_001.ndjson"
    lines = [
        json.dumps({"name": "Sol", "id64": 10477373803}),
        json.dumps({"name": "Alpha Centauri", "id64": 2833906537146}),
    ]
    chunk_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert JSONSplitter.validate_ndjson_chunk(str(chunk_file)) is True


def test_validate_chunk_corrupt_json_returns_false(tmp_path: Path) -> None:
    """Validates that a corrupted .ndjson chunk file returns False without raising unhandled exceptions."""
    chunk_file = tmp_path / "corrupt_part_001.ndjson"
    content = '{"name": "Sol", "id64": 10477373803}\n{"name": "Malformed JSON without closing bracket\n'
    chunk_file.write_text(content, encoding="utf-8")

    assert JSONSplitter.validate_ndjson_chunk(str(chunk_file)) is False


def test_validate_chunk_empty_lines_ignored(tmp_path: Path) -> None:
    """Validates that blank lines and empty whitespace are safely skipped during validation."""
    chunk_file = tmp_path / "blank_lines_part_001.ndjson"
    content = '\n\n{"name": "Sol"}\n   \n{"name": "Colonia"}\n\n'
    chunk_file.write_text(content, encoding="utf-8")

    assert JSONSplitter.validate_ndjson_chunk(str(chunk_file)) is True


def test_split_monolithic_json_partitions_by_chunk_count(tmp_path: Path) -> None:
    """Validates that JSONSplitter correctly partitions a JSON array file into multiple chunks."""
    input_file = tmp_path / "test_galaxy.json"
    output_dir = tmp_path / "output_parts"

    records = [{"id": i, "name": f"System_{i}"} for i in range(10)]
    formatted_array = "[\n" + ",\n".join(json.dumps(r) for r in records) + "\n]\n"
    input_file.write_text(formatted_array, encoding="utf-8")

    splitter = JSONSplitter(
        input_file=str(input_file),
        output_dir=str(output_dir),
        num_chunks=2,
        validate=True,
        threads=1,
    )
    chunks_written = splitter.split()

    assert chunks_written >= 1
    created_files = list(output_dir.glob("*.ndjson"))
    assert len(created_files) >= 1

    total_parsed = 0
    for f in created_files:
        for line in f.read_text(encoding="utf-8").strip().split("\n"):
            if line:
                data = json.loads(line)
                assert "id" in data
                total_parsed += 1
    assert total_parsed == 10


def test_split_monolithic_json_partitions_by_record_limit(tmp_path: Path) -> None:
    """Validates splitting with max_records_per_chunk limits."""
    input_file = tmp_path / "test_galaxy_records.json"
    output_dir = tmp_path / "output_parts_records"

    records = [{"id": i, "name": f"Record_{i}"} for i in range(6)]
    formatted_array = "[\n" + ",\n".join(json.dumps(r) for r in records) + "\n]\n"
    input_file.write_text(formatted_array, encoding="utf-8")

    splitter = JSONSplitter(
        input_file=str(input_file),
        output_dir=str(output_dir),
        max_records_per_chunk=2,
        validate=True,
        threads=1,
    )
    chunks_written = splitter.split()

    assert chunks_written >= 3
    created_files = sorted(output_dir.glob("*.ndjson"))
    assert len(created_files) >= 3


def test_validate_all_chunks_detects_missing_and_existing(tmp_path: Path) -> None:
    """Validates validate_all_chunks identifies missing files and evaluates existing chunks."""
    output_dir = tmp_path / "validation_dir"
    output_dir.mkdir(parents=True, exist_ok=True)

    splitter = JSONSplitter(
        output_dir=str(output_dir),
        num_chunks=2,
        threads=1,
    )

    assert splitter.validate_all_chunks() is False

    chunk1 = output_dir / f"{splitter.file_prefix}_001.ndjson"
    chunk1.write_text('{"test": 1}\n', encoding="utf-8")
    assert splitter.validate_all_chunks() is False

    chunk2 = output_dir / f"{splitter.file_prefix}_002.ndjson"
    chunk2.write_text('{"test": 2}\n', encoding="utf-8")
    assert splitter.validate_all_chunks() is True
