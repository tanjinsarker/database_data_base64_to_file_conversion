#!/usr/bin/env python3
import os
import re
import sys
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

# If you want URLs instead of relative paths, change this prefix.
URL_PREFIX = os.environ.get("URL_PREFIX", "text_editor_files")

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


def decode_and_write_file(row_id, index, mime_type, data_bytes):
    ext = get_extension(mime_type)
    filename = f"{TABLE_NAME}_{row_id}_{index}.{ext}"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(OUTPUT_DIR, filename)
    with open(file_path, "wb") as f:
        f.write(data_bytes)

    prefix = URL_PREFIX.strip()
    if prefix:
        prefix = "/" + prefix.lstrip("/")
        return f"{prefix}/{filename}"
    return filename


def process_row(row_id, details):
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


def main():
    print("Starting base64 extraction from complaints.details...")
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    select_sql = f"SELECT {ID_COLUMN}, {COLUMN_NAME} FROM {TABLE_NAME}"
    cursor.execute(select_sql)

    rows = cursor.fetchall()
    if not rows:
        print("No rows found.")
        return

    updated_rows = 0
    for row in rows:
        row_id = row[ID_COLUMN]
        details = row[COLUMN_NAME]
        if not details:
            continue

        new_details, replacements = process_row(row_id, details)
        if replacements:
            update_sql = f"UPDATE {TABLE_NAME} SET {COLUMN_NAME} = %s WHERE {ID_COLUMN} = %s"
            cursor.execute(update_sql, (new_details, row_id))
            conn.commit()
            updated_rows += 1
            print(f"Updated row {row_id}: extracted {len(replacements)} file(s)")

    print(f"Finished. Rows updated: {updated_rows}")
    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
