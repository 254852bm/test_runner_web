package pro.testrun.demo;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.qameta.allure.Description;
import io.qameta.allure.Feature;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

@Feature("TestRun API: интеграция автотестов")
class TestRunApiIntegrationTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final HttpClient HTTP = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build();

    @Test
    @EnabledIf("pro.testrun.demo.DemoSafety#apiEnabledFromEnvironment")
    @Description("Читает активные строки через API и отправляет автоматический результат в TestRun.")
    void readDataRowsAndPostAutomatedRun() throws Exception {
        String base = requiredEnv("TESTRUN_BASE_URL").replaceAll("/+$", "");
        String token = requiredEnv("TESTRUN_API_TOKEN");
        int testCaseId = Integer.parseInt(requiredEnv("TESTRUN_TEST_CASE_ID"));
        int dataSetId = Integer.parseInt(requiredEnv("TESTRUN_DATA_SET_ID"));

        HttpRequest rowsRequest = HttpRequest.newBuilder(
                URI.create(base + "/api/data-sets/" + dataSetId + "/rows"))
            .timeout(Duration.ofSeconds(20))
            .header("Authorization", "Bearer " + token)
            .GET()
            .build();

        HttpResponse<String> rowsResponse = HTTP.send(rowsRequest, HttpResponse.BodyHandlers.ofString());
        assertEquals(200, rowsResponse.statusCode(), "API чтения строк должна вернуть HTTP 200");
        JsonNode root = JSON.readTree(rowsResponse.body());
        assertEquals(testCaseId, root.path("test_case_id").asInt(),
            "Выбранный набор данных должен принадлежать указанному тест-кейсу");
        assertFalse(root.path("secrets_included").asBoolean(),
            "Обычный API-запрос не должен включать секретные значения");
        for (JsonNode column : root.path("columns")) {
            assertFalse(column.path("is_secret").asBoolean(),
                "Секретные столбцы не должны попадать в обычный ответ API");
        }
        JsonNode rows = root.path("rows");
        assertTrue(rows.isArray() && !rows.isEmpty(), "В наборе должна быть хотя бы одна активная строка");

        JsonNode firstRow = rows.get(0);
        int rowId = firstRow.path("id").asInt();
        assertTrue(rowId > 0, "API должна вернуть ID строки");

        String requestBody = JSON.writeValueAsString(Map.of(
            "test_case_id", testCaseId,
            "data_set_id", dataSetId,
            "data_row_id", rowId,
            "status", "PASS",
            "comment", "Автоматический результат из отдельного Java/JUnit demo-проекта"
        ));

        HttpRequest runRequest = HttpRequest.newBuilder(URI.create(base + "/api/run"))
            .timeout(Duration.ofSeconds(20))
            .header("Authorization", "Bearer " + token)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(requestBody))
            .build();

        HttpResponse<String> runResponse = HTTP.send(runRequest, HttpResponse.BodyHandlers.ofString());
        assertEquals(201, runResponse.statusCode(), "API регистрации результата должна вернуть HTTP 201");
        JsonNode runResult = JSON.readTree(runResponse.body());
        assertTrue(runResult.path("ok").asBoolean(),
            "Ответ API должен подтвердить создание автоматического прогона");
        assertTrue(runResult.path("run_id").asInt() > 0,
            "API должна вернуть ID созданного прогона");
        assertEquals(testCaseId, runResult.path("test_case_id").asInt());
        assertEquals(dataSetId, runResult.path("data_set_id").asInt());
        assertEquals(rowId, runResult.path("data_row_id").asInt());
        assertEquals("PASS", runResult.path("status").asText());
    }

    private static String requiredEnv(String key) {
        String value = System.getenv(key);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("Не задана обязательная переменная окружения: " + key);
        }
        return value;
    }
}
