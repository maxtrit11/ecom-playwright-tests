"""Тесты страницы со списком товаров (Qase suite «Листинг товаров»)

Покрывает кейсы 248-252 и 255-257: переключение вида отображения, плашка
добавления в корзину прямо из листинга, переход в карточку товара и работа
чипов активных фильтров («Очистить все» / «×» у одного фильтра / сортировка
при активных фильтрах).

Разметка проверена вживую 2026-08-17 на /ru/serie-partybox:

- Вид отображения — `.view-type` с двумя кнопками. Класс сетки при
  переключении НЕ меняется, меняется `grid-template-columns`, поэтому
  «сколько товаров в ряду» считаем по координатам карточек, а не по классу.
- Панель фильтров — ВТОРОЙ `.filters-vertical`. Первый с модификатором
  `--subcategory` — это блок подкатегорий, у него нет ни счётчика, ни
  чекбоксов (на этом уже спотыкались в тестах фильтров категории).
- Чипы активных фильтров живут в `.catalog__sort__parameters` и появляются
  ТОЛЬКО у чекбокс-фильтров характеристик. Тумблеры «В наличии» и статусы
  (New/Sale) фильтруют выдачу, но чипа не создают.
- Плашка добавления — `.notification.cart.show`, живёт ~3 секунды, кнопка
  внутри — `button.btn__ntf` (в избранном на этом же месте `<a>`).
"""

import os
import re

import pytest
from playwright.sync_api import Page, expect

from conftest import CART_VIEW_POPUP
from test_price_consistency import _bani
from test_sorting import _grid_signature, _wait_grid_changed

# Категория по умолчанию — из ручного кейса. Русская локаль принципиальна:
# тексты плашки («Товар был добавлен в корзину») проверяются по-русски.
CATEGORY_URL = os.environ.get("LISTING_URL", "/ru/serie-partybox")

GRID = ".product__items"
CARD = ".product__item"
BTN_ADD_CART = "button.btn__add_cart"

# Вид отображения
VIEW_TYPE = ".view-type"
BTN_VIEW_LIST = '.view-type__button[title="Посмотреть в виде списка"]'
BTN_VIEW_GRID = ".view-type__button--grid"
VIEW_ACTIVE = ".view-type__button.active"

# Плашка «Товар был добавлен в корзину»
NOTIFICATION = ".notification.cart.show"
NOTIFICATION_BTN = f"{NOTIFICATION} button.btn__ntf"

# Корзина
HEADER_CART_BTN = "button.btn__action.btn__cart:visible"
CART_MODAL = ".modal__cart"
CART_PRODUCT = ".cart__product"
BTN_CLEAR_CART = "button.cart-products__header__clear-btn"

# Фильтры
FILTERS_PANEL = ".filters-vertical:not(.filters-vertical--subcategory)"
FOUND_GOODS = ".filters-vertical__header__found-goods"
FILTER_GROUP = ".filters-vertical__content__params__item.active"
CHIP = ".catalog__sort__parameters__item:not(.-delete-all)"
CHIP_DELETE = ".catalog__sort__parameters__item__delete"
CHIP_CLEAR_ALL = ".catalog__sort__parameters__item.-delete-all"

# Сортировка
SORT_BTN = ".sorting-bar__btn"
SORT_LIST = ".sorting-bar__list"
SORT_LOWEST_PRICE = "От самой низкой цены"


@pytest.fixture(autouse=True)
def open_listing(page: Page):
    """Открыть категорию и дождаться сетки товаров.

    Вьюпорт фиксируем явно: число товаров в ряду зависит от ширины окна, а
    кейсы 248/249 проверяют именно его.
    """
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(GRID)).to_be_visible(timeout=20_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=20_000)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _products_per_row(page: Page) -> int:
    """Сколько карточек стоит в первом ряду.

    Считаем по верхней координате: класс сетки при смене вида не меняется,
    меняется только `grid-template-columns`, так что по разметке отличить
    виды нельзя.
    """
    return page.evaluate(
        """() => {
            const cards = [...document.querySelectorAll('.product__items .product__item')];
            if (!cards.length) return 0;
            const first = Math.round(cards[0].getBoundingClientRect().top);
            return cards.filter(
                c => Math.abs(Math.round(c.getBoundingClientRect().top) - first) < 20
            ).length;
        }"""
    )


