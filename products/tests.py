"""Тесты приложения products: страница с кнопкой Parse и эндпоинт парсинга.

Сеть не используется: ``parse_url`` подменяется моком.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .models import Product
from .services.hi_parser import DEFAULT_URL

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

