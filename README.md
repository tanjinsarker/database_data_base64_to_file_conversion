# Base64 Migration Script

This repository contains a Python script to migrate inline base64 data stored in the `details` column of a MySQL table into separate files. The script writes files into the `text_editor_files/` directory and replaces inline base64 URIs in `details` with file URLs.

## Requirements

- Python 3
- MySQL server access
- One of these Python clients:
  - `mysql-connector-python`
  - `pymysql`

If your environment is managed by the OS, install the Debian package instead:

```bash
sudo apt update
sudo apt install python3-pymysql
```

## Setup

1. Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

2. Update `.env` with your database and migration settings:

```dotenv
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=12345
DB_NAME=migration_column
TABLE_NAME=complaints
COLUMN_NAME=details
ID_COLUMN=id
OUTPUT_DIR=text_editor_files
URL_PREFIX=text_editor_files
BATCH_SIZE=100
ID_START=1
ID_END=150000
DB_SSL_DISABLED=true
```

- `BATCH_SIZE` sets rows fetched per batch.
- `ID_START` and `ID_END` are optional range filters.
- `OUTPUT_DIR` is where decoded files are saved.
- `URL_PREFIX` is the prefix written into `details` when replacing the base64 URI.

3. Ensure `.env` is not committed in Git. `.gitignore` already includes `.env`.

## Install dependencies

Use the system package manager if direct `pip install` is blocked.

### If you can install with pip:

```bash
python3 -m pip install mysql-connector-python
```

or

```bash
python3 -m pip install pymysql
```

### If pip is blocked by an externally-managed environment:

```bash
sudo apt update
sudo apt install python3-pymysql
```

## Usage

Run the migration script from the repository root:

```bash
python3 migrate_base64_to_files.py --batch-size 100
```

### Dry run

To see what would happen without writing files or updating the database:

```bash
python3 migrate_base64_to_files.py --dry-run --batch-size 100
```

### Using ID range

Process only rows within a specific ID range:

```bash
python3 migrate_base64_to_files.py --batch-size 100 --id-start 1 --id-end 50000
```

### Notes

- The script processes rows in batches using `LIMIT` and `OFFSET` to avoid high memory usage.
- Files are written as `complaints_<id>_<serial>.<ext>` in the `text_editor_files/` folder.
- If the DB connection should not use SSL, set `DB_SSL_DISABLED=true` in `.env`.

## Example workflow

1. Test with a small range and dry-run.
2. Verify generated file paths and row updates.
3. Run full migration with a safe batch size.

## Troubleshooting

- If you get `Error: Neither mysql.connector nor pymysql is installed`, install one of the supported drivers.
- If `pip` is blocked, use the system package (`python3-pymysql`).
- If rows are large, keep `BATCH_SIZE` small (for example `10` or `20`).
