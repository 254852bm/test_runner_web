# 🤖 Автоматизация тестов через Selenium

Это руководство для тех, кто **никогда раньше не писал авто-тесты**. Мы пройдём весь путь шаг за шагом: от установки Python до запуска первого теста, который отправит результат в TestRun.

---

## 📖 Оглавление

1. Что такое Selenium и зачем он нужен
2. Что мы будем делать
3. Что понадобится
4. Шаг 1. Устанавливаем Python
5. Шаг 2. Устанавливаем Chrome
6. Шаг 3. Скачиваем ChromeDriver
7. Шаг 4. Создаём папку для тестов
8. Шаг 5. Устанавливаем библиотеки Python
9. Шаг 6. Создаём API-токен в TestRun
10. Шаг 7. Узнаём ID тест-кейса
11. Шаг 8. Пишем первый тест
12. Шаг 9. Запускаем и проверяем
13. Шаг 10. Смотрим результат в TestRun
14. Как писать свои тесты
15. Частые ошибки
16. Что дальше

---

## 1. Что такое Selenium и зачем он нужен

**Selenium** — это программа, которая управляет браузером программно. Ты пишешь код — он открывает Chrome, кликает кнопки, вводит текст. Как робот за браузером.

**Зачем это нужно:**

- Один раз написал тест → запускаешь его 100 раз → экономишь часы.
- Запускаешь регрессию за 5 минут вместо 5 часов.
- Не забываешь проверить — робот делает всё по чек-листу.

**Как это связано с TestRun:** тест-скрипт после выполнения отправляет результат в TestRun. Ты видишь все прогоны — и ручные, и авто — в одном месте.

---

## 2. Что мы будем делать

Мы напишем тест, который:

1. Откроет **Saucedemo** (тестовый интернет-магазин).
2. Введёт логин `standard_user` и пароль `secret_sauce`.
3. Нажмёт «Login».
4. Проверит, что открылась главная страница.
5. Отправит результат в TestRun через API.

Результат появится в истории твоего проекта с меткой **🤖 auto**.

---

## 3. Что понадобится