def _found_count(page: Page) -> int:
    """Число из «Найдено товаров: N» в шапке панели фильтров."""
    text = page.locator(FILTERS_PANEL).locator(FOUND_GOODS).inner_text()
    m = re.search(r"\d+", text)
    assert m, f"Не удалось прочитать счётчик найденных товаров: {text!r}"
    return int(m.group())


def _card_with_add_to_cart(page: Page):
    """Первая карточка с кнопкой «В корзину».

    В листинге попадаются товары без стока — у них вместо «В корзину»
    предзаказ, и кейс про плашку на них не воспроизводится.
    """
    cards = page.locator(CARD)
    for i in range(cards.count()):
        card = cards.nth(i)
        if card.locator(BTN_ADD_CART).count():
            return card
    pytest.skip("В листинге нет ни одного товара с кнопкой «В корзину»")


def _add_first_product_to_cart(page: Page) -> str:
    """Добавить первый доступный товар из листинга. Возвращает его название."""
    card = _card_with_add_to_cart(page)
    card.scroll_into_view_if_needed()
    name = card.locator('a[href*="/product/"]').first.inner_text().strip()
    card.locator(BTN_ADD_CART).first.click()
    return name


def _wait_results_changed(page: Page, before_text: str) -> None:
    """Дождаться, пока счётчик «Найдено товаров» изменится.

    Ждать появления `filters=` в URL НЕДОСТАТОЧНО: параметр проставляется
    раньше, чем приходит новая выдача, и следующий за этим `_found_count`
    успевает прочитать ещё старое число (ловилось как «21 < 21»).
    """
    expect(page.locator(FILTERS_PANEL).locator(FOUND_GOODS)).not_to_have_text(
        before_text, timeout=25_000
    )


def _apply_option(page: Page, option_id: str) -> None:
    """Отметить опцию фильтра по её `id` и дождаться новой выдачи."""
    before = page.locator(FILTERS_PANEL).locator(FOUND_GOODS).inner_text()
    page.locator(f'label[for="{option_id}"]').click()
    _wait_results_changed(page, before)


def _two_option_ids(page: Page) -> list[str]:
    """`id` двух доступных опций ОДНОЙ группы фильтров.

    Возвращаем именно идентификаторы, а не локаторы: после применения фильтра
    панель перерисовывается целиком, и позиционный локатор (`nth(i)`) начинает
    указывать на другую группу — тест кликал по уже недоступной опции и висел
    до таймаута (поймано на первом прогоне).

    Две опции берём из ОДНОЙ группы осознанно: внутри группы условия
    объединяются по OR, а между группами — по AND, поэтому после первого же
    фильтра опции соседних групп становятся `disabled`, и набрать два фильтра
    из разных групп на большинстве категорий просто невозможно.
    """
    ids = page.evaluate(
        """(sel) => {
            const panel = document.querySelector(sel);
            if (!panel) return [];
            for (const group of panel.querySelectorAll(
                    '.filters-vertical__content__params__item.active')) {
                const free = [...group.querySelectorAll('input[type=checkbox]')]
                    .filter(i => !i.disabled)
                    .map(i => i.id)
                    .filter(Boolean);
                if (free.length >= 2) return free.slice(0, 2);
            }
            return [];
        }""",
        FILTERS_PANEL,
    )
    if len(ids) < 2:
        pytest.skip("Нет группы фильтров с двумя доступными опциями")
    return ids


