"""Тесты поля Поиск (Qase suite: Поле Поиск)"""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import wait_until
from test_product_listing import BTN_VIEW_LIST, VIEW_ACTIVE
from test_sorting import _grid_signature, _in_stock_prices, _wait_grid_changed

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
# Значок запроса: был `.badge`, с октября 2026 — `button.ecom-popular-search-badge`.
POPULAR_BADGES = ".header__items .badges.search :is(.badge, .ecom-popular-search-badge)"
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
SORT_LIST_SHOWN = ".sorting-bar__list.show"

# Сетка результатов и заглушка «ничего не найдено» на /search (DOM снят
# 12.10.2026: та же вёрстка, что у листинга категории)
RESULT_CARD = ".product__items .product__item"
SEARCH_PAGE_EMPTY = ".catalog__container--empty"


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
    """Ввести текст в поле поиска и дождаться выпадашки.

    Раньше здесь стояла пауза 1 с «на debounce», после которой часть тестов
    мгновенно считала карточки. Теперь ждём сам результат: карточки или
    заглушку «ничего не найдено» (как в мобильном зеркале).
    """
    page.locator(SEARCH_INPUT).click()
    page.locator(SEARCH_INPUT).fill(text)
    expect(
        page.locator(f"{RESULT_PRODUCT}, {MESSAGE_NO_RESULTS}").first
    ).to_be_visible(timeout=15_000)


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

    # Запросы задаются в админке; если их не завели — блока нет, и это не
    # дефект. Ждём, а не считаем сразу: мгновенный count() давал ложный skip.
    badges = page.locator(POPULAR_BADGES)
    try:
        badges.first.wait_for(state="visible", timeout=8_000)
    except Exception:
        pytest.skip("Блок «Популярные запросы» пуст — в админке не заведено ни одного запроса")

    expect(page.locator(MODAL_SEARCH_SHOW)).to_be_visible(timeout=5_000)
    expect(badges.first).to_be_visible(timeout=5_000)

    badges.first.click()

    expect(
        page.locator(SEARCH_INPUT), "Значение не подставилось в поле поиска"
    ).not_to_have_value(re.compile(r"^\s*$"), timeout=5_000)


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

    # Нажать X. Раньше при мгновенном `is_visible() == False` тест уходил в
    # skip — пропади крестик, кейс молча перестал бы проверяться. На десктопе
    # он есть (проверено 12.10.2026), поэтому ждём его и падаем, если нет.
    delete_btn = page.locator(BTN_DELETE)
    expect(delete_btn).to_be_visible(timeout=5_000)
    delete_btn.click()

    # Блок закрылся
    expect(page.locator(MODAL_SEARCH_SHOW)).not_to_be_visible(timeout=5_000)

    # Поле очищено
    expect(page.locator(SEARCH_INPUT)).to_have_value("")


# Кейс 293: Поиск с пробелами в начале/конце
def test_search_with_leading_trailing_spaces(page: Page):
    """Поиск с пробелами — результаты такие же как без пробелов."""
    # Поиск без пробелов. Прежняя версия считала карточки после пауз, и при
    # недогрузке выдачи сравнивала 0 == 0 — тест проходил, ничего не найдя.
    type_in_search(page, "pink")
    expect(page.locator(RESULT_PRODUCT).first).to_be_visible(timeout=15_000)
    products_normal = page.locator(RESULT_PRODUCT).count()
    assert products_normal > 0, "По запросу «pink» ничего не нашлось — сравнивать нечего"

    # Ищем с пробелами на свежей странице: в той же выпадашке второй запрос
    # мог бы застать на экране выдачу первого и совпасть с ней «сам собой».
    page.reload()
    expect(page.locator(SEARCH_INPUT)).to_be_visible(timeout=10_000)
    expect(page.locator(RESULT_PRODUCT)).to_have_count(0)
    type_in_search(page, "  pink  ")
    products_spaces = wait_until(
        page,
        lambda: page.locator(RESULT_PRODUCT).count(),
        lambda value: value > 0,
    )

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

    # Есть товары. Прежний ассерт `"jbl" in body or len(body) > 500` был
    # тавтологией: «JBL» есть в шапке и футере любой страницы, а длина body
    # всегда больше 500 символов — проходил и на пустой выдаче.
    expect(page.locator(RESULT_CARD).first).to_be_visible(timeout=15_000)


