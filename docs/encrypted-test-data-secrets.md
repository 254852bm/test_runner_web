# Encrypted test-data secrets (feature-branch implementation)

## Current status

The application now has an authenticated-encryption storage layer based on Fernet
(AES-128-CBC + HMAC-SHA256), a dedicated configuration key, and additive SQLite
columns for encrypted row values and encrypted historical snapshots.

**Secret columns are still intentionally unavailable in the user interface and
parameterized run service in this stage.** They must remain blocked until the
complete read/write, masking, snapshot, PDF/history, and automation authorization
paths have been implemented and tested. Do not remove the current secret-column
rejection as a standalone change.

## Key configuration

Generate a key once in a secure environment:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store the resulting value as `TEST_DATA_ENCRYPTION_KEY` in the server's secret
environment configuration. It is separate from Flask `SECRET_KEY`.

- Never commit the key to Git.
- Never store the key in SQLite, source code, a browser, or a test fixture used
  outside isolated tests.
- Keep a secure offline backup. If the key is lost, encrypted values cannot be
  recovered.
- Back up the database and key as a coordinated pair with access restricted.
- Key rotation requires decrypting with the old key and re-encrypting with the
  new key; simply replacing the environment value makes existing secrets
  unreadable.
- Do not log decrypted values, include them in error messages, or print them in
  CI output.

## Database change

The migration script is additive and refuses to create a missing database:

```bash
python scripts/add_test_data_encryption_columns.py --database /path/to/test_runner.db
```

It adds nullable columns:
- `test_data_row.encrypted_values_json`
- `test_run_data_snapshot.encrypted_values_snapshot`

It does not move or rewrite any existing ordinary values. Existing databases
must be backed up and migrated explicitly before a future release uses these
columns. Do not run this against production until separately approved.

## Security boundary in this stage

- Ordinary test values remain in `values_json` / `values_snapshot_json`.
- Secret payload helpers encrypt/decrypt dictionaries and fail closed if the
  key is missing, malformed, or wrong.
- Empty secret maps do not need ciphertext.
- Current UI and run service continue to reject secret columns. This is
  deliberate until secrets can be masked in the UI and excluded from step-run
  text, comments, PDFs, logs, and ordinary JSON snapshots.
- The existing API continues not to return secret-like columns.
