"""Тесты приложения products.

Страница с кнопкой Parse, эндпоинт парсинга, загрузка HTML (``requests`` с
резервом ``curl_cffi``) и разбор HTML через ``bs4``. Сеть не используется:
HTTP-клиенты и ``parse_url`` подменяются моками, HTML берётся из фикстуры.
"""

from __future__ import annotations

from unittest.mock import patch

import requests
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Product
from .services.hi_parser import DEFAULT_URL, parse_product
from .services.hi_scraper import ScraperError, fetch_html

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

