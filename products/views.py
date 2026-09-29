from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Product
from .services.hi_parser import DEFAULT_URL, parse_url


@require_GET
def index(request):
    """GET /products/ — страница с кнопкой Parse.

    Кнопка через JS дёргает `/products/parse/`, забирает данные о товаре
    и выводит ответ сервера как JSON на экран.
    """
    return render(request, "products/index.html", {"default_url": DEFAULT_URL})


@require_GET
def parse_product(request):
    """GET /products/parse/?url=... — парсит товар и сохраняет его в БД."""
    url = request.GET.get("url") or DEFAULT_URL
    try:
        data = parse_url(url)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)

    product = Product.from_parsed(data)
    return JsonResponse(
        {
            "saved": True,
            "id": product.pk,
            "product": data,
        },
        json_dumps_params={"ensure_ascii": False, "indent": 2},
    )