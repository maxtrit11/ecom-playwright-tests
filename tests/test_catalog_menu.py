"""Тесты кнопки «Каталог товаров» (Qase suite: Кнопка Каталог товаров)"""

import re

import pytest
from playwright.sync_api import Page, expect

# Селекторы
CATALOG_BTN = ".btn__catalog"
MENU_ITEMS = ".menu__items"
MENU_CATEGORY = ".menu__category"
CATEGORY_LINK = ".category__link"
CATEGORY_LINK_ARROW = ".category__link-arrow"
SUBCATEGORIES = ".menu__subcategories"
SUBCATEGORIES_ITEM = ".subcategories__item"
SUBCATEGORY_LINK = ".subcategory__link"
FOOTER_SUBCATEGORY = ".footer__subcategory"
# Последнее звено крошек — текущая страница. Широкий `[class*='breadcrumb']`
# ловит и nav, и ol, и каждый li — strict mode валится через раз.
BREADCRUMB_CURRENT = ".breadcrumb__item[aria-current='page']"


@pytest.fixture(autouse=True)
def open_main_page(page: Page):
    """Открыть главную страницу."""
    page.goto("/ru")
    page.wait_for_load_state("networkidle")
    expect(page.locator(CATALOG_BTN)).to_be_visible(timeout=10_000)


def open_catalog(page: Page):
    """Открыть меню каталога."""
    page.locator(CATALOG_BTN).click()
    expect(page.locator(MENU_ITEMS)).to_be_visible(timeout=5_000)


def hover_category_with_subcategories(page: Page):
    """Навести на первую категорию, у которой есть подкатегории.
    Возвращает локатор категории. Скипает тест, если таких нет."""
    categories = page.locator(CATEGORY_LINK)
    count = categories.count()
    for i in range(count):
        cat = categories.nth(i)
        cat.hover()
        page.wait_for_timeout(300)
        active_panel = page.locator(f"{SUBCATEGORIES}.active")
        if active_panel.count() > 0 and active_panel.locator(SUBCATEGORY_LINK).count() > 0:
            return cat
    pytest.skip("Ни у одной категории нет подкатегорий")


# ===========================================================================
# Кейс 300: Открыть выпадающее меню «Каталог товаров»
# ===========================================================================
@pytest.mark.smoke
def test_open_catalog_menu(page: Page):
    """Нажать «Каталог товаров» — открывается выпадающее меню,
    верстка не ломается."""
    page.locator(CATALOG_BTN).click()

    menu = page.locator(MENU_ITEMS)
    expect(menu).to_be_visible(timeout=5_000)

    # Меню содержит категории
    categories = menu.locator(CATEGORY_LINK)
    assert categories.count() > 0


# ===========================================================================
# Кейс 301: Закрыть меню каталога
# ===========================================================================
def test_close_catalog_menu_by_button(page: Page):
    """Закрыть меню повторным нажатием на «Каталог товаров»."""
    open_catalog(page)

    # Повторный клик — меню закрывается
    page.locator(CATALOG_BTN).click()
    expect(page.locator(MENU_ITEMS)).not_to_be_visible(timeout=5_000)


def test_close_catalog_menu_by_click_outside(page: Page):
    """Закрыть меню кликом вне его области."""
    open_catalog(page)

    # Клик вне меню (на body / overlay)
    page.locator("body").click(position={"x": 10, "y": 10})
    expect(page.locator(MENU_ITEMS)).not_to_be_visible(timeout=5_000)


# ===========================================================================
# Кейс 9: Отображение выделения при наведении на категорию
# ===========================================================================
def test_category_hover_highlight(page: Page):
    """При наведении на категорию — текст и фон меняют стиль."""
    open_catalog(page)

    category = page.locator(CATEGORY_LINK).first
    # Запоминаем цвет до hover
    color_before = category.evaluate("el => getComputedStyle(el).color")

    category.hover()
    page.wait_for_timeout(400)

    # После hover — категория получает класс active или меняет стиль
    color_after = category.evaluate("el => getComputedStyle(el).color")
    bg_after = category.evaluate("el => getComputedStyle(el).backgroundColor")

    # Проверяем что стиль изменился (цвет текста или фон)
    style_changed = color_before != color_after or bg_after != "rgba(0, 0, 0, 0)"
    assert style_changed, "Hover не меняет стиль категории"