- **Компьютер** (Windows, macOS, Linux — любой).
- **Интернет.**
- **~30 минут времени.**
- **Аккаунт в TestRun** (зарегистрируйся на https://testrun.pro).

---

## 4. Шаг 1. Устанавливаем Python

Python — это язык программирования, на котором мы будем писать тест.

1. Скачай Python с [python.org/downloads](https://www.python.org/downloads/).
2. Запусти установщик.
3. **Обязательно поставь галочку** `Add Python to PATH` (внизу первого экрана).
4. Нажми `Install Now`.
5. После установки открой **PowerShell** (или Git Bash) и проверь команду `python --version`.

Должно показать `Python 3.12.x` или похожее. Если ошибка — переустанови Python с галочкой.

---

## 5. Шаг 2. Устанавливаем Chrome

Если у тебя уже стоит Chrome — пропусти этот шаг.

1. Скачай Chrome с [google.com/chrome](https://www.google.com/chrome/).
2. Установи.
3. **Запомни версию:** открой Chrome → три точки → Справка → О Google Chrome.

Первые две цифры понадобятся дальше.

---

## 6. Шаг 3. Скачиваем ChromeDriver

**ChromeDriver** — это «переходник» между Python-кодом и браузером Chrome.

1. Открой [googlechromelabs.github.io/chrome-for-testing](https://googlechromelabs.github.io/chrome-for-testing/).
2. Найди раздел **Stable** — версия должна совпадать с твоим Chrome.
3. В списке файлов найди **chromedriver** → **win64** (для Windows) → скачай ZIP.
4. Распакуй ZIP → внутри будет `chromedriver.exe`.
5. Положи его в папку для тестов (создадим её в следующем шаге).

---

## 7. Шаг 4. Создаём папку для тестов

1. На рабочем столе создай папку `selenium_tests`.
2. Перетащи туда `chromedriver.exe`.
3. Проверь, что ChromeDriver работает: открой PowerShell в этой папке и введи команду `.\chromedriver.exe --version`.

Должно показать `ChromeDriver 154.0.8037.92`.

---

## 8. Шаг 5. Устанавливаем библиотеки Python

Открой PowerShell в папке `selenium_tests` и выполни команду `pip install selenium requests`.

Ждём `Successfully installed selenium-... requests-...`.

Если `pip` не найден — попробуй `python -m pip install selenium requests`.

---

## 9. Шаг 6. Создаём API-токен в TestRun

1. Открой https://testrun.pro/settings/api
2. Введи название токена (например, `Selenium — мой компьютер`).
3. Нажми **«+ Создать токен»**.
4. Скопируй токен — он больше не покажется.

**Что такое токен:** это ключ доступа. Скрипт с этим токеном может писать результаты только в **твои** проекты.

---

## 10. Шаг 7. Узнаём ID тест-кейса

ID — это число, которое идентифицирует конкретный тест в TestRun.

**Как найти ID:**

1. Открой проект в TestRun.
2. Зайди в нужный тест-кейс.
3. Посмотри на URL в браузере — там будет что-то вроде `/test/6`. Число `6` — это ID.

---

## 11. Шаг 8. Пишем первый тест

1. В папке `selenium_tests` создай файл `test_login.py`.
2. Открой его в VS Code.
3. Скопируй код из `docs/examples/selenium_test_login.py`.
4. **Замени:**
   - `API_TOKEN` — на свой токен из TestRun.
   - `TEST_CASE_ID` — на ID своего теста.

**Пример:**

- `API_TOKEN = "OoeXXX8ToNFOje3cz3ZSSdG1AllvqOQrX51QHzB2uRnV3GRiLIw9JjMXW5hyG9kg"`
- `TEST_CASE_ID = 6`

---

## 12. Шаг 9. Запускаем и проверяем

В PowerShell (в папке `selenium_tests`) выполни команду `python test_login.py`.

**Что должно произойти:**

1. Откроется Chrome (управляемый роботом).
2. Перейдёт на Saucedemo.
3. Введёт логин/пароль, нажмёт «Login».
4. Проверит, что открылась главная.
5. Chrome закроется.
6. В терминале появится ответ TestRun с `ok: true`.

**Пример вывода:**

```
Шаг 1: логин введён
Шаг 2: пароль введён
Шаг 3: главная открыта

Отправляю результат в TestRun...
Ответ TestRun: {'ok': True, 'run_id': 48, 'status': 'PASS', 'test_case_id': 6}
```

---

## 13. Шаг 10. Смотрим результат в TestRun

1. Открой TestRun → свой проект.
2. Нажми **📜 История**.
3. В самом верху — новая запись со статусом «Пройден».
4. Рядом с ней — метка **🤖 auto**.

**Поздравляю!** Ты автоматизировал(а) свой первый тест. 🎉

---

## 14. Как писать свои тесты

### Локаторы: как найти элемент на странице

**По ID (самый надёжный):**

```
driver.find_element(By.ID, "login-button")
```

**По CSS-селектору:**

```
driver.find_element(By.CSS_SELECTOR, "button.submit")
```

**По XPath (медленнее, но гибкий):**

```
driver.find_element(By.XPATH, "//button[text()='Войти']")
```

**Как найти локатор:** открой страницу в Chrome → F12 → правой кнопкой на элементе → «Inspect» (Исследовать) → посмотри на `id`, `class`, `name`.

### Ожидания (waits): обязательно

**Никогда не используй `time.sleep`** — это плохо. Используй `WebDriverWait`:

```
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.ID, "user-name"))
)
```

Это подождёт до 10 секунд, пока элемент не появится. Если появится раньше — сразу продолжит.

### Обработка ошибок

Всегда оборачивай тест в `try/except/finally`:

```
try:
    # шаги теста
    pass
except Exception as e:
    status = "FAIL"
    comment = str(e)
finally:
    driver.quit()  # браузер закроется всегда
```

### Отправка результата

В `step_results` указывай `step_id` — ID шага из TestRun. Узнать можно в БД командой:

```
sqlite3 instance/test_runner.db "SELECT id, position, action FROM test_step WHERE test_case_id = 6;"
```

**Пример:**

```
step_results.append({
    "step_id": 1,
    "status": "PASS",
    "actual_result": "Логин введён"
})
```

---

## 15. Частые ошибки

### `chromedriver executable needs to be in PATH`

**Причина:** ChromeDriver не найден.

**Решение:** убедись, что `chromedriver.exe` лежит рядом с `test_login.py`.

### `This version of ChromeDriver only supports Chrome version XX`

**Причина:** версия ChromeDriver не совпадает с Chrome.

**Решение:** скачай ChromeDriver той же версии (первые 2 цифры).

### `TimeoutException: Message: timeout`

**Причина:** элемент не появился на странице за 10 секунд.

**Решение:** увеличь таймаут или проверь локатор через F12.

### `requests.exceptions.ConnectionError`

**Причина:** нет доступа к `testrun.pro`.

**Решение:** открой сайт в браузере, проверь интернет.

### `{"ok": false, "error": "Неверный или отсутствующий API-токен"}`

**Причина:** токен неправильный или отозван.

**Решение:** создай новый токен в `/settings/api`.

### Chrome не закрывается автоматически

**Причина:** упало исключение до `finally`.

**Решение:** проверь логи, добавь `driver.quit()` в `finally`.

---

## 16. Что дальше

### Ближайшее

- Написать 5–10 тестов на Saucedemo (логин, корзина, checkout).
- Запустить их вместе — один скрипт, много тестов.

### Автоматизация

- **Расписание:** запускать скрипты по cron (Linux) или Task Scheduler (Windows).
- **CI/CD:** автозапуск тестов после коммита в Git (GitHub Actions).
- **Selenium Grid:** параллельный запуск в нескольких браузерах.

### Документация Selenium

- [Selenium Python Docs](https://selenium-python.readthedocs.io/)
- [Sauce Labs Docs](https://docs.saucelabs.com/)

---

## 📬 Поддержка

Если что-то не работает — пиши:

- **GitHub Issues:** [github.com/254852bm/test_runner_web/issues](https://github.com/254852bm/test_runner_web/issues)
- **Email:** 254852bm@users.noreply.github.com