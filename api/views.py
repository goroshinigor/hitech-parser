from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.shortcuts import render

from .models import Product
from .services.hi_parser import DEFAULT_URL, parse_url


# Create your views here.
def hello(request):
    return JsonResponse({"message": "hello"})


@require_GET
def parse_view(request):
    """GET /api/parse/?url=... — парсит товар и сохраняет его в БД."""
    url = request.GET.get("url", DEFAULT_URL)
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