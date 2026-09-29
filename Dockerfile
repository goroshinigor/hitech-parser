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

COPY . .
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]