# ===========================================================================
# Кейс 11: Отображение подкатегорий при наведении на категорию
# ===========================================================================
def test_subcategories_displayed_on_hover(page: Page):
    """При наведении на категорию справа отображаются подкатегории
    с иконками и названиями."""
    open_catalog(page)

    # Наводим на первую категорию, у которой есть подкатегории
    hover_category_with_subcategories(page)

    subcategories_panel = page.locator(f"{SUBCATEGORIES}.active")
    expect(subcategories_panel).to_be_visible(timeout=5_000)

    # Подкатегории содержат элементы
    items = subcategories_panel.locator(SUBCATEGORIES_ITEM)
    assert items.count() > 0

    # Каждая подкатегория имеет название
    first_item = items.first
    expect(first_item).to_be_visible()
    assert first_item.text_content().strip() != ""


# ===========================================================================
# Кейс 12: Категория без подкатегорий
# ===========================================================================
def test_category_without_subcategories(page: Page):
    """При наведении на категорию без подкатегорий — панель подкатегорий
    не отображается или пуста."""
    open_catalog(page)

    categories = page.locator(CATEGORY_LINK)
    count = categories.count()

    # Ищем категорию без подкатегорий (перебираем)
    empty_category = None
    for i in range(count):
        cat = categories.nth(i)
        cat.hover()
        page.wait_for_timeout(300)

        active_panel = page.locator(f"{SUBCATEGORIES}.active")
        if active_panel.count() == 0 or active_panel.locator(SUBCATEGORIES_ITEM).count() == 0:
            empty_category = cat
            break

    if empty_category is None:
        pytest.skip("Все категории имеют подкатегории — кейс не применим")

    # Раньше тест на этом заканчивался без единого ассерта: нашли категорию —
    # молча прошёл, не нашли — скип. Упасть он не мог в принципе, то есть
    # регрессию не поймал бы. Проверяем состояние ЯВНО.
    name = (empty_category.inner_text() or "").strip()
    empty_category.hover()

    panel = page.locator(f"{SUBCATEGORIES}.active")
    if panel.count():
        expect(panel.locator(SUBCATEGORIES_ITEM)).to_have_count(
            0, timeout=10_000
        ), f"У категории «{name}» без подкатегорий панель показывает элементы"
    else:
        expect(page.locator(f"{SUBCATEGORIES}.active")).to_have_count(0, timeout=10_000)

    # Меню при этом остаётся рабочим, а не схлопывается вместе с панелью.
    expect(page.locator(MENU_ITEMS)).to_be_visible(timeout=10_000)


# ===========================================================================
# Кейс 13: Переход на страницу подкатегории
# ===========================================================================
def test_navigate_to_subcategory_page(page: Page):
    """Нажать на подкатегорию — открывается страница с хлебными крошками,
    описанием и списком товаров/подкатегорий."""
    open_catalog(page)

    # Наводим на первую категорию, у которой есть подкатегории
    hover_category_with_subcategories(page)
    expect(page.locator(f"{SUBCATEGORIES}.active")).to_be_visible(timeout=5_000)

    # Кликаем на первую подкатегорию
    subcategory = page.locator(f"{SUBCATEGORIES}.active {SUBCATEGORY_LINK}").first
    subcategory_text = subcategory.text_content().strip()
    subcategory.click()

    # Страница загрузилась — URL изменился
    page.wait_for_load_state("networkidle")
    expect(page).not_to_have_url(re.compile(r"^https?://[^/]+/ru/?$"), timeout=10_000)

    # Хлебные крошки отображаются
    expect(page.locator(BREADCRUMB_CURRENT)).to_be_visible(timeout=10_000)


# ===========================================================================
# Кейс 14: Переход на страницу со списком товаров
# ===========================================================================
def test_navigate_to_product_list_page(page: Page):
    """Нажать на категорию (стрелка) — открывается страница со списком товаров,
    сортировкой, фильтрами и пагинацией."""
    open_catalog(page)

    # Нажимаем на стрелку категории или саму категорию для перехода
    arrow = page.locator(CATEGORY_LINK_ARROW).first
    if arrow.count() > 0 and arrow.is_visible():
        arrow.click()
    else:
        page.locator(CATEGORY_LINK).first.click()

    page.wait_for_load_state("networkidle")

    # URL изменился — мы на странице категории
    expect(page).not_to_have_url(re.compile(r"^https?://[^/]+/ru/?$"), timeout=10_000)

    # Хлебные крошки
    expect(page.locator(BREADCRUMB_CURRENT)).to_be_visible(timeout=10_000)

    # Проверяем наличие товаров или подкатегорий на странице
    has_products = page.locator("[class*='product'], [class*='card']").count() > 0
    has_subcategories = page.locator("[class*='subcategor'], [class*='category']").count() > 0
    assert has_products or has_subcategories, "Страница не содержит товаров или подкатегорий"


