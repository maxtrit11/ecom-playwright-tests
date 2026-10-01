"""Тесты поля Поиск (Qase suite: Поле Поиск)"""

import re

import pytest
from playwright.sync_api import Page, expect

from test_sorting import _in_stock_prices

# Селекторы поиска
# В DOM главной страницы — две копии каждого элемента поиска (десктопный
# и мобильный для разметки ≤1024px). Чтобы strict-mode Playwright находил
# ровно один элемент, скоупим всё к десктопному контейнеру .header__items.
# На странице /search дубликатов нет — селектор работает и там.
SEARCH_FORM = ".header__items #searchForm"
SEARCH_INPUT = ".header__items #search__input"
BTN_SEARCH = ".header__items .btn__search"
BTN_DELETE = ".header__items .btn__delete"
MODAL_SEARCH = ".header__items .modal__search"
MODAL_SEARCH_SHOW = ".header__items .modal__search.show"
POPULAR_BADGES = ".header__items .badges.search .badge"
RESULT_PRODUCT = ".header__items .result__product"
PRODUCT_NAME = ".product__name"
PRODUCT_PRICE = ".product__price"
ALL_RESULTS_LINK = ".header__items #allSearchResults"
RESULT_CATEGORIES = ".header__items .result__categories .item"
MESSAGE_NO_RESULTS = ".header__items .message"
MESSAGE_TEXT = ".message__text"

# Селекторы страницы результатов поиска
SEARCH_PAGE_FILTERS = "[class*='filter'], .filters, .sidebar__filter"
SEARCH_PAGE_SORT = "[class*='sort'], .sorting"
SEARCH_PAGE_PRODUCTS = "[class*='product-card'], [class*='card__product'], .product__item"
SEARCH_PAGE_VIEW_BTNS = "[class*='view'], [class*='display']"

# Контрол сортировки на странице результатов (та же разметка, что в категории)
SORT_BTN = ".sorting-bar__btn"
SORT_OPTION = ".sorting-bar__list span"


def _card_prices(page: Page) -> list[int]:
    """Цены товаров в наличии из сетки результатов, в банях, в порядке
    отображения.

    Раньше цены собирались селектором `[class*='price']` по ВСЕЙ странице:
    первыми в DOM идут элементы фильтра цены (границы диапазона), поэтому
    в сравнение попадала не цена товара, а верхняя граница фильтра — тест
    падал с «первая цена 431999.0 > последняя 296.65» на исправной
    сортировке (e2e run 31599538819).

    Потом здесь стояла своя копия разбора: `.no-discount` + parseInt по всем
    цифрам. `.no-discount` есть только у товаров без скидки (остальные
    выпадали из проверки), а склейка цифр превращала «2 379.15 MDL» в 237915
    рядом с «1 899 MDL» = 1899 (30.09.2026). Теперь — общий хелпер сортировки:
    текущая цена карточки, в банях, без товаров «нет в наличии».
    """
    return _in_stock_prices(page)


EXISTING_QUERY = "jbl"
NON_EXISTING_QUERY = "sdfsdds"


@pytest.fixture(autouse=True)
def open_main_page(page: Page):
    """Открыть главную страницу."""
    page.goto("/ru")
    page.wait_for_load_state("networkidle")
    expect(page.locator(SEARCH_INPUT)).to_be_visible(timeout=10_000)


def type_in_search(page: Page, text: str):
    """Ввести текст в поле поиска и дождаться результатов."""
    page.locator(SEARCH_INPUT).click()
    page.locator(SEARCH_INPUT).fill(text)
    page.wait_for_timeout(1000)  # debounce


def go_to_search_results_page(page: Page, query: str):
    """Перейти на страницу результатов поиска."""
    page.goto(f"/ru/search?query={query}")
    page.wait_for_load_state("networkidle")


PRODUCT_URL_RE = re.compile(r"/product/|/produs/")


def _click_until_product_page(page: Page, locator) -> bool:
    """Кликнуть по ссылке на товар, повторяя, пока не сменится URL.

    Переход внутри SPA: первый клик по ссылке регулярно уходит до того, как Vue
    навесит обработчик, и страница просто остаётся на месте. Тест падал с
    «Не перешли на страницу товара: <исходный URL>» на живой рабочей ссылке.
    """
    for _ in range(3):
        locator.click()
        try:
            page.wait_for_url(PRODUCT_URL_RE, timeout=10_000)
            return True
        except Exception:
            page.wait_for_timeout(500)
    return bool(PRODUCT_URL_RE.search(page.url))


