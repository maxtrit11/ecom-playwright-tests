"""Каталог товаров — мобильная версия (зеркало tests/test_catalog_menu.py).

Функционал тот же, устройство другое:
  * кнопки «Каталог товаров» в шапке нет — каталог открывается из нижнего бара
    (`.mobile__bar #showCatalog`) или из бургер-меню (пункт «Каталог»);
  * каталог — полноэкранная шторка `.catalog__mobile`, которая выезжает снизу
    (закрыта = сдвинута за экран через transform, открыта = класс `show`);
  * наведения нет: подкатегории раскрываются аккордеоном по стрелке `.btn__arr`,
    заголовок категории переключает класс `close` → `open`.

Шторка в закрытом состоянии остаётся в DOM и имеет размеры, поэтому
`to_be_visible()` для неё всегда true — открытость проверяем классом `show` и
тем, что шторка в пределах экрана (`to_be_in_viewport`).

Кейсы без мобильного аналога не перенесены: 9 (подсветка при наведении — на
тач-экране наведения нет) и закрытие кликом вне меню из 301 (шторка на весь
экран, «вне» не существует).
"""

import re

import pytest
from playwright.sync_api import Page, expect

# Селекторы
BAR_CATALOG_BTN = ".mobile__bar #showCatalog"
BURGER_BTN = ".header__mobile_ecom .btn__menu"
BURGER_MENU = ".menu__mobile_ecom"
CATALOG = ".catalog__mobile"
CATALOG_CLOSE = ".close__catalog"
CATALOG_ITEM = f"{CATALOG} .catalog__item"
ITEM_HEAD = ".catalog__item_head"
CATALOG_LINK = ".catalog__link"
EXPAND_ARROW = ".btn__arr"
SUBCATEGORIES = ".subcategories"
SUBCATEGORY_LINK = ".subcategories__item a:not(.subcategories__item-all-products)"
ALL_PRODUCTS_LINK = ".subcategories__item-all-products"
BREADCRUMB_CURRENT = ".breadcrumb__item[aria-current='page']"
BREADCRUMB_ITEM = ".breadcrumb__items .breadcrumb__item"

SHOWN = re.compile(r"\bshow\b")
HOME_URL = re.compile(r"^https?://[^/]+/(ru/?)?$")


@pytest.fixture(autouse=True)
def open_main_page(page: Page):
    """Открыть главную и дождаться мобильного нижнего бара."""
    page.goto("/ru")
    page.wait_for_load_state("networkidle")
    expect(page.locator(BAR_CATALOG_BTN)).to_be_visible(timeout=10_000)


def open_catalog(page: Page):
    """Открыть шторку каталога из нижнего бара и вернуть её локатор.

    Тап с повтором: первый тап по бару сразу после загрузки регулярно теряется
    (гонка с гидрацией, как у кнопок шапки на десктопе). Повторяем, только пока
    шторка закрыта, — иначе второй тап пришёлся бы на кнопку под шторкой.
    """
    catalog = page.locator(CATALOG)
    for _ in range(3):
        if SHOWN.search(catalog.get_attribute("class") or ""):
            break
        page.locator(BAR_CATALOG_BTN).tap()
        try:
            expect(catalog).to_have_class(SHOWN, timeout=5_000)
            break
        except AssertionError:
            continue
    expect(catalog).to_have_class(SHOWN)
    expect(catalog).to_be_in_viewport()
    return catalog


def expandable_item(page: Page):
    """Первая категория со стрелкой, то есть с подкатегориями."""
    item = page.locator(CATALOG_ITEM).filter(has=page.locator(EXPAND_ARROW)).first
    if item.count() == 0:
        pytest.skip("Ни у одной категории нет подкатегорий")
    return item


def expand(item):
    """Раскрыть категорию стрелкой и дождаться списка подкатегорий."""
    item.locator(EXPAND_ARROW).tap()
    expect(item.locator(ITEM_HEAD)).to_have_class(re.compile(r"\bopen\b"))
    expect(item.locator(SUBCATEGORIES)).to_be_visible()


def assert_landed_on(page: Page, href: str, name: str):
    """Открылась страница именно этой ссылки, и крошки называют её так же."""
    expect(page).to_have_url(re.compile(re.escape(href) + r"/?(\?.*)?$"), timeout=15_000)
    # Регистр в крошках поднят через CSS — сравниваем без учёта регистра.
    expect(page.locator(BREADCRUMB_CURRENT)).to_have_text(
        re.compile(re.escape(name), re.IGNORECASE), timeout=15_000
    )


