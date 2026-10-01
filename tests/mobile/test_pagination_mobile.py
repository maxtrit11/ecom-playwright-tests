"""Пагинация категории — мобильная версия (зеркало tests/test_pagination.py).

Пагинация на телефоне та же, что на десктопе (`.pagination`, числовые кнопки,
стрелки «вперёд/назад», page= в URL — проверено 29–30.09.2026 в эмуляции
Pixel 7), поэтому все тесты импортированы из десктопного файла и идут с
мобильной фикстурой `open_category` (без принудительного 1920×1080).

Одно отличие — ожидание перехода. Десктопный `_go_to_page` в конце ждёт
`networkidle`, а мобильная категория stage затихает долго или не затихает
вовсе (см. mobile/test_filters_pagination_mobile.py): прогон шёл почти 5 минут
при 15–30 с на тест. На время мобильных тестов хелпер подменяется
(`monkeypatch` в десктопном модуле — импортированные тесты берут его оттуда)
на ожидание по факту: активная кнопка страницы и смена первой карточки грида.
"""

import pytest
from playwright.sync_api import Page, expect

import test_pagination
from test_pagination import (  # noqa: F401 — тесты собирает pytest
    CARD,
    CATEGORY_URL,
    GRID,
    _first_card_key,
    _wait_active_page,
    _wait_first_card_changed,
    test_pagination_control_renders,
    test_first_page_active_and_no_prev,
    test_next_button_advances_page,
    test_pages_have_distinct_products,
    test_click_page_number_navigates,
    test_prev_button_returns_to_previous_page,
    test_deeplink_page_param_loads_page,
    test_pagination_persists_on_reload,
    test_no_next_button_on_last_page,
    test_invalid_page_param_handled_gracefully,
    test_page_size_is_consistent,
    test_browser_back_navigates_to_previous_page,
)


def _go_to_page(page: Page, action, target: int) -> None:
    """Как десктопный, но без финального networkidle — см. докстринг модуля."""
    before_key = _first_card_key(page)
    action()
    _wait_active_page(page, target)
    _wait_first_card_changed(page, before_key)


@pytest.fixture(autouse=True)
def open_category(page: Page, monkeypatch):
    monkeypatch.setattr(test_pagination, "_go_to_page", _go_to_page)
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(GRID)).to_be_visible(timeout=20_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=20_000)
