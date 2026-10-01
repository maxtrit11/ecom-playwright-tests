"""Поп-ап «Купить в кредит» — мобильная версия (зеркало tests/test_credit_popup.py).

Поп-ап на телефоне тот же `.modal__credit` с теми же полями, компаниями,
согласиями и кнопками (проверено в MCP-браузере). Разница в раскладке:
  * кнопка «В кредит» — в блоке `.credit__block` ниже по странице товара;
  * поп-ап почти на весь экран: сверху остаётся полоска тёмного фона ~16px,
    форма с кнопками прилипла к низу, список компаний прокручивается над ней.

Поэтому тесты, которым всё равно, где что лежит, импортированы из десктопного
файла целиком и идут с мобильной фикстурой `open_credit_popup`. Свой здесь
только кейс 87: десктоп закрывает поп-ап синтетическим событием в угол
оверлея, а на телефоне честно тапаем по полоске фона над поп-апом.
"""

import pytest
from playwright.sync_api import Page, expect

from test_credit_popup import (  # noqa: F401 — тесты собирает pytest
    BTN_OPEN_CREDIT,
    MODAL_CREDIT,
    test_close_credit_popup_by_x,
    test_close_credit_popup_by_continue_button,
    test_select_credit_company_highlights_card,
    test_empty_name_shows_error_on_submit,
    test_empty_phone_shows_error_on_submit,
)


@pytest.fixture
def open_credit_popup(page: Page, credit_product: str):
    """Открыть товар с кредитом и поп-ап «Купить в кредит» (тап с повтором —
    первый тап после гидрации может потеряться)."""
    page.goto(credit_product, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1")).to_be_visible(timeout=15_000)

    credit_btn = page.locator(BTN_OPEN_CREDIT).first
    expect(credit_btn).to_be_visible(timeout=10_000)

    modal = page.locator(MODAL_CREDIT)
    for _ in range(3):
        if modal.count():
            break
        credit_btn.tap()
        try:
            expect(modal).to_be_visible(timeout=5_000)
            break
        except AssertionError:
            continue
    expect(modal).to_be_visible(timeout=5_000)
    return page


# ===========================================================================
# Кейс 87 (моб.): Закрыть поп-ап тапом по фону над ним
# ===========================================================================
def test_close_credit_popup_by_overlay_tap(open_credit_popup: Page):
    """Тап по полоске тёмного фона над карточкой поп-апа закрывает его."""
    page = open_credit_popup

    strip = page.evaluate(
        """() => {
            const modal = document.querySelector('.modal__credit.show');
            const card = modal.querySelector('.credit__content');
            const m = modal.getBoundingClientRect(), c = card.getBoundingClientRect();
            return { top: c.top - m.top, width: m.width };
        }"""
    )
    if strip["top"] < 4:
        pytest.skip("Поп-ап на весь экран — фона над ним не осталось, тапать некуда")

    # Тап по самому .modal__credit (это и есть фон) в середине полоски;
    # Playwright проверит, что в эту точку не попадает карточка.
    page.locator(MODAL_CREDIT).tap(position={"x": strip["width"] / 2, "y": strip["top"] / 2})

    expect(page.locator(MODAL_CREDIT)).to_have_count(0, timeout=5_000)
    expect(page.locator("h1")).to_be_visible()


# Реальная заявка на кредит — последней: создаёт лид на стенде.
from test_credit_popup import test_successful_credit_application  # noqa: E402,F401
