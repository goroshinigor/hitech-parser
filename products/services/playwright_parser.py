"""Парсер brain.com.ua на Playwright (Шаг-1 … Шаг-6).

Что делает:

* Шаг-1 — открывает главную страницу https://brain.com.ua/;
* Шаг-2 — вводит в поисковую строку запрос «Apple iPhone 15 128GB Black»;
* Шаг-3 — нажимает кнопку «Найти»;
* Шаг-4 — кликает первый результат и переходит на карточку товара;
* Шаг-5 — собирает данные товара: HTML карточки разбирает тот же bs4-парсер,
  что и у requests-версии (``hi_parser.parse_product``);
* Шаг-6 — печатает полученные данные.

Запуск как скрипта:

    python -m products.services.playwright_parser
    python -m products.services.playwright_parser "Apple iPhone 15 128GB Black"

Перед живым запуском нужен браузер:

    python -m playwright install chromium

Библиотека ``playwright`` импортируется лениво (внутри методов), поэтому
модуль импортируется даже там, где она не установлена.
"""

from __future__ import annotations

import json
import sys
from types import TracebackType
from typing import List, Optional, Type

from .hi_parser import parse_product, print_product
from .search_flow import (
    DEFAULT_QUERY,
    DEFAULT_TIMEOUT,
    HOME_URL,
    LOCALE,
    PRODUCT_READY,
    RESULT_ITEMS,
    RESULT_TITLE_LINK,
    RESULTS_WAIT,
    SEARCH_INPUT,
    SEARCH_SUBMIT,
    SEARCH_SUBMIT_FALLBACK,
    STEALTH_ARGS,
    STEALTH_SCRIPT,
    TIMEZONE,
    USER_AGENT,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    BrowserFlowError,
    looks_like_challenge,
    search_url,
    validate_product,
)

#: XPath формы, внутри которой лежит найденное поле поиска.
_SEARCH_FORM = "xpath=ancestor::form[1]"