# ===========================================================================
# Кейс 300 (моб.): Открыть каталог из нижнего бара
# ===========================================================================
@pytest.mark.smoke
def test_open_catalog_from_bottom_bar(page: Page):
    """Тап по «Каталог» в нижнем баре — выезжает шторка со списком категорий."""
    catalog = open_catalog(page)

    expect(catalog.locator(".catalog__head-title")).to_be_visible()
    links = catalog.locator(CATALOG_LINK)
    expect(links.first).to_be_visible()
    assert links.count() > 0, "В шторке каталога нет ни одной категории"


# ===========================================================================
# Кейс 300 (моб.): Открыть каталог из бургер-меню
# ===========================================================================
def test_open_catalog_from_burger_menu(page: Page):
    """Бургер → «Каталог» — открывается та же шторка, бургер-меню закрывается."""
    burger_menu = page.locator(BURGER_MENU)
    page.locator(BURGER_BTN).tap()
    expect(burger_menu).to_have_class(SHOWN)

    burger_menu.locator("button.menu__item", has_text="Каталог").tap()

    catalog = page.locator(CATALOG)
    expect(catalog).to_have_class(SHOWN)
    expect(catalog).to_be_in_viewport()
    expect(catalog.locator(CATALOG_LINK).first).to_be_visible()
    expect(burger_menu).not_to_have_class(SHOWN)


# ===========================================================================
# Кейс 301 (моб.): Закрыть каталог
# ===========================================================================
def test_close_catalog_by_close_button(page: Page):
    """Крестик в шапке шторки — шторка уезжает за экран."""
    catalog = open_catalog(page)

    catalog.locator(CATALOG_CLOSE).tap()

    expect(catalog).not_to_have_class(SHOWN)
    expect(catalog).not_to_be_in_viewport()
    # Нижний бар снова доступен — шторка его больше не накрывает
    expect(page.locator(BAR_CATALOG_BTN)).to_be_in_viewport()


# ===========================================================================
# Кейс 11 (моб.): Подкатегории раскрываются по стрелке
# ===========================================================================
def test_subcategories_expand_on_arrow(page: Page):
    """Тап по стрелке категории — под ней раскрываются подкатегории с названиями."""
    open_catalog(page)
    item = expandable_item(page)
    expect(item.locator(ITEM_HEAD)).to_have_class(re.compile(r"\bclose\b"))
    expect(item.locator(SUBCATEGORIES)).to_be_hidden()

    expand(item)

    sub_links = item.locator(SUBCATEGORY_LINK)
    expect(sub_links.first).to_be_visible()
    assert sub_links.first.inner_text().strip() != "", "Подкатегория без названия"


# ===========================================================================
# Кейс 11 (моб.): Свернуть подкатегории повторным тапом
# ===========================================================================
def test_subcategories_collapse_on_second_tap(page: Page):
    """Повторный тап по стрелке сворачивает подкатегории обратно."""
    open_catalog(page)
    item = expandable_item(page)
    expand(item)

    item.locator(EXPAND_ARROW).tap()

    expect(item.locator(ITEM_HEAD)).to_have_class(re.compile(r"\bclose\b"))
    expect(item.locator(SUBCATEGORIES)).to_be_hidden()


# ===========================================================================
# Кейс 12 (моб.): Категория без подкатегорий
# ===========================================================================
def test_category_without_subcategories(page: Page):
    """У категории без подкатегорий нет стрелки и нечего раскрывать —
    остаётся только ссылка на саму категорию."""
    catalog = open_catalog(page)

    plain = page.locator(CATALOG_ITEM).filter(has_not=page.locator(EXPAND_ARROW))
    if plain.count() == 0:
        pytest.skip("Все категории имеют подкатегории — кейс не применим")
    item = plain.first
    name = item.locator(CATALOG_LINK).inner_text().strip()

    expect(
        item.locator(SUBCATEGORY_LINK), f"У категории «{name}» без стрелки есть подкатегории"
    ).to_have_count(0)
    expect(item.locator(CATALOG_LINK)).to_have_attribute("href", re.compile(r".+"))
    # Шторка при этом остаётся рабочей
    expect(catalog).to_have_class(SHOWN)


