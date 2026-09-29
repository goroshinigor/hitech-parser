"""Тесты приложения products.

Страница с кнопкой Parse, эндпоинт парсинга, загрузка HTML (``requests`` с
резервом ``curl_cffi``), разбор HTML через ``bs4``, браузерные парсеры
(Selenium и Playwright), команда ``parse_search`` и выгрузка в CSV.
Сеть и браузер не используются: HTTP-клиенты, драйвер и страница браузера
подменяются моками, HTML берётся из фикстуры.
"""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Product
from .services.csv_export import CSV_FIELDS, products_as_csv
from .services.hi_parser import DEFAULT_URL, parse_product
from .services.hi_scraper import ScraperError, fetch_html
from .services.playwright_parser import PlaywrightSearchParser
from .services.search_flow import (
    DEFAULT_QUERY,
    HOME_URL,
    PRODUCT_TITLE,
    RESULT_ITEMS,
    RESULT_TITLE_LINK,
    SEARCH_INPUT,
    BrowserFlowError,
    looks_like_challenge,
    search_url,
    validate_product,
)
from .services.selenium_parser import SeleniumSearchParser

try:  # selenium нужен только этим тестам и стоит в requirements.txt
    from selenium.common.exceptions import (
        NoSuchElementException,
        WebDriverException,
    )
    from selenium.webdriver.common.keys import Keys
except ImportError:  # pragma: no cover - окружение без selenium
    NoSuchElementException = RuntimeError
    WebDriverException = RuntimeError
    Keys = None

#: Ссылка на карточку, которую отдают результаты поиска.
RESULT_URL = (
    "https://brain.com.ua/ukr/Mobilniy_telefon_Apple_iPhone_15_128GB_Black-p1044347.html"
)


PARSED_PRODUCT = {
    "url": "https://brain.com.ua/ukr/example-product-p1.html",
    "name": "Мобільний телефон Apple iPhone 16 Pro Max 256GB Black Titanium",
    "color": "чорний",
    "memory": "256 Gb",
    "manufacturer": "Apple",
    "regular_price": 65799.0,
    "promo_price": None,
    "photos": ["https://brain.com.ua/static/images/prod_img/example.jpg"],
    "product_code": "U0961530",
    "reviews_count": 1,
    "screen_diagonal": '6.9"',
    "screen_resolution": "1320 х 2868",
    "characteristics": {"Основні характеристики": {"Форм-фактор": "моноблок"}},
}

# Мини-копия карточки товара: все селекторы, которые использует парсер.
PRODUCT_HTML = """
<html lang="uk"><head><title>Товар</title></head><body>
  <h1>
    Мобільний телефон Apple iPhone 16 Pro Max 256GB Black Titanium
  </h1>

  <div class="price-bonuses-block">
    <div class="br-pr-price main-price-block">
      <div class="br-pr-op"><span class="price-wrapper">65 799 ₴</span></div>
      <div class="br-pr-np"><span class="price-wrapper">61 999 ₴</span></div>
    </div>
  </div>

  <div class="br-pr-slider">
    <img src="/static/images/prod_img/U0961530_1.jpg" alt="фото 1">
    <img src="/static/images/prod_img/U0961530_2.jpg" alt="фото 2">
    <img src="/static/images/prod_img/U0961530_1_small.jpg" alt="превью">
  </div>

  <div class="product-code-num">Код товару:
    <span class="br-pr-code-val">U0961530</span>
  </div>
  <a class="brackets-reviews" href="#reviews">Відгуки (1)</a>

  <div class="br-pr-chr-wrap">
    <div class="br-pr-chr-item">
      <h3>Основні характеристики</h3>
      <div>
        <div><span>Форм-фактор</span><span>моноблок</span></div>
        <div><span>Колір</span><span>чорний</span></div>
      </div>
    </div>
    <div class="br-pr-chr-item">
      <h3>Дисплей</h3>
      <div>
        <div><span>Діагональ екрану</span><span>6.9"</span></div>
        <div><span>Роздільна здатність екрану</span><span>1320 х 2868</span></div>
      </div>
    </div>
    <div class="br-pr-chr-item">
      <h3>Функції пам'яті</h3>
      <div>
        <div><span>Вбудована пам'ять</span><span>256 Gb</span></div>
      </div>
    </div>
    <div class="br-pr-chr-item">
      <h3>Інше</h3>
      <div>
        <div><span>Виробник</span><span>Apple</span></div>
      </div>
    </div>
  </div>
</body></html>
"""

