"""Скрейпер страниц brain.com.ua.

Сайт защищён Cloudflare (managed challenge), поэтому обычный ``requests``
получает заглушку "Just a moment...". Вместо него используется ``curl_cffi``
с имперсонацией браузера Chrome — это проходит проверку TLS-отпечатка и
позволяет получить реальный HTML.
"""

from __future__ import annotations

import time
from typing import Optional

from curl_cffi import requests as curl_requests

DEFAULT_TIMEOUT = 30
DEFAULT_IMPERSONATE = "chrome"
DEFAULT_RETRIES = 3
RETRY_DELAY = 2.0

BROWSER_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6",
    "Cache-Control": "no-cache",
}


class ScraperError(RuntimeError):
    """Не удалось получить HTML страницы."""


def fetch_html(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> str:
    """Загружает HTML страницы и возвращает его как строку.

    Делает несколько попыток с паузой, чтобы пережить периодические
    срабатывания Cloudflare.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            response = curl_requests.get(
                url,
                impersonate=DEFAULT_IMPERSONATE,
                headers=BROWSER_HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()

            html = response.text
            # Признак не пройденной проверки Cloudflare.
            if "Just a moment" in html or "cf_chl_opt" in html:
                raise ScraperError("Cloudflare challenge не пройден")

            return html
        except Exception as exc:  # noqa: BLE001 - нужен общий ретрай
            last_error = exc
            if attempt < retries:
                time.sleep(RETRY_DELAY * attempt)

    raise ScraperError(f"Не удалось загрузить {url}: {last_error}")


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else (
        "https://brain.com.ua/ukr/Mobilniy_telefon_Apple_iPhone_16_Pro_Max_"
        "256GB_Black_Titanium-p1145443.html"
    )
    page = fetch_html(target)
    print(f"Загружено {len(page)} символов с {target}")
