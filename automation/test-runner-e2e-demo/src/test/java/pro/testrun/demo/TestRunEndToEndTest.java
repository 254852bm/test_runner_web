package pro.testrun.demo;

import io.qameta.allure.Allure;
import io.qameta.allure.Description;
import io.qameta.allure.Feature;
import io.qameta.allure.Step;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.openqa.selenium.By;
import org.openqa.selenium.OutputType;
import org.openqa.selenium.TakesScreenshot;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.chrome.ChromeDriver;
import org.openqa.selenium.chrome.ChromeOptions;
import org.openqa.selenium.support.ui.ExpectedConditions;
import org.openqa.selenium.support.ui.Select;
import org.openqa.selenium.support.ui.WebDriverWait;

import java.io.ByteArrayInputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.stream.Collectors;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

@Feature("TestRun: сквозной демонстрационный сценарий")
class TestRunEndToEndTest {
    private WebDriver driver;
    private WebDriverWait wait;
    private String baseUrl;
    private String projectName;
    private String testTitle;
    private String projectId;

    @BeforeEach
    void setUp() {
        baseUrl = requiredEnv("TESTRUN_BASE_URL").replaceAll("/+$", "");
        String email = requiredEnv("TESTRUN_DEMO_EMAIL");
        String password = requiredEnv("TESTRUN_DEMO_PASSWORD");

        ChromeOptions options = new ChromeOptions();
        options.addArguments("--window-size=1440,1000", "--disable-dev-shm-usage");
        if (Boolean.parseBoolean(System.getenv().getOrDefault("TESTRUN_HEADLESS", "false"))) {
            options.addArguments("--headless=new", "--no-sandbox");
        }
        driver = new ChromeDriver(options);
        wait = new WebDriverWait(driver, Duration.ofSeconds(20));

        String suffix = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"));
        projectName = "E2E Demo " + suffix;
        testTitle = "Проверка сквозного сценария " + suffix;

        login(email, password);
    }

    @AfterEach
    void tearDown() {
        if (driver != null) {
            try {
                attachScreenshot("Последний экран TestRun");
            } catch (Exception ignored) {
                // A screenshot is diagnostic only; it must not hide the test result.
            }
            driver.quit();
        }
    }

    @Test
    @Description("Создаёт проект и параметризованный тест-кейс, выполняет прогон, проверяет историю и PDF.")
    void fullDemoJourney() {
        createProject();
        createParameterizedTestCase();
        verifySavedTestCaseAndParameters();
        executeManualRun();
        verifyHistoryAndPdf();
        verifyNavigationBackToDashboard();
    }

    @Step("Войти в TestRun под отдельной demo-учётной записью")
    private void login(String email, String password) {
        driver.get(baseUrl + "/login");
        wait.until(ExpectedConditions.visibilityOfElementLocated(By.name("email"))).sendKeys(email);
        driver.findElement(By.name("password")).sendKeys(password);
        driver.findElement(By.xpath("//button[contains(normalize-space(.),'Войти')]")).click();
        wait.until(ExpectedConditions.urlContains("/dashboard"));
        assertTrue(driver.getCurrentUrl().contains("/dashboard"), "После входа должна открыться панель");
    }

    @Step("Создать демонстрационный проект")
    private void createProject() {
        driver.get(baseUrl + "/projects/create");
        wait.until(ExpectedConditions.visibilityOfElementLocated(By.name("name"))).sendKeys(projectName);
        driver.findElement(By.xpath("//button[contains(normalize-space(.),'Создать')]")).click();
        wait.until(ExpectedConditions.urlContains("/project/"));
        assertTrue(driver.getPageSource().contains(projectName), "Название проекта должно отображаться");
        String[] urlParts = driver.getCurrentUrl().split("/");
        for (int i = 0; i < urlParts.length - 1; i++) {
            if ("project".equals(urlParts[i])) {
                projectId = urlParts[i + 1];
                break;
            }
        }
        assertNotNull(projectId, "В адресе должен быть ID проекта");
        assertTrue(projectId.chars().allMatch(Character::isDigit), "ID проекта должен быть числовым");
        attachScreenshot("Создан демонстрационный проект");
    }

    @Step("Создать тест-кейс с предусловием, шагом и параметрами")
    private void createParameterizedTestCase() {
        clickLink("+ Добавить тест");
        wait.until(ExpectedConditions.visibilityOfElementLocated(By.id("title"))).sendKeys(testTitle);
        driver.findElement(By.id("precondition")).sendKeys("Подготовить тестовую среду {{base_url}}");

        driver.findElement(By.id("add-parameter")).click();
        driver.findElement(By.id("add-parameter")).click();
        List<WebElement> rows = driver.findElements(By.cssSelector("#parameters-body tr.parameter-row"));
        assertEquals(2, rows.size(), "Должны быть созданы две строки параметров");

        rows.get(0).findElement(By.cssSelector("[data-role='parameter-key']")).sendKeys("base_url");
        rows.get(0).findElement(By.cssSelector("[data-role='parameter-value']")).sendKeys(baseUrl);
        rows.get(1).findElement(By.cssSelector("[data-role='parameter-key']")).sendKeys("login");
        rows.get(1).findElement(By.cssSelector("[data-role='parameter-value']")).sendKeys("demo-user");

        List<WebElement> actions = driver.findElements(By.cssSelector("textarea[name='step_action[]']"));
        List<WebElement> expected = driver.findElements(By.cssSelector("textarea[name='step_expected[]']"));
        actions.get(0).sendKeys("Выполнить демонстрационную проверку для {{login}}");
        expected.get(0).sendKeys("Тест-кейс доступен для выполнения");

        driver.findElement(By.xpath("//button[contains(normalize-space(.),'Сохранить тест-кейс')]")).click();
        wait.until(d -> d.getCurrentUrl().contains("/project/") && !d.getCurrentUrl().contains("/create_test"));
        assertTrue(driver.getPageSource().contains(testTitle), "Новый тест-кейс должен появиться в проекте");
        attachScreenshot("Создан тест-кейс с параметрами");
    }

