package pro.testrun.demo;

import java.util.Map;

/**
 * Fail-closed environment checks for integration tests.
 * These checks are deliberately pure so CI can exercise them without a server.
 */
public final class DemoSafety {
    private DemoSafety() {}

    public static boolean uiEnabled(Map<String, String> env) {
        return "true".equals(env.get("TESTRUN_E2E_ENABLED"))
            && "isolated-test".equals(env.get("TESTRUN_ENVIRONMENT"));
    }

    public static boolean apiEnabled(Map<String, String> env) {
        return uiEnabled(env)
            && present(env, "TESTRUN_BASE_URL")
            && present(env, "TESTRUN_API_TOKEN")
            && digits(env, "TESTRUN_TEST_CASE_ID")
            && digits(env, "TESTRUN_DATA_SET_ID");
    }

    public static boolean uiEnabledFromEnvironment() {
        return uiEnabled(System.getenv());
    }

    public static boolean apiEnabledFromEnvironment() {
        return apiEnabled(System.getenv());
    }

    private static boolean present(Map<String, String> env, String key) {
        String value = env.get(key);
        return value != null && !value.isBlank();
    }

    private static boolean digits(Map<String, String> env, String key) {
        String value = env.get(key);
        return value != null && value.matches("\\d+");
    }
}
