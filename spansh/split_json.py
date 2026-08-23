"""Massive JSON array splitting into parallel NDJSON chunk files.

Splits monolithic Spansh galaxy JSON dumps (hundreds of GB) into clean,
validated .ndjson files suitable for parallel DuckDB ingestion. Supports
multi-process worker parallelism, configurable chunk sizing (by count,
by GB, or by record limit), and inline JSON-per-line validation.
"""

import datetime
import json
import logging
import multiprocessing
import sys
import time
from pathlib import Path


logger = logging.getLogger(__name__)


class JSONSplitter:
    """Splits massive JSON array dumps directly into clean .ndjson files with parallel validation.

    Invoked by the ``galaxy_sync split`` command to partition monolithic Spansh galaxy
    data dumps into balanced chunk files for downstream DuckDB ingestion.
    """

    def __init__(
        self,
        input_file: str | None = None,
        output_dir: str = r"D:\galaxy_parts",
        num_chunks: int = 100,
        chunk_size_gb: float | None = None,
        max_records_per_chunk: int | None = None,
        start_chunk: int = 1,
        max_chunks: int | None = None,
        validate: bool = True,
        threads: int = 1,
    ) -> None:
        """Initializes the JSONSplitter instance.

        Args:
            input_file: Path to the input JSON file.
            output_dir: Target directory for .ndjson chunk output files.
            num_chunks: Target number of chunks to split input file into (default: 100).
            chunk_size_gb: Target size in GB per chunk file (overrides num_chunks).
            max_records_per_chunk: Maximum record count per chunk file.
            start_chunk: Starting chunk index to resume splitting (default: 1).
            max_chunks: Maximum number of chunks to create during execution.
            validate: Whether to run JSON line validation on output chunks (default: True).
            threads: Number of parallel worker processes to spawn (default: 1).
        """
        self.input_file = input_file
        self.output_dir = output_dir
        self.num_chunks = num_chunks
        self.chunk_size_gb = chunk_size_gb
        self.max_records_per_chunk = max_records_per_chunk
        self.start_chunk = start_chunk
        self.max_chunks = max_chunks
        self.validate = validate
        self.threads = threads
        self.file_prefix = f"galaxy_split_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}_part"
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def validate_ndjson_chunk(file_path: str) -> bool:
        """Scans an .ndjson chunk file line-by-line using orjson/json decoding.

        Args:
            file_path: Path to the .ndjson file to validate.

        Returns:
            bool: True if all lines are valid JSON, False if malformed JSON is detected.
        """
        total_lines = 0
        file_path_obj = Path(file_path)
        with file_path_obj.open(encoding="utf-8", errors="replace") as file_handle:
            for line_number, line in enumerate(file_handle, 1):
                total_lines += 1
                stripped_line = line.strip()
                if not stripped_line:
                    continue
                try:
                    json.loads(stripped_line)
                except Exception as error:
                    file_name = file_path_obj.name
                    logger.info("\n==================================================")
                    logger.info(f"❌ ANOMALY DETECTED IN {file_name} AT LINE {line_number:,}!")
                    logger.info(f"   Error  : {error}")
                    logger.info(f"   Snippet: {stripped_line[:150]}")
                    logger.info("==================================================")
                    return False

        file_name = file_path_obj.name
        logger.info(f"   ✅ [Validation Passed] {file_name}: 100% clean ({total_lines:,} records)")
        return True

    def validate_all_chunks(self) -> bool:
        """Runs multi-threaded parallel line-by-line JSON validation across all expected .ndjson chunks.

        Scans the output directory for all expected chunk files, validates each
        line using ``json.loads()``, and reports per-file pass/fail status.

        Returns:
            bool: True if all expected chunks exist and pass validation, False otherwise.
        """
        output_dir_path = Path(self.output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        missing_files = []
        expected_file_paths = []
        for chunk_index in range(1, self.num_chunks + 1):
            chunk_file_path = str(output_dir_path / f"{self.file_prefix}_{chunk_index:03d}.ndjson")
            expected_file_paths.append(chunk_file_path)
            if not Path(chunk_file_path).exists():
                missing_files.append(f"part_{chunk_index:03d}.ndjson")

        existing_files = [chunk_file_path for chunk_file_path in expected_file_paths if Path(chunk_file_path).exists()]

        logger.info("==================================================")
        logger.info("   PARALLEL NDJSON CHUNK VALIDATION SCANNER")
        logger.info(f"Directory           : {self.output_dir}")
        logger.info(f"Expected Chunks     : {self.num_chunks} files (part_001 to part_{self.num_chunks:03d})")
        logger.info(f"Found Chunk Files   : {len(existing_files)} / {self.num_chunks}")
        logger.info(f"Parallel Workers    : {self.threads} Workers")
        logger.info("==================================================")

        if missing_files:
            logger.info(f"\n⚠️ MISSING CHUNK FILES ({len(missing_files)} missing):")
            for missing_file_name in missing_files[:10]:
                logger.info(f"   ❌ {missing_file_name}")
            if len(missing_files) > 10:
                logger.info(f"   ... and {len(missing_files) - 10} more missing files.")
            logger.info("")

        if not existing_files:
            logger.info(f"Error: No .ndjson chunk files found in '{self.output_dir}'.")
            return False

        start_time = time.time()
        if self.threads <= 1:
            results = [JSONSplitter.validate_ndjson_chunk(file_path) for file_path in existing_files]
        else:
            with multiprocessing.Pool(processes=self.threads) as pool:
                results = pool.map(JSONSplitter.validate_ndjson_chunk, existing_files)

        clean_count = sum(1 for result in results if result)
        failed_count = len(existing_files) - clean_count
        elapsed = time.time() - start_time

        logger.info("==================================================")
        logger.info(f"VALIDATION COMPLETED IN {elapsed:.2f} SECONDS ({elapsed / 60:.2f} minutes)")
        logger.info(f"Expected Chunks Count : {self.num_chunks}")
        logger.info(f"Existing Files Tested : {len(existing_files)}")
        logger.info(f"Missing Chunks Count  : {len(missing_files)}")
        logger.info(f"Clean Validated Chunks: {clean_count}")
        logger.info(f"Corrupt / Failed      : {failed_count}")
        logger.info("==================================================")

        is_100_percent_pass = (len(missing_files) == 0) and (failed_count == 0)
        if is_100_percent_pass:
            logger.info(f"🎉 100% COMPLETE & CLEAN! All {self.num_chunks} chunk files exist and passed validation.")
        else:
            logger.info(f"❌ VALIDATION INCOMPLETE: {len(missing_files)} missing file(s), {failed_count} failed file(s).")
        return is_100_percent_pass

    @staticmethod
    def _split_worker_task(worker_arguments):
        """Worker task for processing a subset of chunks in parallel."""
        (
            input_file,
            output_dir,
            num_chunks,
            chunk_size_gb,
            max_records_per_chunk,
            start_chunk,
            max_chunks,
            validate,
            target_chunk_bytes,
            worker_id,
            file_prefix,
            start_byte,
            end_byte,
        ) = worker_arguments

        chunk_index = start_chunk
        chunks_processed_count = 0
        current_chunk_bytes = 0
        lines_in_chunk = 0

        output_dir_path = Path(output_dir)
        current_output_path = output_dir_path / f"{file_prefix}_{chunk_index:03d}.ndjson"
        output_file_handle = current_output_path.open("wb")
        logger.info(f"   [Worker {worker_id}] Writing {current_output_path.name}...")

        start_time = time.time()
        last_report_time = start_time

        with Path(input_file).open("rb") as input_file_handle:
            if start_byte > 0:
                input_file_handle.seek(start_byte)
                input_file_handle.readline()  # Align to next record line boundary

            for raw_line in input_file_handle:
                stripped_line = raw_line.strip()
                if not stripped_line or stripped_line == b"[" or stripped_line == b"]":
                    continue

                if stripped_line.endswith(b","):
                    stripped_line = stripped_line[:-1]

                clean_record = stripped_line + b"\n"
                output_file_handle.write(clean_record)
                current_chunk_bytes += len(clean_record)
                lines_in_chunk += 1

                if time.time() - last_report_time > 15:
                    chunk_mb = current_chunk_bytes / (1024**2)
                    logger.info(
                        f"   [Worker {worker_id} - Part {chunk_index:03d}] Writing... {lines_in_chunk:,} records ({chunk_mb:.1f} MB)"
                    )
                    last_report_time = time.time()

                split_triggered = bool(
                    (max_records_per_chunk and lines_in_chunk >= max_records_per_chunk)
                    or (not max_records_per_chunk and current_chunk_bytes >= target_chunk_bytes)
                )

                if split_triggered:
                    output_file_handle.close()
                    chunks_processed_count += 1
                    size_mb = current_output_path.stat().st_size / (1024**2)
                    logger.info(
                        f"   [Worker {worker_id} - Chunk {chunk_index:03d} Written] {lines_in_chunk:,} records | {size_mb:.1f} MB"
                    )

                    if validate and not JSONSplitter.validate_ndjson_chunk(str(current_output_path)):
                        logger.info(f"🛑 CRITICAL ERROR: Execution stopped due to anomaly in {current_output_path.name}")
                        sys.exit(1)

                    if max_chunks and chunks_processed_count >= max_chunks:
                        break

                    chunk_index += 1
                    current_chunk_bytes = 0
                    lines_in_chunk = 0
                    current_output_path = output_dir_path / f"{file_prefix}_{chunk_index:03d}.ndjson"
                    output_file_handle = current_output_path.open("wb")
                    logger.info(f"   [Worker {worker_id}] Writing {current_output_path.name}...")

                # Stop if we've consumed past our assigned input byte range
                if end_byte is not None and input_file_handle.tell() >= end_byte:
                    break

        if not output_file_handle.closed:
            output_file_handle.close()

        if (
            current_output_path.exists()
            and current_output_path.stat().st_size > 0
            and (not max_chunks or chunks_processed_count < max_chunks)
        ):
            chunks_processed_count += 1
            size_mb = current_output_path.stat().st_size / (1024**2)
            logger.info(f"   [Worker {worker_id} - Chunk {chunk_index:03d} Written] {lines_in_chunk:,} records | {size_mb:.1f} MB")
            if validate and not JSONSplitter.validate_ndjson_chunk(str(current_output_path)):
                logger.info(f"🛑 CRITICAL ERROR: Execution stopped due to anomaly in {current_output_path.name}")
                sys.exit(1)
        elif current_output_path.exists() and current_output_path.stat().st_size == 0:
            current_output_path.unlink(missing_ok=True)

        return chunks_processed_count

    def split(self) -> int:
        """Splits a monolithic JSON array file into clean .ndjson files.

        Returns:
            int: Total number of .ndjson chunk files written and validated.
        """
        input_path = Path(self.input_file) if self.input_file else None
        if not input_path or not input_path.exists():
            logger.info(f"Error: Input file '{self.input_file}' does not exist.")
            sys.exit(1)

        file_size_bytes = input_path.stat().st_size
        file_size_gb = file_size_bytes / (1024**3)

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        if self.chunk_size_gb is not None and self.chunk_size_gb > 0:
            target_chunk_bytes = int(self.chunk_size_gb * 1024**3)
        else:
            target_chunk_bytes = int(file_size_bytes / self.num_chunks)

        logger.info("==================================================")
        logger.info("   PARALLEL MASSIVE JSON TO NDJSON SPLITTER")
        logger.info("==================================================")
        logger.info(f"Input File            : {self.input_file} ({file_size_gb:.2f} GB)")
        logger.info(f"Output Directory      : {self.output_dir}")
        logger.info(f"Total Chunks Plan     : {self.num_chunks} chunks")
        logger.info(f"Target Chunk Size     : {target_chunk_bytes / (1024**3):.2f} GB per file")
        logger.info(f"Parallel Worker Threads: {self.threads} Workers")
        logger.info(f"Validation Enabled    : {self.validate}")
        if self.start_chunk > 1:
            logger.info(f"Target Starting Chunk : Chunk #{self.start_chunk} (part_{self.start_chunk:03d}.ndjson)")
        if self.max_chunks:
            logger.info(f"Max Chunks Limit      : {self.max_chunks}")
        logger.info("==================================================")

        start_time = time.time()

        if self.threads <= 1 or self.max_chunks is not None or self.start_chunk > 1:
            start_byte = int((self.start_chunk - 1) * target_chunk_bytes) if self.start_chunk > 1 else 0
            total_processed = JSONSplitter._split_worker_task(
                (
                    self.input_file,
                    self.output_dir,
                    self.num_chunks,
                    self.chunk_size_gb,
                    self.max_records_per_chunk,
                    self.start_chunk,
                    self.max_chunks,
                    self.validate,
                    target_chunk_bytes,
                    1,
                    self.file_prefix,
                    start_byte,
                    None,
                )
            )
        else:
            chunks_per_worker = self.num_chunks // self.threads
            bytes_per_worker = file_size_bytes // self.threads
            worker_tasks = []

            for worker_index in range(self.threads):
                worker_start_chunk = worker_index * chunks_per_worker + 1
                worker_max_chunks = (
                    self.num_chunks - worker_start_chunk + 1 if worker_index == self.threads - 1 else chunks_per_worker
                )

                worker_start_byte = worker_index * bytes_per_worker
                worker_end_byte = file_size_bytes if worker_index == self.threads - 1 else (worker_index + 1) * bytes_per_worker

                worker_tasks.append(
                    (
                        self.input_file,
                        self.output_dir,
                        self.num_chunks,
                        self.chunk_size_gb,
                        self.max_records_per_chunk,
                        worker_start_chunk,
                        worker_max_chunks,
                        self.validate,
                        target_chunk_bytes,
                        worker_index + 1,
                        self.file_prefix,
                        worker_start_byte,
                        worker_end_byte,
                    )
                )

            logger.info(f"\nSpawning {self.threads} parallel worker processes to split chunks...")
            with multiprocessing.Pool(processes=self.threads) as pool:
                results = pool.map(JSONSplitter._split_worker_task, worker_tasks)

            total_processed = sum(results)

        total_time = time.time() - start_time
        logger.info("\n==================================================")
        logger.info(f"SPLITTING FINISHED IN {total_time:.2f} SECONDS ({total_time / 60:.2f} minutes)")
        logger.info(f"Total .ndjson Chunks Processed: {total_processed}")
        logger.info(f"Validation Executed           : {self.validate}")
        logger.info("==================================================")
        return total_processed
