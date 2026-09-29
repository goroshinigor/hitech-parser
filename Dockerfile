FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Браузер для Selenium/Playwright (нужен для шагов 1-4 через реальный браузер).
# По умолчанию образ остаётся slim; браузер ставится по флагу:
#   docker compose build --build-arg INSTALL_BROWSERS=1
ARG INSTALL_BROWSERS=0
RUN if [ "$INSTALL_BROWSERS" = "1" ]; then \
        python -m playwright install --with-deps chromium; \
    fi

# Selenium Manager скачивает chromedriver сам, но только при запуске и только с
# сетью. Для Selenium берём драйвер к тому же Chromium, что поставил Playwright,
# ещё на этапе сборки — тогда образ работает и без доступа в интернет.
# Если браузеры не ставили, шаг пропускается (см. selenium_parser).
RUN if [ "$INSTALL_BROWSERS" = "1" ]; then \
        CHROME=$(ls -d /root/.cache/ms-playwright/chromium-*/chrome-linux64/chrome | head -n 1); \
        python -c "import sys; from selenium.webdriver.common.selenium_manager import SeleniumManager; print(SeleniumManager().binary_paths(['--browser', 'chrome', '--browser-path', sys.argv[1], '--avoid-browser-download']))" "$CHROME"; \
    fi

COPY . .
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]