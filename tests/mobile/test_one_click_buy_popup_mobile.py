"""Поп-ап «Покупка в один клик» — мобильная версия (зеркало
tests/test_one_click_buy_popup.py).

Что на телефоне иначе (проверено 30.09.2026 в MCP-браузере на ширине 412):
  * кнопка открытия — `button.btn__buy_click` с текстом под ценой
    (`.prices .actions-row`); десктопной `.btn-one-click` нет;
  * вторая такая же кнопка (только иконка, title «Купить в 1 клик») — в
    липкой нижней панели `.bottom-buy-bar` над нижним баром. Вверху
    страницы панель `display: none`, появляется после прокрутки ниже блока
    цены — на это отдельный тест;
  * поп-ап `.modal__buy_onclick` на телефоне во весь экран: карточка
    `.buy__onclick_content` 412×839, затемнённого фона вокруг не остаётся.
    Поэтому кейс 109 «закрыть кликом вокруг поп-апа» НЕ перенесён — тапать
    некуда (как кейс 106 в корзине).

Остальные кейсы от раскладки не зависят и импортированы из десктопного
файла; им достаётся мобильная фикстура `open_one_click_popup`.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from test_one_click_buy_popup import (  # noqa: F401 — тесты собирает pytest
    BTN_OPEN,
    MODAL,
    PRODUCT_URL,
    test_open_one_click_popup_shows_product_and_locks_scroll,
    test_close_one_click_popup_by_x,
    test_shop_phone_is_tel_link,
    test_empty_phone_shows_error_on_submit,
)

BOTTOM_BAR = ".bottom-buy-bar"
BOTTOM_BAR_BTN = f"{BOTTOM_BAR} button.btn__buy_click"
PRODUCT_NAME = "JBL PartyBox On-the-Go 2"


def _tap_open(page: Page, button) -> None:
    """Тапать кнопку, пока не откроется поп-ап: первый тап до гидрации
    теряется. Повторяем, только пока поп-апа нет, — иначе лишний тап
    пришёлся бы уже по нему."""
    modal = page.locator(MODAL)
    for _ in range(3):
        if modal.count():
            break
        button.tap()
        try:
            expect(modal).to_be_visible(timeout=5_000)
            break
        except AssertionError:
            continue
    expect(modal).to_be_visible(timeout=5_000)


@pytest.fixture
def open_one_click_popup(page: Page):
    """Открыть товар и поп-ап кнопкой под ценой (без принудительного 1920×1080)."""
    page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1")).to_be_visible(timeout=15_000)

    # Кнопки две (под ценой и в нижней панели), вверху страницы видна одна
    open_btn = page.locator(f"{BTN_OPEN} >> visible=true").first
    expect(open_btn).to_be_visible(timeout=10_000)
    open_btn.scroll_into_view_if_needed()
    _tap_open(page, open_btn)
    return page


# ===========================================================================
# Кейс 305 (моб.): Открытие поп-апа из липкой нижней панели
# ===========================================================================
def test_open_one_click_popup_from_bottom_bar(page: Page):
    """Нижняя панель покупки появляется после прокрутки, и её кнопка
    «Купить в 1 клик» открывает тот же поп-ап с этим товаром."""
    page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1")).to_be_visible(timeout=15_000)

    bar_btn = page.locator(BOTTOM_BAR_BTN)
    expect(page.locator(BOTTOM_BAR)).to_be_hidden()

    # Прокрутка колесом/пальцем, а не scrollTo: панель показывается по
    # событию прокрутки. Докручиваем, пока не появится.
    for _ in range(10):
        page.mouse.wheel(0, 400)
        try:
            expect(bar_btn).to_be_visible(timeout=1_000)
            break
        except AssertionError:
            continue
    expect(bar_btn).to_be_visible()
    expect(bar_btn).to_have_attribute("title", re.compile(r"1 клик", re.I))

    _tap_open(page, bar_btn)
    expect(page.locator(MODAL)).to_contain_text(re.compile(re.escape(PRODUCT_NAME), re.I))


# Реальный заказ — последним: создаёт заявку на стенде.
from test_one_click_buy_popup import test_successful_one_click_purchase  # noqa: E402,F401
