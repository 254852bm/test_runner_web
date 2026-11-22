package pro.testrun.demo;

import java.net.URI;
import java.util.Map;

/**
 * Fail-closed environment checks for integration tests.
 * These checks are deliberately pure so CI can exercise them without a server.
 */
public final class DemoSafety {
    private DemoSafety() {}

    public static boolean uiEnabled(Map<String, String> env) {
        return "true".equals(env.get("TESTRUN_E2E_ENABLED"))
            && "isolated-test".equals(env.get("TESTRUN_ENVIRONMENT"))
            && loopbackBaseUrl(env);
    }

    public static boolean apiEnabled(Map<String, String> env) {
        return "true".equals(env.get("TESTRUN_API_TEST_ENABLED"))
            && "isolated-test".equals(env.get("TESTRUN_ENVIRONMENT"))
            && loopbackBaseUrl(env)
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

    private static boolean loopbackBaseUrl(Map<String, String> env) {
        String value = env.get("TESTRUN_BASE_URL");
        if (value == null || value.isBlank()) return false;
        try {
            URI uri = URI.create(value);
            String host = uri.getHost();
            return ("http".equalsIgnoreCase(uri.getScheme())
                    || "https".equalsIgnoreCase(uri.getScheme()))
                && host != null
                && (host.equalsIgnoreCase("localhost")
                    || host.equals("127.0.0.1")
                    || host.equals("::1"));
        } catch (IllegalArgumentException error) {
            return false;
        }
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
