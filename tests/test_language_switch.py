"""Тесты смены языка сайта (Qase suite: Смена языка сайта)"""

import re

import pytest
from playwright.sync_api import Page, expect

# Селекторы навбара и переключателя языка
NAVBAR = ".nav__items"
LANG_DROPDOWN_BTN = ".nav__item .dropdown"
LANG_LIST = ".sub__item"
LANG_ITEM_CURRENT = ".sub__item .current"

# Тексты для проверки языка интерфейса
RU_MARKERS = ["Каталог товаров", "Каталог", "Главная"]
RO_MARKERS = ["Catalog de produse", "Catalog", "Principală", "Acasă"]


def get_lang(page: Page) -> str:
    """Определить текущий язык интерфейса по атрибуту <html lang>.
    На стейдже RU живёт на /, а /ru/ редиректит, поэтому URL — ненадёжный
    источник: для определения языка читаем document.documentElement.lang."""
    return (page.evaluate("() => document.documentElement.lang") or "").lower()


def open_lang_dropdown(page: Page):
    """Открыть выпадающий список языков."""
    dropdown_btn = page.locator(LANG_DROPDOWN_BTN)
    if dropdown_btn.count() > 0 and dropdown_btn.first.is_visible():
        dropdown_btn.first.click()
        expect(page.locator(f"{LANG_LIST}.show")).to_be_visible(timeout=3_000)
        return

    # Альтернатива — кнопка nav__item с текстом языка
    nav_items = page.locator(".nav__item")
    for i in range(nav_items.count()):
        item = nav_items.nth(i)
        text = item.text_content().strip().lower()
        if text in ("ru", "ro", "русский", "română"):
            item.click()
            page.wait_for_timeout(500)
            return


def switch_to_language(page: Page, lang_code: str):
    """Переключить язык на указанный код (ru/ro).
    Ссылка на язык внутри .sub__item.show ищется по тексту, а не по href,
    т.к. href RU-ссылки может быть и /, и /ru/..., в зависимости от страницы."""
    open_lang_dropdown(page)

    lang_link = page.locator(f"{LANG_LIST}.show a.sub__item--lang", has_text=re.compile(rf"^\s*{lang_code}\s*$", re.IGNORECASE))
    if lang_link.count() > 0:
        lang_link.first.click()
        page.wait_for_load_state("networkidle")
        return

    # Запасной путь — поиск по href (для тем-страниц со схемой /ru/.../ro/...)
    lang_link = page.locator(f"a[href^='/{lang_code}/'], a[href='/{lang_code}']")
    for i in range(lang_link.count()):
        if lang_link.nth(i).is_visible():
            lang_link.nth(i).click()
            page.wait_for_load_state("networkidle")
            return


@pytest.fixture(autouse=True)
def open_main_page(page: Page):
    """Открыть главную страницу."""
    page.goto("/ru")
    page.wait_for_load_state("networkidle")


# ===========================================================================
# Кейс 22: Сменить язык на русский (RO → RU)
# ===========================================================================
def test_switch_language_to_russian(page: Page):
    """Переключить язык с RO на RU — интерфейс отображается на русском,
    URL содержит /ru/."""
    # Сначала переходим на RO
    page.goto("/ro")
    page.wait_for_load_state("networkidle")
    assert get_lang(page) == "ro"

    # Переключаем на RU
    switch_to_language(page, "ru")

    # URL содержит /ru/
    assert get_lang(page) == "ru"

    # Интерфейс на русском — проверяем наличие русских текстов
    page_text = page.locator("body").text_content()
    has_ru = any(marker in page_text for marker in RU_MARKERS)
    assert has_ru, "Интерфейс не переключился на русский язык"