def _widest_group_option_ids(page: Page) -> list[str]:
    """`id` опций самой широкой группы фильтров — от широких к узким (подпись «… (N)»).

    Нужен там, где после фильтрации должно остаться минимум два товара С ЦЕНОЙ.
    Одной опции для этого мало: счётчик учитывает и товары без стока, а у них в
    листинге нет цены (предзаказ). 27.10.2026 у Partybox Club 120 и Stage 320
    White сток стал 0, и КАЖДАЯ опция категории оставляла пару «товар с ценой +
    его цвет без цены» — сортировку проверить было не на чем. Поэтому тест
    набирает опции одной группы (внутри группы — OR, выдача только растёт),
    пока цен не станет две; группа берётся с наибольшей суммой счётчиков.
    """
    option_ids = page.evaluate(
        """(sel) => {
            const panel = document.querySelector(sel);
            if (!panel) return [];
            let best = null;
            panel.querySelectorAll(
                '.filters-vertical__content__params__item.active'
            ).forEach(group => {
                const opts = [];
                group.querySelectorAll('label').forEach(label => {
                    const input = panel.querySelector('#' + CSS.escape(label.htmlFor || ''));
                    if (!input || input.disabled) return;
                    const m = (label.innerText || '').match(/\\((\\d+)\\)/);
                    if (m) opts.push({n: parseInt(m[1]), id: label.htmlFor});
                });
                const total = opts.reduce((s, o) => s + o.n, 0);
                if (!best || total > best.total) best = {total, opts};
            });
            if (!best || best.total < 2) return [];
            return best.opts.sort((a, b) => b.n - a.n).map(o => o.id);
        }""",
        FILTERS_PANEL,
    )
    if not option_ids:
        pytest.skip("В панели фильтров нет группы, оставляющей хотя бы два товара")
    return option_ids


def _priced_cards(page: Page) -> list[str]:
    """Тексты блоков цены в выдаче — только у карточек, где цена выведена."""
    texts = page.locator(f"{GRID} {CARD} .product__prices").all_inner_texts()
    return [t for t in texts if "MDL" in t]


# ===========================================================================
# Кейс 248: Переключение на табличный вид
# ===========================================================================
def test_switch_to_list_view(page: Page):
    """Вид «Таблица» выстраивает товары по одному в ряд."""
    # Стартовое состояние — плитка (несколько товаров в ряду)
    assert _products_per_row(page) > 1, (
        "Листинг открылся не в плиточном виде — переключать не с чего"
    )

    page.locator(BTN_VIEW_LIST).click()

    expect(page.locator(VIEW_ACTIVE)).to_have_attribute(
        "title", "Посмотреть в виде списка", timeout=10_000
    )
    per_row = _products_per_row(page)
    assert per_row == 1, f"В табличном виде в ряду {per_row} товаров вместо 1"


# ===========================================================================
# Кейс 249: Переключение на плиточный вид
# ===========================================================================
def test_switch_to_grid_view(page: Page):
    """Вид «Плитка» выстраивает товары по три в ряд."""
    # Предусловие кейса — открыт табличный вид
    page.locator(BTN_VIEW_LIST).click()
    expect(page.locator(VIEW_ACTIVE)).to_have_attribute(
        "title", "Посмотреть в виде списка", timeout=10_000
    )
    assert _products_per_row(page) == 1, "Табличный вид не включился"

    page.locator(BTN_VIEW_GRID).click()

    expect(page.locator(VIEW_ACTIVE)).to_have_attribute(
        "title", "Посмотреть в виде grid", timeout=10_000
    )
    per_row = _products_per_row(page)
    assert per_row == 3, f"В плиточном виде в ряду {per_row} товаров вместо 3"


# ===========================================================================
# Кейс 250: Плашка после добавления в корзину из листинга
# ===========================================================================
def test_add_to_cart_from_listing_shows_notification(page: Page):
    """«В корзину» на карточке листинга показывает плашку с кнопкой перехода."""
    _add_first_product_to_cart(page)

    toast = page.locator(NOTIFICATION)
    expect(toast).to_be_visible(timeout=15_000)
    expect(toast).to_contain_text(re.compile("добавлен.* в корзину", re.I))
    expect(page.locator(NOTIFICATION_BTN)).to_contain_text(
        re.compile("открыть корзину", re.I)
    )