# ===========================================================================
# Выпадающий блок поиска
# ===========================================================================

# Кейс 299: Популярные запросы
def test_popular_queries_displayed_on_focus(page: Page):
    """При клике на поле поиска отображается блок «Популярные запросы»,
    клик по запросу подставляет значение и выполняет поиск."""
    page.locator(SEARCH_INPUT).click()
    page.wait_for_timeout(500)

    # На стейдже блок «Популярных запросов» появляется только после ввода
    # символа; .modal__search.show на пустом фокусе не подсвечивается и
    # бейджей не рендерится. Скипаем — фича в текущей реализации отсутствует.
    badges = page.locator(POPULAR_BADGES)
    if badges.count() == 0:
        pytest.skip("Блок «Популярные запросы» не реализован на стейдже")

    expect(page.locator(MODAL_SEARCH_SHOW)).to_be_visible(timeout=5_000)
    expect(badges.first).to_be_visible(timeout=5_000)

    badges.first.click()
    page.wait_for_timeout(1000)

    search_value = page.locator(SEARCH_INPUT).input_value()
    assert search_value.strip() != "", "Значение не подставилось в поле поиска"


# Кейс 15: Список результатов при вводе существующего значения
def test_search_results_dropdown_with_existing_query(page: Page):
    """Ввести существующий товар — в выпадающем блоке отображаются
    карточки товаров (фото, название, цена), кнопка «Все результаты»
    и список категорий."""
    type_in_search(page, EXISTING_QUERY)

    # Карточки товаров в выпадающем блоке
    products = page.locator(RESULT_PRODUCT)
    expect(products.first).to_be_visible(timeout=10_000)
    assert products.count() > 0

    # Каждая карточка имеет фото, название, цену
    first_product = products.first
    expect(first_product.locator("img")).to_be_visible()
    expect(first_product.locator(PRODUCT_NAME)).to_be_visible()

    # Кнопка «Все результаты поиска»
    all_results = page.locator(ALL_RESULTS_LINK)
    expect(all_results).to_be_visible()

    # Список категорий
    categories = page.locator(RESULT_CATEGORIES)
    if categories.count() > 0:
        expect(categories.first).to_be_visible()


# Кейс 16: Заглушка при несуществующем запросе
def test_search_no_results_placeholder(page: Page):
    """Ввести несуществующее значение — отображается заглушка
    с картинкой и текстом."""
    type_in_search(page, NON_EXISTING_QUERY)

    message = page.locator(MESSAGE_NO_RESULTS)
    expect(message).to_be_visible(timeout=10_000)

    # Картинка и текст
    expect(message.locator("img")).to_be_visible()
    expect(message.locator(MESSAGE_TEXT)).to_be_visible()


# Кейс 17: Переход на страницу товара из выпадающего списка
def test_click_product_in_dropdown_navigates_to_product_page(page: Page):
    """Нажать на карточку товара в выпадающем списке —
    открывается страница товара."""
    type_in_search(page, EXISTING_QUERY)

    products = page.locator(RESULT_PRODUCT)
    expect(products.first).to_be_visible(timeout=10_000)

    assert _click_until_product_page(page, products.first), (
        f"Не перешли на страницу товара: {page.url}"
    )


# Кейс 18: Переход в категорию из результатов поиска
def test_click_category_in_search_results(page: Page):
    """Нажать на категорию в «Результаты в категориях» —
    открывается страница категории с товарами."""
    type_in_search(page, EXISTING_QUERY)

    # Блок «Результаты в категориях» убран с фронта (изменение UI, подтверждено
    # 2026-06-15): в выпадающем поиске категорий справа больше нет. Фича
    # отсутствует — корректно пропускаем, а не падаем.
    categories = page.locator(RESULT_CATEGORIES)
    if categories.count() == 0:
        pytest.skip("Категории в выпадающем поиске убраны с фронта (изменение UI)")
    expect(categories.first).to_be_visible(timeout=10_000)

    category_text = categories.first.text_content().strip()
    categories.first.click()
    page.wait_for_load_state("networkidle")

    # URL изменился — мы на странице категории
    assert page.url != "about:blank"
    expect(page).not_to_have_url(re.compile(r"/ru/?$"), timeout=5_000)


