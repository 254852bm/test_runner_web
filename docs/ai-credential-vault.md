# BYOK credential vault — implementation notes

## Product and billing model

AI assistance is an optional add-on. The standard TestRun subscription does not include an AI allowance and is not increased to cover AI usage. A customer who wants generation connects their own provider account and pays that provider directly under the provider's tariff. Customers who do not need AI can use TestRun without connecting a key.

TestRun must not make automatic payments to an AI provider on behalf of a customer, pool customer usage under a shared provider account, or trigger a billable request merely because a key is saved. Before each generation request, the user must explicitly confirm that the provider may charge their own account. A future TestRun-managed AI package would require a separate product and cost decision.

## Scope

This change adds a user-owned credential record and a settings page for the first supported provider, Yandex AI Studio. Saving a credential does not call Yandex, validate a key against the provider, generate content, or incur provider usage. The generation route can use the current user's enabled credential only when the AI feature flag is enabled and the user confirms the possible provider charge for that individual request.

## Storage and isolation

- One credential record per TestRun user account.
- The encrypted payload contains the provider API key, Yandex Cloud folder ID, owner user ID, and provider identifier.
- The owner and provider identifiers are checked again after decryption, so ciphertext copied to another user's row cannot be used as that user's credential.
- Fernet authenticated encryption is used. No plaintext fallback exists.
- The encryption key is independent from Flask `SECRET_KEY` and `TEST_DATA_ENCRYPTION_KEY`.
- The browser receives neither the stored ciphertext nor the decrypted credential. The key field is never repopulated after save.
- The key is never included in a URL or application log by these routes.
- Saving requires explicit acknowledgement of potential provider charges and consent to encrypted storage. It does not run a connection test.
- Disabling a credential prevents generation while retaining the encrypted value; deleting removes the user's credential record.
- Every generation request requires a separate explicit payment confirmation. Without it, the provider must not be called.

## Server configuration

Before accepting real user credentials in any environment, generate a dedicated Fernet key:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set the resulting value as `AI_CREDENTIAL_ENCRYPTION_KEY` in the server's secret environment configuration. Do not commit it, put it in source control, send it to the browser, or reuse the Flask session/test-data encryption key.

**Back up this key separately and securely.** If it is lost, previously stored credentials cannot be decrypted. If it is exposed, treat every stored credential as compromised and arrange key rotation/re-entry before enabling requests. A key rotation procedure is not part of this MVP.

When the encryption key is missing or invalid, credential saving fails closed. This is intentional.

The paid adapter targets Yandex AI Studio. Its model URI is server configuration; the customer's API key and folder ID are taken from that customer's encrypted credential. For local development only, `AI_PROVIDER_MODE=ollama` selects the Ollama adapter at `http://127.0.0.1:11434`; it accepts only loopback HTTP addresses and requires `AI_LOCAL_MODEL`. Local generation does not require a customer key or paid-request confirmation. Do not install a model on the production VPS with its current 2 GB RAM; run Ollama on a developer workstation. A separately hosted inference service is not implemented.

## Database setup

The models are additive, but the existing application database is not modified automatically by this feature branch. First back up an isolated TEST database, then run:

```bash
python scripts/add_ai_credential_table.py --database /absolute/path/to/test_runner.db
```

The script refuses to create a missing database, verifies the existing `user` table, and creates only `ai_credential`, `ai_generation_attempt`, and `ai_draft_save`. The generation-attempt table stores only user ID and timestamp, not requirement text, response text, keys, or other content. The draft-save table stores a random one-time token, owner/project IDs, the resulting test-case ID, and a timestamp; it stores no draft text and prevents duplicate creation if the save form is submitted twice. Old idempotency records are pruned after 30 days. Do not run this against production as part of this change.


## Request limits and cost estimate

Generation attempts are rate-limited per user with a rolling one-hour window. The default is five attempts per hour; the server setting `AI_GENERATIONS_PER_HOUR` may adjust this from 1 to 100. A metadata-only attempt record is committed before provider I/O, so provider failures and retries also consume an attempt. This intentionally discourages repeated paid requests. No requirement or response content is stored in this table.

For Yandex, an optional upper-bound estimate is shown before generation when the administrator configures `AI_PRICE_INPUT_RUB_PER_1K` and `AI_PRICE_OUTPUT_RUB_PER_1K` for the selected model's current tariff. The estimate assumes the maximum allowed requirement length and configured maximum completion tokens; it is not a guaranteed invoice amount. If rates are absent, the UI explicitly says the estimate is not configured and asks the user to check the provider tariff. The rates must be reviewed whenever the model or tariff changes. The local Ollama mode shows no provider charge estimate.

## Not implemented yet

- A local Ollama adapter and a separately hosted model endpoint.
- A second customer-selectable provider or multi-key support.
- Reliable per-user token/cost reporting; this should be shown only when the provider returns trustworthy usage data.
- Automatic credential migration or key rotation.
- A TestRun-billed AI package. That is a separate future commercial decision.

## Required checks before enabling production requests

1. Verify the provider contract, data processing terms, model, and current tariff.
2. Configure and back up the dedicated encryption key.
3. Apply the additive table creation to an isolated test database.
4. Test provider resolution using only the current user's credential.
5. Confirm that the per-request payment acknowledgement is present and blocks the outbound call when absent.
6. Test missing/wrong encryption key, wrong owner, deleted/disabled credential, provider timeout, malformed provider output, and no-consent paths.
7. Keep AI generation disabled in production until all checks, provider/account review, isolated database migration, and manual acceptance are complete.