class PlaywrightSearchParser:
    """Шаги 1-6 на Playwright.

    Браузер запускается лениво при первом обращении к :attr:`page` и
    закрывается методом :meth:`close` (или выходом из ``with``). Готовую
    страницу можно передать в конструктор — так парсер тестируется без
    браузера.
    """

    def __init__(
        self,
        query: str = DEFAULT_QUERY,
        headless: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
        page=None,
    ) -> None:
        self.query = query
        self.headless = headless
        self.timeout = timeout
        self._last_query: Optional[str] = None
        self._page = page
        self._owns_page = page is None
        self._playwright = None
        self._browser = None
        self._context = None

    # ------------------------------------------------------------------ #
    # Инфраструктура
    # ------------------------------------------------------------------ #
    @property
    def timeout_ms(self) -> int:
        """Таймауты Playwright задаются в миллисекундах."""
        return self.timeout * 1000

    def _start_browser(self):
        """Запускает Chromium с настройками, проходящими Cloudflare."""
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless, args=list(STEALTH_ARGS)
        )
        self._context = self._new_context()
        self._page = self._context.new_page()
        return self._page

    def _new_context(self):
        """Новый контекст браузера: своя «сессия» (cookie, кэш) и своя страница."""
        context = self._browser.new_context(
            locale=LOCALE,
            timezone_id=TIMEZONE,
            viewport={"width": WINDOW_WIDTH, "height": WINDOW_HEIGHT},
            user_agent=USER_AGENT,
        )
        # Убираем navigator.webdriver: без этого Cloudflare не пускает headless.
        context.add_init_script(STEALTH_SCRIPT)
        context.set_default_timeout(self.timeout_ms)
        return context

    @property
    def page(self):
        """Страница Playwright (браузер стартует лениво)."""
        if self._page is None:
            self._page = self._start_browser()
        return self._page

    def close(self) -> None:
        """Закрывает браузер, если парсер его сам запустил."""
        if not self._owns_page:
            return
        for closer in (self._context, self._browser):
            if closer is not None:
                closer.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._page = self._context = self._browser = self._playwright = None

    def __enter__(self) -> "PlaywrightSearchParser":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Шаг-1 … Шаг-4
    # ------------------------------------------------------------------ #
    def open_home(self) -> str:
        """Шаг-1: открывает главную страницу и дожидается формы поиска."""
        self.page.goto(HOME_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        try:
            # Ждём появления поля в DOM (state="attached"): форм поиска две, и
            # первая (мобильная) скрыта, поэтому ожидание видимого элемента по
            # умолчанию упиралось бы в таймаут. Видимое поле выбирает
            # ``_visible_search_input``.
            self.page.wait_for_selector(
                SEARCH_INPUT, state="attached", timeout=self.timeout_ms
            )
            self._visible_search_input()
        except BrowserFlowError:
            raise
        except Exception as exc:  # noqa: BLE001
            if looks_like_challenge(self.page.content()):
                raise BrowserFlowError(
                    "Cloudflare показал челлендж вместо главной страницы"
                ) from exc
            raise
        return self.page.url

    def _visible_search_input(self):
        """Первое видимое поле поиска (форм на странице две)."""
        fields = self.page.locator(SEARCH_INPUT)
        for index in range(fields.count()):
            field = fields.nth(index)
            if field.is_visible():
                return field
        raise BrowserFlowError(
            f"не найдено видимое поле поиска ({SEARCH_INPUT}) — "
            "возможно, Cloudflare не пустил на главную страницу"
        )

    def _reset_session(self) -> None:
        """Сбрасывает cookie сессии перед следующим переходом.

        Cloudflare на этом сайте отдаёт челлендж на любую навигацию, кроме
        первой: браузер получает cookie, помечающую сессию, и следующий переход
        блокируется. Без cookie каждый переход снова выглядит «свежим» и
        проходит (проверено живым прогоном).
        """
        context = self._context or getattr(self.page, "context", None)
        if context is None:  # pragma: no cover - страница без контекста
            return
        try:
            context.clear_cookies()
        except Exception:  # noqa: BLE001 - сброс cookie не критичен
            pass

    def restart(self) -> None:
        """Начинает новую сессию браузера (Шаг-4).

        Cloudflare на этом сайте отдаёт челлендж на третью навигацию в сессии, а
        первая навигация свежего контекста всегда проходит: в нём нет ни cookie,
        ни следов предыдущих переходов. Чужую страницу (переданную в
        конструктор) пересоздавать нельзя — тогда просто чистим cookie.
        """
        if not self._owns_page:
            self._reset_session()
            return
        if self._browser is None:  # браузер ещё не запускали — перезапускать нечего
            self._page = None
            return
        if self._context is not None:
            self._context.close()
        self._context = self._new_context()
        self._page = self._context.new_page()

    def _wait_card(self, timeout: Optional[int] = None) -> None:
        """Ждёт, что открылась карточка товара, а не челлендж Cloudflare.

        Признак — блок характеристик (``PRODUCT_READY``): на странице челленджа
        его нет, хотя ``h1`` («Just a moment...») есть.
        """
        self.page.locator(PRODUCT_READY).first.wait_for(
            state="attached", timeout=(timeout or self.timeout) * 1000
        )

    def search(self, query: Optional[str] = None) -> str:
        """Шаг-2 и Шаг-3: вводит запрос и нажимает кнопку «Найти»."""
        query = query or self.query
        self._last_query = query
        field = self._visible_search_input()
        field.click()
        field.fill(query)

        submit = field.locator(_SEARCH_FORM).locator(SEARCH_SUBMIT)
        button = (
            submit.first
            if submit.count()
            else self.page.locator(SEARCH_SUBMIT_FALLBACK).first
        )
        self._reset_session()  # переход на страницу результатов = вторая навигация
        try:
            button.click()
        except Exception:  # noqa: BLE001 - кнопка не сработала, пробуем Enter
            field.press("Enter")
        return query

    def open_results_page(self, query: Optional[str] = None) -> str:
        """Страховка для Шага-3: открывает страницу результатов по адресу."""
        self._reset_session()
        self.page.goto(
            search_url(query or self._last_query or self.query),
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        return self.page.url

    def open_first_result(self, wait: Optional[int] = None) -> str:
        """Шаг-4: кликает первый результат и возвращает URL карточки товара.

        ``wait`` — сколько секунд ждать список результатов и загрузку карточки
        (по умолчанию ``self.timeout``). Короткое ожидание на первой попытке
        нужно, чтобы быстро перейти к страховке, если Cloudflare отдал челлендж.
        """
        try:
            self.page.locator(RESULT_ITEMS).first.wait_for(
                state="visible", timeout=(wait or self.timeout) * 1000
            )
        except Exception as exc:  # noqa: BLE001
            raise BrowserFlowError(
                f"результаты поиска не появились ({RESULT_ITEMS}) — "
                "возможно, изменилась разметка или Cloudflare не пустил на сайт"
            ) from exc

        link = self.page.locator(f"{RESULT_ITEMS} {RESULT_TITLE_LINK}").first
        url = link.get_attribute("href") or ""
        # Ссылка в карточке скрыта до наведения, поэтому клик «силой»; перед
        # переходом на карточку товара сбрасываем cookie (третья навигация).
        try:
            self._reset_session()
            link.click(force=True)
            self._wait_card(wait)
            return self.page.url or url
        except Exception:  # noqa: BLE001 - челлендж или клик не сработал
            pass

        # Челлендж Cloudflare: открываем адрес карточки в свежей сессии — её
        # первая навигация проходит без проверки.
        self.restart()
        self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self._wait_card()
        return self.page.url or url

    # ------------------------------------------------------------------ #
    # Шаг-5 и Шаг-6
    # ------------------------------------------------------------------ #
    def collect(self) -> dict:
        """Шаги 1-5: поиск товара и сбор данных (без печати)."""
        self.open_home()
        self.search()
        try:
            url = self.open_first_result(wait=RESULTS_WAIT)
        except BrowserFlowError:
            # Список результатов не отрисовался — открываем его адрес напрямую.
            self.open_results_page()
            url = self.open_first_result()
        return validate_product(parse_product(self.page.content(), url))

    def run(self) -> dict:
        """Все шаги: ищет товар, печатает данные (Шаг-6) и возвращает словарь."""
        try:
            data = self.collect()
        finally:
            self.close()
        print_product(data)
        return data


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: ``python -m products.services.playwright_parser [запрос]``."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    query = arguments[0] if arguments else DEFAULT_QUERY

    parser = PlaywrightSearchParser(query=query)
    try:
        data = parser.collect()
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        parser.close()

    # Шаг-6: печать полученных данных.
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - ручной запуск
    raise SystemExit(main())