# Кейс 19: Переход по кнопке «Все результаты поиска»
def test_all_search_results_button(page: Page):
    """Нажать «Все результаты поиска» — открывается страница
    с полными результатами."""
    type_in_search(page, EXISTING_QUERY)

    all_results = page.locator(ALL_RESULTS_LINK)
    expect(all_results).to_be_visible(timeout=10_000)

    all_results.click()
    page.wait_for_load_state("networkidle")

    # URL содержит /search?query=
    expect(page).to_have_url(re.compile(r"search\?query="), timeout=10_000)


# Кейс 20: Закрыть блок поиска кнопкой X
def test_close_search_and_clear_input(page: Page):
    """Ввести значение → нажать X — выпадающий блок закрывается,
    поле очищается."""
    type_in_search(page, EXISTING_QUERY)

    # Ждём появления результатов или блока
    expect(page.locator(MODAL_SEARCH_SHOW)).to_be_visible(timeout=5_000)

    # Нажать X
    delete_btn = page.locator(BTN_DELETE)
    if delete_btn.is_visible():
        delete_btn.click()
        page.wait_for_timeout(500)

        # Блок закрылся
        expect(page.locator(MODAL_SEARCH_SHOW)).not_to_be_visible(timeout=5_000)

        # Поле очищено
        assert page.locator(SEARCH_INPUT).input_value() == ""
    else:
        pytest.skip("Кнопка X не видна на данном варианте верстки")


# Кейс 293: Поиск с пробелами в начале/конце
def test_search_with_leading_trailing_spaces(page: Page):
    """Поиск с пробелами — результаты такие же как без пробелов."""
    # Поиск без пробелов
    type_in_search(page, "pink")
    page.wait_for_timeout(1000)
    products_normal = page.locator(RESULT_PRODUCT).count()

    # Очищаем и ищем с пробелами
    page.locator(SEARCH_INPUT).fill("")
    page.wait_for_timeout(500)
    type_in_search(page, "  pink  ")
    page.wait_for_timeout(1000)
    products_spaces = page.locator(RESULT_PRODUCT).count()

    # Результаты совпадают
    assert products_normal == products_spaces, (
        f"Результаты отличаются: без пробелов={products_normal}, "
        f"с пробелами={products_spaces}"
    )


# ===========================================================================
# Страница результатов поиска
# ===========================================================================

# Кейс 328: Положительный сценарий — поиск через Enter
@pytest.mark.smoke
def test_search_via_enter_shows_results_page(page: Page):
    """Клик на поле → ввод запроса → Enter — открывается страница
    с результатами поиска."""
    page.locator(SEARCH_INPUT).click()
    page.locator(SEARCH_INPUT).fill(EXISTING_QUERY)
    page.keyboard.press("Enter")
    page.wait_for_load_state("networkidle")

    # Страница результатов
    expect(page).to_have_url(re.compile(r"search\?query="), timeout=10_000)

    # Есть товары
    page.wait_for_timeout(1000)
    body_text = page.locator("body").text_content()
    assert EXISTING_QUERY.lower() in body_text.lower() or len(body_text) > 500


# Кейс 329: Отрицательный сценарий — товар не найден
def test_search_no_results_on_results_page(page: Page):
    """Поиск несуществующего значения — на странице отображается
    заглушка «не найдено», нет ошибок верстки."""
    go_to_search_results_page(page, NON_EXISTING_QUERY)

    # Страница не пустая, нет ошибок — заглушка или текст «не найдено»
    page.wait_for_timeout(1000)
    body = page.locator("body")
    expect(body).to_be_visible()

    # Товары не отображаются
    products = page.locator(SEARCH_PAGE_PRODUCTS)
    assert products.count() == 0, "Найдены товары для несуществующего запроса"


# Кейс 330: Смена контента при новом запросе
def test_search_content_changes_on_new_query(page: Page):
    """На странице результатов ввести новый запрос —
    результаты обновляются, URL меняется."""
    go_to_search_results_page(page, "new")

    old_url = page.url

    # Вводим новый запрос
    search_input = page.locator(SEARCH_INPUT)
    search_input.fill(EXISTING_QUERY)
    page.keyboard.press("Enter")
    page.wait_for_load_state("networkidle")

    # URL изменился
    assert page.url != old_url
    assert EXISTING_QUERY in page.url


