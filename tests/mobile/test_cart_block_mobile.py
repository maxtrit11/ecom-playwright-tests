"""Блок «Корзина» — мобильная версия (зеркало tests/test_cart_block.py).

Корзина на телефоне — тот же поп-ап `.modal__cart` с теми же кнопками внутри
(проверено в MCP-браузере), поэтому селекторы содержимого и хелперы берём из
десктопного файла. Отличается немногое:
  * иконка корзины — в мобильной шапке `.header__mobile_ecom .btn__cart`
    (без `title`); десктопная `[title="Корзина"]` на телефоне скрыта;
  * поп-ап занимает весь экран и выезжает с анимацией.

Кейс 106 (закрыть кликом по области вокруг) не перенесён: поп-ап на весь
экран, области вокруг нет.
"""

import re

import pytest
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from test_cart_block import (  # noqa: F401 — only_popup_cart_view: autouse-фикстура
    BTN_ADD_TO_CART,
    BTN_CLEAR_ALL,
    BTN_CLOSE,
    BTN_DELETE_ONE,
    BTN_MINUS,
    BTN_PLUS,
    BTN_SUBMIT_REQUEST,
    CART_MODAL_SHOWN,
    CART_PRODUCT,
    CHECKOUT_FORM,
    EMPTY_STUB,
    _click_until,
    _hide_b24_widget,
    _quantity_of_first_item,
    _reset_cart_storage,
    only_popup_cart_view,
)

# Иконка корзины в мобильной шапке
HEADER_CART_BTN = ".header__mobile_ecom .btn__cart"
# Выезжающая панель поп-апа. Не `.cart__sidebar`: у пустой корзины сайдбара
# с итогом нет вовсе, а панель есть всегда.
CART_PANEL = f"{CART_MODAL_SHOWN} .cart__content"


# ---------------------------------------------------------------------------
# Хелперы — мобильные версии тех, что завязаны на иконку корзины в шапке
# ---------------------------------------------------------------------------
def _open_cart_drawer(page: Page):
    """Открыть поп-ап корзины и дождаться, пока он выедет на экран."""
    _hide_b24_widget(page)
    _click_until(
        page,
        page.locator(HEADER_CART_BTN),
        lambda: page.locator(CART_MODAL_SHOWN).count() > 0,
    )
    expect(page.locator(CART_MODAL_SHOWN)).to_be_visible(timeout=10_000)
    # Панель выезжает с анимацией — ждём, пока она почти целиком на экране.
    expect(page.locator(CART_PANEL)).to_be_in_viewport(ratio=0.9)
    _hide_b24_widget(page)


def _click_add_to_cart(page: Page):
    """«В корзину» на открытой PDP; признак добавления — смена надписи на
    иконке корзины в шапке (подробности — в десктопном файле)."""
    add_btn = page.locator(BTN_ADD_TO_CART).first
    expect(add_btn).to_be_visible(timeout=15_000)
    header_cart = page.locator(HEADER_CART_BTN)
    label_before = header_cart.inner_text()
    _click_until(page, add_btn, lambda: header_cart.inner_text() != label_before)


def _add_one_product_to_cart(page: Page, product_url: str):
    """Открыть PDP и добавить товар в корзину, где УЖЕ что-то лежит.

    Сначала ждём сумму в шапке: на свежей странице надпись ~3 с врёт
    «Корзина» даже при непустой корзине.
    """
    page.goto(product_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(HEADER_CART_BTN)).to_contain_text("MDL", timeout=15_000)
    _click_add_to_cart(page)


def _close_drawer(page: Page, button):
    _click_until(page, button, lambda: page.locator(CART_MODAL_SHOWN).count() == 0)


@pytest.fixture
def cart_with_product(page: Page, in_stock_product: str):
    """Поп-ап корзины открыт, в корзине ровно один товар."""
    page.context.clear_cookies()
    page.goto(in_stock_product, wait_until="domcontentloaded", timeout=60_000)
    _reset_cart_storage(page)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("h1")).to_be_visible(timeout=15_000)
    _hide_b24_widget(page)

    # Остатки прошлой сессии на сервере — чистим через UI.
    _open_cart_drawer(page)
    if page.locator(CART_PRODUCT).count() > 0:
        _click_until(
            page,
            page.locator(BTN_CLEAR_ALL).first,
            lambda: page.locator(CART_PRODUCT).count() == 0,
        )
    _close_drawer(page, page.locator(BTN_CLOSE))

    # Корзину на этой странице уже открывали, поэтому после добавления сайт
    # ~через 1 с перечитывает её с сервера (GET /api/cart-redis). Серверная копия —
    # с `productId` строкой, как на PDP; число из него делает открытие корзины.
    # Откроем корзину раньше этого GET — он затрёт исправленный id обратно
    # строкой, и заказ уйдёт с "12563" → 400 «При создании заказа произошла
    # ошибка» (мобильный happy path на Partybox, разбор 02.10.2026). Человек
    # быстрее секунды корзину не открывает, поэтому ждём синхронизацию, как он.
    # Не дождались — идём дальше: GET мог и не понадобиться.
    try:
        with page.expect_response(
            lambda r: "/api/cart-redis" in r.url and r.request.method == "GET",
            timeout=5_000,
        ):
            _click_add_to_cart(page)
    except PlaywrightTimeoutError:
        pass
    _open_cart_drawer(page)
    expect(page.locator(CART_PRODUCT).first).to_be_visible(timeout=10_000)
    return page