# Кейс 329: Отрицательный сценарий — товар не найден
def test_search_no_results_on_results_page(page: Page):
    """Поиск несуществующего значения — на странице отображается
    заглушка «не найдено», нет ошибок верстки."""
    go_to_search_results_page(page, NON_EXISTING_QUERY)

    # Заглушка «ничего не найдено». Раньше проверялось лишь «body виден» после
    # паузы, а отсутствие товаров — мгновенным count(): пустая/недогруженная
    # страница проходила тест так же, как правильная заглушка.
    empty = page.locator(SEARCH_PAGE_EMPTY).first
    expect(empty).to_be_visible(timeout=15_000)
    expect(empty).to_contain_text(re.compile(r"ничего не найдено", re.I))

    # Товары не отображаются (заглушка видна — значит, выдача уже отрисована)
    products = page.locator(SEARCH_PAGE_PRODUCTS)
    expect(products, "Найдены товары для несуществующего запроса").to_have_count(0)


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

    # Фильтры на странице результатов — это сайдбар .filters-vertical (как на
    # странице категории). Широкий [class*='filter'] первым матчит СКРЫТЫЙ
    # .filter-btn (mobile-тоггл), из-за чего .first.to_be_visible() давал ложное
    # падение — проверяем именно видимый контейнер фильтров.
    # Раньше после паузы шёл мгновенный count() с запасным вариантом «любой
    # видимый [class*='sidebar']» и skip: фильтры могли пропасть, а тест —
    # пройти по постороннему сайдбару. Теперь ждём именно блок фильтров.
    filters = page.locator(".filters-vertical, .filter-vertical-container").first
    expect(filters).to_be_visible(timeout=15_000)
    expect(filters.locator("input[type=checkbox]").first).to_be_attached()


# Кейс 297: Сортировка — открытие списка
def test_sort_dropdown_opens_on_results_page(page: Page):
    """Нажать на блок сортировки — открывается список вариантов,
    элементы кликабельны."""
    go_to_search_results_page(page, EXISTING_QUERY)

    # Раньше кликался широкий `[class*='sort'].first` — обёртка
    # `div.catalog__sort`, по которой список не открывается, — а затем
    # считались опции `.sorting-bar__list span`, которые лежат в DOM ВСЕГДА
    # (скрытыми). Тест проходил, не раскрыв список. Теперь кликаем саму кнопку
    # и ждём видимый список (класс `show`), как в tests/test_sorting.py.
    sort_btn = page.locator(SORT_BTN).first
    expect(sort_btn).to_be_visible(timeout=15_000)
    for _ in range(3):
        sort_btn.click()
        try:
            expect(page.locator(SORT_LIST_SHOWN)).to_be_visible(timeout=3_000)
            break
        except AssertionError:
            continue
    expect(page.locator(SORT_LIST_SHOWN), "Список сортировок не раскрылся").to_be_visible()
    options = page.locator(f"{SORT_LIST_SHOWN} span")
    assert options.count() >= 2, "В раскрытом списке сортировок меньше двух вариантов"
    expect(options.first).to_be_visible()


# Кейс 298: Смена вида отображения (плитка/список)
def test_toggle_view_mode_on_results_page(page: Page):
    """Переключение вида отображения товаров — карточки меняют
    отображение, данные сохраняются."""
    go_to_search_results_page(page, EXISTING_QUERY)

    # Раньше «кнопками вида» считалось всё с `view`/`display` в классе (под
    # такой селектор попадает что угодно), кликался второй найденный элемент,
    # а итог проверялся мгновенным count() карточек в DOM — то есть вид мог
    # вовсе не переключиться. Тумблер тот же, что в листинге категории.
    cards = page.locator(RESULT_CARD)
    expect(cards.first).to_be_visible(timeout=15_000)
    count_before = cards.count()

    page.locator(BTN_VIEW_LIST).click()

    expect(page.locator(VIEW_ACTIVE)).to_have_attribute(
        "title", "Посмотреть в виде списка", timeout=10_000
    )
    # Товары остались те же
    expect(cards, "Товары пропали после смены вида").to_have_count(count_before)
    expect(cards.first).to_be_visible()


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

    grid_before = _grid_signature(page)
    page.evaluate("() => { window.__sortSig = null; }")
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

    # Грид перерисовывается позже смены URL. Вместо секунды по часам ждём,
    # пока выдача сменится и перестанет меняться (хелпер сортировки категории).
    # Не «пока станет по возрастанию» — это был бы ассерт, вывернутый в
    # ожидание. Не дождались — ассерт ниже покажет прочитанные цены.
    _wait_grid_changed(page, grid_before)
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