# Та же карточка, но без скидки: есть только новая цена.
NO_DISCOUNT_HTML = """
<html><body>
  <h1>Мобільний телефон Apple iPhone 16 Pro Max 256GB Black Titanium</h1>
  <div class="br-pr-price main-price-block">
    <div class="br-pr-np"><span class="price-wrapper">61 999 ₴</span></div>
  </div>
</body></html>
"""

# Заглушка Cloudflare вместо страницы товара.
CHALLENGE_HTML = """
<html><head><title>Just a moment...</title></head>
<body><script>var cf_chl_opt = {};</script></body></html>
"""


class FakeResponse:
    """Минимальная заглушка ответа ``requests``/``curl_cffi``."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class IndexViewTests(TestCase):
    """GET /products/ — страница с кнопкой Parse."""

    def test_page_is_rendered_with_parse_button(self):
        response = self.client.get(reverse("index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="parse-btn"')
        self.assertContains(response, "/products/parse/")

    def test_page_has_csv_export_link(self):
        response = self.client.get(reverse("index"))

        self.assertContains(response, reverse("export_csv"))

    def test_url_input_is_prefilled_with_default_url(self):
        response = self.client.get(reverse("index"))

        self.assertContains(response, DEFAULT_URL)
        self.assertEqual(response.context["default_url"], DEFAULT_URL)


class ParseProductViewTests(TestCase):
    """GET /products/parse/?url=... — парсинг и сохранение товара."""

    @patch("products.views.parse_url", return_value=PARSED_PRODUCT)
    def test_saves_product_and_returns_json(self, parse_url_mock):
        response = self.client.get(reverse("parse"), {"url": PARSED_PRODUCT["url"]})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["saved"])
        self.assertEqual(payload["product"]["name"], PARSED_PRODUCT["name"])

        product = Product.objects.get(pk=payload["id"])
        self.assertEqual(product.name, PARSED_PRODUCT["name"])
        self.assertEqual(product.product_code, "U0961530")
        self.assertEqual(product.reviews_count, 1)
        parse_url_mock.assert_called_once_with(PARSED_PRODUCT["url"])

    @patch("products.views.parse_url", return_value=PARSED_PRODUCT)
    def test_without_url_uses_default_url(self, parse_url_mock):
        response = self.client.get(reverse("parse"))

        self.assertEqual(response.status_code, 200)
        parse_url_mock.assert_called_once_with(DEFAULT_URL)

    @patch("products.views.parse_url", return_value=PARSED_PRODUCT)
    def test_second_parse_of_same_url_updates_the_same_row(self, parse_url_mock):
        first = self.client.get(reverse("parse"), {"url": PARSED_PRODUCT["url"]}).json()
        second = self.client.get(reverse("parse"), {"url": PARSED_PRODUCT["url"]}).json()

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(Product.objects.count(), 1)

    @patch("products.views.parse_url", side_effect=RuntimeError("Cloudflare 403"))
    def test_parse_error_returns_502_and_saves_nothing(self, parse_url_mock):
        response = self.client.get(reverse("parse"), {"url": PARSED_PRODUCT["url"]})

        self.assertEqual(response.status_code, 502)
        self.assertIn("Cloudflare 403", response.json()["error"])
        self.assertEqual(Product.objects.count(), 0)


class FetchHtmlTests(SimpleTestCase):
    """Загрузка HTML: основной клиент — requests, резерв — curl_cffi."""

    URL = "https://brain.com.ua/ukr/example-product-p1.html"

    @patch("curl_cffi.requests.get")
    @patch("products.services.hi_scraper.requests.get")
    def test_requests_is_used_first_and_returns_html(self, requests_get, curl_cffi_get):
        requests_get.return_value = FakeResponse(PRODUCT_HTML)

        html = fetch_html(self.URL)

        self.assertEqual(html, PRODUCT_HTML)
        requests_get.assert_called_once()
        self.assertEqual(requests_get.call_args.args[0], self.URL)
        self.assertIn("User-Agent", requests_get.call_args.kwargs["headers"])
        curl_cffi_get.assert_not_called()

    @patch("curl_cffi.requests.get")
    @patch("products.services.hi_scraper.requests.get")
    def test_cloudflare_http_403_falls_back_to_curl_cffi(
        self, requests_get, curl_cffi_get
    ):
        requests_get.return_value = FakeResponse(CHALLENGE_HTML, status_code=403)
        curl_cffi_get.return_value = FakeResponse(PRODUCT_HTML)

        html = fetch_html(self.URL)

        self.assertEqual(html, PRODUCT_HTML)
        self.assertEqual(curl_cffi_get.call_count, 1)
        self.assertEqual(curl_cffi_get.call_args.kwargs["impersonate"], "chrome")
        self.assertEqual(curl_cffi_get.call_args.args[0], self.URL)

    @patch("curl_cffi.requests.get")
    @patch("products.services.hi_scraper.requests.get")
    def test_cloudflare_challenge_page_falls_back_to_curl_cffi(
        self, requests_get, curl_cffi_get
    ):
        # Cloudflare умеет отдавать челлендж и с кодом 200.
        requests_get.return_value = FakeResponse(CHALLENGE_HTML)
        curl_cffi_get.return_value = FakeResponse(PRODUCT_HTML)

        self.assertEqual(fetch_html(self.URL), PRODUCT_HTML)
        self.assertEqual(curl_cffi_get.call_count, 1)

    @patch("products.services.hi_scraper.time.sleep")
    @patch("curl_cffi.requests.get")
    @patch("products.services.hi_scraper.requests.get")
    def test_curl_cffi_retries_before_giving_up(
        self, requests_get, curl_cffi_get, sleep_mock
    ):
        requests_get.return_value = FakeResponse(CHALLENGE_HTML, status_code=403)
        curl_cffi_get.side_effect = [
            requests.HTTPError("503 Service Unavailable"),
            FakeResponse(PRODUCT_HTML),
        ]

        html = fetch_html(self.URL, retries=2)

        self.assertEqual(html, PRODUCT_HTML)
        self.assertEqual(curl_cffi_get.call_count, 2)
        self.assertEqual(sleep_mock.call_count, 1)

    @patch("products.services.hi_scraper.time.sleep")
    @patch("curl_cffi.requests.get")
    @patch("products.services.hi_scraper.requests.get")
    def test_both_clients_blocked_raises_scraper_error(
        self, requests_get, curl_cffi_get, sleep_mock
    ):
        requests_get.return_value = FakeResponse(CHALLENGE_HTML, status_code=403)
        curl_cffi_get.return_value = FakeResponse(CHALLENGE_HTML, status_code=403)

        with self.assertRaises(ScraperError) as ctx:
            fetch_html(self.URL, retries=1)

        message = str(ctx.exception)
        self.assertIn("requests ->", message)
        self.assertIn("curl_cffi ->", message)
        self.assertEqual(sleep_mock.call_count, 0)


class ParserFunctionTests(SimpleTestCase):
    """Разбор HTML через bs4 (``BeautifulSoup``) — на фикстуре, без сети."""

    URL = "https://brain.com.ua/ukr/example-product-p1.html"

    def test_extracts_all_fields_from_page(self):
        data = parse_product(PRODUCT_HTML, self.URL)

        self.assertEqual(data["url"], self.URL)
        self.assertEqual(
            data["name"],
            "Мобільний телефон Apple iPhone 16 Pro Max 256GB Black Titanium",
        )
        self.assertEqual(data["color"], "чорний")
        self.assertEqual(data["memory"], "256 Gb")
        self.assertEqual(data["manufacturer"], "Apple")
        self.assertEqual(data["regular_price"], 65799.0)
        self.assertEqual(data["promo_price"], 61999.0)
        self.assertEqual(data["product_code"], "U0961530")
        self.assertEqual(data["reviews_count"], 1)
        self.assertEqual(data["screen_diagonal"], '6.9"')
        self.assertEqual(data["screen_resolution"], "1320 х 2868")
        self.assertEqual(
            data["characteristics"]["Основні характеристики"],
            {"Форм-фактор": "моноблок", "Колір": "чорний"},
        )
        self.assertEqual(
            data["characteristics"]["Дисплей"],
            {"Діагональ екрану": '6.9"', "Роздільна здатність екрану": "1320 х 2868"},
        )

    def test_collects_full_size_photos_and_skips_thumbnails(self):
        data = parse_product(PRODUCT_HTML, self.URL)

        self.assertEqual(
            data["photos"],
            [
                "https://brain.com.ua/static/images/prod_img/U0961530_1.jpg",
                "https://brain.com.ua/static/images/prod_img/U0961530_2.jpg",
            ],
        )

    def test_without_discount_promo_price_is_none(self):
        data = parse_product(NO_DISCOUNT_HTML, self.URL)

        self.assertEqual(data["regular_price"], 61999.0)
        self.assertIsNone(data["promo_price"])

    def test_empty_html_does_not_break(self):
        data = parse_product("", self.URL)

        self.assertEqual(data["name"], "")
        self.assertEqual(data["color"], "")
        self.assertIsNone(data["regular_price"])
        self.assertIsNone(data["promo_price"])
        self.assertEqual(data["photos"], [])
        self.assertEqual(data["reviews_count"], 0)
        self.assertEqual(data["characteristics"], {})


class SearchFlowTests(SimpleTestCase):
    """Общие шаги поиска: проверка челленджа и валидация данных товара."""

    def test_challenge_page_is_detected(self):
        self.assertTrue(looks_like_challenge(CHALLENGE_HTML))
        self.assertFalse(looks_like_challenge(PRODUCT_HTML))

    def test_valid_product_passes_through(self):
        data = parse_product(PRODUCT_HTML, RESULT_URL)

        self.assertIs(validate_product(data), data)

    def test_product_without_name_is_rejected(self):
        with self.assertRaises(BrowserFlowError):
            validate_product({"name": "", "characteristics": {"Інше": {"Виробник": "Apple"}}})

    def test_product_without_characteristics_is_rejected(self):
        with self.assertRaises(BrowserFlowError):
            validate_product({"name": "iPhone", "characteristics": {}})

    def test_search_url_escapes_query(self):
        self.assertEqual(
            search_url("Apple iPhone 15 128GB Black"),
            "https://brain.com.ua/ukr/search/?Search=Apple+iPhone+15+128GB+Black",
        )
        self.assertEqual(
            search_url('телефон & "чохол"'),
            "https://brain.com.ua/ukr/search/?Search=%D1%82%D0%B5%D0%BB%D0%B5%D1%84%D0%BE%D0%BD+%26+%22%D1%87%D0%BE%D1%85%D0%BE%D0%BB%22",
        )


class FakeDriverMixin:
    """Собирает мок драйвера Selenium/страницы Playwright (без браузера)."""

    @staticmethod
    def selenium_driver(html: str = PRODUCT_HTML, url: str = RESULT_URL):
        """Мок webdriver.Chrome: ищет те же селекторы, что и парсер.

        Элементам выставлены ``is_displayed()/is_enabled() == True``: внутри
        ``element_to_be_clickable`` Selenium сравнивает результат
        ``is_displayed()`` с ``True`` (у «сырого» мока это сравнение ложно,
        и ожидание просто висело бы до таймаута).
        """
        driver = MagicMock(name="driver")
        driver.page_source = html
        driver.current_url = url

        def element(name):
            mock = MagicMock(name=name)
            mock.is_displayed.return_value = True
            mock.is_enabled.return_value = True
            return mock

        search_input = element("search_input")
        submit = element("submit")
        search_input.find_elements.return_value = [submit]

        result_item = element("result_item")
        result_link = element("result_link")
        result_link.get_attribute.return_value = url

        elements = {
            SEARCH_INPUT: search_input,
            RESULT_ITEMS: result_item,
            PRODUCT_TITLE: element("product_title"),
        }
        driver.find_element.side_effect = lambda by, selector: elements[selector]
        driver.find_elements.side_effect = lambda by, selector: {
            SEARCH_INPUT: [search_input],
            f"{RESULT_ITEMS} {RESULT_TITLE_LINK}": [result_link],
        }[selector]
        return driver, {
            "search_input": search_input,
            "submit": submit,
            "result_link": result_link,
        }

    @staticmethod
    def playwright_page(html: str = PRODUCT_HTML, url: str = RESULT_URL):
        """Мок page Playwright с теми же локаторами, что и парсер."""
        page = MagicMock(name="page")
        page.url = url
        page.content.return_value = html

        field = MagicMock(name="search_field")
        field.is_visible.return_value = True
        fields = MagicMock(name="fields")
        fields.count.return_value = 1
        fields.nth.return_value = field

        submit = MagicMock(name="submit")
        submit.count.return_value = 1
        submit.first = submit
        form = MagicMock(name="form")
        form.locator.return_value = submit
        field.locator.return_value = form

        result_item = MagicMock(name="result_item")
        result_item.first = result_item
        items = MagicMock(name="items")
        items.first = result_item

        result_link = MagicMock(name="result_link")
        result_link.first = result_link
        result_link.get_attribute.return_value = url

        product_title = MagicMock(name="product_title")
        product_title.first = product_title

        locators = {
            SEARCH_INPUT: fields,
            RESULT_ITEMS: items,
            f"{RESULT_ITEMS} {RESULT_TITLE_LINK}": result_link,
            PRODUCT_TITLE: product_title,
        }
        page.locator.side_effect = lambda selector: locators[selector]
        return page, {
            "search_input": field,
            "submit": submit,
            "result_link": result_link,
            "items": items,
        }



class SeleniumFlowTests(FakeDriverMixin, SimpleTestCase):
    """Шаги 1-6 на Selenium: драйвер подменён моком, браузер не запускается."""

    def test_full_flow_searches_and_parses_product(self):
        driver, elements = self.selenium_driver()
        parser = SeleniumSearchParser(driver=driver)

        data = parser.collect()

        # Шаг-1: главная страница сайта.
        driver.get.assert_called_once_with(HOME_URL)
        # Шаг-2: запрос введён в поисковую строку.
        elements["search_input"].clear.assert_called_once()
        elements["search_input"].send_keys.assert_called_once_with(DEFAULT_QUERY)
        # Шаг-3: нажата кнопка «Найти» внутри формы поиска.
        elements["submit"].click.assert_called_once()
        # Шаг-4: клик по первому результату и переход на карточку.
        driver.execute_script.assert_called_once()
        self.assertEqual(
            driver.execute_script.call_args.args,
            ("arguments[0].click()", elements["result_link"]),
        )
        self.assertEqual(elements["result_link"].get_attribute.call_args.args, ("href",))
        # Cookie сброшены перед второй и третьей навигацией: иначе Cloudflare
        # отдаёт челлендж вместо страницы.
        self.assertEqual(driver.delete_all_cookies.call_count, 2)
        # Шаг-5: данные собраны тем же bs4-парсером, что и в requests-версии.
        self.assertEqual(data, parse_product(PRODUCT_HTML, RESULT_URL))
        self.assertEqual(data["product_code"], "U0961530")

    def test_steps_run_in_required_order(self):
        driver, _ = self.selenium_driver()
        parser = SeleniumSearchParser(driver=driver)
        steps = []

        with (
            patch.object(
                SeleniumSearchParser, "open_home", lambda self: steps.append("home")
            ),
            patch.object(
                SeleniumSearchParser,
                "search",
                lambda self, query=None: steps.append("find"),
            ),
            patch.object(
                SeleniumSearchParser,
                "open_first_result",
                lambda self, wait=None: steps.append("first") or RESULT_URL,
            ),
        ):
            parser.collect()

        self.assertEqual(steps, ["home", "find", "first"])

    def test_custom_query_is_typed_instead_of_default(self):
        driver, elements = self.selenium_driver()
        parser = SeleniumSearchParser(query="Samsung Galaxy S24", driver=driver)

        parser.search()

        elements["search_input"].send_keys.assert_called_once_with("Samsung Galaxy S24")

    def test_submit_button_failure_falls_back_to_enter(self):
        driver, elements = self.selenium_driver()
        elements["submit"].click.side_effect = WebDriverException("not interactable")
        parser = SeleniumSearchParser(driver=driver)

        parser.search()

        elements["search_input"].send_keys.assert_any_call(Keys.ENTER)

    def test_missing_results_raise_flow_error(self):
        driver, _ = self.selenium_driver()
        driver.find_element.side_effect = NoSuchElementException("нет результатов")
        parser = SeleniumSearchParser(driver=driver, timeout=0)

        with self.assertRaises(BrowserFlowError) as ctx:
            parser.open_first_result()

        self.assertIn("результаты поиска", str(ctx.exception))

    def test_missing_results_fall_back_to_search_url(self):
        driver, _ = self.selenium_driver()
        parser = SeleniumSearchParser(driver=driver)
        opened = []

        def open_first_result(self, wait=None):
            opened.append(1)
            if len(opened) == 1:
                raise BrowserFlowError("результаты поиска не появились")
            return RESULT_URL

        with patch.object(SeleniumSearchParser, "open_first_result", open_first_result):
            data = parser.collect()

        self.assertEqual(len(opened), 2)
        self.assertEqual(driver.get.call_args.args, (search_url(DEFAULT_QUERY),))
        self.assertEqual(data, parse_product(PRODUCT_HTML, RESULT_URL))

    def test_card_click_failure_falls_back_to_direct_url(self):
        driver, elements = self.selenium_driver()
        driver.execute_script.side_effect = WebDriverException("element not visible")
        parser = SeleniumSearchParser(driver=driver)

        url = parser.open_first_result()

        self.assertEqual(url, RESULT_URL)
        self.assertEqual(driver.get.call_args.args, (RESULT_URL,))

    def test_run_prints_product_and_keeps_foreign_driver_open(self):
        driver, _ = self.selenium_driver()
        parser = SeleniumSearchParser(driver=driver)

        with patch("products.services.selenium_parser.print_product") as print_mock:
            data = parser.run()

        print_mock.assert_called_once_with(data)
        driver.quit.assert_not_called()

    def test_cloudflare_challenge_instead_of_home_page(self):
        driver, _ = self.selenium_driver(html=CHALLENGE_HTML)
        driver.find_element.side_effect = NoSuchElementException("нет формы поиска")
        parser = SeleniumSearchParser(driver=driver, timeout=0)

        with self.assertRaises(BrowserFlowError) as ctx:
            parser.open_home()

        self.assertIn("Cloudflare", str(ctx.exception))
        driver.get.assert_called_once_with(HOME_URL)

    def test_hidden_search_fields_raise_flow_error(self):
        driver, _ = self.selenium_driver()
        hidden = MagicMock(name="hidden_field")
        hidden.is_displayed.return_value = False
        driver.find_elements.side_effect = lambda by, selector: [hidden]
        parser = SeleniumSearchParser(driver=driver)

        with self.assertRaises(BrowserFlowError) as ctx:
            parser.search()

        self.assertIn("поле поиска", str(ctx.exception))

    def test_empty_results_raise_flow_error(self):
        driver, _ = self.selenium_driver()
        driver.find_elements.side_effect = lambda by, selector: []
        parser = SeleniumSearchParser(driver=driver)

        with self.assertRaises(BrowserFlowError) as ctx:
            parser.open_first_result()

        self.assertIn("результатах поиска", str(ctx.exception))




class PlaywrightFlowTests(FakeDriverMixin, SimpleTestCase):
    """Шаги 1-6 на Playwright: страница подменена моком, браузер не стартует."""

    def test_full_flow_searches_and_parses_product(self):
        page, locators = self.playwright_page()
        parser = PlaywrightSearchParser(page=page)

        data = parser.collect()

        # Шаг-1: главная страница сайта.
        page.goto.assert_called_once_with(
            HOME_URL, wait_until="domcontentloaded", timeout=60000
        )
        page.wait_for_selector.assert_called_once_with(
            SEARCH_INPUT, state="attached", timeout=60000
        )
        # Шаг-2: запрос введён в поисковую строку.
        locators["search_input"].click.assert_called_once()
        locators["search_input"].fill.assert_called_once_with(DEFAULT_QUERY)
        # Шаг-3: нажата кнопка «Найти».
        locators["submit"].click.assert_called_once()
        # Шаг-4: клик по первому результату и переход на карточку.
        self.assertEqual(locators["result_link"].click.call_args.args, ())
        self.assertEqual(
            locators["result_link"].click.call_args.kwargs, {"force": True}
        )
        self.assertEqual(locators["result_link"].get_attribute.call_args.args, ("href",))
        # Cookie сброшены перед второй и третьей навигацией: иначе Cloudflare
        # отдаёт челлендж вместо страницы.
        self.assertEqual(page.context.clear_cookies.call_count, 2)
        # Шаг-5: данные собраны тем же bs4-парсером, что и в requests-версии.
        self.assertEqual(data, parse_product(PRODUCT_HTML, RESULT_URL))
        self.assertEqual(data["name"], PARSED_PRODUCT["name"])

    def test_steps_run_in_required_order(self):
        page, _ = self.playwright_page()
        parser = PlaywrightSearchParser(page=page)
        steps = []

        with (
            patch.object(
                PlaywrightSearchParser, "open_home", lambda self: steps.append("home")
            ),
            patch.object(
                PlaywrightSearchParser,
                "search",
                lambda self, query=None: steps.append("find"),
            ),
            patch.object(
                PlaywrightSearchParser,
                "open_first_result",
                lambda self, wait=None: steps.append("first") or RESULT_URL,
            ),
        ):
            parser.collect()

        self.assertEqual(steps, ["home", "find", "first"])

    def test_run_prints_product_and_keeps_foreign_page_open(self):
        page, _ = self.playwright_page()
        parser = PlaywrightSearchParser(page=page)

        with patch("products.services.playwright_parser.print_product") as print_mock:
            data = parser.run()

        print_mock.assert_called_once_with(data)
        page.close.assert_not_called()

    def test_cloudflare_challenge_instead_of_home_page(self):
        page, _ = self.playwright_page(html=CHALLENGE_HTML)
        page.wait_for_selector.side_effect = RuntimeError("Timeout 60000ms exceeded")
        parser = PlaywrightSearchParser(page=page)

        with self.assertRaises(BrowserFlowError) as ctx:
            parser.open_home()

        self.assertIn("Cloudflare", str(ctx.exception))
        page.goto.assert_called_once()

    def test_hidden_search_fields_raise_flow_error(self):
        page, locators = self.playwright_page()
        locators["search_input"].is_visible.return_value = False
        parser = PlaywrightSearchParser(page=page)

        with self.assertRaises(BrowserFlowError) as ctx:
            parser.search()

        self.assertIn("поле поиска", str(ctx.exception))

    def test_submit_failure_falls_back_to_enter(self):
        page, locators = self.playwright_page()
        locators["submit"].click.side_effect = RuntimeError("element is not visible")
        parser = PlaywrightSearchParser(page=page)

        parser.search()

        locators["search_input"].press.assert_called_once_with("Enter")

    def test_missing_results_raise_flow_error(self):
        page, locators = self.playwright_page()
        locators["items"].first.wait_for.side_effect = RuntimeError(
            "Timeout 60000ms exceeded"
        )
        parser = PlaywrightSearchParser(page=page)

        with self.assertRaises(BrowserFlowError) as ctx:
            parser.open_first_result()

        self.assertIn("результаты поиска", str(ctx.exception))

    def test_missing_results_fall_back_to_search_url(self):
        page, _ = self.playwright_page()
        parser = PlaywrightSearchParser(page=page)
        opened = []

        def open_first_result(self, wait=None):
            opened.append(1)
            if len(opened) == 1:
                raise BrowserFlowError("результаты поиска не появились")
            return RESULT_URL

        with patch.object(PlaywrightSearchParser, "open_first_result", open_first_result):
            data = parser.collect()

        self.assertEqual(len(opened), 2)
        self.assertEqual(page.goto.call_args.args, (search_url(DEFAULT_QUERY),))
        self.assertEqual(data, parse_product(PRODUCT_HTML, RESULT_URL))

    def test_card_click_failure_falls_back_to_direct_url(self):
        page, locators = self.playwright_page()
        locators["result_link"].click.side_effect = RuntimeError("element is not visible")
        parser = PlaywrightSearchParser(page=page)

        url = parser.open_first_result()

        self.assertEqual(url, RESULT_URL)
        self.assertEqual(page.goto.call_args.args, (RESULT_URL,))

class FakeSearchParser:
    """Заглушка браузерного парсера для тестов команды ``parse_search``."""

    instances: list = []

    def __init__(self, **options):
        self.options = options
        self.closed = False
        FakeSearchParser.instances.append(self)

    def collect(self) -> dict:
        return PARSED_PRODUCT

    def close(self) -> None:
        self.closed = True


class ParseSearchCommandTests(TestCase):
    """Команда ``parse_search``: браузерный парсер -> печать -> сохранение в БД."""

    def setUp(self):
        FakeSearchParser.instances = []
        patcher = patch.dict(
            "products.management.commands.parse_search.ENGINES",
            {"selenium": FakeSearchParser, "playwright": FakeSearchParser},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_prints_data_and_saves_product(self):
        out = io.StringIO()

        call_command("parse_search", stdout=out)

        parser = FakeSearchParser.instances[0]
        self.assertEqual(parser.options, {"query": DEFAULT_QUERY, "headless": True})
        self.assertTrue(parser.closed)

        printed = out.getvalue()
        self.assertIn(PARSED_PRODUCT["name"], printed)
        self.assertIn("Сохранено в БД", printed)
        self.assertEqual(json.loads(printed[printed.index("{") : printed.rindex("}") + 1]), PARSED_PRODUCT)

        product = Product.objects.get()
        self.assertEqual(product.name, PARSED_PRODUCT["name"])
        self.assertEqual(product.product_code, "U0961530")
        self.assertEqual(product.photos, PARSED_PRODUCT["photos"])

    def test_options_are_forwarded_to_engine(self):
        out = io.StringIO()

        call_command(
            "parse_search",
            "--query",
            "Apple iPhone 15 128GB Black",
            "--no-headless",
            "--chrome-binary",
            "/usr/bin/chromium",
            stdout=out,
        )

        self.assertEqual(
            FakeSearchParser.instances[0].options,
            {
                "query": "Apple iPhone 15 128GB Black",
                "headless": False,
                "browser_binary": "/usr/bin/chromium",
            },
        )

    def test_no_save_flag_skips_database(self):
        out = io.StringIO()

        call_command("parse_search", "--no-save", stdout=out)

        self.assertEqual(Product.objects.count(), 0)
        self.assertIn("Сохранение в БД отключено", out.getvalue())

    def test_engine_error_becomes_command_error(self):
        class BrokenSearchParser(FakeSearchParser):
            def collect(self) -> dict:
                raise BrowserFlowError("Cloudflare показал челлендж")

        with patch.dict(
            "products.management.commands.parse_search.ENGINES",
            {"selenium": BrokenSearchParser, "playwright": BrokenSearchParser},
        ):
            with self.assertRaises(CommandError) as ctx:
                call_command("parse_search", stdout=io.StringIO())

        self.assertIn("Cloudflare", str(ctx.exception))
        self.assertEqual(Product.objects.count(), 0)
        self.assertTrue(BrokenSearchParser.instances[0].closed)


class CsvExportServiceTests(SimpleTestCase):
    """Сервис выгрузки: CSV собирается из объектов Product."""

    def test_env_without_products_returns_only_header(self):
        reader = csv.reader(io.StringIO(products_as_csv([])))

        self.assertEqual(next(reader), list(CSV_FIELDS))
        with self.assertRaises(StopIteration):
            next(reader)


class ExportCsvTests(TestCase):
    """Шаг-7: выгрузка товаров из БД в CSV (команда и HTTP-эндпоинт)."""

    PHOTOS = (
        "https://brain.com.ua/static/images/prod_img/second_1.jpg",
        "https://brain.com.ua/static/images/prod_img/second_2.jpg",
    )

    def setUp(self):
        Product.from_parsed(PARSED_PRODUCT)
        Product.from_parsed(
            {
                **PARSED_PRODUCT,
                "url": "https://brain.com.ua/ukr/second-p2.html",
                "name": "Другий товар",
                "photos": list(self.PHOTOS),
            }
        )

    def _read_rows(self, text: str) -> list:
        return list(csv.DictReader(io.StringIO(text)))

    def test_command_writes_csv_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "products.csv")

            call_command("export_csv", "--output", path, stdout=io.StringIO())

            with open(path, encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))

        self.assertEqual(len(rows), 2)
        self.assertEqual(list(rows[0]), list(CSV_FIELDS))

        row = next(item for item in rows if item["url"].endswith("second-p2.html"))
        self.assertEqual(row["name"], "Другий товар")
        self.assertEqual(row["product_code"], "U0961530")
        self.assertEqual(row["regular_price"], "65799.00")
        self.assertEqual(row["photos_count"], "2")
        self.assertEqual(row["photos"], ", ".join(self.PHOTOS))
        self.assertEqual(
            json.loads(row["characteristics"]), PARSED_PRODUCT["characteristics"]
        )

    def test_command_stdout_mode(self):
        out = io.StringIO()

        call_command("export_csv", "--to-stdout", stdout=out, stderr=io.StringIO())

        rows = self._read_rows(out.getvalue())

        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(rows[0]), sorted(CSV_FIELDS))

    def test_http_endpoint_returns_csv_attachment(self):
        response = self.client.get(reverse("export_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])

        rows = self._read_rows(response.content.decode("utf-8"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(list(rows[0]), list(CSV_FIELDS))

    def test_endpoint_with_empty_database_returns_header_only(self):
        Product.objects.all().delete()

        response = self.client.get(reverse("export_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._read_rows(response.content.decode("utf-8")), [])