# ===========================================================================
# Кейс 251: Переход в корзину из плашки на листинге
# ===========================================================================
def test_open_cart_from_listing_notification(page: Page, require_cart_view):
    """Кнопка «Открыть корзину» в плашке открывает корзину с этим товаром."""
    # Единственный тест файла, завязанный на поп-ап корзины: при Виде 2
    # плашка ведёт на /ru/cart, а `.modal__cart` не существует.
    require_cart_view(CART_VIEW_POPUP, "корзина поп-апом")

    # Чистим корзину: иначе товар мог лежать там и до нажатия, и проверка
    # «в корзине именно он» ничего бы не доказывала.
    page.locator(HEADER_CART_BTN).first.click()
    cart = page.locator(CART_MODAL)
    expect(cart).to_be_visible(timeout=15_000)
    if page.locator(CART_PRODUCT).count():
        page.locator(BTN_CLEAR_CART).first.click()
        expect(page.locator(CART_PRODUCT)).to_have_count(0, timeout=15_000)
    cart.locator(".btn__close").first.click()
    expect(page.locator(f"{CART_MODAL}.show")).to_have_count(0, timeout=15_000)

    name = _add_first_product_to_cart(page)

    # Плашка живёт ~3 секунды — кликаем сразу, без промежуточных проверок
    page.locator(NOTIFICATION_BTN).click(timeout=10_000)

    expect(page.locator(f"{CART_MODAL}.show")).to_have_count(1, timeout=15_000)
    expect(page.locator(CART_PRODUCT).first).to_be_visible(timeout=15_000)
    assert name in page.locator(CART_MODAL).inner_text(), (
        f"Добавленного товара «{name}» нет в открывшейся корзине"
    )


# ===========================================================================
# Кейс 252: Переход на страницу товара из карточки листинга
# ===========================================================================
def test_open_product_page_from_listing_card(page: Page):
    """Клик по карточке открывает страницу именно этого товара."""
    link = page.locator(CARD).first.locator('a[href*="/product/"]').first
    name = link.inner_text().strip()
    href = link.get_attribute("href")

    link.click()

    expect(page).to_have_url(re.compile(re.escape(href)), timeout=20_000)
    # Страница товара загрузилась корректно и это тот самый товар
    expect(page.locator("h1")).to_be_visible(timeout=20_000)
    expect(page.locator("h1")).to_have_text(
        re.compile(re.escape(name), re.I), timeout=15_000
    )


# ===========================================================================
# Кейс 255: Сброс всех фильтров кнопкой «Очистить все»
# ===========================================================================
def test_clear_all_filters(page: Page):
    """«Очистить все» снимает фильтры и возвращает выдачу к исходной."""
    found_initial = _found_count(page)
    found_text_initial = page.locator(FILTERS_PANEL).locator(FOUND_GOODS).inner_text()

    option_id = _two_option_ids(page)[0]
    _apply_option(page, option_id)

    expect(page.locator(CHIP)).to_have_count(1, timeout=15_000)
    found_filtered = _found_count(page)
    assert found_filtered < found_initial, (
        f"После применения фильтра число найденных товаров не уменьшилось: "
        f"{found_filtered} против {found_initial}"
    )

    page.locator(CHIP_CLEAR_ALL).click()
    _wait_results_changed(page, f"Найдено товаров: {found_filtered}")

    expect(page.locator(CHIP)).to_have_count(0, timeout=15_000)
    expect(page.locator(CHIP_CLEAR_ALL)).to_have_count(0, timeout=15_000)
    assert _found_count(page) == found_initial, (
        f"Выдача не вернулась к исходной: {_found_count(page)} против {found_initial}"
    )
    assert "filters=" not in page.url, f"В URL остались фильтры: {page.url}"


# ===========================================================================
# Кейс 256: Сброс одного фильтра крестиком на чипе
# ===========================================================================
def test_remove_single_filter_chip(page: Page):
    """«×» на чипе убирает только свой фильтр, остальные остаются."""
    first_id, second_id = _two_option_ids(page)

    _apply_option(page, first_id)
    expect(page.locator(CHIP)).to_have_count(1, timeout=15_000)

    _apply_option(page, second_id)
    expect(page.locator(CHIP)).to_have_count(2, timeout=15_000)

    chips_before = page.locator(CHIP).all_inner_texts()
    removed, kept = chips_before[0], chips_before[1]

    page.locator(CHIP).first.locator(CHIP_DELETE).click()

    expect(page.locator(CHIP)).to_have_count(1, timeout=15_000)
    remaining = page.locator(CHIP).first.inner_text()
    assert remaining == kept, (
        f"Удалился не тот фильтр: ожидали, что останется «{kept}», "
        f"осталось «{remaining}» (удаляли «{removed}»)"
    )
    # Второй фильтр всё ещё в URL — сброса всех фильтров не произошло
    assert "filters=" in page.url, f"Вместе с чипом слетели все фильтры: {page.url}"


