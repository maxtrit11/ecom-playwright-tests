"""Смена языка — мобильная версия (зеркало tests/test_language_switch.py).

Что на телефоне иначе (проверено 30.09.2026 в MCP-браузере на ширине 412 и в
эмуляции Pixel 7):
  * навбар с выпадашкой языка (`.nav__items`, `.nav__item .dropdown`) скрыт —
    переключатель живёт в бургер-меню: `.header__mobile_ecom .btn__menu` →
    `.menu__mobile_ecom.show` → `.menu__language button.btn__language`;
  * кнопка показывает текущий язык («Ru»/«Ro»), тап раскрывает
    `ul.language__items` (класс `show`; закрытый — `visibility: hidden`).
    В списке текущий язык — `span.current`, остальные — ссылки. Языков ТРИ:
    ro, ru, en (у en на странице товара свой слаг, `...-en`);
  * ссылки ведут на ту же страницу в другой локали
    (`/ro/product/<slug>`), как и на десктопе.

Замечено 30.09.2026: после смены языка НА ГЛАВНОЙ бургер-меню остаётся
открытым (и `body.popup-open` блокирует прокрутку), а на товаре и контактах —
закрывается. Вынесено юзеру; пока не решено, баг ли это, тесты состояние
меню после переключения не проверяют.

Десктопные тесты импортировать нельзя: все они ходят через навбарный
`switch_to_language` десктопного модуля. Переиспользуем только чтение языка
и ожидание его применения.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from test_language_switch import RO_MARKERS, RU_MARKERS, _wait_lang_applied, get_lang

BTN_MENU = ".header__mobile_ecom .btn__menu"
MENU_OPEN = ".menu__mobile_ecom.show"
BTN_LANGUAGE = ".menu__mobile_ecom .btn__language"
BTN_LANGUAGE_LABEL = f"{BTN_LANGUAGE} > a"
LANG_LIST = ".menu__mobile_ecom .language__items"
LANG_LIST_OPEN = f"{LANG_LIST}.show"
LANG_CURRENT = f"{LANG_LIST} .current"

PRODUCT_URL = "/ru/product/jbl-partybox-on-the-go-2"


def _tap_until(page: Page, target: str, expected: str, attempts: int = 3) -> None:
    """Тапать `target`, пока не появится `expected`.

    Первый тап после domcontentloaded теряется, пока Vue не догидрировался
    (см. десктопный `open_lang_dropdown`) — повторяем, а не ждём наугад.
    """
    for attempt in range(attempts):
        page.locator(target).first.tap()
        try:
            expect(page.locator(expected)).to_be_visible(timeout=3_000)
            return
        except AssertionError:
            if attempt == attempts - 1:
                raise


def open_mobile_menu(page: Page) -> None:
    """Открыть бургер-меню (если оно уже открыто — ничего не делать).

    Уже открытым оно бывает после смены языка на главной — см. докстринг модуля.
    """
    if page.locator(MENU_OPEN).count():
        return
    _tap_until(page, BTN_MENU, MENU_OPEN)


def open_lang_list(page: Page) -> None:
    """Открыть меню и раскрыть в нём список языков."""
    open_mobile_menu(page)
    if page.locator(LANG_LIST_OPEN).count():
        return
    _tap_until(page, BTN_LANGUAGE, LANG_LIST_OPEN)


def switch_to_language(page: Page, lang_code: str) -> None:
    """Переключить язык через бургер-меню. Ссылку ищем по тексту, а не по
    href: href зависит от страницы (`/ro`, `/ro/product/...`)."""
    open_lang_list(page)
    link = page.locator(f"{LANG_LIST_OPEN} a", has_text=re.compile(rf"^\s*{lang_code}\s*$", re.I))
    expect(link).to_be_visible()
    link.tap()
    _wait_lang_applied(page, lang_code)


def _body_has_any(page: Page, markers: list[str]) -> bool:
    text = page.locator("body").text_content() or ""
    return any(m in text for m in markers)


@pytest.fixture(autouse=True)
def open_main_page(page: Page):
    """Открыть главную. networkidle на мобильных страницах stage наступает
    ненадёжно — ждём кнопку бургер-меню."""
    page.goto("/ru", wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(BTN_MENU)).to_be_visible(timeout=30_000)


# ===========================================================================
# Кейс 22 (моб.): Сменить язык на русский (RO → RU)
# ===========================================================================
def test_switch_language_to_russian(page: Page):
    page.goto("/ro", wait_until="domcontentloaded")
    _wait_lang_applied(page, "ro")
    assert get_lang(page) == "ro"

    switch_to_language(page, "ru")

    assert get_lang(page) == "ru"
    assert _body_has_any(page, RU_MARKERS), "Интерфейс не переключился на русский язык"


# ===========================================================================
# Кейс 23 (моб.): Сменить язык на румынский (RU → RO)
# ===========================================================================
def test_switch_language_to_romanian(page: Page):
    assert get_lang(page) == "ru"

    switch_to_language(page, "ro")

    assert get_lang(page) == "ro"
    assert _body_has_any(page, RO_MARKERS), "Интерфейс не переключился на румынский язык"


# ===========================================================================
# Кейс 304 (моб.): Сохранение языка при навигации и обновлении
# ===========================================================================
def test_language_persists_on_navigation(page: Page):
    switch_to_language(page, "ro")
    assert get_lang(page) == "ro"

    page.goto("/ro/contacts", wait_until="domcontentloaded")
    _wait_lang_applied(page, "ro")
    assert get_lang(page) == "ro"

    page.reload(wait_until="domcontentloaded")
    _wait_lang_applied(page, "ro")
    assert get_lang(page) == "ro", "Язык сбросился после обновления страницы"
    assert _body_has_any(page, RO_MARKERS), "Интерфейс не на румынском после обновления"


# ===========================================================================
# Дополнительные регрессионные тесты
# ===========================================================================
def test_language_switch_on_product_page(page: Page):
    """Смена языка на товаре оставляет на том же товаре в новой локали."""
    page.goto(PRODUCT_URL, wait_until="domcontentloaded")
    expect(page.locator("h1").first).to_be_visible(timeout=15_000)
    slug = PRODUCT_URL.rsplit("/", 1)[-1]

    switch_to_language(page, "ro")

    assert get_lang(page) == "ro"
    expect(page).to_have_url(re.compile(rf"/ro/product/{re.escape(slug)}"))


def test_language_dropdown_opens_and_closes(page: Page):
    """Тап по кнопке языка в меню раскрывает список, повторный — сворачивает.
    В списке все языки: текущий (без ссылки) и минимум одна ссылка."""
    open_mobile_menu(page)
    expect(page.locator(LANG_LIST)).to_be_hidden()

    _tap_until(page, BTN_LANGUAGE, LANG_LIST_OPEN)
    links = page.locator(f"{LANG_LIST_OPEN} a")
    assert links.count() >= 1, "В списке языков нет ни одной ссылки на другой язык"
    expect(page.locator(LANG_CURRENT)).to_have_count(1)

    page.locator(BTN_LANGUAGE).tap()
    expect(page.locator(LANG_LIST_OPEN)).to_have_count(0, timeout=5_000)
    expect(page.locator(LANG_LIST)).to_be_hidden()


def test_current_language_highlighted(page: Page):
    """Текущий язык отмечен `.current` и подписан на кнопке меню; после смены
    на RO — и то и другое показывает RO."""
    open_lang_list(page)
    expect(page.locator(LANG_CURRENT)).to_have_text(re.compile(r"^\s*ru\s*$", re.I))
    expect(page.locator(BTN_LANGUAGE_LABEL)).to_have_text(re.compile(r"^\s*ru\s*$", re.I))

    switch_to_language(page, "ro")

    # Подпись на кнопке видна только в открытом меню. textContent, а не
    # innerText: у свёрнутого списка `.current` скрыт, и innerText пуст.
    open_mobile_menu(page)
    expect(page.locator(BTN_LANGUAGE_LABEL)).to_have_text(re.compile(r"^\s*ro\s*$", re.I))
    current = (page.locator(LANG_CURRENT).text_content() or "").strip().lower()
    assert current == "ro", f"После смены на RO текущим отмечен {current!r}"


def test_language_switch_preserves_page_content(page: Page):
    """После смены языка контент главной не пропадает."""
    content = "main a, main img, .product, [class*='card']"
    elements_ru = page.locator(content).count()

    switch_to_language(page, "ro")

    # Без этой проверки тест зеленел и без смены языка — сравнивал RU с RU
    # (поймано мутацией 30.09.2026; у десктопного оригинала та же дыра).
    assert get_lang(page) == "ro", "Язык не переключился — сравнивать контент не с чем"
    elements_ro = page.locator(content).count()
    assert elements_ro > 0, "Страница пустая после смены языка"
    if elements_ru > 0:
        ratio = elements_ro / elements_ru
        assert ratio > 0.5, f"Потеря контента при смене языка: {elements_ru} → {elements_ro}"
