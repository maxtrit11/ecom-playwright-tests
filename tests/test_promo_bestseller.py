"""Тесты подборки «Bestseller» (`/ru/promo/bestseller`).

Подборка — это товары со статусом `bestseller` (в данных товара
`status: [{slug: "bestseller", key: "Bestseller", id: 3757}, ...]`; у товара
может быть сразу несколько статусов — sale, new, bestseller). Проверено
вживую 2026-10-12:

- Страница — обычный листинг (как категория): заголовок `.category-title`
  («Bestseller (7 товаров)»), крошки «Главная / Bestseller», сайдбар
  фильтров, сортировка. Данные первой загрузки —
  `window.__NUXT__.state.products` (`products`, `totalCount`,
  `currentCategory` = сам статус).
- Фильтры и сортировка уходят в API
  `stage.admin.ecom.md/general/v2/status/bestseller/?page=&sortBy=&filters=`
  (фильтры в JSON-формате, не как в адресе страницы — см. test_brands.py).
  Ответ проверяем: после любого фильтра в выдаче только бестселлеры.
- На карточке и на странице товара бейдж `.badge.badge-custom` «Bestseller».
- На главной карусель «Bestseller» с кнопкой «Смотреть все» → эта страница.
- ТОВАР БЕЗ ЦЕНЫ уходит в предзаказ — ТАК ЗАДУМАНО (подтвердил юзер
  12.10.2026). На 12.10 это PartyBox 520 (`price: null`, сток 942): на
  карточке «Нет в наличии», на своей странице «Предзаказ», а фильтр
  «В наличии» (по стоку) его пропускает. Поэтому товар без цены — законное
  исключение в проверке «В наличии» и в порядке цен (сравнивать нечего).
- Заголовок без «(N товаров)» — в отличие от бренда, считаем по «Найдено».
- Есть такие же страницы `/ru/promo/new` и `/ru/promo/sale`; неизвестный
  статус → 404.
"""

import re
from urllib.parse import unquote

import pytest
from playwright.sync_api import Page, expect

from test_brands import _check_option_filter, _card_slugs
from test_category_filters import _found_count, _sidebar, _wait_found_count
from test_sorting import _pick_sort

STATUS = "bestseller"
PROMO_URL = f"/ru/promo/{STATUS}"
HOME_URL = "/ru"
UNKNOWN_URL = "/ru/promo/qa-nonexistent-status"
STATUS_API = f"/general/v2/status/{STATUS}/"

CARD = ".product__items .product__item"
CARD_BADGE = ".badge.badge-custom"
OUT_OF_STOCK = ".product__out-of-stock-label"
TITLE_BLOCK = ".category-title"
BREADCRUMB_ITEM = ".breadcrumb .breadcrumb__item"
IN_STOCK_SWITCH = ".filters-vertical__in-stock button.ui-switch-toggler__switch"
CAROUSEL = ".products__wrapper"
ERROR_PAGE = ".error-page"
PRODUCT_BADGE = ".primary__product_info .badge.badge-custom, .product__slider .badge.badge-custom"

SORT_LOWEST_PRICE = "От самой низкой цены"

PAGE_JS = """() => {
    const s = window.__NUXT__?.state?.products || {};
    return {
        name: s.currentCategory?.name,
        total: s.totalCount,
        products: (s.products || []).map(p => ({
            url: p.url, stock: p.stock, price: p.price,
            statuses: (p.status || []).map(x => x.slug),
        })),
    };
}"""


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _page_data(page: Page) -> dict:
    return page.evaluate(PAGE_JS)


def _not_bestsellers(products: list[dict]) -> list[str]:
    return [p["url"] for p in products if STATUS not in p["statuses"]]


def _api_products(payload: dict) -> list[dict]:
    """Товары из ответа API статуса в том же виде, что `PAGE_JS`."""
    return [
        {
            "url": p["url"],
            "stock": p.get("stock"),
            "price": p.get("price"),
            "statuses": [s.get("slug") for s in (p.get("status") or [])],
        }
        for p in payload["data"]["products"]
    ]