# ===========================================================================
# Кейс 257: Сортировка при активных фильтрах
# ===========================================================================
def test_sorting_keeps_active_filters(page: Page):
    """Сортировка применяется к отфильтрованной выдаче и не сбрасывает фильтры."""
    # Сортировать по цене имеет смысл минимум на двух товарах С ЦЕНОЙ, а товары
    # без стока выводятся без неё. Набираем опции одной группы (OR), пока цен
    # не станет две, — см. `_widest_group_option_ids`.
    for applied, option_id in enumerate(_widest_group_option_ids(page)[:5], 1):
        _apply_option(page, option_id)
        expect(page.locator(CHIP)).to_have_count(applied, timeout=15_000)
        # Счётчик «Найдено» меняется раньше сетки — ждём, пока карточек станет
        # столько же, иначе цены считаются по прежней выдаче.
        found = _found_count(page)
        if found <= 12:
            expect(page.locator(CARD)).to_have_count(found, timeout=15_000)
        if len(_priced_cards(page)) >= 2:
            break
    else:
        pytest.skip("Даже несколько фильтров не оставляют двух товаров с ценой — сортировать нечего")

    chips_before = page.locator(CHIP).all_inner_texts()
    found_before = _found_count(page)
    cards_before = page.locator(CARD).count()

    # Открыть список сортировок и выбрать «От самой низкой цены»
    grid_before = _grid_signature(page)
    page.evaluate("() => { window.__sortSig = null; }")
    page.locator(SORT_BTN).click()
    expect(page.locator(f"{SORT_LIST}.show")).to_be_visible(timeout=10_000)
    page.locator(SORT_LIST).get_by_text(SORT_LOWEST_PRICE, exact=True).click()
    page.wait_for_function(
        "() => location.search.includes('sort=')", timeout=20_000
    )
    # Грид перерисовывается позже смены URL: ждём, пока выдача сменится и
    # устоится (хелпер сортировки), а не 2 с по часам. Если порядок и так был
    # по возрастанию, хелпер дождётся потолка и вернёт управление.
    _wait_grid_changed(page, grid_before)

    # 1. Фильтры не сбросились
    expect(page.locator(CHIP)).to_have_count(len(chips_before), timeout=15_000)
    assert page.locator(CHIP).all_inner_texts() == chips_before, "Чипы фильтров изменились"
    assert "filters=" in page.url, f"Сортировка потеряла фильтры: {page.url}"

    # 2. Сортировка применилась именно к отфильтрованной выдаче
    assert _found_count(page) == found_before, (
        f"После сортировки изменилось число найденных: "
        f"{_found_count(page)} против {found_before}"
    )
    assert page.locator(CARD).count() == cards_before, (
        "После сортировки изменилось число карточек в выдаче"
    )

    # Цены дробные («5 099.15 MDL») — разбираем в бани через `_bani`. Прежний
    # parseInt по всем цифрам склеивал копейки с целой частью (509915), и
    # порядок таких чисел мог не совпасть с порядком цен.
    #
    # Цену берём из всего блока `.product__prices` (первая сумма в нём —
    # текущая цена), а не из `.no-discount`: тот есть только у товаров без
    # скидки, и в отфильтрованной выдаче из двух-трёх карточек в проверку
    # попадала одна цена — порядок одной цены «верен» всегда (30.09.2026).
    texts = _priced_cards(page)
    prices = [_bani(t) for t in texts]
    assert len(prices) >= 2, f"В отфильтрованной выдаче меньше двух цен: {texts}"
    assert prices == sorted(prices), (
        f"Цены в отфильтрованной выдаче не по возрастанию: {[p / 100 for p in prices]}"
    )
