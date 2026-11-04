# Test Runner API: test data for Java/Selenide

This document describes the test-data API added in the parameterization feature branch.

## Authentication

Use an API token in an HTTP header. Do not put tokens in URLs.

Preferred header:

```http
Authorization: Bearer YOUR_API_TOKEN
```

Alternative:

```http
X-API-Token: YOUR_API_TOKEN
```

Store the token in an environment variable or CI secret, for example `TEST_RUNNER_API_TOKEN`. Do not commit it to the repository or print it in test logs.

## 1. List data sets for a test case

```http
GET /api/test-cases/{test_case_id}/data-sets
```

Example response:

```json
{
  "ok": true,
  "test_case_id": 42,
  "data_sets": [
    {
      "id": 7,
      "name": "Login examples",
      "columns": [
        {"key": "base_url", "label": "Base URL", "is_secret": false},
        {"key": "login", "label": "Login", "is_secret": false}
      ],
      "active_rows_count": 2
    }
  ]
}
```

## 2. Read active rows from a data set

```http
GET /api/data-sets/{data_set_id}/rows
```

Example response:

```json
{
  "ok": true,
  "data_set_id": 7,
  "test_case_id": 42,
  "data_set_name": "Login examples",
  "columns": [
    {"key": "base_url", "label": "Base URL"},
    {"key": "login", "label": "Login"}
  ],
  "rows": [
    {
      "id": 101,
      "name": "Valid user",
      "values": {
        "base_url": "https://example.test",
        "login": "qa@example.test"
      }
    }
  ]
}
```

Only active rows are returned. By default, secret columns and columns with names that look like passwords, tokens or API keys are omitted.

If an automation job is explicitly authorized to receive credentials, it may send the additional header `X-Test-Runner-Include-Secrets: true`. The server then decrypts secret values and returns them only if that API token also has the separate **Allow secret test data** permission enabled in Settings → API tokens. Both the per-token permission and this explicit header are required. Use this only over HTTPS, keep the response in memory, never print it to test logs or CI artifacts, and use a dedicated token for automation. Without this header, secrets are omitted. If the encryption key is missing or invalid, the server returns HTTP 503 rather than exposing plaintext or falling back to unencrypted storage.

Secret values are encrypted at rest with the dedicated `TEST_DATA_ENCRYPTION_KEY`; ordinary columns remain separate. See `docs/encrypted-test-data-secrets.md` for key management and migration instructions.

The API checks that the API-token owner owns the project containing the test case. A token cannot read another user's test data.

## 3. Send an automated result linked to a data row

The existing `POST /api/run` contract remains compatible. Add two optional fields to associate an automated run with the exact data row:

```json
{
  "test_case_id": 42,
  "data_set_id": 7,
  "data_row_id": 101,
  "status": "PASS",
  "comment": "JUnit/Selenide iteration completed",
  "duration_ms": 1530
}
```

Send the token using the Authorization header. Existing clients may continue to send `token` in the JSON body.

When these fields are supplied, the server verifies that the data set belongs to the test case and the row belongs to the data set. It stores a historical snapshot and records rendered step text. Send both IDs or neither.

Optional `step_results` can still be included in the same request:

```json
{
  "step_results": [
    {"step_id": 301, "status": "PASS", "actual_result": "Dashboard is visible"}
  ]
}
```

## 4. Java 17 + JUnit 5 + Selenide example

Add Jackson Databind to the Java automation project's Gradle dependencies if it is not already present:

```groovy
testImplementation 'com.fasterxml.jackson.core:jackson-databind:2.18.2'
```

The example below fetches active rows once for a JUnit parameterized test and reports each invocation as a separate Test Runner run. Replace the sample UI locators and assertions with the real application's locators.

