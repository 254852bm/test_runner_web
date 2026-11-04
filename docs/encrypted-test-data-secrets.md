# Encrypted test-data secrets (feature-branch implementation)

## Current status

The application now has an authenticated-encryption storage layer based on Fernet
(AES-128-CBC + HMAC-SHA256), a dedicated configuration key, and additive SQLite
columns for encrypted row values and encrypted historical snapshots.

Secret columns can now be marked in the data-set editor. Their values are written
only to the encrypted payload column, decrypted only while rendering an authorized
manual run or when an API caller explicitly opts in, and copied to a separate
encrypted historical snapshot. Ordinary JSON snapshots do not contain secrets.

The run history stores redacted step text, expected results and comments. PDF
reports use the run history and do not include decrypted secret values. The normal
automation data endpoint omits secrets; a caller must explicitly send
`X-Test-Runner-Include-Secrets: true` to receive them. This is restricted to the
API-token owner and should only be used over HTTPS. Never print returned values
to test logs, CI artifacts, or exception messages.

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
- `api_token.allow_secret_data` (defaults to false for existing tokens)

It does not move or rewrite any existing ordinary values. Existing databases
must be backed up and migrated explicitly before a future release uses these
columns. Do not run this against production until separately approved.

## Security boundary in this stage

- Ordinary test values remain in `values_json` / `values_snapshot_json`.
- Secret payload helpers encrypt/decrypt dictionaries and fail closed if the
  key is missing, malformed, or wrong.
- Empty secret maps do not need ciphertext.
- The editor uses password inputs and never pre-fills decrypted values. A blank
  edit field preserves the stored value; a separate checkbox clears it.
- Manual run pages render the decrypted value for the authenticated project
  owner, but persistent StepRun text, expected results and comments are redacted.
- Secret values are stored only in encrypted run snapshots, not ordinary JSON
  snapshots. PDF/history output uses redacted records.
- The automation API omits secrets by default. Retrieval requires both the
  per-token **Allow secret test data** permission in Settings → API tokens and
  the explicit `X-Test-Runner-Include-Secrets: true` header. Use this only over
  HTTPS. Protect API tokens as credentials and prefer a dedicated token for CI.
- The existing API continues not to return secret-like columns.
