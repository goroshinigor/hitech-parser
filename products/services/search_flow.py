"""Общие шаги поиска товара на brain.com.ua (Шаг-1 … Шаг-4).

Модуль не зависит ни от Selenium, ни от Playwright: здесь собраны адрес сайта,
поисковый запрос, селекторы и настройки маскировки, которые используют оба
браузерных парсера — ``selenium_parser`` и ``playwright_parser``.

Шаги из задания:

* Шаг-1 — открыть главную страницу https://brain.com.ua/;
* Шаг-2 — ввести в поисковую строку запрос;
* Шаг-3 — нажать кнопку «Найти»;
* Шаг-4 — кликнуть первый результат и перейти на карточку товара.

Селекторы проверены на живой разметке сайта (см. README, раздел «Селекторы»).
"""

from __future__ import annotations

from urllib.parse import quote_plus

HOME_URL = "https://brain.com.ua/"
DEFAULT_QUERY = "Apple iPhone 15 128GB Black"
DEFAULT_TIMEOUT = 60

#: Результаты поиска можно открыть и напрямую (без формы в шапке). Используется
#: как страховка: если JS-поиск не отрисовал список, парсер открывает этот адрес.
SEARCH_URL = "https://brain.com.ua/ukr/search/?Search={query}"

#: Сколько секунд ждать список результатов на первой попытке. Cloudflare на
#: этом сайте отдаёт челлендж на любую вторую навигацию в сессии, поэтому
#: короткое первое ожидание позволяет быстро перейти к страховке (сброс cookie
#: + прямой адрес поиска), не выжидая полный ``timeout``.
RESULTS_WAIT = 15

#: Шаг-2/Шаг-3. На странице две одинаковые формы поиска (десктопная и
#: мобильная), причём одна из них скрыта, поэтому поле ищем среди всех
#: совпадений и берём первое видимое, а кнопку «Найти» — внутри формы этого поля.
SEARCH_INPUT = ".quick-search-input"
SEARCH_SUBMIT = "input[type=submit]"
SEARCH_SUBMIT_FALLBACK = ".search-button-first-form"

#: Шаг-4. Результаты поиска: карточка списка и ссылка с названием товара.
RESULT_ITEMS = ".search-wrapper .goods-block__item"
RESULT_TITLE_LINK = ".br-pp-ipd-shown a[href]"

#: Шаг-5. Признак того, что открылась именно карточка товара.
PRODUCT_TITLE = "h1"

#: Признаки челленджа Cloudflare: если они в разметке, страница не открылась.
CHALLENGE_MARKERS = ("Just a moment", "cf_chl_opt")

#: Реальный User-Agent: в headless-браузере по умолчанию он содержит
#: «HeadlessChrome», и Cloudflare сразу отдаёт 403 / челлендж.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)

#: Скрываем признак автоматизации — Cloudflare ориентируется на него.
STEALTH_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)

#: Аргументы запуска Chromium (без них headless-браузер получает челлендж).
STEALTH_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
)

WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900
LOCALE = "uk-UA"
TIMEZONE = "Europe/Kyiv"


class BrowserFlowError(RuntimeError):
    """Не удалось выполнить шаги поиска в браузере."""


def search_url(query: str) -> str:
    """Прямой адрес страницы результатов поиска для запроса."""
    return SEARCH_URL.format(query=quote_plus(query))


def looks_like_challenge(html: str) -> bool:
    """Похоже ли, что вместо страницы пришла проверка Cloudflare."""
    return any(marker in html for marker in CHALLENGE_MARKERS)


def validate_product(data: dict) -> dict:
    """Проверяет, что карточка товара действительно распарсилась.

    Если браузер всё-таки уткнулся в Cloudflare или результат поиска открылся
    не тот, данные будут пустыми — тогда лучше упасть с понятной ошибкой.
    """
    if not data.get("name"):
        raise BrowserFlowError(
            "не удалось прочитать название товара: страница карточки пустая "
            "или закрыта проверкой Cloudflare"
        )
    if not data.get("characteristics"):
        raise BrowserFlowError(
            "не удалось прочитать характеристики товара: изменилась разметка "
            "карточки или страница не догрузилась"
        )
    return data