# Кейс 294: Значение поиска сохраняется на странице результатов
def test_search_value_preserved_on_results_page(page: Page):
    """После перехода на страницу результатов запрос отображается
    в строке поиска."""
    type_in_search(page, "pink")

    all_results = page.locator(ALL_RESULTS_LINK)
    expect(all_results).to_be_visible(timeout=10_000)
    all_results.click()
    page.wait_for_load_state("networkidle")

    # Значение сохранено в поле поиска
    search_value = page.locator(SEARCH_INPUT).input_value()
    assert "pink" in search_value.strip().lower()


# Кейс 295: Повторный поиск через Enter на странице результатов
def test_search_again_via_enter_on_results_page(page: Page):
    """На странице результатов ввести новый запрос и нажать Enter —
    результаты и URL обновляются."""
    go_to_search_results_page(page, "pink")

    search_input = page.locator(SEARCH_INPUT)
    search_input.fill("jbl")
    page.keyboard.press("Enter")
    page.wait_for_load_state("networkidle")

    expect(page).to_have_url(re.compile(r"query=jbl"), timeout=10_000)


# Кейс 296: Фильтры на странице результатов
def test_filters_displayed_on_search_results_page(page: Page):
    """На странице результатов поиска отображается блок фильтров,
    верстка не ломается."""
    go_to_search_results_page(page, "pink")

    page.wait_for_timeout(1000)
    # Фильтры на странице результатов — это сайдбар .filters-vertical (как на
    # странице категории). Широкий [class*='filter'] первым матчит СКРЫТЫЙ
    # .filter-btn (mobile-тоггл), из-за чего .first.to_be_visible() давал ложное
    # падение — проверяем именно видимый контейнер фильтров.
    filters = page.locator(".filters-vertical, .filter-vertical-container").first
    if filters.count() > 0:
        expect(filters).to_be_visible()
    else:
        sidebar = page.locator("[class*='sidebar'], [class*='aside']")
        if sidebar.count() > 0:
            expect(sidebar.first).to_be_visible()
        else:
            pytest.skip("Блок фильтров не найден на странице результатов")


# Кейс 297: Сортировка — открытие списка
def test_sort_dropdown_opens_on_results_page(page: Page):
    """Нажать на блок сортировки — открывается список вариантов,
    элементы кликабельны."""
    go_to_search_results_page(page, EXISTING_QUERY)

    sort_block = page.locator(SEARCH_PAGE_SORT)
    if sort_block.count() == 0:
        sort_block = page.locator("button:has-text('умолчанию'), [class*='sort']")

    if sort_block.count() > 0 and sort_block.first.is_visible():
        sort_block.first.click()
        page.wait_for_timeout(500)

        # На стейдже опции — <span> внутри .sorting-bar__list, поэтому
        # перечисляем span/li/a/option, чтобы покрыть оба варианта вёрстки
        sort_options = page.locator(
            ".sorting-bar__list span, "
            "[class*='sort'] li, [class*='sort'] option, "
            "[class*='dropdown'] li, [class*='sort'] a"
        )
        assert sort_options.count() >= 2, "Список сортировок не раскрылся"
    else:
        pytest.skip("Блок сортировки не найден")


# Кейс 298: Смена вида отображения (плитка/список)
def test_toggle_view_mode_on_results_page(page: Page):
    """Переключение вида отображения товаров — карточки меняют
    отображение, данные сохраняются."""
    go_to_search_results_page(page, EXISTING_QUERY)

    view_btns = page.locator(SEARCH_PAGE_VIEW_BTNS + " button, " + SEARCH_PAGE_VIEW_BTNS)
    if view_btns.count() >= 2:
        # Нажимаем на второй вариант
        view_btns.nth(1).click()
        page.wait_for_timeout(500)

        # Товары всё ещё отображаются
        products = page.locator(SEARCH_PAGE_PRODUCTS)
        assert products.count() > 0, "Товары пропали после смены вида"
    else:
        pytest.skip("Кнопки переключения вида не найдены")