def _status_payload(page: Page, action, *must_contain: str) -> dict:
    """Выполнить `action` и вернуть JSON ответа API статуса (ждём именно
    ответ, а не networkidle — см. test_brands.py)."""

    def matches(response) -> bool:
        url = unquote(response.url)
        return STATUS_API in url and response.request.method == "GET" and all(
            s in url for s in must_contain
        )

    with page.expect_response(matches, timeout=30_000) as info:
        action()
    response = info.value
    assert response.ok, f"API статуса ответил {response.status}: {unquote(response.url)}"
    return response.json()


@pytest.fixture
def promo(page: Page) -> Page:
    page.goto(PROMO_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(_sidebar(page)).to_be_visible(timeout=30_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=30_000)
    return page


# ===========================================================================
# Страница подборки
# ===========================================================================
def test_bestseller_page_header_and_counters(promo: Page):
    """Заголовок = название статуса, крошки «Главная / Bestseller», и все
    счётчики (заголовок, «Найдено товаров», карточки, данные) совпадают."""
    page = promo
    data = _page_data(page)

    expect(page.locator(f"{TITLE_BLOCK} h1")).to_have_text(data["name"])
    crumbs = page.locator(BREADCRUMB_ITEM)
    expect(crumbs).to_have_count(2)
    expect(crumbs.last).to_have_text(re.compile(re.escape(data["name"]), re.I))

    found = _found_count(page)
    assert found == data["total"], f"«Найдено товаров: {found}», а в данных {data['total']}"
    if data["total"] <= len(data["products"]):
        assert len(_card_slugs(page)) == found, (
            f"Карточек {len(_card_slugs(page))}, а «Найдено товаров» {found}"
        )


def test_every_product_is_bestseller(promo: Page):
    """У каждого товара подборки статус bestseller — и в данных, и бейджем
    «Bestseller» на карточке."""
    page = promo
    data = _page_data(page)

    wrong = _not_bestsellers(data["products"])
    assert not wrong, f"В подборке товары без статуса {STATUS}: {wrong}"

    cards = page.locator(CARD)
    no_badge = [
        _card_slugs(page)[i]
        for i in range(cards.count())
        if not cards.nth(i).locator(CARD_BADGE, has_text=re.compile(r"Bestseller", re.I)).count()
    ]
    assert not no_badge, f"Карточки без бейджа «Bestseller»: {no_badge}"


def test_product_page_shows_bestseller_badge(promo: Page):
    """Товар из подборки и на своей странице помечен «Bestseller»."""
    page = promo
    slug = _card_slugs(page)[0]

    page.locator(f'{CARD} a[href$="/product/{slug}"]').first.click()

    expect(page).to_have_url(re.compile(rf"/product/{re.escape(slug)}"), timeout=30_000)
    expect(
        page.locator(PRODUCT_BADGE).filter(has_text=re.compile(r"Bestseller", re.I)).first
    ).to_be_visible(timeout=20_000)


def test_homepage_carousel_see_all_opens_bestseller(page: Page):
    """На главной «Смотреть все» у карусели «Bestseller» открывает подборку,
    и все товары карусели в ней есть."""
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    index = page.evaluate(
        """(href) => [...document.querySelectorAll('.products__wrapper')]
            .findIndex(b => b.querySelector('a[href$="' + href + '"]'))""",
        PROMO_URL,
    )
    if index < 0:
        pytest.skip("На главной нет карусели со ссылкой на подборку Bestseller")
    carousel = page.locator(CAROUSEL).nth(index)

    # Карусели монтируются лениво и по порядку — прокручиваем все до нужной
    # (см. test_homepage.py: без прокрутки карточек в DOM нет).
    for i in range(index + 1):
        page.locator(CAROUSEL).nth(i).scroll_into_view_if_needed()
    expect(carousel.locator(".product__item").first).to_be_visible(timeout=20_000)
    in_carousel = set(
        carousel.evaluate(
            """b => [...b.querySelectorAll('.product__item a[href*="/product/"]')]
                .map(a => a.getAttribute('href').split('?')[0].split('/').pop())"""
        )
    )

    carousel.locator(f'a[href$="{PROMO_URL}"]').first.click()

    expect(page).to_have_url(re.compile(rf"{re.escape(PROMO_URL)}/?$"), timeout=30_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=30_000)
    on_page = set(p["url"] for p in _page_data(page)["products"])
    missing = sorted(in_carousel - on_page)
    assert not missing, f"Товары из карусели «Bestseller» не нашлись в подборке: {missing}"


# ===========================================================================
# Фильтры и сортировка
# ===========================================================================
def test_in_stock_filter_keeps_only_available_bestsellers(promo: Page):
    """«В наличии»: сервер вернул только бестселлеры со стоком, на странице
    ни одной карточки «Нет в наличии», счётчик пересчитан."""
    page = promo
    payload = _status_payload(page, page.locator(IN_STOCK_SWITCH).click, '"inStock"')
    products = _api_products(payload)

    assert not _not_bestsellers(products), (
        f"С фильтром «В наличии» в подборке не-бестселлеры: {_not_bestsellers(products)}"
    )
    no_stock = [p["url"] for p in products if (p["stock"] or 0) <= 0]
    assert not no_stock, f"С фильтром «В наличии» сервер вернул товары без стока: {no_stock}"

    count = _wait_found_count(page, payload["totalCount"])
    assert count == payload["totalCount"], (
        f"Сервер вернул {payload['totalCount']} товаров, а счётчик {count}"
    )
    # «Нет в наличии» допустимо только у товара без цены (см. шапку файла).
    no_price = {p["url"] for p in products if p["price"] is None}
    labelled = set(
        page.evaluate(
            """() => [...document.querySelectorAll('.product__items .product__item')]
                .filter(c => { const l = c.querySelector('.product__out-of-stock-label');
                               return l && l.getBoundingClientRect().height > 0; })
                .map(c => c.querySelector('a[href*="/product/"]')
                    .getAttribute('href').split('?')[0].split('/').pop())"""
        )
    )
    unexpected = sorted(labelled - no_price)
    assert not unexpected, (
        f"С фильтром «В наличии» карточки «Нет в наличии» у товаров с ценой: {unexpected}"
    )


def test_category_filter_keeps_only_bestsellers(promo: Page):
    """Галочка категории: товаров столько, сколько в скобках, после снятия —
    исходная выдача (общий сценарий из test_brands.py)."""
    _check_option_filter(promo, "sp-key-categoryId-", "categoryId:")


def test_sort_lowest_price_matches_backend(promo: Page):
    """«От самой низкой цены»: карточки в порядке ответа сервера, в ответе
    только бестселлеры, и цены по возрастанию внутри групп «в наличии» /
    «без стока» (товары в наличии всегда первыми — как и на бренде)."""
    page = promo
    payload = _status_payload(page, lambda: _pick_sort(page, SORT_LOWEST_PRICE), "sortBy=price-")
    products = _api_products(payload)

    assert not _not_bestsellers(products), f"В ответе не-бестселлеры: {_not_bestsellers(products)}"
    assert _card_slugs(page) == [p["url"] for p in products], (
        f"Карточки {_card_slugs(page)} не в порядке ответа сервера {[p['url'] for p in products]}"
    )
    for in_stock, group in ((True, "в наличии"), (False, "без стока")):
        # Товар без цены сравнить не с чем (см. шапку файла) — пропускаем.
        prices = [
            float(p["price"]) for p in products
            if p["price"] is not None and ((p["stock"] or 0) > 0) == in_stock
        ]
        assert prices == sorted(prices), f"Товары {group} не по возрастанию цены: {prices}"


# ===========================================================================
# Ошибки и локаль
# ===========================================================================
def test_unknown_status_shows_404(page: Page):
    """Несуществующий статус — HTTP 404 и страница ошибки."""
    response = page.goto(UNKNOWN_URL, wait_until="domcontentloaded", timeout=60_000)

    assert response is not None and response.status == 404, (
        f"Несуществующий статус вернул HTTP {response.status if response else None}, ждали 404"
    )
    expect(page.locator(ERROR_PAGE)).to_be_visible(timeout=20_000)


def test_bestseller_in_romanian(promo: Page):
    """`/ro/promo/bestseller` — те же товары, что и на /ru."""
    page = promo
    ru = sorted(p["url"] for p in _page_data(page)["products"])

    page.goto(f"/ro/promo/{STATUS}", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_function("() => document.documentElement.lang === 'ro'", timeout=20_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=30_000)

    ro = sorted(p["url"] for p in _page_data(page)["products"])
    assert ro == ru, f"На /ro товары {ro}, на /ru {ru}"
