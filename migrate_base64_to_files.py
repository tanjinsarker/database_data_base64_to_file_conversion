#!/usr/bin/env python3
import argparse
import os
import re
import sys
import time
import base64
import mimetypes

try:
    import mysql.connector as mysql
except ImportError:
    try:
        import pymysql as mysql
    except ImportError:
        print(
            "Error: Neither mysql.connector nor pymysql is installed. Install one of them first."
        )
        sys.exit(1)


def load_env_file(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

load_env_file()

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "text_editor_files")
TABLE_NAME = os.environ.get("TABLE_NAME", "complaints")
COLUMN_NAME = os.environ.get("COLUMN_NAME", "details")
ID_COLUMN = os.environ.get("ID_COLUMN", "id")
LOG_FILE = os.environ.get("LOG_FILE", "migration.log")

# If you want URLs instead of relative paths, change this prefix.
URL_PREFIX = os.environ.get("URL_PREFIX", "text_editor_files")


def parse_bool(value, default=False):
    if value is None:
        return default
    value = str(value).strip().lower()
    return value in ("1", "true", "yes", "y")


def parse_env_int(name, default=None):
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_script_args():
    parser = argparse.ArgumentParser(
        description="Migrate inline base64 data in details to files and update records."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write files or update the database; just show what would happen.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=parse_env_int("BATCH_SIZE"),
        help="Number of rows to fetch per batch. This is mandatory via env or CLI.",
    )
    parser.add_argument(
        "--id-start",
        type=int,
        default=parse_env_int("ID_START"),
        help="Optional start ID for migration range.",
    )
    parser.add_argument(
        "--id-end",
        type=int,
        default=parse_env_int("ID_END"),
        help="Optional end ID for migration range.",
    )
    return parser.parse_args()

DATA_URI_PATTERN = re.compile(
    r"(?P<attr>src|href)\s*=\s*(?P<quote>[\'\"])(?P<uri>data:(?P<mime>[^;]+);base64,(?P<data>[^\"\']+))(?P=quote)",
    re.IGNORECASE,
)

EXTENSION_OVERRIDES = {
    "image/svg+xml": "svg",
    "text/plain": "txt",
    "application/json": "json",
    "text/html": "html",
    "application/javascript": "js",
}


def get_extension(mime_type):
    if mime_type in EXTENSION_OVERRIDES:
        return EXTENSION_OVERRIDES[mime_type]

    guessed = mimetypes.guess_extension(mime_type)
    if guessed:
        return guessed.lstrip(".")

    if "/" in mime_type:
        return mime_type.split("/")[-1]
    return "bin"


def decode_and_write_file(row_id, index, mime_type, data_bytes, dry_run=False):
    ext = get_extension(mime_type)
    filename = f"{TABLE_NAME}_{row_id}_{index}.{ext}"
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not dry_run:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(data_bytes)

    prefix = URL_PREFIX.strip()
    if prefix:
        prefix = "/" + prefix.lstrip("/")
        return f"{prefix}/{filename}"
    return filename


def process_row(row_id, details, dry_run=False):
    matches = list(DATA_URI_PATTERN.finditer(details))
    if not matches:
        return details, []

    replacements = []
    file_index = 1
    new_details_parts = []
    last_end = 0

    for match in matches:
        mime_type = match.group("mime")
        raw_data = match.group("data")
        try:
            decoded = base64.b64decode(raw_data, validate=True)
        except Exception:
            print(f"Warning: invalid base64 in row {row_id}, skipping this match.")
            continue

        output_url = decode_and_write_file(row_id, file_index, mime_type, decoded)
        file_index += 1

        original_uri = match.group("uri")
        replacements.append((original_uri, output_url))

        new_details_parts.append(details[last_end:match.start("uri")])
        new_details_parts.append(output_url)
        last_end = match.end("uri")

    new_details_parts.append(details[last_end:])
    new_details = "".join(new_details_parts)

    return new_details, replacements


