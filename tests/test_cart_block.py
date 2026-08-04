"""Тесты блока «Корзина» (Qase suite 18: Блок Корзина).

Адаптировано под реальную реализацию stage.ecom.md (проверено через MCP):
- Иконка корзины в шапке: `button.btn__action.btn__cart[title="Корзина"]`.
- Сам дровер: `.modal__cart` (получает класс `show` при открытии),
  внутренняя панель — `.cart__sidebar`.
- Карточка товара в корзине: `.cart__product`.
- Кнопка X: `button.btn__close[title="Закрыть корзину"]`.
- Кнопка очистки всей корзины: `button.cart-products__header__clear-btn`
  с текстом «Очистить корзину».
- Кнопка удаления одного товара: `.cart__product button.btn__delete[title="Удалить товар"]`.
- +/-: `button.item__control.plus` / `button.item__control.minus`
  (у `minus` класс `disabled` когда количество = 1).
- «Оформить заявку»: `button.request[title="Следующий шаг"]`. После клика
  внутри `.modal__cart.show` рендерится `.checkout__form` (форма
  оформления заказа), а `.cart__sidebar` получает модификатор
  `cart__sidebar--checkout`.
- «Продолжить покупки» — второй `button.request` без `title`,
  ищем по тексту.
- Заглушка пустой корзины: `.cart__items-container.cart__items-container--empty`
  с текстом «Здесь пока ничего нет».
"""

import re
from typing import Callable

import pytest
from playwright.sync_api import Locator, Page, expect


# Товар(ы) выбираются динамически фикстурой `in_stock_products` (conftest.py):
# если у товара нет стока — берётся следующий доступный.

# Кнопка «В корзину» на странице товара
BTN_ADD_TO_CART = "button.btn__add_cart"

# Иконка корзины в шапке
HEADER_CART_BTN = 'button.btn__action.btn__cart[title="Корзина"]'

# Дровер
CART_MODAL = ".modal__cart"
CART_MODAL_SHOWN = ".modal__cart.show"
CART_SIDEBAR = ".cart__sidebar"
CART_PRODUCT = ".cart__product"

# Кнопки внутри дровера
BTN_CLOSE = '.modal__cart button.btn__close[title="Закрыть корзину"]'
BTN_CLEAR_ALL = "button.cart-products__header__clear-btn"
BTN_DELETE_ONE = '.cart__product button.btn__delete[title="Удалить товар"]'
BTN_MINUS = ".cart__product button.item__control.minus"
BTN_PLUS = ".cart__product button.item__control.plus"
BTN_SUBMIT_REQUEST = 'button.request[title="Следующий шаг"]'  # «Оформить заявку»

# Чекаут-блок (рендерится в том же модале вместо списка)
CHECKOUT_FORM = ".checkout__form"

# Заглушка пустой корзины
EMPTY_STUB = ".cart__items-container--empty"


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _reset_cart_storage(page: Page):
    """Сбрасываем хранилища анонимной корзины."""
    page.evaluate(
        """() => {
            ['cart-data', 'cart-version', 'cart-owner-token'].forEach(k => {
                try { localStorage.removeItem(k); } catch (e) {}
            });
            ['cart', 'cart-owner-token'].forEach(name => {
                document.cookie = name + '=; path=/; max-age=0';
            });
        }"""
    )


def _hide_b24_widget(page: Page):
    """Bitrix24-чат-виджет перехватывает клики по кнопкам корзины
    (его popup плавает поверх сайдбара). Удаляем все его элементы."""
    page.evaluate(
        """() => {
            document.querySelectorAll('[class*="b24-widget"]').forEach(el => el.remove());
        }"""
    )


def _click_until(
    page: Page,
    button: Locator,
    done: Callable[[], bool],
    attempts: int = 3,
    timeout_ms: int = 5_000,
    **click_kwargs,
) -> None:
    """Кликнуть и дождаться фактического изменения корзины, повторив клик.

    Виджет корзины перерисовывается при открытии дровера и после каждой
    операции, и первый клик по свежеотрисованной кнопке регулярно теряется:
    обработчик ещё не навешен, DOM не меняется вообще. В CI 2026-08-04 это
    дало «Количество не увеличилось на 1: 1 → 1» и «Карточек не стало меньше
    на 1: 2 → 2», тогда как вручную кнопки работают.

    Фиксированной паузой это не лечится: замер в браузере показал, что
    значение обновляется за ~75 мс, то есть прежних 600 мс хватало с запасом
    — терялся сам клик. Поэтому ждём результат по факту (`done()`) и только
    затем повторяем: медленный, но успешный клик мы не продублируем (иначе
    получили бы количество 3 вместо 2), а потерянный — повторим.

    Перед каждым кликом ждём, пока с кнопки снимут `disabled`: количество в
    поле обновляется раньше, чем Vue пересчитывает состояние контролов, а
    `disabled`-кнопка не принимает клик — его перехватывает `.items__counter`,
    и `click()` висит до таймаута в 45 с. Прежняя фиксированная пауза в 600 мс
    это прикрывала случайно.

    Исключение не бросаем: падать должен ассерт теста со своим сообщением.
    """
    for attempt in range(attempts):
        try:
            expect(button).not_to_have_class(
                re.compile(r"\bdisabled\b"), timeout=5_000
            )
        except AssertionError:
            pass  # не дождались — пробуем кликнуть, ассерт теста рассудит

        try:
            button.click(timeout=10_000, **click_kwargs)
        except Exception:
            if attempt == attempts - 1:
                raise
            page.wait_for_timeout(300)
            continue

        waited = 0
        while waited < timeout_ms:
            if done():
                return
            page.wait_for_timeout(100)
            waited += 100


