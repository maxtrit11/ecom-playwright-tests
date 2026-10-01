"""Поиск — мобильная версия (зеркало tests/test_search.py).

Что на телефоне иначе (проверено 30.09.2026 в эмуляции Pixel 7):
  * поля поиска в шапке нет — только иконка-лупа `#button-search` в мобильной
    шапке. Тап открывает поиск во весь экран: в `.header__mobile_ecom`
    появляется `#header-content.show` со своей копией `#searchForm`
    (`#search__input`, крестик `.btn__delete`, выпадашка `.modal__search`),
    на `body` — классы `search-open popup-open`. Копия рисуется через v-if:
    до тапа её в DOM нет. Десктопные селекторы (`.header__items …`) на
    телефоне указывают на скрытое десктопное поле;
  * результаты в выпадашке — те же `.result__product` (фото, название, цена),
    но это `<button>`, а не ссылка; сначала ~1 с показываются скелетоны,
    поэтому ждать надо карточки или заглушку, а не фиксированную паузу;
  * крестик закрывает поиск ЦЕЛИКОМ (а не только чистит поле, как на
    десктопе): форма пропадает из DOM, классы с `body` снимаются;
  * страница /search — та же вёрстка, что у листинга категории: кнопка
    «Фильтры» с поп-апом вместо сайдбара, `.sorting-bar`, один тумблер вида;
  * `networkidle` на мобильной /search наступает через 10–20 с, поэтому
    десктопный `go_to_search_results_page` на время тестов подменяется
    (monkeypatch в десктопном модуле — импортированные тесты берут его
    оттуда) на мягкое ожидание.

Блоков «Популярные запросы» и «Результаты в категориях» нет и на телефоне —
кейсы 299 и 18 скипаются, как на десктопе (кейс 18 не перенесён вовсе).
"""

import re

import pytest
from playwright.sync_api import Page, expect

from mobile.test_category_filters_mobile import FILTERS_MODAL, _open_filters
from mobile.test_product_listing_mobile import VIEW_LIST_TITLE, _toggle_view
from test_price_consistency import _bani
from test_product_listing import VIEW_ACTIVE
import test_search
from test_search import (  # noqa: F401 — тесты собирает pytest
    EXISTING_QUERY,
    NON_EXISTING_QUERY,
    PRODUCT_URL_RE,
    SORT_BTN,
    SORT_OPTION,
    test_search_no_results_on_results_page,
    test_click_product_card_on_search_page,
    test_add_to_cart_from_search_page,
)

M = ".header__mobile_ecom"
SEARCH_ICON = f"{M} #button-search"
SEARCH_PANEL = f"{M} #header-content.show"
SEARCH_INPUT = f"{M} #search__input"
BTN_DELETE = f"{M} .btn__delete"
MODAL_SEARCH_SHOW = f"{M} .modal__search.show"
POPULAR_BADGES = f"{M} .badges.search .badge"
RESULT_PRODUCT = f"{M} .result__product"
ALL_RESULTS_LINK = f"{M} #allSearchResults"
MESSAGE_NO_RESULTS = f"{M} .message"
MESSAGE_TEXT = ".message__text"

SORT_LIST_SHOWN = ".sorting-bar__list.show"
RESULT_CARD = ".product__items .product__item"