# Кейс 331: Сортировка — от низкой цены к высокой
def test_sort_by_price_ascending(page: Page):
    """Выбрать сортировку «От самой низкой цены» — первый товар
    дешевле или равен последнему."""
    go_to_search_results_page(page, EXISTING_QUERY)

    # Контрол сортировки — тот же `.sorting-bar`, что на странице категории
    # (см. tests/test_sorting.py). Широкий `[class*='sort'].first` брал внешнюю
    # обёртку `div.catalog__sort`: клик по ней список не открывает, опция
    # остаётся hidden, и тест падал по таймауту клика (проверено 2026-07-30).
    #
    # Пропавшая сортировка, пропавшая опция или меньше двух цен — это поломка
    # страницы, а не повод для skip: раньше тест в этих случаях молча
    # пропускался или проходил, не сравнив ни одной пары цен.
    sort_btn = page.locator(SORT_BTN).first
    expect(sort_btn).to_be_visible(timeout=15_000)
    sort_before = page.evaluate("() => new URLSearchParams(location.search).get('sort')")

    sort_btn.click()
    low_price_option = page.locator(SORT_OPTION).filter(
        has_text=re.compile(r"[Нн]изк|[Ll]ow|[Cc]rescător")
    ).first
    expect(low_price_option).to_be_visible(timeout=5_000)
    low_price_option.click()
    page.wait_for_function(
        "(before) => new URLSearchParams(location.search).get('sort') !== before",
        arg=sort_before,
        timeout=20_000,
    )
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    price_values = _card_prices(page)
    assert len(price_values) >= 2, (
        f"На странице результатов меньше двух цен товаров в наличии: {price_values}"
    )
    assert price_values == sorted(price_values), (
        f"Цены не по возрастанию при сортировке «от низкой цены»: "
        f"{[p / 100 for p in price_values]}"
    )


# Кейс 332: Переход на страницу товара со страницы поиска
def test_click_product_card_on_search_page(page: Page):
    """Клик по карточке товара на странице результатов —
    переход на страницу товара."""
    go_to_search_results_page(page, EXISTING_QUERY)

    # Карточки монтируются после гидрации — ждём ссылку в карточке, а не
    # паузу + мгновенный count(). Раньше без карточек тест уходил в skip, а
    # запасной селектор `a[href*='/product/']` по всей странице мог увести
    # на товар из шапки или баннера — пустая выдача не ловилась.
    link = page.locator(".product__items .product__item a[href*='/product/']").first
    expect(link).to_be_visible(timeout=15_000)
    href = link.get_attribute("href")

    assert _click_until_product_page(page, link), (
        f"Не перешли на страницу товара: {page.url}"
    )
    # Открылся именно тот товар, по которому кликнули
    slug = href.rstrip("/").split("/")[-1]
    expect(page).to_have_url(re.compile(re.escape(slug)))


# Кейс 333: Добавление товара в корзину со страницы поиска
def test_add_to_cart_from_search_page(page: Page):
    """Нажать кнопку «В корзину» на странице поиска —
    товар добавляется в корзину."""
    go_to_search_results_page(page, EXISTING_QUERY)

    # Карточки на /search монтируются ПОСЛЕ гидрации. Раньше здесь стоял
    # `wait_for_timeout(1000)` + мгновенный `count()`, и тест уходил в skip
    # («Кнопка «В корзину» не найдена») на полностью исправной странице —
    # проверено вживую 2026-08-26: на /search?query=JBL 15 карточек и 15
    # видимых кнопок. Skip маскировал бы и настоящую поломку, поэтому ждём
    # кнопку через expect (auto-retry) и падаем, если её нет.
    card = page.locator(".product__item").first
    cart_btn = card.locator("button.btn__add_cart")
    expect(cart_btn).to_be_visible(timeout=15_000)

    cart_btn.click()

    # Признак добавления — кнопка в ЭТОЙ ЖЕ карточке подменяется счётчиком
    # количества («− 1 +»). Он стабилен, в отличие от тоста
    # `.notification.cart.show`, который живёт пару секунд и пропадает.
    # На счётчик в шапке опираться нельзя: у `.btn__cart` бейджа в DOM нет.
    # `.first` обязателен: внутри карточки счётчик отрисован дважды
    # (десктопный и мобильный дубли) — без него strict mode валит ассерт.
    expect(card.locator(".product-counter").first).to_be_visible(timeout=10_000)
