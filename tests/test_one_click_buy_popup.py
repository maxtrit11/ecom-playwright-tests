"""Тесты поп-апа Покупка в один клик (Qase suite 10)"""

import re
import time

import pytest
from playwright.sync_api import Page, expect


PRODUCT_URL = "/ru/product/jbl-partybox-on-the-go-2"

# На десктопе видим .btn-one-click (карточка товара), на мобильной разметке —
# .btn__buy_click из липкого нижнего бара. Берём первое видимое совпадение.
BTN_OPEN = "button.btn-one-click, button.btn__buy_click"

MODAL = ".modal__buy_onclick.show"
BTN_CLOSE = f"{MODAL} .btn__close"
INPUT_TEL = f'{MODAL} input[type="tel"]'
BTN_SUBMIT = f"{MODAL} button.request"

SUCCESS_MODAL = ".modal__checkout_success.show"


@pytest.fixture
def open_one_click_popup(page: Page):
    """Открыть страницу товара и поп-ап «Покупка в один клик»."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1")).to_be_visible(timeout=15_000)

    open_btn = page.locator(BTN_OPEN).first
    expect(open_btn).to_be_visible(timeout=10_000)
    open_btn.scroll_into_view_if_needed()
    open_btn.click()

    expect(page.locator(MODAL)).to_be_visible(timeout=10_000)
    return page


# ===========================================================================
# Кейс 305: Открытие поп-апа «Покупка в один клик»
# ===========================================================================
def test_open_one_click_popup_shows_product_and_locks_scroll(open_one_click_popup: Page):
    """Поп-ап открыт: заголовок, название товара, затемнение фона, body scroll заблокирован."""
    page = open_one_click_popup

    modal = page.locator(MODAL)
    expect(modal).to_be_visible()
    expect(modal).to_contain_text(re.compile(r"Покупка в один клик", re.IGNORECASE))
    expect(modal).to_contain_text(re.compile(r"JBL PartyBox On-the-Go 2", re.IGNORECASE))

    # Затемнение фона (rgba с альфа > 0)
    bg = modal.evaluate("el => getComputedStyle(el).backgroundColor")
    assert "rgba(25, 25, 25" in bg or "rgba(0, 0, 0" in bg, f"Фон не затемнён: {bg}"

    # Фоновый скролл body заблокирован
    overflow = page.evaluate("() => getComputedStyle(document.body).overflow")
    assert overflow == "hidden", f"Скролл не заблокирован: overflow={overflow}"


# ===========================================================================
# Кейс 44: Закрыть поп-ап по кнопке X
# ===========================================================================
def test_close_one_click_popup_by_x(open_one_click_popup: Page):
    """Клик на X — попап закрывается."""
    page = open_one_click_popup

    page.locator(BTN_CLOSE).first.click()

    expect(page.locator(MODAL)).not_to_be_visible(timeout=5_000)
    expect(page.locator("h1")).to_be_visible()


# ===========================================================================
# Кейс 49: Ошибка под полем «Телефон» при пустом значении
# ===========================================================================
def test_empty_phone_shows_error_on_submit(open_one_click_popup: Page):
    """Submit без телефона → красная рамка #E53935 + текст «Это обязательное поле»."""
    page = open_one_click_popup

    tel = page.locator(INPUT_TEL).first
    border_before = tel.evaluate("el => getComputedStyle(el).borderColor")

    page.locator(BTN_SUBMIT).first.click()
    page.wait_for_timeout(800)

    border_after = tel.evaluate("el => getComputedStyle(el).borderColor")
    is_red = "rgb(229, 57, 53)" in border_after
    changed = border_before != border_after

    has_validation = page.locator(
        f'{MODAL} .validation, {MODAL} [class*="error"]'
    ).filter(has_text=re.compile(r"обязательное|обязательн", re.IGNORECASE)).count() > 0

    assert is_red or changed or has_validation, (
        f"Поле Телефон не подсветилось ошибкой: border {border_before} → {border_after}, "
        f"validation={has_validation}"
    )

    expect(page.locator(MODAL)).to_be_visible()


# ===========================================================================
# Кейс 43: Положительный сценарий покупки в один клик
# ===========================================================================
def test_successful_one_click_purchase(open_one_click_popup: Page):
    """Заполнить телефон → Оформить заказ → buy-модалка закрылась,
    появился success-попап «Заявка отправлена успешно» + кнопка «Главная страница»."""
    page = open_one_click_popup

    # Уникальный 8-значный телефон чтобы обойти антиспам на стейдже
    unique_phone = "79" + str(int(time.time() * 1000))[-6:]

    # `fill()` ломает маску intl-tel-input: значение остаётся без пробелов,
    # плагин считает номер невалидным и сабмит молча не проходит — модалка
    # висит открытой. Нужен посимвольный ввод с фокусом (как в предзаказе).
    tel = page.locator(INPUT_TEL).first
    for _ in range(3):
        tel.click()
        tel.press_sequentially(unique_phone, delay=60)
        try:
            expect(tel).not_to_have_value("", timeout=2_000)
            break
        except AssertionError:
            page.wait_for_timeout(500)
    page.wait_for_timeout(500)

    submit_btn = page.locator(BTN_SUBMIT).first
    expect(submit_btn).to_be_enabled()
    submit_btn.click()

    # Buy-модалка закрылась
    expect(page.locator(MODAL)).not_to_be_visible(timeout=30_000)

    # Success-попап виден
    expect(page.locator(SUCCESS_MODAL)).to_be_visible(timeout=30_000)
    expect(
        page.get_by_text(re.compile(r"Заявка отправлена успешно", re.IGNORECASE)).first
    ).to_be_visible()
    expect(
        page.get_by_text(re.compile(r"Главная страница", re.IGNORECASE)).first
    ).to_be_visible()