    @Step("Проверить сохранённый тест-кейс и его параметры")
    private void verifySavedTestCaseAndParameters() {
        WebElement testItem = wait.until(ExpectedConditions.presenceOfElementLocated(
            By.xpath("//div[contains(@class,'list-group-item')][.//h5[contains(normalize-space(.),'" + testTitle + "')]]")
        ));
        testItem.findElement(By.xpath(".//a[normalize-space()='Открыть']")).click();
        wait.until(ExpectedConditions.visibilityOfElementLocated(By.xpath("//*[contains(normalize-space(.),'" + testTitle + "')]")));
        String page = driver.getPageSource();
        assertTrue(page.contains("base_url"), "Переменная base_url должна сохраниться");
        assertTrue(page.contains("demo-user"), "Обычное значение параметра должно сохраниться");
        attachScreenshot("Сохранённый тест-кейс и параметры");
    }

    @Step("Выполнить ручной прогон и сохранить статус с комментарием")
    private void executeManualRun() {
        driver.findElement(By.xpath("//a[contains(normalize-space(.),'Запустить этот тест')]")).click();
        wait.until(ExpectedConditions.visibilityOfElementLocated(By.cssSelector("select[name='step_status[]']")));
        List<WebElement> statuses = driver.findElements(By.cssSelector("select[name='step_status[]']"));
        assertFalse(statuses.isEmpty(), "В прогоне должен быть хотя бы один шаг");
        for (WebElement status : statuses) {
            new Select(status).selectByValue("PASS");
        }
        List<WebElement> comments = driver.findElements(By.cssSelector("textarea[name='step_comment[]']"));
        if (!comments.isEmpty()) {
            comments.get(0).sendKeys("Автоматическая демонстрационная проверка Selenium");
        }
        driver.findElement(By.xpath("//button[contains(normalize-space(.),'Сохранить результат теста')]")).click();
        wait.until(ExpectedConditions.urlContains("/stats"));
        attachScreenshot("Результат ручного прогона");
    }

    @Step("Проверить историю прогонов и PDF-отчёт")
    private void verifyHistoryAndPdf() throws Exception {
        driver.get(baseUrl + "/project/" + projectId + "/history");
        wait.until(ExpectedConditions.urlContains("/history"));
        String history = driver.getPageSource();
        assertTrue(history.contains(testTitle), "История должна содержать тест-кейс");
        assertTrue(history.contains("Автоматическая демонстрационная проверка Selenium"),
            "Комментарий шага должен сохраниться");
        attachScreenshot("История прогонов");

        String cookieHeader = driver.manage().getCookies().stream()
            .map(cookie -> cookie.getName() + "=" + cookie.getValue())
            .collect(Collectors.joining("; "));
        HttpRequest pdfRequest = HttpRequest.newBuilder(
                URI.create(baseUrl + "/project/" + projectId + "/export_pdf"))
            .header("Cookie", cookieHeader)
            .GET()
            .build();
        HttpResponse<byte[]> pdfResponse = HttpClient.newHttpClient().send(
            pdfRequest, HttpResponse.BodyHandlers.ofByteArray());
        assertEquals(200, pdfResponse.statusCode(), "Экспорт PDF должен вернуть HTTP 200");
        assertTrue(pdfResponse.headers().firstValue("Content-Type").orElse("")
            .toLowerCase().contains("application/pdf"), "Ответ должен иметь PDF content-type");
        assertTrue(pdfResponse.body().length > 5, "PDF не должен быть пустым");
        assertEquals("%PDF-", new String(pdfResponse.body(), 0, 5),
            "Скачанный отчёт должен иметь сигнатуру PDF");
        Allure.addAttachment("PDF-отчёт TestRun", "application/pdf",
            new ByteArrayInputStream(pdfResponse.body()), ".pdf");
    }

    @Step("Вернуться к панели через навигацию")
    private void verifyNavigationBackToDashboard() {
        driver.get(baseUrl + "/dashboard");
        wait.until(ExpectedConditions.urlContains("/dashboard"));
        assertTrue(driver.getPageSource().contains("Панель") || driver.getPageSource().contains("Последние прогоны"));
    }

    private void clickLink(String text) {
        wait.until(ExpectedConditions.elementToBeClickable(
            By.xpath("//a[contains(normalize-space(.),'" + text + "')]")
        )).click();
    }

    private void attachScreenshot(String name) {
        if (driver instanceof TakesScreenshot screenshotDriver) {
            byte[] bytes = screenshotDriver.getScreenshotAs(OutputType.BYTES);
            Allure.addAttachment(name, "image/png", new ByteArrayInputStream(bytes), ".png");
        }
    }

    private static String requiredEnv(String key) {
        String value = System.getenv(key);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("Не задана обязательная переменная окружения: " + key);
        }
        return value;
    }
}
