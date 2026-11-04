# BYOK credential vault — implementation notes

## Scope

This change adds a user-owned credential record and a settings page for the first supported provider, Yandex AI Studio. It does not call Yandex, validate a key against the provider, or enable AI generation. Saving a credential is not a billable provider request.

## Storage and isolation

- One credential record per TestRun user account.
- The encrypted payload contains the provider API key, Yandex Cloud folder ID, owner user ID, and provider identifier.
- The owner and provider identifiers are checked again after decryption, so ciphertext copied to another user's row cannot be used as that user's credential.
- Fernet authenticated encryption is used. No plaintext fallback exists.
- The encryption key is independent from Flask `SECRET_KEY` and `TEST_DATA_ENCRYPTION_KEY`.
- The browser receives neither the stored ciphertext nor the decrypted credential. The key field is never repopulated after save.
- The key is never included in a URL or application log by these routes.
- Saving requires explicit acknowledgement of potential provider charges and consent to encrypted storage. It does not run a connection test.

## Server configuration

Before accepting real user credentials in any environment, generate a dedicated Fernet key:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set the resulting value as `AI_CREDENTIAL_ENCRYPTION_KEY` in the server's secret environment configuration. Do not commit it, put it in source control, send it to the browser, or reuse the Flask session/test-data encryption key.

**Back up this key separately and securely.** If it is lost, previously stored credentials cannot be decrypted. If it is exposed, treat every stored credential as compromised and arrange key rotation/re-entry before enabling requests. A key rotation procedure is not part of this MVP.

When the encryption key is missing or invalid, credential saving fails closed. This is intentional.

## Database setup

The model is additive, but the existing application database is not modified automatically by this feature branch. First back up an isolated TEST database, then run:

```bash
python scripts/add_ai_credential_table.py --database /absolute/path/to/test_runner.db
```

The script refuses to create a missing database, verifies the existing `user` table, and creates only `ai_credential`. Do not run this against production as part of this change.

## Not implemented yet

- No provider request, key validation, or billable operation. Automated tests use mocked provider adapters only.
- No per-request confirmation UI; this must be implemented before any provider call is connected.
- No usage/token/cost reporting.
- No second provider or multi-key support.
- No automatic credential migration or key rotation.
- No deletion/retention policy beyond the user's explicit delete action.

## Required checks before enabling requests

1. Verify the provider contract, data processing terms, model, and current tariff.
2. Configure and back up the dedicated encryption key.
3. Apply the additive table creation to an isolated test database.
4. Add provider resolution that decrypts only the current user's credential.
5. Add an explicit per-request cost/consent confirmation before any outbound call.
6. Test missing/wrong encryption key, wrong owner, deleted/disabled credential, provider timeout, and no-consent paths.
7. Keep AI generation disabled until all checks and manual acceptance are complete.