def get_connection():
    config = {
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "migration_column"),
    }

    ssl_disabled = os.environ.get("DB_SSL_DISABLED", "true").strip().lower()
    if ssl_disabled in ("1", "true", "yes", "y"):
        config["ssl_disabled"] = True

    return mysql.connect(**config)


def ensure_log_file():
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    open(LOG_FILE, "a", encoding="utf-8").close()


def log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"[{timestamp}] {message}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    print(message)


def main():
    args = get_script_args()
    dry_run = args.dry_run
    batch_size = args.batch_size
    id_start = args.id_start
    id_end = args.id_end

    if batch_size is None or batch_size <= 0:
        print("Error: BATCH_SIZE must be set to a positive integer via --batch-size or BATCH_SIZE env.")
        sys.exit(1)

    if id_start is not None and id_end is not None and id_start > id_end:
        print("Error: --id-start cannot be greater than --id-end.")
        sys.exit(1)

    ensure_log_file()
    log("Starting base64 extraction from complaints.details...")
    if dry_run:
        log("Running in dry-run mode: no files will be written and database updates are skipped.")
    log(f"Batch size: {batch_size}")
    if id_start is not None or id_end is not None:
        log(f"ID range: {id_start or '-infinity'} to {id_end or 'infinity'}")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Build WHERE clause for counting and fetching
    where_clauses = []
    params = []
    if id_start is not None:
        where_clauses.append(f"{ID_COLUMN} >= %s")
        params.append(id_start)
    if id_end is not None:
        where_clauses.append(f"{ID_COLUMN} <= %s")
        params.append(id_end)

    where_clause = ""
    if where_clauses:
        where_clause = " WHERE " + " AND ".join(where_clauses)

    # Count total rows in the range
    count_sql = f"SELECT COUNT(*) as cnt FROM {TABLE_NAME}" + where_clause
    cursor.execute(count_sql, tuple(params))
    count_result = cursor.fetchone()
    total_rows_in_range = count_result["cnt"] if count_result else 0

    if total_rows_in_range == 0:
        log("No rows found in the specified range.")
        cursor.close()
        conn.close()
        return

    log(f"Total rows in range: {total_rows_in_range}")

    start_time = time.time()
    total_rows = 0
    updated_rows = 0
    batch_number = 0
    offset = 0

    # Fetch and process in batches using LIMIT OFFSET
    while offset < total_rows_in_range:
        fetch_sql = (
            f"SELECT {ID_COLUMN}, {COLUMN_NAME} FROM {TABLE_NAME}"
            + where_clause
            + f" ORDER BY {ID_COLUMN} ASC LIMIT %s OFFSET %s"
        )
        fetch_params = list(params) + [batch_size, offset]
        cursor.execute(fetch_sql, tuple(fetch_params))
        rows = cursor.fetchall()

        if not rows:
            break

        batch_number += 1
        batch_start = time.time()
        log(f"Processing batch {batch_number}, rows: {len(rows)}")

        for row in rows:
            total_rows += 1
            row_id = row[ID_COLUMN]
            details = row[COLUMN_NAME]
            if not details:
                continue

            new_details, replacements = process_row(row_id, details, dry_run=dry_run)
            if replacements:
                if dry_run:
                    log(f"Dry-run: row {row_id} would extract {len(replacements)} file(s).")
                else:
                    update_sql = f"UPDATE {TABLE_NAME} SET {COLUMN_NAME} = %s WHERE {ID_COLUMN} = %s"
                    cursor.execute(update_sql, (new_details, row_id))
                    conn.commit()
                    updated_rows += 1
                    log(f"Updated row {row_id}: extracted {len(replacements)} file(s)")

        batch_end = time.time()
        batch_seconds = batch_end - batch_start
        elapsed = batch_end - start_time

        log(f"Batch {batch_number} completed in {batch_seconds:.2f}s, elapsed {elapsed:.2f}s")

        offset += batch_size

    log(f"Finished. Total rows scanned: {total_rows}")
    if not dry_run:
        log(f"Rows updated: {updated_rows}")
    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
