# hitech-parser

Django + PostgreSQL парсер карточек товаров с [brain.com.ua](https://brain.com.ua).

Два способа попасть на карточку товара:

* **по прямой ссылке** — `requests` (резерв `curl_cffi`) + `bs4`;
* **через поиск сайта реальным браузером** — Selenium или Playwright: главная →
  ввод запроса → кнопка «Найти» → первый результат → карточка товара.

Дальше данные печатаются, сохраняются в БД и выгружаются в CSV.

## Что делает

1. Открывает главную страницу `https://brain.com.ua/` (Шаг-1).
2. Вводит в поисковую строку запрос «Apple iPhone 15 128GB Black» (Шаг-2).
3. Нажимает кнопку «Найти» (Шаг-3).
4. Кликает первый результат и переходит на карточку товара (Шаг-4).
5. Собирает данные о товаре (Шаг-5).
6. Печатает результат в консоль (Шаг-6).
7. Сохраняет результат в базу данных (Шаг-7) и отдаёт выгрузку в CSV.

Если запускать по прямой ссылке (`parse_product`), шаги 1-4 заменяются загрузкой
HTML карточки.

### Извлекаемые данные

| Поле | Источник |
| --- | --- |
| Полное название | `h1` |
| Цвет | характеристика «Колір» |
| Объём памяти | характеристика «Вбудована пам'ять» |
| Производитель | характеристика «Виробник» |
| Цена обычная | `.br-pr-op` (или `.br-pr-np`, если скидки нет) |
| Цена акционная | `.br-pr-np` при наличии скидки |
| Все фото (список ссылок) | `.br-pr-slider img` |
| Код товара | `.br-pr-code-val` |
| Кол-во отзывов | `.brackets-reviews` / `.reviews-count` |
| Диагональ экрана | характеристика «Діагональ екрану» |
| Разрешение дисплея | характеристика «Роздільна здатність екрану» |
| Все характеристики (словарь) | `.br-pr-chr-wrap` → `группа -> {характеристика: значение}` |

> **Чем парсим.** Разбор HTML — `bs4` (`BeautifulSoup` с парсером `lxml`),
> загрузка — `requests`. Но сайт закрыт Cloudflare managed challenge: обычный
> `requests` (в том числе с браузерным `User-Agent` и с `Session`) получает
> **403** и страницу «Just a moment…». Поэтому загрузка устроена в два шага:
> сначала одна попытка через `requests`, а если пришёл челлендж — повтор через
> `curl_cffi` с имперсонацией Chrome (у него API как у `requests`). Обе ветки
> покрыты тестами, см. `products/tests.py`.

## Поиск через браузер (Шаги 1-4)

Шаги 1-4 выполняет один из браузерных парсеров — `SeleniumSearchParser` или
`PlaywrightSearchParser`. Логика у них одинаковая, отличается только API:
общие адреса, селекторы и настройки лежат в `products/services/search_flow.py`,
а HTML карточки разбирает тот же `hi_parser.parse_product`, что и у
`requests`-версии.

### Селекторы (проверены на живой разметке)

| Шаг | Что ищем | Селектор |
| --- | --- | --- |
| 2 | поле поиска | `.quick-search-input` (форм две — берём первое видимое) |
| 3 | кнопка «Найти» | `input[type=submit]` внутри формы поля, резерв — `.search-button-first-form` |
| 4 | карточки результатов | `.search-wrapper .goods-block__item` |
| 4 | ссылка на товар | `.br-pp-ipd-shown a[href]` (скрыта до наведения) |
| 5 | заголовок карточки | `h1` |

Ссылка в карточке результатов появляется только при наведении, поэтому по ней
кликают не мышью, а скриптом (`force` в Playwright, `execute_script` в Selenium).

### Нюансы Cloudflare

* Headless-браузер по умолчанию подписывается «HeadlessChrome» и сразу получает
  челлендж, поэтому запускаются с «человеческим» `User-Agent`, локалью `uk-UA`
  и скрытым `navigator.webdriver` (`--disable-blink-features=AutomationControlled`
  + `STEALTH_SCRIPT`).
* Челлендж приходит на **любую навигацию, кроме первой**: браузер получает
  `cf_clearance` и следующий переход блокируется. Парсеры сбрасывают cookie
  перед вторым и третьим переходом (перед «Найти», перед открытием карточки) —
  каждая навигация снова выглядит «свежей» и проходит.
* В Selenium `delete_all_cookies()` **не** удаляет HttpOnly-cookie
  `cf_clearance`, и с пустой сессией + одним `cf_clearance` челлендж всё равно
  показывается. Поэтому Selenium чистит cookie через CDP
  (`Network.clearBrowserCookies`), а `delete_all_cookies()` оставлен резервом.
* Если список результатов всё же не отрисовался (например, Cloudflare успел
  вмешаться), парсер открывает страницу поиска по адресу
  `https://brain.com.ua/ukr/search/?Search=<запрос>` и пробует снова.
* Третья навигация (переход на карточку по клику) чаще всего попадает на
  челлендж. Поэтому после клика парсер ждёт признак карточки — блок
  характеристик `.br-pr-chr-wrap` (на странице челленджа его нет, а `h1` там
  есть: «Just a moment...»), и если карточка не открылась, переходит по адресу
  товара в **свежей сессии**: Selenium перезапускает браузер, Playwright создаёт
  новый контекст. Первая навигация новой сессии Cloudflare не проверяет —
  проверено живым прогоном (карточка открывается за ~3-4 с).

Порядок ожиданий: список результатов — `RESULTS_WAIT` секунд (15), дальше
страховки; на второй попытке и при ожидании карточки — полный `timeout` (60).
Живой прогон Selenium CLI занимает ~12 секунд: главная 3.7 с, отправка формы
4.4 с, карточка (свежая сессия) 3.4 с.

> Селекторы и поведение проверены живыми прогонами: Playwright и Selenium
> открывают главную, отправляют поиск, получают 24 карточки и открывают карточку
> товара без челленджа.

## Запуск

### Вариант 1. Docker (PostgreSQL)

```bash
docker compose up --build
```

Затем в другом терминале применить миграции и запустить парсер:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py parse_product
```

Если нужен поиск через браузер (Selenium/Playwright), образ собирается с
браузером — это долго и весит больше:

```bash
docker compose build --build-arg INSTALL_BROWSERS=1
docker compose up -d
docker compose exec web python manage.py parse_search --engine playwright
```

Сборка с `INSTALL_BROWSERS=1` ставит Chromium для Playwright (`--with-deps`) и
сразу же скачивает подходящий `chromedriver` через Selenium Manager. Поэтому
шаги 1-4 работают в контейнере даже без доступа в интернет на этапе запуска.
Без этого флага Selenium сам попробует скачать драйвер при первом запуске —
это требует сети и прав на запись в `~/.cache/selenium`.

### Вариант 2. Локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Для браузерных парсеров нужен Chromium:

```bash
python -m playwright install chromium
```

Selenium сам найдёт браузер: сначала системный Chrome/Chromium, потом Chromium
из кэша Playwright (`find_browser_binary`), а `chromedriver` подтянет Selenium
Manager при первом запуске. Если браузер лежит в нестандартном месте — путь
передаётся явно: `--chrome-binary /path/to/chrome`.

С PostgreSQL (по умолчанию хост `db`) или без него — для быстрого запуска
есть SQLite-фолбэк:

```bash
USE_SQLITE=1 python manage.py migrate
USE_SQLITE=1 python manage.py parse_product
```

## Использование

### Поиск через браузер (Шаги 1-6)

```bash
python manage.py parse_search --engine playwright
python manage.py parse_search --engine selenium --no-headless
python manage.py parse_search --engine selenium --query "Apple iPhone 15 128GB Black"
python manage.py parse_search --engine selenium --chrome-binary /usr/bin/chromium
python manage.py parse_search --engine selenium --no-save     # без записи в БД
```

Команда выводит JSON с данными товара и сохраняет его в БД (та же модель, что и
у `parse_product`). Тот же сценарий можно запустить как скрипт:

```bash
python -m products.services.selenium_parser "Apple iPhone 15 128GB Black"
python -m products.services.playwright_parser "Apple iPhone 15 128GB Black"
```

### Парсинг по прямой ссылке

```bash
python -m products.services.hi_parser
python -m products.services.hi_parser "<URL товара>"
python manage.py parse_product
python manage.py parse_product "<URL товара>"
```

HTTP-эндпоинт:

```
GET /products/parse/?url=<URL товара>
```

Возвращает JSON `{"saved": true, "id": ..., "product": {...}}` и сохраняет
товар в БД. Без параметра `url` парсится товар из задания.

### Шаг-7: выгрузка в CSV

```bash
python manage.py export_csv                        # stdout
python manage.py export_csv --output /tmp/products.csv
```

```
GET /products/export/csv/          # скачивание файла products.csv
```

В файл попадают поля из `CSV_FIELDS` (URL, название, код, цена, фото и т.д.),
файл пишется в UTF-8 с BOM, чтобы Excel корректно открывал кириллицу.

### Веб-страница с кнопкой

```
GET /products/
```

Страница с предзаполненным URL товара и кнопкой **Parse**: по клику JS
обращается к `/products/parse/`, сохраняет товар и выводит полученный JSON
в блок на странице (ошибки парсинга показываются там же).

## Тесты

```bash
USE_SQLITE=1 python manage.py test
docker compose exec web python manage.py test
```

64 теста, сеть и браузер не используются: HTTP-клиенты, драйвер Selenium и
страница Playwright подменяются моками, HTML берётся из фикстуры. Проверяются
`/products/` и `/products/parse/`, разбор HTML, браузерные шаги 1-6 (в том числе
сброс cookie, челлендж Cloudflare, перезапуск сессии, страховки при пропавшей
разметке), поиск браузера для Selenium, команда `parse_search` и выгрузка в CSV.

## Структура

```
config/                         настройки Django
products/
  models.py                     модель Product
  views.py                      /products/, /products/parse/, /products/export/csv/
  admin.py                      админка для Product
  templates/products/index.html UI: кнопка Parse + вывод JSON
  tests.py                      тесты (без сети и браузера)
  services/
    search_flow.py              общие для браузеров селекторы, URL и проверки
    selenium_parser.py          Шаги 1-6 на Selenium
    playwright_parser.py        Шаги 1-6 на Playwright
    hi_scraper.py               загрузка HTML (requests, резерв — curl_cffi)
    hi_parser.py                разбор HTML в словарь
    csv_export.py               сборка CSV из Product
  management/commands/
    parse_product.py            CLI: парсинг + сохранение
    parse_search.py             CLI: поиск браузером + печать + сохранение
    export_csv.py               CLI: выгрузка товаров в CSV
```
