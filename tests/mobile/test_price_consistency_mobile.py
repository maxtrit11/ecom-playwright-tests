"""Сверка цен с бэкендом — мобильная версия (зеркало tests/test_price_consistency.py).

На телефоне цены товара показаны в ДВУХ местах (проверено 30.09.2026 в
MCP-браузере на ширине 412, /ru/product/jbl-charge-6-purple):
  * основной блок `.primary__product_info` — новая, старая, выгода, процент;
  * липкая нижняя панель `.bottom-buy-bar` (появляется после прокрутки) —
    новая, старая и выгода, БЕЗ процента.

Основной блок в DOM идёт первым, поэтому десктопные тесты (`.first`) на
телефоне читают именно его — они импортированы как есть. Нижнюю панель не
проверяет никто, кроме теста ниже: она рисуется отдельным компонентом и
может разойтись с основным блоком и с бэкендом независимо от него.
"""

from playwright.sync_api import Page, expect

from test_price_consistency import (  # noqa: F401 — тесты собирает pytest
    PDP_DISCOUNT_AMOUNT,
    PDP_NEW_PRICE,
    PDP_OLD_PRICE,
    _bani,
    _open_discounted_product,
    test_product_page_price_matches_backend,
    test_product_page_old_price_matches_backend,
    test_product_page_discount_percent_matches_backend,
    test_discount_amount_equals_price_difference,
    test_listing_card_price_matches_product_page,
)

BOTTOM_BAR = ".bottom-buy-bar"


def _show_bottom_bar(page: Page):
    """Прокручивать, пока не покажется нижняя панель (появляется по событию
    прокрутки, scrollTo не годится)."""
    bar = page.locator(BOTTOM_BAR)
    for _ in range(10):
        page.mouse.wheel(0, 400)
        try:
            expect(bar).to_be_visible(timeout=1_000)
            return bar
        except AssertionError:
            continue
    expect(bar).to_be_visible()
    return bar


# ===========================================================================
# Нижняя панель покупки против бэкенда (только мобильная вёрстка)
# ===========================================================================
def test_bottom_bar_prices_match_backend(page: Page):
    """Новая и старая цена в нижней панели совпадают с `price`/`old_price`
    бэкенда, а выгода в ней — с их разницей."""
    data = _open_discounted_product(page)
    bar = _show_bottom_bar(page)

    new_price = _bani(bar.locator(PDP_NEW_PRICE).inner_text())
    old_price = _bani(bar.locator(PDP_OLD_PRICE).inner_text())
    expected_new = _bani(str(data["price"]))
    expected_old = _bani(str(data["old_price"]))

    assert new_price == expected_new, (
        f"В нижней панели цена {new_price / 100:.2f} MDL, бэкенд отдал "
        f"{expected_new / 100:.2f} MDL ({page.url})"
    )
    assert old_price == expected_old, (
        f"В нижней панели зачёркнутая {old_price / 100:.2f} MDL, в пейлоаде "
        f"old_price {expected_old / 100:.2f} MDL ({page.url})"
    )

    amount = bar.locator(PDP_DISCOUNT_AMOUNT)
    if amount.count():
        benefit = _bani(amount.inner_text())
        assert benefit == expected_old - expected_new, (
            f"Выгода в нижней панели {benefit / 100:.2f} MDL, а разница цен "
            f"{(expected_old - expected_new) / 100:.2f} MDL ({page.url})"
        )
