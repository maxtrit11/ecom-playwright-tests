"""Сверка цен на витрине с данными бэкенда (stage.ecom.md, локаль /ru)

Остальные тесты суиты проверяют цены «сами с собой»: что цена есть, что
Итог == Товары − Скидка + Доставка. Такие проверки не заметят случая, когда
бэкенд отдал одну цену, а витрина нарисовала другую — арифметика сойдётся на
любых числах. Здесь закрывается именно этот разрыв.

Источник истины — SSR-пейлоад `window.__NUXT__`, который инлайнится в HTML и
доступен сразу после domcontentloaded (тем же приёмом conftest читает сток и
признак кредита). На карточке товара цены лежат в
`state.product.product`:

    price        — текущая цена, строкой: '3399.00'
    old_price    — цена до скидки: '3999.00' (None, если скидки нет)
    discount     — процент скидки числом: 15
    is_sale      — признак акции

Разметка проверена вживую 2026-08-18 на /ru/product/jbl-charge-6-purple:

    .price.new__price      «3 399 MDL»
    .price.old__price      «3 999 MDL -600 MDL»  ← внутри ДВЕ суммы
    .calculated-discount   «-600 MDL»
    .discount              «-15%»

Ловушки, заложенные в код:
- у `.old__price` в innerText попадает и сумма скидки, поэтому берём ПЕРВОЕ
  число, а не весь текст;
- суммы бывают дробными («14 449.15 MDL»), поэтому считаем в БАНАХ: наивный
  `int` по цифрам превратил бы 14 449.15 в 1444915 и сравнение развалилось бы
  (та же грабля уже ловилась в тестах сортировки);
- разряды разделяются неразрывными пробелами.

Тест листинга сверяет карточку категории с карточкой товара. Через связку с
проверкой выше это косвенно сверяет и листинг с бэкендом: цена товара уже
подтверждена пейлоадом.
"""

import re

import pytest
from playwright.sync_api import Page, expect

# Товары со скидкой: нужны, чтобы проверки старой цены и процента были
# осмысленными, а не скипались. Если ни один не подошёл — добираем с категории.
# Сток обязателен: без него витрина прячет цены и показывает «Предзаказ», хотя
# price/old_price в пейлоаде остаются. 21.10.2026 у jbl-charge-6-purple сток
# стал 0, и все четыре теста ждали на нём `.price.new__price`, которого нет.
_DISCOUNT_CANDIDATES = [
    "/ru/product/harman-kardon-onyx-studio-9-grey",
    "/ru/product/jbl-jbl-partybox-710",
    "/ru/product/jbl-charge-6-purple",
]
_CATEGORY_FALLBACK = "/ru/acustica-portabila"

CARD = ".product__item"
CARD_NAME = ".product__name"
CARD_PRICES = ".product__prices"

PDP_NEW_PRICE = ".price.new__price"
PDP_OLD_PRICE = ".price.old__price"
PDP_DISCOUNT_AMOUNT = ".calculated-discount"
PDP_DISCOUNT_PERCENT = ".discount"

_PAYLOAD_JS = """() => {
  const p = window.__NUXT__?.state?.product?.product;
  if (!p) return null;
  return {price: p.price, old_price: p.old_price, discount: p.discount, is_sale: p.is_sale, stock: p.stock};
}"""

_AMOUNT_RE = re.compile(r"(\d[\d\s ]*(?:[.,]\d{1,2})?)")


def _bani(text: str) -> int:
    """Первая сумма из текста в банах. «14 449.15 MDL» → 1444915."""
    match = _AMOUNT_RE.search(text or "")
    assert match, f"В строке {text!r} не нашли суммы"
    normalized = (
        match.group(1).replace(" ", "").replace(" ", "").replace(",", ".")
    )
    return int(round(float(normalized) * 100))


def _payload(page: Page) -> dict:
    data = page.evaluate(_PAYLOAD_JS)
    assert data is not None, (
        "В window.__NUXT__ нет state.product.product — страница товара не "
        "отрисовалась или изменилась структура пейлоада"
    )
    return data


def _is_discounted_in_stock(data: dict | None) -> bool:
    return bool(
        data
        and data.get("price")
        and data.get("old_price")
        and int(data.get("stock") or 0) > 0
    )


