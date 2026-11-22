package pro.testrun.demo;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class DemoSafetyTest {
    @Test
    void uiTestIsDisabledWhenNoExplicitPermissionIsProvided() {
        assertFalse(DemoSafety.uiEnabled(Map.of()));
        assertFalse(DemoSafety.uiEnabled(Map.of("TESTRUN_E2E_ENABLED", "true")));
        assertFalse(DemoSafety.uiEnabled(Map.of(
            "TESTRUN_E2E_ENABLED", "true",
            "TESTRUN_ENVIRONMENT", "production"
        )));
    }

    @Test
    void uiTestIsEnabledOnlyForExplicitIsolatedEnvironment() {
        assertTrue(DemoSafety.uiEnabled(Map.of(
            "TESTRUN_E2E_ENABLED", "true",
            "TESTRUN_ENVIRONMENT", "isolated-test"
        )));
        assertFalse(DemoSafety.uiEnabled(Map.of(
            "TESTRUN_E2E_ENABLED", "TRUE",
            "TESTRUN_ENVIRONMENT", "isolated-test"
        )));
    }

    @Test
    void apiTestRequiresAllExplicitCredentialsAndIds() {
        Map<String, String> valid = Map.of(
            "TESTRUN_ENVIRONMENT", "isolated-test",
            "TESTRUN_API_TEST_ENABLED", "true",
            "TESTRUN_BASE_URL", "http://127.0.0.1:15052",
            "TESTRUN_API_TOKEN", "test-only-token",
            "TESTRUN_TEST_CASE_ID", "12",
            "TESTRUN_DATA_SET_ID", "34"
        );
        assertTrue(DemoSafety.apiEnabled(valid));

        assertFalse(DemoSafety.apiEnabled(Map.of(
            "TESTRUN_E2E_ENABLED", "true",
            "TESTRUN_ENVIRONMENT", "isolated-test",
            "TESTRUN_BASE_URL", "http://127.0.0.1:15052",
            "TESTRUN_TEST_CASE_ID", "12",
            "TESTRUN_DATA_SET_ID", "34"
        )));
    }

    @Test
    void apiTestRejectsMalformedIdsAndNonIsolatedEnvironment() {
        Map<String, String> malformed = Map.of(
            "TESTRUN_ENVIRONMENT", "isolated-test",
            "TESTRUN_API_TEST_ENABLED", "true",
            "TESTRUN_BASE_URL", "http://127.0.0.1:15052",
            "TESTRUN_API_TOKEN", "test-only-token",
            "TESTRUN_TEST_CASE_ID", "12; DROP TABLE test_case",
            "TESTRUN_DATA_SET_ID", "34"
        );
        assertFalse(DemoSafety.apiEnabled(malformed));

        Map<String, String> production = Map.of(
            "TESTRUN_ENVIRONMENT", "production",
            "TESTRUN_API_TEST_ENABLED", "true",
            "TESTRUN_BASE_URL", "https://testrun.pro",
            "TESTRUN_API_TOKEN", "token",
            "TESTRUN_TEST_CASE_ID", "12",
            "TESTRUN_DATA_SET_ID", "34"
        );
        assertFalse(DemoSafety.apiEnabled(production));
    }
}
