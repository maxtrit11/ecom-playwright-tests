"""Блок «Оформление заказа» — мобильная версия (зеркало tests/test_checkout_block.py).

Форма оформления на телефоне — та же `.checkout__form` в том же поп-апе
корзины, с теми же полями, радио и кнопками (проверено в MCP-браузере).
Отличается только обвязка:
  * до формы добираемся через мобильную иконку корзины (фикстура
    `cart_with_product` из мобильного файла корзины);
  * форма на весь экран, итог, согласие и кнопка «Оформить заказ»
    прилипли к низу экрана;
  * в шапке формы есть стрелка «←» (`#step-back-button`) — шаг назад в корзину.

Поэтому десктопные тесты формы НЕ переписаны, а импортированы целиком: pytest
соберёт их в этом модуле, и фикстуру `checkout` они получат отсюда — то есть
пройдут на телефоне. Починка десктопного теста автоматически чинит мобильный.

Кейс 202 (закрыть кликом по области вокруг) не перенесён: форма на весь экран.
"""

import pytest
from playwright.sync_api import Page, expect

from mobile.test_cart_block_mobile import cart_with_product  # noqa: F401 — фикстура
from test_cart_block import _click_until
from test_checkout_block import (  # noqa: F401 — тесты и autouse-фикстуру собирает pytest
    BTN_SUBMIT_REQUEST,
    CART_MODAL_SHOWN,
    CART_PRODUCT,
    CHECKOUT_FORM,
    SIDEBAR_CHECKOUT,
    only_popup_cart_view,
    test_close_checkout_via_x,
    test_dont_call_me_reveals_messenger_field,
    test_terms_link_opens_in_new_tab,
    test_select_payment_method,
    test_select_delivery_method,
    test_select_delivery_type,
    test_region_and_city_dropdowns_open_with_items,
    test_required_fields_errors_on_empty_submit,
    test_transfer_payment_reveals_required_legal_fields,
    test_dont_call_makes_phone_optional,
    test_delivery_cost_updates_in_summary,
)

BTN_STEP_BACK = f"{CHECKOUT_FORM} #step-back-button"


@pytest.fixture
def checkout(cart_with_product: Page):
    """Форма оформления открыта: товар в корзине → «Оформить заявку»."""
    page = cart_with_product
    _click_until(
        page,
        page.locator(BTN_SUBMIT_REQUEST).first,
        lambda: page.locator(CHECKOUT_FORM).count() > 0,
    )
    expect(page.locator(CHECKOUT_FORM)).to_be_visible(timeout=10_000)
    expect(page.locator(SIDEBAR_CHECKOUT)).to_be_attached()
    return page


# ===========================================================================
# Моб.: Стрелка «←» возвращает из оформления в корзину (своего кейса в Qase нет)
# ===========================================================================
def test_step_back_returns_to_cart(checkout: Page):
    """«←» в шапке формы — шаг назад: формы нет, открыта корзина с тем же
    товаром и кнопкой «Оформить заявку». Поп-ап при этом НЕ закрывается —
    этим стрелка и отличается от крестика."""
    page = checkout

    page.locator(BTN_STEP_BACK).tap()

    expect(page.locator(CHECKOUT_FORM)).to_have_count(0)
    expect(page.locator(CART_MODAL_SHOWN)).to_be_visible()
    expect(page.locator(CART_PRODUCT)).to_have_count(1)
    expect(page.locator(BTN_SUBMIT_REQUEST).first).to_be_visible()


# Реальный заказ импортируем ПОСЛЕДНИМ, отдельно от остальных: pytest гонит
# тесты в порядке появления имён в модуле, а этот тест расходует сток товара и
# должен идти после валидационных (подробности — у него в десктопном файле).
from test_checkout_block import test_place_order_happy_path  # noqa: E402,F401