def _open_cart_drawer(page: Page):
    """Открыть дровер корзины и дождаться появления `.show`."""
    _hide_b24_widget(page)
    page.locator(HEADER_CART_BTN).click()
    expect(page.locator(CART_MODAL_SHOWN)).to_be_visible(timeout=10_000)
    # Виджет может перерисоваться поверх дровера — убираем повторно
    _hide_b24_widget(page)


def _add_one_product_to_cart(page: Page, product_url: str):
    """Открыть PDP, нажать «В корзину»."""
    page.goto(product_url, wait_until="domcontentloaded", timeout=60_000)
    add_btn = page.locator(BTN_ADD_TO_CART).first
    expect(add_btn).to_be_visible(timeout=15_000)
    add_btn.click()
    page.wait_for_timeout(800)


@pytest.fixture
def cart_with_product(page: Page, in_stock_product: str):
    """Дровер корзины открыт, в корзине ровно один товар."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.context.clear_cookies()
    page.goto(in_stock_product, wait_until="domcontentloaded", timeout=60_000)
    _reset_cart_storage(page)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("h1")).to_be_visible(timeout=15_000)
    _hide_b24_widget(page)

    # На случай если на сервере остались товары от прошлой сессии —
    # открываем корзину и чистим её через UI.
    _open_cart_drawer(page)
    if page.locator(CART_PRODUCT).count() > 0:
        _click_until(
            page,
            page.locator(BTN_CLEAR_ALL).first,
            lambda: page.locator(CART_PRODUCT).count() == 0,
        )
        # Закрываем после очистки, чтобы вернуться на PDP
        _click_until(
            page,
            page.locator(BTN_CLOSE),
            lambda: page.locator(CART_MODAL_SHOWN).count() == 0,
        )

    _add_one_product_to_cart(page, in_stock_product)
    _open_cart_drawer(page)
    expect(page.locator(CART_PRODUCT).first).to_be_visible(timeout=10_000)
    return page


# ===========================================================================
# Кейс 105: Закрыть блок Корзина нажав на кнопку Х
# ===========================================================================
def test_close_cart_via_x_button(cart_with_product: Page):
    page = cart_with_product

    _click_until(
        page,
        page.locator(BTN_CLOSE),
        lambda: page.locator(CART_MODAL_SHOWN).count() == 0,
    )

    # Класса `show` больше нет → модал скрыт
    expect(page.locator(CART_MODAL_SHOWN)).to_have_count(0, timeout=5_000)
    # И мы по-прежнему на PDP
    expect(page.locator("h1")).to_be_visible()


# ===========================================================================
# Кейс 106: Закрыть блок Корзина нажав на область вокруг него
# ===========================================================================
def test_close_cart_by_clicking_outside(cart_with_product: Page):
    page = cart_with_product

    # Кликаем по `.modal__cart`, но мимо сайдбара (в левом верхнем углу
    # лежит overlay-область модала).
    _click_until(
        page,
        page.locator(CART_MODAL_SHOWN),
        lambda: page.locator(CART_MODAL_SHOWN).count() == 0,
        position={"x": 50, "y": 50},
    )

    expect(page.locator(CART_MODAL_SHOWN)).to_have_count(0, timeout=5_000)


# ===========================================================================
# Кейс 107: Удалить товар нажав на кнопку Удалить в карточке товара
# ===========================================================================
def test_delete_one_product_from_cart(cart_with_product: Page, in_stock_products: list):
    page = cart_with_product

    # Добираем второй товар, чтобы убедиться, что удаляется именно одна карточка.
    # Берём второй доступный со стоком; если он один — повторяем первый (всё равно
    # в корзине станет 2 карточки разных позиций либо +1 к количеству — проверяем
    # уменьшение числа карточек после удаления).
    second_url = in_stock_products[1] if len(in_stock_products) > 1 else in_stock_products[0]
    # Закрываем дровер, идём на второй PDP, добавляем, возвращаемся
    page.locator(BTN_CLOSE).click()
    page.wait_for_timeout(400)
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
# Кейс 108: Отображение заглушки при удалении последней карточки
# ===========================================================================
def test_empty_stub_when_removing_last_product(cart_with_product: Page):
    page = cart_with_product

    # В фикстуре уже ровно 1 товар.
    assert page.locator(CART_PRODUCT).count() == 1

    # Тот же потерянный первый клик, что и в кейсе 107 — кликаем с проверкой.
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
# Кейс 109: Увеличить количество кнопкой «+»
# ===========================================================================
def test_increase_quantity_plus(cart_with_product: Page):
    page = cart_with_product

    # До клика minus может быть disabled (количество 1)
    minus = page.locator(BTN_MINUS).first
    expect(minus).to_have_class(re.compile(r"\bdisabled\b"))

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

    # И minus теперь активен
    expect(page.locator(BTN_MINUS).first).not_to_have_class(
        re.compile(r"\bdisabled\b")
    )


# ===========================================================================
# Кейс 110: Уменьшить количество кнопкой «-»
# ===========================================================================
def test_decrease_quantity_minus(cart_with_product: Page):
    page = cart_with_product

    # Сначала доводим количество до 2
    _click_until(
        page,
        page.locator(BTN_PLUS).first,
        lambda: _quantity_of_first_item(page) == 2,
    )
    assert _quantity_of_first_item(page) == 2

    qty_before = _quantity_of_first_item(page)
    _click_until(
        page,
        page.locator(BTN_MINUS).first,
        lambda: _quantity_of_first_item(page) == qty_before - 1,
    )

    qty_after = _quantity_of_first_item(page)
    assert qty_after == qty_before - 1, (
        f"Количество не уменьшилось на 1: {qty_before} → {qty_after}"
    )

    # И minus снова неактивен
    expect(page.locator(BTN_MINUS).first).to_have_class(
        re.compile(r"\bdisabled\b")
    )


# ===========================================================================
# Кейс 114: Открыть «Оформление заказа» через «Оформить заявку»
# ===========================================================================
def test_open_checkout_via_submit_button(cart_with_product: Page):
    page = cart_with_product

    _click_until(
        page,
        page.locator(BTN_SUBMIT_REQUEST).first,
        lambda: page.locator(CHECKOUT_FORM).count() > 0,
    )

    # Блок оформления заказа отрендерился в том же модале
    expect(page.locator(CHECKOUT_FORM)).to_be_visible(timeout=10_000)
    # Сайдбар получил модификатор --checkout
    expect(page.locator(".cart__sidebar--checkout")).to_be_visible()


# ===========================================================================
# Кейс 245: Закрыть корзину кнопкой «Продолжить покупки»
# ===========================================================================
def test_close_cart_via_continue_shopping(cart_with_product: Page):
    page = cart_with_product

    cont_btn = (
        page.locator(f"{CART_MODAL_SHOWN} button.request")
        .filter(has_text=re.compile(r"Продолжить.*покупк", re.IGNORECASE))
        .first
    )
    expect(cont_btn).to_be_visible()
    _click_until(
        page, cont_btn, lambda: page.locator(CART_MODAL_SHOWN).count() == 0
    )

    expect(page.locator(CART_MODAL_SHOWN)).to_have_count(0, timeout=5_000)


# ===========================================================================
# Кейс 246: Очистить корзину кнопкой «Очистить корзину»
# ===========================================================================
def test_clear_cart_via_clear_button(cart_with_product: Page):
    page = cart_with_product

    assert page.locator(CART_PRODUCT).count() >= 1

    clear_btn = page.locator(BTN_CLEAR_ALL).first
    expect(clear_btn).to_be_visible()
    expect(clear_btn).to_contain_text(re.compile(r"Очистить.*корзин", re.IGNORECASE))
    _click_until(page, clear_btn, lambda: page.locator(CART_PRODUCT).count() == 0)

    expect(page.locator(CART_PRODUCT)).to_have_count(0, timeout=10_000)


# ---------------------------------------------------------------------------
# Внутренние утилиты
# ---------------------------------------------------------------------------
def _quantity_of_first_item(page: Page) -> int:
    """Прочитать текущее количество из карточки первого товара.

    DOM выводит число в `.item__control` между minus и plus как input,
    либо как текстовый элемент. Берём первое число рядом с этими кнопками.
    """
    return page.evaluate(
        """() => {
            const card = document.querySelector('.cart__product');
            if (!card) return -1;
            // Поле количества — input.item__current--input (type="text")
            const inp = card.querySelector('input.item__current--input, input[type="number"]');
            if (inp) {
                const v = parseInt(inp.value, 10);
                if (!isNaN(v)) return v;
            }
            // fallback — текстовое содержимое рядом с кнопками
            const minus = card.querySelector('button.item__control.minus');
            if (minus && minus.parentElement) {
                const txt = (minus.parentElement.textContent || '').trim();
                const m = txt.match(/\\d+/);
                if (m) return parseInt(m[0], 10);
            }
            return -1;
        }"""
    )