def _open_discounted_product(page: Page) -> dict:
    """Открыть товар со скидкой и вернуть его цены из пейлоада."""
    for i, url in enumerate(_DISCOUNT_CANDIDATES):
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        # Первый кандидат читаем строгим `_payload`: если путь в __NUXT__
        # сломается, null иначе принимался бы за «нет скидки» у всех товаров,
        # и весь файл молча уходил бы в skip.
        data = _payload(page) if i == 0 else page.evaluate(_PAYLOAD_JS)
        if _is_discounted_in_stock(data):
            return data

    # Кандидаты не подошли — ищем товар со скидкой в категории.
    page.goto(_CATEGORY_FALLBACK, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=30_000)
    hrefs = page.evaluate(
        """() => [...document.querySelectorAll('.product__item')]
             .map(c => (c.querySelector('a[href*="/product/"]')||{}).getAttribute?.('href'))
             .filter(Boolean).slice(0, 10)"""
    )
    for href in hrefs:
        page.goto(href, wait_until="domcontentloaded", timeout=60_000)
        data = page.evaluate(_PAYLOAD_JS)
        if _is_discounted_in_stock(data):
            return data

    pytest.skip("На стенде не нашли товара со скидкой — сверять старую цену не с чем")


# ===========================================================================
# Карточка товара против бэкенда
# ===========================================================================
def test_product_page_price_matches_backend(page: Page):
    """Цена на витрине совпадает с ценой, которую отдал бэкенд."""
    data = _open_discounted_product(page)

    shown = _bani(page.locator(PDP_NEW_PRICE).first.inner_text())
    expected = _bani(str(data["price"]))

    assert shown == expected, (
        f"Витрина показывает {shown / 100:.2f} MDL, а бэкенд отдал "
        f"{expected / 100:.2f} MDL ({page.url})"
    )


def test_product_page_old_price_matches_backend(page: Page):
    """Зачёркнутая цена совпадает с `old_price` из пейлоада."""
    data = _open_discounted_product(page)

    old = page.locator(PDP_OLD_PRICE).first
    expect(old).to_be_visible(timeout=15_000)

    # В innerText старой цены попадает ещё и сумма скидки — берём первую сумму.
    shown = _bani(old.inner_text())
    expected = _bani(str(data["old_price"]))

    assert shown == expected, (
        f"Зачёркнутая цена на витрине {shown / 100:.2f} MDL, в пейлоаде "
        f"old_price {expected / 100:.2f} MDL ({page.url})"
    )


def test_product_page_discount_percent_matches_backend(page: Page):
    """Процент скидки на витрине совпадает с `discount` из пейлоада."""
    data = _open_discounted_product(page)
    if not data.get("discount"):
        pytest.skip("У товара нет процента скидки в пейлоаде")

    text = page.locator(PDP_DISCOUNT_PERCENT).first.inner_text()
    match = re.search(r"(\d+)\s*%", text)
    assert match, f"В блоке скидки {text!r} нет процента"

    assert int(match.group(1)) == int(data["discount"]), (
        f"На витрине скидка {match.group(1)}%, бэкенд отдал "
        f"{data['discount']}% ({page.url})"
    )


def test_discount_amount_equals_price_difference(page: Page):
    """Сумма выгоды равна разнице старой и новой цены.

    Ловит потерю копеек при округлении: проценты могут совпадать, а
    показанная выгода не сходиться с реальной разницей.
    """
    _open_discounted_product(page)

    amount = page.locator(PDP_DISCOUNT_AMOUNT).first
    # У товара уже подтверждена старая цена — значит, сумма выгоды обязана быть.
    # Раньше мгновенный count() уводил тест в skip (и при переименованном классе).
    expect(amount, "На карточке со скидкой не показана сумма выгоды").to_be_visible(
        timeout=10_000
    )

    new_price = _bani(page.locator(PDP_NEW_PRICE).first.inner_text())
    old_price = _bani(page.locator(PDP_OLD_PRICE).first.inner_text())
    shown_benefit = _bani(amount.inner_text())

    assert shown_benefit == old_price - new_price, (
        f"Выгода на витрине {shown_benefit / 100:.2f} MDL, а разница цен "
        f"{(old_price - new_price) / 100:.2f} MDL "
        f"({old_price / 100:.2f} − {new_price / 100:.2f}) — {page.url}"
    )


# ===========================================================================
# Листинг против карточки товара
# ===========================================================================
def test_listing_card_price_matches_product_page(page: Page):
    """Цена в карточке листинга совпадает с ценой на странице товара."""
    page.goto(_CATEGORY_FALLBACK, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=30_000)

    card = page.locator(f"{CARD}:has({CARD_PRICES})").first
    if not card.count():
        pytest.skip("В категории нет карточек с ценой")

    name = (card.locator(CARD_NAME).first.inner_text() or "").strip()
    listing_price = _bani(card.locator(CARD_PRICES).first.inner_text())
    href = card.locator('a[href*="/product/"]').first.get_attribute("href")

    page.goto(href, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(PDP_NEW_PRICE).first).to_be_visible(timeout=20_000)
    pdp_price = _bani(page.locator(PDP_NEW_PRICE).first.inner_text())

    assert listing_price == pdp_price, (
        f"«{name}»: в листинге {listing_price / 100:.2f} MDL, на странице "
        f"товара {pdp_price / 100:.2f} MDL ({href})"
    )