# ===========================================================================
# Кейс 105 (моб.): Закрыть блок Корзина нажав на кнопку Х
# ===========================================================================
def test_close_cart_via_x_button(cart_with_product: Page):
    page = cart_with_product

    _close_drawer(page, page.locator(BTN_CLOSE))

    expect(page.locator(CART_MODAL_SHOWN)).to_have_count(0, timeout=5_000)
    expect(page.locator("h1")).to_be_visible()


# ===========================================================================
# Кейс 107 (моб.): Удалить товар нажав на кнопку Удалить в карточке товара
# ===========================================================================
def test_delete_one_product_from_cart(cart_with_product: Page, in_stock_products: list):
    page = cart_with_product

    second_url = in_stock_products[1] if len(in_stock_products) > 1 else in_stock_products[0]
    _close_drawer(page, page.locator(BTN_CLOSE))
    _add_one_product_to_cart(page, second_url)
    _open_cart_drawer(page)

    expect(page.locator(CART_PRODUCT).first).to_be_visible()
    count_before = page.locator(CART_PRODUCT).count()
    assert count_before >= 2, f"Ожидалось ≥2 товара, фактически {count_before}"

    _click_until(
        page,
        page.locator(BTN_DELETE_ONE).first,
        lambda: page.locator(CART_PRODUCT).count() == count_before - 1,
    )

    count_after = page.locator(CART_PRODUCT).count()
    assert count_after == count_before - 1, (
        f"Карточек не стало меньше на 1: {count_before} → {count_after}"
    )


# ===========================================================================
# Кейс 108 (моб.): Отображение заглушки при удалении последней карточки
# ===========================================================================
def test_empty_stub_when_removing_last_product(cart_with_product: Page):
    page = cart_with_product
    assert page.locator(CART_PRODUCT).count() == 1

    _click_until(
        page,
        page.locator(BTN_DELETE_ONE).first,
        lambda: page.locator(CART_PRODUCT).count() == 0,
    )

    expect(page.locator(CART_PRODUCT)).to_have_count(0)
    expect(page.locator(EMPTY_STUB)).to_be_visible(timeout=5_000)
    expect(page.locator(EMPTY_STUB)).to_contain_text(
        re.compile(r"Здесь.*пока.*ничего.*нет", re.IGNORECASE)
    )


# ===========================================================================
# Кейс 109 (моб.): Увеличить количество кнопкой «+»
# ===========================================================================
def test_increase_quantity_plus(cart_with_product: Page):
    page = cart_with_product

    expect(page.locator(BTN_MINUS).first).to_have_class(re.compile(r"\bdisabled\b"))

    qty_before = _quantity_of_first_item(page)
    _click_until(
        page,
        page.locator(BTN_PLUS).first,
        lambda: _quantity_of_first_item(page) == qty_before + 1,
    )

    qty_after = _quantity_of_first_item(page)
    assert qty_after == qty_before + 1, (
        f"Количество не увеличилось на 1: {qty_before} → {qty_after}"
    )
    expect(page.locator(BTN_MINUS).first).not_to_have_class(re.compile(r"\bdisabled\b"))


# ===========================================================================
# Кейс 110 (моб.): Уменьшить количество кнопкой «-»
# ===========================================================================
def test_decrease_quantity_minus(cart_with_product: Page):
    page = cart_with_product

    _click_until(
        page,
        page.locator(BTN_PLUS).first,
        lambda: _quantity_of_first_item(page) == 2,
    )
    assert _quantity_of_first_item(page) == 2

    _click_until(
        page,
        page.locator(BTN_MINUS).first,
        lambda: _quantity_of_first_item(page) == 1,
    )

    qty_after = _quantity_of_first_item(page)
    assert qty_after == 1, f"Количество не уменьшилось на 1: 2 → {qty_after}"
    expect(page.locator(BTN_MINUS).first).to_have_class(re.compile(r"\bdisabled\b"))


# ===========================================================================
# Кейс 114 (моб.): Открыть «Оформление заказа» через «Оформить заявку»
# ===========================================================================
def test_open_checkout_via_submit_button(cart_with_product: Page):
    page = cart_with_product

    _click_until(
        page,
        page.locator(BTN_SUBMIT_REQUEST).first,
        lambda: page.locator(CHECKOUT_FORM).count() > 0,
    )

    expect(page.locator(CHECKOUT_FORM)).to_be_visible(timeout=10_000)
    expect(page.locator(".cart__sidebar--checkout")).to_be_visible()


# ===========================================================================
# Кейс 245 (моб.): Закрыть корзину кнопкой «Продолжить покупки»
# ===========================================================================
def test_close_cart_via_continue_shopping(cart_with_product: Page):
    page = cart_with_product

    cont_btn = (
        page.locator(f"{CART_MODAL_SHOWN} button.request")
        .filter(has_text=re.compile(r"Продолжить.*покупк", re.IGNORECASE))
        .first
    )
    expect(cont_btn).to_be_visible()
    _close_drawer(page, cont_btn)

    expect(page.locator(CART_MODAL_SHOWN)).to_have_count(0, timeout=5_000)


# ===========================================================================
# Кейс 246 (моб.): Очистить корзину кнопкой «Очистить корзину»
# ===========================================================================
def test_clear_cart_via_clear_button(cart_with_product: Page):
    page = cart_with_product
    assert page.locator(CART_PRODUCT).count() >= 1

    clear_btn = page.locator(BTN_CLEAR_ALL).first
    expect(clear_btn).to_be_visible()
    expect(clear_btn).to_contain_text(re.compile(r"Очистить.*корзин", re.IGNORECASE))
    _click_until(page, clear_btn, lambda: page.locator(CART_PRODUCT).count() == 0)

    expect(page.locator(CART_PRODUCT)).to_have_count(0, timeout=10_000)
