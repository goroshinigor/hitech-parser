"""Парсер brain.com.ua на Selenium (Шаг-1 … Шаг-6).

Что делает:

* Шаг-1 — открывает главную страницу https://brain.com.ua/;
* Шаг-2 — вводит в поисковую строку запрос «Apple iPhone 15 128GB Black»;
* Шаг-3 — нажимает кнопку «Найти»;
* Шаг-4 — кликает первый результат и переходит на карточку товара;
* Шаг-5 — собирает данные товара: HTML карточки разбирает тот же bs4-парсер,
  что и у requests-версии (``hi_parser.parse_product``);
* Шаг-6 — печатает полученные данные.

Запуск как скрипта:

    python -m products.services.selenium_parser
    python -m products.services.selenium_parser "Apple iPhone 15 128GB Black"

Живьём нужен Chrome/Chromium: chromedriver Selenium подбирает сам
(Selenium Manager). Если браузер лежит в нестандартном месте, путь можно
передать в ``browser_binary`` (у CLI — ``--chrome-binary``).

Библиотека ``selenium`` импортируется лениво (внутри методов), поэтому модуль
импортируется даже там, где браузерные библиотеки не установлены.
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
    PRODUCT_TITLE,
    RESULT_ITEMS,
    RESULT_TITLE_LINK,
    RESULTS_WAIT,
    SEARCH_INPUT,
    SEARCH_SUBMIT,
    SEARCH_SUBMIT_FALLBACK,
    STEALTH_ARGS,
    STEALTH_SCRIPT,
    USER_AGENT,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    BrowserFlowError,
    looks_like_challenge,
    search_url,
    validate_product,
)


def _css_selector() -> str:
    """``By.CSS_SELECTOR`` (импорт selenium — ленивый)."""
    from selenium.webdriver.common.by import By

    return By.CSS_SELECTOR


class SeleniumSearchParser:
    """Шаги 1-6 на Selenium.

    Драйвер создаётся при первом обращении к :attr:`driver` и закрывается
    методом :meth:`close` (или выходом из ``with``). Готовый драйвер можно
    передать в конструктор — так парсер тестируется без браузера.
    """

    def __init__(
        self,
        query: str = DEFAULT_QUERY,
        headless: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
        driver=None,
        browser_binary: Optional[str] = None,
    ) -> None:
        self.query = query
        self.headless = headless
        self.timeout = timeout
        self.browser_binary = browser_binary
        self._last_query: Optional[str] = None
        self._driver = driver
        self._owns_driver = driver is None

    # ------------------------------------------------------------------ #
    # Инфраструктура
    # ------------------------------------------------------------------ #
    def _create_driver(self):
        """Запускает Chrome/Chromium с настройками, проходящими Cloudflare."""
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        for argument in STEALTH_ARGS:
            options.add_argument(argument)
        options.add_argument(f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}")
        options.add_argument(f"--user-agent={USER_AGENT}")
        options.add_argument(f"--lang={LOCALE}")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        if self.browser_binary:
            options.binary_location = self.browser_binary

        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(self.timeout)
        # Убираем navigator.webdriver: без этого Cloudflare не пускает headless.
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument", {"source": STEALTH_SCRIPT}
        )
        return driver

    @property
    def driver(self):
        """Драйвер Selenium (создаётся лениво)."""
        if self._driver is None:
            self._driver = self._create_driver()
        return self._driver

    def close(self) -> None:
        """Закрывает браузер, если парсер его сам запустил."""
        if self._owns_driver and self._driver is not None:
            self._driver.quit()
            self._driver = None

    def __enter__(self) -> "SeleniumSearchParser":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.close()


    # ------------------------------------------------------------------ #
    # Вспомогательные шаги
    # ------------------------------------------------------------------ #
    def _wait(self, condition, timeout: Optional[int] = None):
        """Ждёт выполнения условия Selenium (по умолчанию до ``timeout``)."""
        from selenium.webdriver.support.ui import WebDriverWait

        return WebDriverWait(self.driver, timeout or self.timeout).until(condition)

    def _wait_css(self, css: str, timeout: Optional[int] = None):
        """Ждёт появления кликабельного элемента по CSS-селектору."""
        from selenium.webdriver.support import expected_conditions as conditions

        return self._wait(
            conditions.element_to_be_clickable((_css_selector(), css)), timeout
        )

    def _wait_present(self, css: str):
        """Ждёт появления элемента в DOM (видимость не требуется)."""
        from selenium.webdriver.support import expected_conditions as conditions

        return self._wait(conditions.presence_of_element_located((_css_selector(), css)))

    def _visible_search_input(self):
        """Первое видимое поле поиска (форм на странице две)."""
        elements = self.driver.find_elements(_css_selector(), SEARCH_INPUT)
        for element in elements:
            if element.is_displayed():
                return element
        raise BrowserFlowError(
            f"не найдено видимое поле поиска ({SEARCH_INPUT}) — "
            "возможно, Cloudflare не пустил на главную страницу"
        )

    def _submit_button(self, field):
        """Кнопка «Найти» внутри формы поискового поля."""
        buttons = field.find_elements(_css_selector(), SEARCH_SUBMIT)
        if buttons:
            return buttons[0]
        return self._wait_css(SEARCH_SUBMIT_FALLBACK)

    # ------------------------------------------------------------------ #
    # Шаг-1 … Шаг-4
    # ------------------------------------------------------------------ #
    def _reset_session(self) -> None:
        """Сбрасывает cookie сессии перед следующим переходом.

        Cloudflare на этом сайте отдаёт челлендж на любую навигацию, кроме
        первой: браузер получает cookie, помечающую сессию, и следующий переход
        блокируется. Без cookie каждый переход снова выглядит «свежим» и
        проходит (проверено живым прогоном).
        """
        try:
            self.driver.delete_all_cookies()
        except Exception:  # noqa: BLE001 - сброс cookie не критичен
            pass

    def open_home(self) -> str:
        """Шаг-1: открывает главную страницу и дожидается формы поиска."""
        self.driver.get(HOME_URL)
        try:
            # Поле поиска ждём в DOM: форм на странице две, и первая (мобильная)
            # скрыта, поэтому «кликабельного» элемента можно не дождаться.
            # Видимое поле выбирает ``_visible_search_input``.
            self._wait_present(SEARCH_INPUT)
            self._visible_search_input()
        except BrowserFlowError:
            raise
        except Exception as exc:  # noqa: BLE001
            if looks_like_challenge(self.driver.page_source or ""):
                raise BrowserFlowError(
                    "Cloudflare показал челлендж вместо главной страницы"
                ) from exc
            raise
        return self.driver.current_url

    def search(self, query: Optional[str] = None) -> str:
        """Шаг-2 и Шаг-3: вводит запрос и нажимает кнопку «Найти»."""
        query = query or self.query
        self._last_query = query
        field = self._visible_search_input()
        field.click()
        field.clear()
        field.send_keys(query)

        self._reset_session()  # переход на страницу результатов = вторая навигация
        try:
            self._submit_button(field).click()
        except Exception:  # noqa: BLE001 - кнопка не сработала, отправляем Enter
            from selenium.webdriver.common.keys import Keys

            field.send_keys(Keys.ENTER)
        return query

    def open_results_page(self, query: Optional[str] = None) -> str:
        """Страховка для Шага-3: открывает страницу результатов по адресу."""
        address = search_url(query or self._last_query or self.query)
        self._reset_session()
        self.driver.get(address)
        return address

    def open_first_result(self, wait: Optional[int] = None) -> str:
        """Шаг-4: кликает первый результат и возвращает URL карточки товара.

        ``wait`` — сколько секунд ждать список результатов (по умолчанию
        ``self.timeout``). Короткое ожидание на первой попытке нужно, чтобы
        быстро перейти к страховке, если Cloudflare отдал челлендж.
        """
        try:
            self._wait_css(RESULT_ITEMS, wait)
        except Exception as exc:  # noqa: BLE001
            raise BrowserFlowError(
                f"результаты поиска не появились ({RESULT_ITEMS}) — "
                "возможно, изменилась разметка или Cloudflare не пустил на сайт"
            ) from exc

        links = self.driver.find_elements(
            _css_selector(), f"{RESULT_ITEMS} {RESULT_TITLE_LINK}"
        )
        if not links:
            raise BrowserFlowError(
                f"в результатах поиска нет ссылок на товары ({RESULT_ITEMS})"
            )

        link = links[0]
        url = link.get_attribute("href") or ""
        # Ссылка в карточке скрыта до наведения, поэтому клик через JS; перед
        # переходом на карточку товара сбрасываем cookie (третья навигация).
        self._reset_session()
        try:
            self.driver.execute_script("arguments[0].click()", link)
            self._wait_css(PRODUCT_TITLE)
            return self.driver.current_url or url
        except Exception:  # noqa: BLE001 - клик не сработал, открываем по адресу
            self._reset_session()
            self.driver.get(url)
            return self.driver.current_url or url

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
        return validate_product(parse_product(self.driver.page_source, url))

    def run(self) -> dict:
        """Все шаги: ищет товар, печатает данные (Шаг-6) и возвращает словарь."""
        try:
            data = self.collect()
        finally:
            self.close()
        print_product(data)
        return data


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: ``python -m products.services.selenium_parser [запрос]``."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    query = arguments[0] if arguments else DEFAULT_QUERY

    parser = SeleniumSearchParser(query=query)
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