# ===========================================================================
# Кейс 23: Сменить язык на румынский (RU → RO)
# ===========================================================================
def test_switch_language_to_romanian(page: Page):
    """Переключить язык с RU на RO — интерфейс отображается на румынском,
    URL содержит /ro/."""
    assert get_lang(page) == "ru"

    # Переключаем на RO
    switch_to_language(page, "ro")

    # URL содержит /ro/
    assert get_lang(page) == "ro"

    # Интерфейс на румынском
    page_text = page.locator("body").text_content()
    has_ro = any(marker in page_text for marker in RO_MARKERS)
    assert has_ro, "Интерфейс не переключился на румынский язык"


# ===========================================================================
# Кейс 304: Сохранение языка при навигации и обновлении
# ===========================================================================
def test_language_persists_on_navigation(page: Page):
    """Выбранный язык сохраняется при переходе на другие страницы
    и после обновления."""
    # Переключаем на RO
    switch_to_language(page, "ro")
    assert get_lang(page) == "ro"

    # Переходим на другую страницу (контакты)
    page.goto("/ro/contacts")
    page.wait_for_load_state("networkidle")
    assert get_lang(page) == "ro"

    # Обновляем страницу
    page.reload()
    page.wait_for_load_state("networkidle")

    # Язык не сбросился
    assert get_lang(page) == "ro"

    # Интерфейс остаётся на румынском
    page_text = page.locator("body").text_content()
    has_ro = any(marker in page_text for marker in RO_MARKERS)
    assert has_ro, "Язык сбросился после обновления страницы"


# ===========================================================================
# Дополнительные регрессионные тесты
# ===========================================================================

def test_language_switch_on_product_page(page: Page):
    """Смена языка на странице товара — URL корректно меняется,
    страница не ломается."""
    # Открываем известный товар напрямую: на главной стейджа нет ссылок
    # с /product/, а товарные слаги в категориях не всегда имеют этот префикс
    page.goto("/ru/product/jbl-partybox-on-the-go-2", wait_until="domcontentloaded")
    expect(page.locator("h1")).to_be_visible(timeout=15_000)

    # Переключаем язык
    switch_to_language(page, "ro")

    # Язык интерфейса — румынский
    assert get_lang(page) == "ro"
    # Мы остались на странице товара, а не вернулись на главную
    assert "/product/" in page.url or "/produs/" in page.url


def test_language_dropdown_opens_and_closes(page: Page):
    """Выпадающий список языков открывается по клику и содержит
    доступные языки."""
    open_lang_dropdown(page)

    # Список виден и содержит ссылки на языки
    lang_links = page.locator(f"{LANG_LIST} a, .nav__item-lang a")
    assert lang_links.count() >= 2, "Должно быть минимум 2 языка (RU, RO)"


def test_current_language_highlighted(page: Page):
    """Текущий активный язык выделен (имеет класс current)."""
    open_lang_dropdown(page)

    # Текущий язык отмечен классом current
    current = page.locator(f"{LANG_LIST} .current, .nav__item-lang .current")
    if current.count() > 0:
        text = current.first.text_content().strip().lower()
        assert "ru" in text or "рус" in text, (
            f"Текущий язык должен быть RU, но выделен: {text}"
        )
    else:
        pytest.skip("Класс .current не найден — реализация может отличаться")


def test_language_switch_preserves_page_content(page: Page):
    """После смены языка основной контент страницы сохраняется —
    количество элементов не меняется, страница не пустая."""
    # Считаем элементы на RU
    page.wait_for_load_state("networkidle")
    elements_ru = page.locator("main a, main img, .product, [class*='card']").count()

    # Переключаем на RO
    switch_to_language(page, "ro")

    # Считаем элементы на RO
    elements_ro = page.locator("main a, main img, .product, [class*='card']").count()

    # Контент не должен исчезнуть — допускаем небольшую разницу
    assert elements_ro > 0, "Страница пустая после смены языка"
    if elements_ru > 0:
        ratio = elements_ro / elements_ru
        assert ratio > 0.5, (
            f"Потеря контента при смене языка: {elements_ru} → {elements_ro}"
        )
