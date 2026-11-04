# Test-data parameterization: manual acceptance checklist

Run this checklist only on the isolated test deployment and its test database.
Do not point any command in this document at the production database.

## 1. Before changing the test copy

- Confirm the checkout is on `feature/test-data-parameterization`.
- Confirm the configured SQLite path belongs to the test copy, not production.
- Make a separate SQLite backup of the test database and verify it with `PRAGMA integrity_check`.
- Keep the test copy's current branch/commit and backup path so it can be restored.
- Do not copy production API tokens or real passwords into the test environment.

## 2. Configure encryption for the test copy

Generate a dedicated Fernet key in a secure terminal:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add the generated value to the test copy's environment configuration as
`TEST_DATA_ENCRYPTION_KEY`. Do not commit it to Git, put it in a screenshot,
or paste it into an issue or chat. Keep a secure backup of the key: encrypted
values cannot be recovered if the key is lost.

The key is independent from Flask's `SECRET_KEY`.

## 3. Prepare only the test database

Run the migration with the exact test database path:

```bash
python scripts/add_test_data_encryption_columns.py --database /absolute/path/to/test/instance/test_runner.db
```

The script refuses to create a missing database. It checks the base application
tables, creates only the missing test-data feature tables, and adds the encrypted
payload columns and per-token secret permission when absent.

Then verify SQLite integrity:

```bash
sqlite3 /absolute/path/to/test/instance/test_runner.db "PRAGMA integrity_check;"
```

Expected result: `ok`.

## 4. Manual UI checks

Create a disposable project and a test case with at least these placeholders:

- `{{base_url}}`
- `{{login}}`
- `{{password}}`
- `{{expected_message}}`

Create a data set with:
- ordinary columns for base URL, login and expected message;
- a password column marked **Секрет**;
- at least two rows, one active and one disabled.

Check the following:

- [ ] Ordinary values can be entered, edited and saved.
- [ ] A secret value can be entered and saved.
- [ ] Returning to the data-set editor does not pre-fill the secret value.
- [ ] An empty secret edit preserves the existing value.
- [ ] The explicit clear-secret checkbox removes the value.
- [ ] Column label/key can be edited; current row values move to the new key.
- [ ] A column can be added and deleted; a data set cannot be left without columns.
- [ ] Deleting or editing the current data set does not rewrite old run snapshots.
- [ ] The test case can be run once with one selected row.
- [ ] Sequential run processes active rows only and creates a separate history entry per row.
- [ ] Disabled rows cannot be started directly.
- [ ] History and PDF show the data-set/row labels but do not expose secret values.
- [ ] Step text, expected results and comments in history do not contain the secret.
- [ ] The manual run page keeps secrets out of the instruction text and shows them only in the dedicated masked password field.

## 5. API checks

Create a new API token specifically for the test automation check.

- [ ] With **Allow secret test data** disabled, a request with
  `X-Test-Runner-Include-Secrets: true` returns HTTP 403.
- [ ] With the permission enabled, the same request over HTTPS returns the
  secret values.
- [ ] Without the opt-in header, secret values remain omitted even when the
  token has permission.
- [ ] With an invalid/missing encryption key, secret retrieval returns HTTP 503
  and does not return plaintext.
- [ ] POST `/api/run` accepts `data_set_id` and `data_row_id`, creates an
  automated run, stores an encrypted snapshot and masks secrets in result text.
- [ ] The legacy POST `/api/run` request without data-set fields still works.
- [ ] A token cannot read another user's data.

Use a disposable non-secret test password. Never print returned secrets to
terminal output, CI logs, or build artifacts.

## 6. Final checks

- [ ] Existing project, test-case, manual-run, history, screenshot and PDF flows still work.
- [ ] Existing test accounts and projects remain intact.
- [ ] The test service responds normally after restart.
- [ ] Production branch, production service and production database have not been changed.

If any check fails, stop and keep the failure on the isolated test copy. Do not
attempt a production update as a workaround. Restore only the test database from
its pre-test backup if needed, and keep the failure details for diagnosis.