# ===========================================================================
# Кейс 13 (моб.): Переход на страницу подкатегории
# ===========================================================================
def test_navigate_to_subcategory_page(page: Page):
    """Раскрыть категорию → тап по подкатегории — открывается её страница
    с хлебными крошками."""
    open_catalog(page)
    item = expandable_item(page)
    expand(item)

    sub = item.locator(SUBCATEGORY_LINK).first
    name = sub.inner_text().strip()
    href = sub.get_attribute("href")
    sub.tap()

    assert_landed_on(page, href, name)


# ===========================================================================
# Кейс 14 (моб.): Переход на страницу со списком товаров
# ===========================================================================
def test_navigate_to_product_list_page(page: Page):
    """Тап по названию категории — открывается страница категории с товарами
    или подкатегориями."""
    open_catalog(page)

    link = page.locator(f"{CATALOG_ITEM} {CATALOG_LINK}").first
    name = link.inner_text().strip()
    href = link.get_attribute("href")
    link.tap()

    assert_landed_on(page, href, name)
    expect(page).not_to_have_url(HOME_URL)

    has_products = page.locator("[class*='product'], [class*='card']").count() > 0
    has_subcategories = page.locator("[class*='subcategor'], [class*='category']").count() > 0
    assert has_products or has_subcategories, "Страница не содержит товаров или подкатегорий"


# ===========================================================================
# Кейс 302 (моб.): Переход по кнопке «Все товары»
# ===========================================================================
def test_navigate_via_all_products_button(page: Page):
    """Раскрыть категорию → «Все товары» в группе подкатегорий — открывается
    страница этой группы."""
    open_catalog(page)
    item = expandable_item(page)
    expand(item)

    all_btn = item.locator(ALL_PRODUCTS_LINK).first
    if all_btn.count() == 0:
        pytest.skip("Кнопка «Все товары» не найдена")
    href = all_btn.get_attribute("href")
    # «Все товары» ведёт на страницу группы — её название стоит в заголовке
    # той же группы (li.title).
    group_title = (
        item.locator(".subcategories__group")
        .filter(has=page.locator(ALL_PRODUCTS_LINK))
        .first.locator(".title a")
        .inner_text()
        .strip()
    )
    all_btn.tap()

    assert_landed_on(page, href, group_title)


# ===========================================================================
# Кейс 303 (моб.): Отключение фонового скролла при открытом каталоге
# ===========================================================================
def test_background_scroll_disabled_when_catalog_open(page: Page):
    """Пока шторка открыта, страница под ней не прокручивается."""
    # Контроль: при закрытой шторке тот же жест страницу прокручивает, иначе
    # проверка ниже прошла бы и на непрокручиваемой странице.
    page.mouse.move(200, 300)
    page.mouse.wheel(0, 500)
    page.wait_for_function("() => window.scrollY > 0", timeout=5_000)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_function("() => window.scrollY === 0", timeout=5_000)

    open_catalog(page)
    expect(page.locator("body")).to_have_class(re.compile(r"\bpopup-open\b"))
    expect(page.locator("body")).to_have_css("overflow", "hidden")

    page.mouse.move(200, 300)
    page.mouse.wheel(0, 500)
    page.wait_for_timeout(500)
    assert page.evaluate("window.scrollY") == 0, "Фон прокрутился под открытым каталогом"


# ===========================================================================
# Кейс 21 (моб.): Хлебные крошки — переход на прошлую страницу
# ===========================================================================
def test_breadcrumb_navigates_to_parent_page(page: Page, in_stock_product: str):
    """Тап по предыдущей крошке на карточке товара возвращает в категорию
    (см. десктопный тест — почему именно карточка товара)."""
    page.goto(in_stock_product, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1")).to_be_visible(timeout=15_000)

    items = page.locator(BREADCRUMB_ITEM)
    expect(items.first).to_be_visible(timeout=10_000)
    depth_before = items.count()
    assert depth_before >= 3, (
        f"В крошках {depth_before} звена — родительской страницы нет, "
        f"проверять переход не на что"
    )

    links = items.locator("a")
    parent = links.nth(links.count() - 1)
    parent_text = parent.inner_text().strip()
    parent_href = parent.get_attribute("href")

    parent.tap()

    expect(page).to_have_url(re.compile(re.escape(parent_href) + r"/?$"), timeout=15_000)
    expect(page.locator("h1")).to_have_text(
        re.compile(re.escape(parent_text), re.IGNORECASE), timeout=15_000
    )
    expect(page.locator(BREADCRUMB_ITEM)).to_have_count(depth_before - 1, timeout=10_000)