# ===========================================================================
# Кейс 302: Переход по кнопке «Все <категория>»
# ===========================================================================
def test_navigate_via_all_category_button(page: Page):
    """Навести на категорию → нажать «Все <категория>» в футере подкатегорий —
    открывается страница с товарами выбранной категории."""
    open_catalog(page)

    # Наводим на первую категорию
    page.locator(CATEGORY_LINK).first.hover()
    expect(page.locator(f"{SUBCATEGORIES}.active")).to_be_visible(timeout=5_000)

    # Ищем кнопку «Все ...» в футере подкатегорий
    all_btn = page.locator(f"{FOOTER_SUBCATEGORY} a, {FOOTER_SUBCATEGORY} button").first

    if all_btn.count() == 0:
        # Альтернативный селектор
        all_btn = page.locator(f"{SUBCATEGORIES}.active").locator(
            "a:has-text('Все'), button:has-text('Все')"
        ).first

    if all_btn.count() > 0 and all_btn.is_visible():
        all_btn.click()
        page.wait_for_load_state("networkidle")

        # Страница категории загрузилась
        expect(page).not_to_have_url(
            re.compile(r"^https?://[^/]+/ru/?$"), timeout=10_000
        )
        expect(page.locator(BREADCRUMB_CURRENT)).to_be_visible(timeout=10_000)
    else:
        pytest.skip("Кнопка «Все <категория>» не найдена")


# ===========================================================================
# Кейс 303: Отключение фонового скролла при открытом меню
# ===========================================================================
def test_background_scroll_disabled_when_menu_open(page: Page):
    """При открытом меню каталога фоновая страница не прокручивается."""
    # Запоминаем позицию скролла
    scroll_before = page.evaluate("window.scrollY")

    open_catalog(page)

    # Проверяем что body имеет overflow: hidden или аналог
    overflow = page.evaluate(
        "getComputedStyle(document.body).overflow"
    )
    overflow_y = page.evaluate(
        "getComputedStyle(document.body).overflowY"
    )

    # Пробуем прокрутить страницу через JS
    page.evaluate("window.scrollBy(0, 300)")
    page.wait_for_timeout(300)
    scroll_after = page.evaluate("window.scrollY")

    # Скролл заблокирован — позиция не изменилась, или body имеет overflow: hidden
    scroll_blocked = (
        scroll_before == scroll_after
        or "hidden" in overflow
        or "hidden" in overflow_y
    )
    assert scroll_blocked, (
        f"Фоновый скролл не заблокирован: overflow={overflow}, "
        f"scroll before={scroll_before}, after={scroll_after}"
    )


# ===========================================================================
# Кейс 21: Хлебные крошки — переход на прошлую страницу
# ===========================================================================
BREADCRUMB_ITEM = ".breadcrumb__items .breadcrumb__item"


def test_breadcrumb_navigates_to_parent_page(page: Page, in_stock_product: str):
    """Клик по предыдущей крошке возвращает на родительскую страницу.

    Берём страницу товара, а не подкатегории: там цепочка из трёх звеньев
    (Главная → категория → товар), и «прошлая страница» — это именно категория.
    У подкатегории звеньев два, и тест сводился бы к переходу на главную,
    то есть проверял бы обычную ссылку, а не работу крошек.
    """
    page.goto(in_stock_product, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1")).to_be_visible(timeout=15_000)

    items = page.locator(BREADCRUMB_ITEM)
    expect(items.first).to_be_visible(timeout=10_000)
    depth_before = items.count()
    assert depth_before >= 3, (
        f"В крошках {depth_before} звена — родительской страницы нет, "
        f"проверять переход не на что"
    )

    # Последнее звено — текущая страница (span без ссылки), поэтому родитель —
    # это последняя ССЫЛКА в цепочке.
    links = items.locator("a")
    parent = links.nth(links.count() - 1)
    parent_text = parent.inner_text().strip()
    parent_href = parent.get_attribute("href")

    parent.click()

    # Перешли именно на страницу из крошки
    expect(page).to_have_url(re.compile(re.escape(parent_href) + r"/?$"), timeout=15_000)
    # Заголовок открытой страницы совпадает с текстом крошки (регистр другой —
    # в крошках он поднят капсом через CSS)
    expect(page.locator("h1")).to_have_text(
        re.compile(re.escape(parent_text), re.IGNORECASE), timeout=15_000
    )

    # Цепочка укоротилась на одно звено — мы поднялись на уровень выше
    expect(page.locator(BREADCRUMB_ITEM)).to_have_count(
        depth_before - 1, timeout=10_000
    )