def go_to_search_results_page(page: Page, query: str):
    """Открыть /search: заголовок + до 5 с тишины сети, без падения по ней."""
    page.goto(f"/ru/search?query={query}", wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1")).to_be_visible(timeout=20_000)
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def open_main_page(page: Page, monkeypatch):
    """Главная на телефоне; иконка поиска в шапке на месте."""
    monkeypatch.setattr(test_search, "go_to_search_results_page", go_to_search_results_page)
    page.goto("/ru", wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(SEARCH_ICON)).to_be_visible(timeout=15_000)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _open_search(page: Page):
    """Тапнуть лупу и дождаться поля поиска. Тап с повтором: первый после
    загрузки может прийтись до гидрации. Повторяем, только пока поле не
    появилось, — лишний тап по лупе закрыл бы поиск обратно."""
    field = page.locator(SEARCH_INPUT)
    for _ in range(3):
        if field.is_visible():
            break
        page.locator(SEARCH_ICON).tap()
        try:
            expect(field).to_be_visible(timeout=5_000)
        except AssertionError:
            continue
    expect(field).to_be_visible()
    return field


def _wait_dropdown(page: Page) -> None:
    """Дождаться, пока вместо скелетонов придут карточки или заглушка."""
    expect(
        page.locator(f"{RESULT_PRODUCT}, {MESSAGE_NO_RESULTS}").first
    ).to_be_visible(timeout=15_000)


def type_in_search(page: Page, text: str):
    """Открыть поиск, ввести запрос и дождаться выпадашки."""
    field = _open_search(page)
    field.fill(text)
    _wait_dropdown(page)
    return field


def _close_search(page: Page) -> None:
    page.locator(BTN_DELETE).tap()
    expect(page.locator(SEARCH_PANEL)).to_have_count(0, timeout=5_000)


def _all_results_count(page: Page) -> int:
    """Число из «Все результаты поиска [N товаров]»."""
    m = re.search(r"\d+", page.locator(ALL_RESULTS_LINK).inner_text())
    return int(m.group()) if m else 0


def _tap_until_url(page: Page, locator, url_re) -> bool:
    """Тапать, пока не сменится URL (первый тап в SPA теряется до гидрации)."""
    for _ in range(3):
        locator.tap()
        try:
            page.wait_for_url(url_re, timeout=10_000)
            return True
        except Exception:
            if not locator.is_visible():
                break
    return bool(url_re.search(page.url))


def _search_via_enter(page: Page, query: str) -> None:
    field = _open_search(page)
    field.fill(query)
    field.press("Enter")
    expect(page).to_have_url(re.compile(rf"search\?query={re.escape(query)}"), timeout=15_000)
    expect(page.locator(SEARCH_PANEL)).to_have_count(0, timeout=10_000)


# ===========================================================================
# Выпадающий блок поиска
# ===========================================================================

# Кейс 14 (моб.): Лупа в шапке открывает поиск во весь экран
def test_search_icon_opens_fullscreen_search(page: Page):
    """Тап по лупе открывает панель поиска с пустым полем и крестиком,
    страница под ней блокируется (`body.popup-open`)."""
    expect(page.locator(SEARCH_INPUT)).to_have_count(0)

    field = _open_search(page)

    expect(field).to_have_value("")
    expect(page.locator(BTN_DELETE)).to_be_visible()
    expect(page.locator("body")).to_have_class(re.compile(r"\bsearch-open\b"))
    expect(page.locator("body")).to_have_class(re.compile(r"\bpopup-open\b"))
    box = page.locator(SEARCH_PANEL).bounding_box()
    width = page.viewport_size["width"]
    assert box and box["width"] >= width - 1, (
        f"Панель поиска не во всю ширину экрана: {box} при ширине {width}"
    )


# Кейс 299 (моб.): Популярные запросы
def test_popular_queries_displayed_on_focus(page: Page):
    """При открытии поиска отображаются «Популярные запросы»; тап по
    запросу подставляет его в поле."""
    _open_search(page)
    badges = page.locator(POPULAR_BADGES)
    if badges.count() == 0:
        pytest.skip("Блок «Популярные запросы» не реализован на стейдже")

    expect(badges.first).to_be_visible(timeout=5_000)
    badges.first.tap()
    expect(page.locator(SEARCH_INPUT)).not_to_have_value("", timeout=5_000)


# Кейс 15 (моб.): Список результатов при вводе существующего значения
def test_search_results_dropdown_with_existing_query(page: Page):
    """Существующий запрос — карточки товаров с фото, названием и ценой и
    ссылка «Все результаты поиска» с ненулевым числом товаров."""
    type_in_search(page, EXISTING_QUERY)

    products = page.locator(RESULT_PRODUCT)
    expect(products.first).to_be_visible()
    first = products.first
    expect(first.locator("img")).to_be_visible()
    expect(first.locator(".product__name")).to_contain_text(re.compile(EXISTING_QUERY, re.I))
    expect(first.locator(".product__price")).to_contain_text("MDL")

    expect(page.locator(ALL_RESULTS_LINK)).to_be_visible()
    total = _all_results_count(page)
    assert total >= products.count() > 0, (
        f"«Все результаты» обещают {total} товаров, в выпадашке {products.count()}"
    )


# Кейс 16 (моб.): Заглушка при несуществующем запросе
def test_search_no_results_placeholder(page: Page):
    """Несуществующий запрос — заглушка с картинкой и текстом, карточек нет."""
    type_in_search(page, NON_EXISTING_QUERY)

    message = page.locator(MESSAGE_NO_RESULTS)
    expect(message).to_be_visible()
    expect(message.locator("img")).to_be_visible()
    expect(message.locator(MESSAGE_TEXT)).to_be_visible()
    expect(page.locator(RESULT_PRODUCT)).to_have_count(0)


# Кейс 17 (моб.): Переход на страницу товара из выпадающего списка
def test_click_product_in_dropdown_navigates_to_product_page(page: Page):
    """Тап по карточке в выпадашке открывает страницу этого товара, поиск
    закрывается."""
    type_in_search(page, EXISTING_QUERY)
    first = page.locator(RESULT_PRODUCT).first
    name = first.locator(".product__name").inner_text().strip()

    assert _tap_until_url(page, first, PRODUCT_URL_RE), (
        f"Не перешли на страницу товара: {page.url}"
    )
    expect(page.locator("h1")).to_contain_text(name, timeout=15_000)
    expect(page.locator("body")).not_to_have_class(re.compile(r"\bsearch-open\b"))


# Кейс 19 (моб.): Переход по кнопке «Все результаты поиска»
def test_all_search_results_button(page: Page):
    """«Все результаты поиска» ведёт на /search с этим запросом."""
    type_in_search(page, EXISTING_QUERY)
    expect(page.locator(ALL_RESULTS_LINK)).to_be_visible()

    assert _tap_until_url(page, page.locator(ALL_RESULTS_LINK), re.compile(r"search\?query=")), (
        f"Не перешли на страницу результатов: {page.url}"
    )
    expect(page).to_have_url(re.compile(rf"query={EXISTING_QUERY}", re.I))
    expect(page.locator(RESULT_CARD).first).to_be_visible(timeout=20_000)


# Кейс 20 (моб.): Закрыть поиск кнопкой X
def test_close_search_and_clear_input(page: Page):
    """Крестик закрывает поиск целиком и снимает блокировку страницы; при
    повторном открытии поле пустое."""
    type_in_search(page, EXISTING_QUERY)
    expect(page.locator(MODAL_SEARCH_SHOW)).to_be_visible()

    _close_search(page)

    expect(page.locator(MODAL_SEARCH_SHOW)).to_have_count(0)
    expect(page.locator("body")).not_to_have_class(re.compile(r"\bsearch-open\b"))
    expect(page.locator("body")).not_to_have_class(re.compile(r"\bpopup-open\b"))

    field = _open_search(page)
    expect(field).to_have_value("")
    expect(page.locator(RESULT_PRODUCT)).to_have_count(0)


# Кейс 293 (моб.): Поиск с пробелами в начале/конце
def test_search_with_leading_trailing_spaces(page: Page):
    """Запрос с пробелами по краям даёт те же результаты, что без них.

    Между запросами поиск закрывается: иначе второй запрос мог бы застать на
    экране выдачу первого и совпасть с ней «сам собой».
    """
    type_in_search(page, "pink")
    normal = page.locator(RESULT_PRODUCT).count()
    normal_total = _all_results_count(page)
    assert normal > 0, "По запросу «pink» ничего не нашлось — сравнивать нечего"
    _close_search(page)

    type_in_search(page, "  pink  ")
    spaced = page.locator(RESULT_PRODUCT).count()
    spaced_total = _all_results_count(page)

    assert (spaced, spaced_total) == (normal, normal_total), (
        f"Результаты отличаются: без пробелов {normal} карточек / {normal_total} всего, "
        f"с пробелами {spaced} / {spaced_total}"
    )


# ===========================================================================
# Страница результатов поиска
# ===========================================================================

# Кейс 328 (моб.): Положительный сценарий — поиск через Enter
@pytest.mark.smoke
def test_search_via_enter_shows_results_page(page: Page):
    """Запрос + Enter на клавиатуре — страница результатов с товарами."""
    _search_via_enter(page, EXISTING_QUERY)
    expect(page.locator("h1")).to_contain_text(EXISTING_QUERY, timeout=15_000)
    expect(page.locator(RESULT_CARD).first).to_be_visible(timeout=20_000)


# Кейс 330 (моб.): Смена контента при новом запросе
def test_search_content_changes_on_new_query(page: Page):
    """На странице результатов новый запрос через поиск в шапке — меняются
    URL, заголовок и выдача."""
    go_to_search_results_page(page, "new")
    expect(page.locator(RESULT_CARD).first).to_be_visible(timeout=20_000)
    first_before = page.locator(RESULT_CARD).first.inner_text()

    _search_via_enter(page, EXISTING_QUERY)

    expect(page.locator("h1")).to_contain_text(EXISTING_QUERY, timeout=15_000)
    expect(page.locator(RESULT_CARD).first).not_to_have_text(first_before, timeout=15_000)


# Кейс 294 (моб.): Значение поиска сохраняется на странице результатов
def test_search_value_preserved_on_results_page(page: Page):
    """После перехода на страницу результатов запрос стоит в поле поиска
    при его открытии."""
    type_in_search(page, "pink")
    assert _tap_until_url(page, page.locator(ALL_RESULTS_LINK), re.compile(r"search\?query=")), (
        f"Не перешли на страницу результатов: {page.url}"
    )
    expect(page.locator(RESULT_CARD).first).to_be_visible(timeout=20_000)

    field = _open_search(page)
    expect(field).to_have_value(re.compile(r"^\s*pink\s*$", re.I))


# Кейс 295 (моб.): Повторный поиск через Enter на странице результатов
def test_search_again_via_enter_on_results_page(page: Page):
    """На странице результатов новый запрос + Enter — обновляются URL и
    заголовок."""
    go_to_search_results_page(page, "pink")
    _search_via_enter(page, "jbl")
    expect(page.locator("h1")).to_contain_text("jbl", timeout=15_000)


# Кейс 296 (моб.): Фильтры на странице результатов
def test_filters_displayed_on_search_results_page(page: Page):
    """Кнопка «Фильтры» открывает поп-ап с опциями фильтра."""
    go_to_search_results_page(page, "pink")
    expect(page.locator(RESULT_CARD).first).to_be_visible(timeout=20_000)

    _open_filters(page)
    modal = page.locator(FILTERS_MODAL)
    expect(modal).to_be_visible()
    expect(modal.locator("input[type=checkbox]").first).to_be_attached()
    assert modal.locator("label").count() > 1, "В поп-апе фильтров нет опций"


# Кейс 297 (моб.): Сортировка — открытие списка
def test_sort_dropdown_opens_on_results_page(page: Page):
    """Тап по сортировке раскрывает список минимум из двух вариантов."""
    go_to_search_results_page(page, EXISTING_QUERY)
    sort_btn = page.locator(SORT_BTN)
    expect(sort_btn).to_be_visible(timeout=15_000)

    for _ in range(3):
        sort_btn.tap()
        try:
            expect(page.locator(SORT_LIST_SHOWN)).to_be_visible(timeout=3_000)
            break
        except AssertionError:
            continue
    expect(page.locator(SORT_LIST_SHOWN)).to_be_visible()
    options = page.locator(f"{SORT_LIST_SHOWN} span")
    assert options.count() >= 2, "Список сортировок не раскрылся"
    expect(options.first).to_be_visible()


# Кейс 298 (моб.): Смена вида отображения (плитка/список)
def test_toggle_view_mode_on_results_page(page: Page):
    """Тумблер вида переключает выдачу в список, товары остаются те же."""
    go_to_search_results_page(page, EXISTING_QUERY)
    cards = page.locator(RESULT_CARD)
    expect(cards.first).to_be_visible(timeout=20_000)
    count_before = cards.count()

    _toggle_view(page, VIEW_LIST_TITLE)

    expect(page.locator(VIEW_ACTIVE)).to_have_attribute("title", VIEW_LIST_TITLE)
    expect(cards).to_have_count(count_before)


# Кейс 331 (моб.): Сортировка — от низкой цены к высокой
def test_sort_by_price_ascending(page: Page):
    """«От самой низкой цены» — цены товаров в наличии по возрастанию.

    Цены дробные — считаем в банях (`_bani`). Берём первую сумму из блока
    цен карточки (текущую цену), у товаров «нет в наличии» её нет, и они
    всё равно уезжают в конец выдачи.
    """
    go_to_search_results_page(page, EXISTING_QUERY)
    expect(page.locator(RESULT_CARD).first).to_be_visible(timeout=20_000)
    sort_before = page.evaluate("() => new URLSearchParams(location.search).get('sort')")

    sort_btn = page.locator(SORT_BTN)
    for _ in range(3):
        sort_btn.tap()
        try:
            expect(page.locator(SORT_LIST_SHOWN)).to_be_visible(timeout=3_000)
            break
        except AssertionError:
            continue
    page.locator(SORT_OPTION).filter(has_text=re.compile(r"низк", re.I)).first.tap()
    page.wait_for_function(
        "(before) => new URLSearchParams(location.search).get('sort') !== before",
        arg=sort_before,
        timeout=20_000,
    )
    # Грид перерисовывается позже смены URL — ждём упорядоченную выдачу, без
    # исключения: если порядок не сложится, упадёт ассерт ниже со списком цен.
    try:
        page.wait_for_function(
            """() => {
                const v = [...document.querySelectorAll('.product__items .product__item')]
                    .filter(c => !c.querySelector('.product__out-of-stock-label'))
                    .map(c => c.querySelector('.product__prices'))
                    .filter(p => p && p.innerText.includes('MDL'))
                    .map(p => parseFloat(p.innerText.split('MDL')[0].replace(/[^\\d.,]/g, '').replace(',', '.')));
                return v.length > 1 && v.every((x, i) => i === 0 || v[i - 1] <= x);
            }""",
            timeout=15_000,
        )
    except Exception:
        pass

    texts = page.evaluate(
        """() => [...document.querySelectorAll('.product__items .product__item')]
            .filter(c => !c.querySelector('.product__out-of-stock-label'))
            .map(c => c.querySelector('.product__prices')?.innerText || '')"""
    )
    prices = [_bani(t) for t in texts if "MDL" in t]
    assert len(prices) >= 2, f"На странице результатов меньше двух цен: {texts}"
    assert prices == sorted(prices), (
        f"Цены не по возрастанию при «от низкой цены»: {[p / 100 for p in prices]}"
    )
