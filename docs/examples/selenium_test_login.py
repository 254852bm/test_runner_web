"""
Пример Selenium-теста, который отправляет результат в TestRun.

Что делает:
1. Открывает Saucedemo (тестовый интернет-магазин).
2. Вводит логин и пароль.
3. Нажимает «Login».
4. Проверяет, что открылась главная страница.
5. Отправляет результат в TestRun через API.

Перед запуском:
- Замени API_TOKEN на свой токен (создаётся на /settings/api).
- Замени TEST_CASE_ID на ID теста из твоего проекта.
- Установи selenium и requests: pip install selenium requests
- Скачай ChromeDriver под свою версию Chrome.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
import time

# ===== НАСТРОЙКИ (ЗАМЕНИ НА СВОИ) =====
TESTRUN_URL = "https://testrun.pro/api/run"
API_TOKEN = "ВСТАВЬ_СВОЙ_API_ТОКЕН_ЗДЕСЬ"
TEST_CASE_ID = 6   # ID теста из твоего проекта

# ===== ЗАПУСК =====
driver = webdriver.Chrome()
start_time = time.time()
status = "PASS"
comment = ""
step_results = []

try:
    # Шаг 1: Ввести логин
    driver.get("https://www.saucedemo.com/")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "user-name"))
    )
    driver.find_element(By.ID, "user-name").send_keys("standard_user")
    step_results.append({
        "step_id": 1,
        "status": "PASS",
        "actual_result": "Логин введён"
    })
    print("Шаг 1: логин введён")

    # Шаг 2: Ввести пароль
    driver.find_element(By.ID, "password").send_keys("secret_sauce")
    step_results.append({
        "step_id": 2,
        "status": "PASS",
        "actual_result": "Пароль введён"
    })
    print("Шаг 2: пароль введён")

    # Шаг 3: Нажать Войти
    driver.find_element(By.ID, "login-button").click()
    WebDriverWait(driver, 10).until(EC.url_contains("/inventory.html"))
    step_results.append({
        "step_id": 3,
        "status": "PASS",
        "actual_result": "Главная открыта"
    })
    print("Шаг 3: главная открыта")

except Exception as e:
    status = "FAIL"
    comment = str(e)
    step_results.append({
        "step_id": 3,
        "status": "FAIL",
        "actual_result": str(e)[:200]
    })
    print(f"Ошибка: {e}")

finally:
    driver.quit()
    duration_ms = int((time.time() - start_time) * 1000)

    # ===== ОТПРАВКА РЕЗУЛЬТАТА В TESTRUN =====
    print("\nОтправляю результат в TestRun...")
    try:
        response = requests.post(TESTRUN_URL, json={
            "token": API_TOKEN,
            "test_case_id": TEST_CASE_ID,
            "status": status,
            "comment": comment,
            "duration_ms": duration_ms,
            "step_results": step_results
        }, timeout=15)
        print(f"Ответ TestRun: {response.json()}")
    except Exception as e:
        print(f"Не удалось отправить в TestRun: {e}")
