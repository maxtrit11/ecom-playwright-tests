"""Раздел «Акции» — мобильная версия (зеркало tests/test_special_offers.py).

Разметка на телефоне та же, что на десктопе (проверено 01.10.2026 в эмуляции
Pixel 7): листинг `/ro/special-offers` — карточки `.promo__item` (сами ссылки)
в одну колонку на всю ширину, у завершённой плашка `.promo__finished` лежит
поверх картинки; детальная — те же `.promo-countdown` / `.promo-finished` с
кнопкой «Promoții active». Поэтому все десктопные тесты импортированы и идут с
мобильной фикстурой `open_offers` (без принудительного 1920×1080).

На 01.10.2026 на стенде только две акции, обе завершённые, — тесты активной
акции скипаются, как и на десктопе.

Своё — только то, чего на десктопе не бывает: карточки обязаны уложиться в
ширину экрана одной колонкой, и переход по карточке должен срабатывать от
касания (tap), а не только от клика мышью.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from test_special_offers import (  # noqa: F401 — тесты собирает pytest
    test_offers_page_lists_promotions,
    test_active_promo_card_shows_countdown,
    test_expired_promo_card_shows_expired_badge,
    test_promo_card_opens_matching_promo_page,
    test_active_promo_page_shows_countdown_and_products,
    test_expired_promo_page_shows_finished_notice,
    test_finished_promo_button_returns_to_offers,
)
from test_special_offers import CARD_NAME, OFFERS_URL, PROMO_ITEM


@pytest.fixture(autouse=True)
def open_offers(page: Page):
    """Как десктопная, но без принудительного 1920×1080 — вьюпорт телефона."""
    page.goto(OFFERS_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(PROMO_ITEM).first).to_be_visible(timeout=30_000)
    yield


# ===========================================================================
# Моб. Карточки акций укладываются в экран одной колонкой
# ===========================================================================
def test_promo_cards_fit_screen_in_one_column(page: Page):
    """Ни одна карточка не вылезает за край экрана, страница не скроллится
    вбок, карточки идут друг под другом (каждая ниже предыдущей)."""
    width = page.viewport_size["width"]
    layout = page.evaluate(
        """(sel) => ({
            scroll: document.documentElement.scrollWidth,
            boxes: [...document.querySelectorAll(sel)].map(c => {
                const r = c.getBoundingClientRect();
                return {x: r.left, right: r.right, top: r.top + scrollY, bottom: r.bottom + scrollY};
            }),
        })""",
        PROMO_ITEM,
    )
    boxes = layout["boxes"]
    assert boxes, "На странице акций нет карточек"

    assert layout["scroll"] <= width + 1, (
        f"Страница акций шире экрана: scrollWidth={layout['scroll']} при ширине {width}"
    )
    outside = [i for i, b in enumerate(boxes) if b["x"] < 0 or b["right"] > width + 1]
    assert not outside, f"Карточки #{outside} выходят за край экрана шириной {width}: {boxes}"

    overlapping = [
        i for i in range(1, len(boxes)) if boxes[i]["top"] < boxes[i - 1]["bottom"] - 1
    ]
    assert not overlapping, (
        f"Карточки #{overlapping} стоят не под предыдущей (не одна колонка): {boxes}"
    )


# ===========================================================================
# Моб. Касание карточки открывает страницу этой акции
# ===========================================================================
def test_tap_on_promo_card_opens_its_page(page: Page):
    """Тап по ПОСЛЕДНЕЙ карточке (первую проверяет импортированный тест
    кликом) ведёт на её детальную страницу с тем же названием в h1."""
    card = page.locator(PROMO_ITEM).last
    name = (card.locator(CARD_NAME).first.inner_text() or "").strip()
    href = card.get_attribute("href") or ""
    assert name and href, f"У карточки нет названия или ссылки: {name!r}, {href!r}"

    card.scroll_into_view_if_needed()
    card.tap()

    # Страница акции может дописать сортировку товаров (`?sort=price%2B`).
    expect(page).to_have_url(re.compile(re.escape(href) + r"/?(\?.*)?$"), timeout=30_000)
    expect(page.locator("h1")).to_have_text(name, timeout=20_000)