```java
import com.codeborne.selenide.Selenide;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.stream.Stream;
import static com.codeborne.selenide.Selenide.$;
import static com.codeborne.selenide.Condition.visible;

class LoginParameterizedTest {
    private static final String BASE_URL = System.getenv("TEST_RUNNER_URL");
    private static final String TOKEN = System.getenv("TEST_RUNNER_API_TOKEN");
    private static final int TEST_CASE_ID =
        Integer.parseInt(System.getenv("TEST_RUNNER_TEST_CASE_ID"));
    private static final int DATA_SET_ID =
        Integer.parseInt(System.getenv("TEST_RUNNER_DATA_SET_ID"));

    private static final HttpClient HTTP = HttpClient.newHttpClient();
    private static final ObjectMapper JSON = new ObjectMapper();

    record DataRow(int id, String name, JsonNode values) {}

    static Stream<Arguments> rows() throws Exception {
        HttpRequest request = HttpRequest.newBuilder(
                URI.create(BASE_URL + "/api/data-sets/" + DATA_SET_ID + "/rows"))
            .header("Authorization", "Bearer " + TOKEN)
            .GET()
            .build();

        HttpResponse<String> response =
            HTTP.send(request, HttpResponse.BodyHandlers.ofString());

        if (response.statusCode() != 200) {
            throw new IllegalStateException(
                "Test Runner data API returned HTTP " + response.statusCode());
        }

        JsonNode root = JSON.readTree(response.body());
        return java.util.stream.StreamSupport.stream(
                root.path("rows").spliterator(), false)
            .map(row -> Arguments.of(new DataRow(
                row.path("id").asInt(),
                row.path("name").asText(),
                row.path("values")
            )));
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("rows")
    void loginWithDataRow(DataRow row) throws Exception {
        String status = "PASS";
        String comment = "JUnit/Selenide iteration: " + row.name();

        try {
            String baseUrl = row.values().path("base_url").asText();
            String login = row.values().path("login").asText();

            Selenide.open(baseUrl);
            $("#login").setValue(login);
            $("#submit").click();
            $("#dashboard").shouldBe(visible);
        } catch (RuntimeException | AssertionError error) {
            status = "FAIL";
            comment = error.getClass().getSimpleName() + ": " + error.getMessage();
            throw error;
        } finally {
            reportResult(row, status, comment);
        }
    }

    private static void reportResult(
        DataRow row, String status, String comment
    ) throws Exception {
        String body = JSON.writeValueAsString(Map.of(
            "test_case_id", TEST_CASE_ID,
            "data_set_id", DATA_SET_ID,
            "data_row_id", row.id(),
            "status", status,
            "comment", comment
        ));

        HttpRequest request = HttpRequest.newBuilder(
                URI.create(BASE_URL + "/api/run"))
            .header("Authorization", "Bearer " + TOKEN)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build();

        HttpResponse<String> response =
            HTTP.send(request, HttpResponse.BodyHandlers.ofString());

        if (response.statusCode() != 201) {
            throw new IllegalStateException(
                "Could not report Test Runner result: HTTP " + response.statusCode());
        }
    }
}
```

Environment variables to configure in the local run configuration or CI secret store:

- `TEST_RUNNER_URL` — for example `https://testrun.pro`;
- `TEST_RUNNER_API_TOKEN` — API token created in Test Runner;
- `TEST_RUNNER_TEST_CASE_ID` — ID of the test case in Test Runner;
- `TEST_RUNNER_DATA_SET_ID` — ID of the data set attached to that test case.

The sample intentionally uses non-secret values. If you add a secret column, mark it as secret in the Test Runner UI, enable **Allow secret test data** only for the dedicated automation token, and retrieve it only when the job genuinely requires it using the explicit header described above. Never put secrets into ordinary columns.

## Compatibility notes

- Old `POST /api/run` clients may continue sending `token` in JSON and omit data-set fields.
- `data_set_id` and `data_row_id` must be sent together.
- The row must be active and belong to the selected data set; the data set must belong to the selected test case.
- Each POST creates a separate automated TestRun. The Test Runner stores a data snapshot so later edits to the row do not rewrite run history.
