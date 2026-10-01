"""Товар без стока («Предзаказ») — мобильная версия (зеркало
tests/test_preorder_product.py).

На телефоне страница предзаказа та же (проверено 30.09.2026 в MCP-браузере на
ширине 412): видимая «Предзаказ» под ценой, −/+ заблокированы, «Покупка в
один клик» disabled, «В кредит» нет, активной цены нет. Десктопные селекторы
уже отсеивают мобильные дубли через `:visible`/`.first`, а фикстура не
навязывает ширину окна — поэтому и тесты, и autouse-фикстура импортированы
как есть.

Своё здесь — липкая нижняя панель `.bottom-buy-bar`: вверху страницы её нет,
после прокрутки она показывает ту же «Предзаказ» (активную) и иконку «в один
клик» (disabled), и её «Предзаказ» открывает тот же поп-ап.
"""

import re

from playwright.sync_api import Page, expect

from test_preorder_product import (  # noqa: F401 — тесты и фикстуру собирает pytest
    MODAL_PREORDER,
    PRODUCT_NAME,
    open_product_page,
    test_preorder_button_shown_instead_of_add_cart,
    test_price_not_displayed,
    test_quantity_controls_disabled,
    test_one_click_and_credit_disabled,
    test_open_preorder_popup,
    test_preorder_popup_empty_phone_validation,
    test_preorder_popup_accepts_valid_phone,
    test_close_preorder_popup,
    test_preorder_does_not_add_to_cart,
)

BOTTOM_BAR = ".bottom-buy-bar"
BAR_PREORDER = f"{BOTTOM_BAR} button.btn__add_cart_preorder"
BAR_ONE_CLICK = f"{BOTTOM_BAR} button.btn__buy_click"


def _scroll_until_bottom_bar(page: Page) -> None:
    """Прокручивать, пока не покажется нижняя панель (она появляется по
    событию прокрутки, scrollTo не годится)."""
    for _ in range(10):
        page.mouse.wheel(0, 400)
        try:
            expect(page.locator(BOTTOM_BAR)).to_be_visible(timeout=1_000)
            return
        except AssertionError:
            continue
    expect(page.locator(BOTTOM_BAR)).to_be_visible()


# ===========================================================================
# Мобильная нижняя панель в режиме предзаказа
# ===========================================================================
def test_bottom_bar_in_preorder_mode(page: Page):
    """После прокрутки нижняя панель показывает активную «Предзаказ» и
    неактивную «в один клик»; «Предзаказ» оттуда открывает поп-ап."""
    expect(page.locator(BOTTOM_BAR)).to_be_hidden()
    _scroll_until_bottom_bar(page)

    preorder = page.locator(BAR_PREORDER)
    expect(preorder).to_be_visible()
    expect(preorder).to_have_text(re.compile(r"Предзаказ", re.I))
    expect(preorder).to_be_enabled()
    expect(page.locator(BAR_ONE_CLICK)).to_be_disabled()

    modal = page.locator(MODAL_PREORDER)
    for _ in range(3):
        if modal.count():
            break
        preorder.tap()
        try:
            expect(modal).to_be_visible(timeout=4_000)
        except AssertionError:
            continue
    expect(modal).to_be_visible()
    expect(modal.locator("h4").filter(has_text=re.compile(r"Предзаказ", re.I)).first).to_be_visible()
    expect(modal.get_by_text(PRODUCT_NAME).first).to_be_visible()


# Реальная заявка — последней (в headless сама скипается, см. десктопный тест).
from test_preorder_product import test_preorder_real_submit_succeeds  # noqa: E402,F401
