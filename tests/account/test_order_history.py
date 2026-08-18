"""Тесты страницы История заказов (Qase suite: История заказов)

Весь файл требует реального входа в кабинет — маркер `requires_auth`
(нужен tests/fixtures/users.json). Раньше эти тесты исключались из ночного CI:
stage не пускал в аккаунт с IP GitHub Actions. С 2026-08-17 блокировки нет,
файл гоняется и в CI — подробности в pytest.ini и .github/workflows/e2e.yml.
"""

import re
from datetime import datetime

import pytest
from playwright.sync_api import Page, expect

from conftest import load_users

# Учётки: при отсутствии/незаполненности users.json вернётся шаблон и причина
# скипа — файл в .gitignore, и на свежем клоне его нет (подробности в conftest).
USERS, _USERS_SKIP = load_users()

pytestmark = [
    pytest.mark.requires_auth,
    pytest.mark.skipif(_USERS_SKIP is not None, reason=_USERS_SKIP or ""),
]

# Селекторы страницы «История заказов» (реальная разметка stage)
PAGE_ACCOUNT = ".page-account"
PAGE_HEADING = ".page-account__heading .title"
TABLE = ".account-table"
TABLE_FILTERS = ".account-table__filters"
TABLE_HEADER = ".account-table__content__table__header"
TABLE_LIST = ".account-table__content__table__list"
ORDER_ROW = ".account-table__content__table__list__row"
ORDER_ITEM = ".account-table__content__table__list__row__item"

# Фильтры.
#
# ВНИМАНИЕ (проверено вживую 2026-08-18): блоков `.account-table__filters` ДВА
# — в первом «Поиск» и «Статус заказа», во втором «Дата заказа», «Компания» и
# «Избранные заказы». Селектор `.account-table__filters .v-select` попадает
# ТОЛЬКО в «Компанию»: у неё корень `<v-select class="v-select …">`, а у
# «Статуса заказа» — тег `<v-select>` БЕЗ этого класса, поэтому по `.v-select`
# он не находится. Из-за этого тесты статуса и комбинированных фильтров
# фактически дёргали фильтр компании. Поэтому поля адресуем по их подписи.
SEARCH_INPUT = ".account-table__filters .g-input input"
STATUS_FIELD = '.account-table__filters-item:has(label:text-is("Статус заказа"))'
STATUS_TRIGGER = f"{STATUS_FIELD} input.vs__search"
DROPDOWN_OPTION = ".vs__dropdown-menu li"
# Оставлено ради обратной совместимости с тестом компании: это ИМЕННО она.
COMPANY_SELECT = ".account-table__filters .v-select"
DATE_PICKER = ".account-table__filters .mx-datepicker"
DATE_INPUT = ".account-table__filters .mx-input"

# Колонки таблицы: Номер | Дата оформления | Тип доставки | Тип оплаты |
# Компания | Тип заказа | Статус заказа | Общая сумма | Действия
COL_NUMBER = 0
COL_DATE = 1
COL_STATUS = 6

# «Все заказы» — это сброс фильтра, а не статус: выбирать его для проверки
# фильтрации бессмысленно.
STATUS_ANY = "Все заказы"

# Кнопка просмотра деталей заказа — иконка «глаз» (svg.open) в колонке
# «Действия». Рядом стоят кнопки «избранное» и «скачать PDF», поэтому
# нельзя брать просто .last — это PDF, а не детали.
ORDER_VIEW_BTN = "button:has(svg.open)"
# Модалка деталей заказа
ORDER_DETAILS_MODAL = ".modal__authentification__ecom"

# Кнопка «избранный заказ» — звёздочка в колонке «Действия». Берём по иконке
# в спрайте, а не по порядку: в ячейке три кнопки (звезда, глаз, PDF), и любой
# новый экшен сдвинул бы индекс.
ORDER_FAV_BTN = "button:has(use[href*='i-icon-favorite'])"
# Отмеченная звезда получает класс `active` на svg
ORDER_FAV_ACTIVE = f"{ORDER_FAV_BTN} svg.active"

# Фильтр «Избранные заказы» — отдельный v-select во втором ряду фильтров
FAV_FILTER_LABEL = "Избранные заказы"
FAV_FILTER_ONLY = "Показать только избранные"
FAV_FILTER_ALL = "Показать все"

# Повтор заказа (кейс 164)
BTN_REPEAT_ORDER = "Повторить заказ"
# Товары внутри модалки деталей заказа
ORDER_DETAILS_PRODUCT = ".modal__authentification__ecom-content-order-products-item"
# Тост «Товар был добавлен в корзину» — то же семейство, что у избранного
CART_NOTIFICATION = ".notification.cart.show"
# Корзина. В шапке ДВЕ кнопки корзины (мобильная и десктопная), мобильная
# скрыта — без `:visible` клик уходит в невидимую и висит до таймаута.
HEADER_CART_BTN = "button.btn__action.btn__cart:visible"
CART_MODAL = ".modal__cart"
CART_PRODUCT = ".cart__product"
BTN_CLEAR_CART = "button.cart-products__header__clear-btn"

# Sidebar
SIDEBAR = ".account-sidebar"
SIDEBAR_ITEM = ".account-sidebar__list__item"


# ---------------------------------------------------------------------------
# Фикстура: логин и переход на страницу «История заказов»
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def login_and_open_order_history(page: Page):
    page.goto("/", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=30_000)

    # Открыть поп-ап авторизации
    auth_btn = page.locator(".btn__action.btn__auth")
    auth_btn.wait_for(state="visible", timeout=15_000)
    auth_btn.click(force=True)

    modal = page.locator(".modal__authentification__ecom-content").first
    modal.wait_for(state="visible", timeout=15_000)

    # Ввести email и пароль
    page.locator('input[placeholder="Введи e-mail адрес"]').first.fill(
        USERS["loginUser"]["email"]
    )
    modal.locator('input[type="password"]').fill(USERS["loginUser"]["password"])

    # Нажать кнопку входа
    submit_btn = modal.get_by_text("Войдите в аккаунт")
    submit_btn.click()

    # Ждём успешный логин — кнопка меняется на «Кабинет»
    expect(auth_btn).to_contain_text("Кабинет", timeout=30_000)

    # Дожидаемся закрытия модалки и стабилизации страницы, иначе
    # `page.goto` после логина гоняется с пост-логин редиректами Vue
    # и падает с ERR_ABORTED.
    modal.wait_for(state="hidden", timeout=10_000)
    page.wait_for_load_state("networkidle", timeout=20_000)

    # Переход в Историю заказов с повтором при гонке навигаций
    for attempt in range(3):
        try:
            page.goto(
                "/ru/account/history",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            break
        except Exception as e:
            if "ERR_ABORTED" in str(e) and attempt < 2:
                page.wait_for_timeout(1500)
                continue
            raise
    page.wait_for_load_state("networkidle", timeout=30_000)
    expect(page).to_have_url(re.compile(r"account/history"), timeout=15_000)

    # Ждём загрузки таблицы заказов
    expect(page.locator(TABLE)).to_be_visible(timeout=15_000)


# ---------------------------------------------------------------------------
# Хелперы разбора таблицы
# ---------------------------------------------------------------------------
def _orders(page: Page) -> list[dict]:
    """Заказы из таблицы: номер, дата оформления и статус по каждой строке."""
    return page.evaluate(
        """() => [...document.querySelectorAll(
             '.account-table__content__table__list__row')].map(r => {
               const c = [...r.querySelectorAll(
                 '.account-table__content__table__list__row__item')]
                 .map(e => e.innerText.replace(/\\s+/g, ' ').trim());
               return {number: c[0], date: c[1], status: c[6]};
             })"""
    )


def _order_date(value: str):
    """Дата строки таблицы (`17.08.26`) как `date`."""
    return datetime.strptime(value.strip(), "%d.%m.%y").date()


def _selected_range(page: Page) -> tuple:
    """Границы выбранного диапазона из поля даты (`2026-07-27 ~ 2026-08-18`)."""
    raw = page.locator(DATE_INPUT).input_value()
    parts = [p.strip() for p in raw.split("~")]
    assert len(parts) == 2, f"Ожидали диапазон вида «дата ~ дата», получили {raw!r}"
    return tuple(datetime.strptime(p, "%Y-%m-%d").date() for p in parts)


def _apply_status(page: Page, wanted: str | None = None) -> str:
    """Выбрать статус в фильтре «Статус заказа». Возвращает выбранное значение.

    Поле адресуем по подписи: по `.v-select` находится фильтр компании, а не
    статуса (подробности в комментарии к селекторам).
    """
    page.locator(STATUS_TRIGGER).click()
    options = page.locator(DROPDOWN_OPTION)
    expect(options.first).to_be_visible(timeout=10_000)

    names = [options.nth(i).inner_text().strip() for i in range(options.count())]
    target = wanted or next((n for n in names if n != STATUS_ANY), None)
    assert target in names, f"Статуса {target!r} нет в списке: {names}"

    options.nth(names.index(target)).click()
    page.wait_for_timeout(2500)
    return target


# ===========================================================================
# Кейс 283: Отображение страницы «История заказов»
# ===========================================================================
# NB: НЕ помечен @smoke. Когда-то он там был и давал стабильно красный: логин
# проходил, но таблица заказов грузится с аутентифицированного API, который
# стейдж резал с дата-центровых IP GitHub. На прогоне 2026-08-17 тест зелёный
# в CI, так что причина, похоже, ушла вместе с блокировкой логина. В smoke
# всё равно не возвращаем: смысл смоука — пара минут на самое критичное, а
# это длинный аутентифицированный сценарий. Его место — ночная суита.
def test_order_history_page_displayed(page: Page):
    """Страница «История заказов»: заголовок, фильтры (Поиск, Статус, Дата),
    заголовки колонок и список заказов."""
    # Заголовок
    heading = page.locator(PAGE_HEADING)
    expect(heading).to_be_visible()

    # Фильтры видимы.
    # Панель разбита на ДВА ряда `.account-table__filters` (проверено вживую
    # 2026-08-12): ряд 1 — «Поиск» и «Статус заказа», ряд 2 — «Дата заказа»,
    # «Компания» и «Избранные заказы». Раньше ряд был один, поэтому строгий
    # `expect` по общему селектору падал со strict mode violation, а не по
    # вине продукта. Проверяем все ряды и наличие заявленных фильтров.
    filters = page.locator(TABLE_FILTERS)
    assert filters.count() >= 1, "Панель фильтров на странице не найдена"

    filters_text = ""
    for i in range(filters.count()):
        expect(filters.nth(i)).to_be_visible()
        filters_text += " " + (filters.nth(i).inner_text() or "")

    upper = filters_text.upper()
    for label in ("ПОИСК", "СТАТУС", "ДАТА"):
        assert label in upper, f"В фильтрах нет «{label}»: {filters_text.strip()}"

    # Заголовки колонок: Номер, Дата оформления, Тип доставки, Статус заказа, Действия
    header = page.locator(TABLE_HEADER)
    expect(header).to_be_visible()
    header_text = header.text_content()
    assert "Номер" in header_text
    assert "Дата" in header_text
    assert "Статус" in header_text

    # Список заказов
    rows = page.locator(ORDER_ROW)
    assert rows.count() > 0


# ===========================================================================
# Кейс 285: Поиск заказа по названию товара
# ===========================================================================
def test_search_order_by_product_name(page: Page):
    """Ввести название товара в поле поиска — отображаются только
    подходящие заказы."""
    search = page.locator(SEARCH_INPUT)
    expect(search).to_be_visible(timeout=5_000)

    # Ищем по номеру РЕАЛЬНО существующего заказа, а не по константе: на стенде
    # заказы меняются, и зашитый номер рано или поздно перестанет находиться.
    orders = _orders(page)
    if not orders:
        pytest.skip("У учётки нет заказов — искать нечего")
    target = orders[0]["number"].lstrip("#")

    search.fill(target)
    search.press("Enter")
    page.wait_for_timeout(2500)

    # Раньше здесь стояло `assert rows_after >= 0` — тавтология, истинная
    # всегда, даже если поиск вообще не работает. Проверяем результат по сути.
    found = _orders(page)
    assert found, f"Поиск по номеру существующего заказа {target!r} не нашёл ничего"

    numbers = [o["number"].lstrip("#") for o in found]
    assert all(target in n for n in numbers), (
        f"В выдаче по запросу {target!r} есть посторонние заказы: {numbers}"
    )


# ===========================================================================
# Кейс 286: Фильтр по статусу заказа
# ===========================================================================
def test_filter_by_order_status(page: Page):
    """Открыть select «Статус заказа», выбрать статус —
    отображаются только заказы с выбранным статусом."""
    # Прежняя версия открывала `.account-table__filters .v-select` — это фильтр
    # КОМПАНИИ, а не статуса (см. комментарий к селекторам), и проверяла лишь
    # что таблица не исчезла. Работаем с настоящим полем «Статус заказа».
    expect(page.locator(STATUS_FIELD)).to_be_visible(timeout=10_000)

    # Берём статус СУЩЕСТВУЮЩЕГО заказа, а не первый из списка. Иначе легко
    # выбрать статус, которого у учётки нет (например «Предзаказ» — проверено,
    # даёт 0 строк), и проверка «все строки нужного статуса» станет
    # тавтологией на пустой выдаче.
    orders = _orders(page)
    if not orders:
        pytest.skip("У учётки нет заказов — фильтровать нечего")
    status = _apply_status(page, orders[0]["status"])

    filtered = _orders(page)
    assert filtered, (
        f"Фильтр по статусу «{status}» очистил выдачу, хотя заказы с таким "
        f"статусом есть (например {orders[0]['number']})"
    )
    wrong = [o for o in filtered if o["status"] != status]
    assert not wrong, (
        f"После фильтра по статусу «{status}» в выдаче остались заказы с другими "
        "статусами: " + ", ".join(f"{o['number']}/{o['status']}" for o in wrong[:5])
    )


# ===========================================================================
# Кейс 287: Фильтр по дате заказа
# ===========================================================================
def test_filter_by_order_date(page: Page):
    """Нажать на поле «Дата заказа», выбрать дату —
    отображаются заказы за выбранную дату/диапазон."""
    expect(page.locator(DATE_PICKER)).to_be_visible(timeout=5_000)

    page.locator(DATE_INPUT).click()
    calendar = page.locator(".mx-datepicker-main").first
    expect(calendar).to_be_visible(timeout=10_000)

    # Поле работает как ДИАПАЗОН (mx-datepicker-range): нужно два клика —
    # начало и конец. После одного календарь остаётся открытым и фильтр не
    # применяется, поэтому прежняя версия теста по сути ничего не выбирала.
    cells = page.locator(".mx-table-date td.cell:not(.disabled)")
    expect(cells.first).to_be_visible(timeout=10_000)
    assert cells.count() >= 2, "В календаре нет двух доступных дат — диапазон не выбрать"
    cells.first.click()
    cells.last.click()
    page.wait_for_timeout(2500)

    start, end = _selected_range(page)

    # Суть кейса: в выдаче остаются ТОЛЬКО заказы из выбранного диапазона.
    # Раньше проверялось лишь «таблица видна», что проходило и при полностью
    # неработающем фильтре.
    outside = [
        o for o in _orders(page) if not (start <= _order_date(o["date"]) <= end)
    ]
    assert not outside, (
        f"После фильтра {start}…{end} в выдаче остались заказы вне диапазона: "
        + ", ".join(f"{o['number']} от {o['date']}" for o in outside[:5])
    )


# ===========================================================================
# Кейс 288: Совместная работа фильтров (поиск + статус + дата)
# ===========================================================================
def test_combined_filters(page: Page):
    """Ввести значение в поиск, выбрать статус, выбрать дату —
    список корректно фильтруется по всем условиям одновременно."""
    # Берём реальный заказ за образец: все три фильтра настроим так, чтобы он
    # им удовлетворял, и проверим, что он остался, а лишнего не осталось.
    orders = _orders(page)
    if not orders:
        pytest.skip("У учётки нет заказов — комбинировать фильтры не на чем")
    sample = orders[0]
    number = sample["number"].lstrip("#")

    # 1. Поиск по номеру этого заказа
    search = page.locator(SEARCH_INPUT)
    search.fill(number)
    search.press("Enter")
    page.wait_for_timeout(2000)

    # 2. Его же статус. Прежняя версия кликала `.v-select`, а это фильтр
    #    КОМПАНИИ, а не статуса — то есть кейс проверял не то, что заявлено.
    status = _apply_status(page, sample["status"])

    # 3. Диапазон дат, покрывающий его дату оформления
    page.locator(DATE_INPUT).click()
    cells = page.locator(".mx-table-date td.cell:not(.disabled)")
    expect(cells.first).to_be_visible(timeout=10_000)
    cells.first.click()
    cells.last.click()
    page.wait_for_timeout(2500)
    start, end = _selected_range(page)

    result = _orders(page)

    # Если образец выпал из диапазона календаря — сверять нечего, но и молча
    # проходить нельзя: тогда проверяем только согласованность выдачи.
    if start <= _order_date(sample["date"]) <= end:
        assert any(o["number"] == sample["number"] for o in result), (
            f"Заказ {sample['number']} удовлетворяет всем трём фильтрам "
            f"(номер {number}, статус «{status}», дата {sample['date']} "
            f"в диапазоне {start}…{end}), но пропал из выдачи"
        )

    broken = [
        o for o in result
        if number not in o["number"].lstrip("#")
        or o["status"] != status
        or not (start <= _order_date(o["date"]) <= end)
    ]
    assert not broken, (
        "Фильтры применились не совместно — в выдаче есть заказы, не подходящие "
        "хотя бы под одно условие: "
        + ", ".join(f"{o['number']}/{o['status']}/{o['date']}" for o in broken[:5])
    )


# ===========================================================================
# Кейс 289: Пустой результат поиска/фильтрации
# ===========================================================================
def test_empty_search_result(page: Page):
    """Ввести несуществующее значение — корректное состояние
    «нет заказов» / пустая таблица без ошибок."""
    search = page.locator(SEARCH_INPUT)
    search.fill("99999999")
    search.press("Enter")
    page.wait_for_timeout(2000)

    # Заказы не отображаются
    rows = page.locator(ORDER_ROW)
    assert rows.count() == 0, "Найдены заказы для несуществующего запроса"

    # Страница не сломана — таблица или заглушка видна
    expect(page.locator(TABLE)).to_be_visible()


# ===========================================================================
# Кейс 290: Открытие деталей заказа
# ===========================================================================
def test_open_order_details(page: Page):
    """Нажать на иконку просмотра (глаз) — открываются детали заказа."""
    rows = page.locator(ORDER_ROW)
    expect(rows.first).to_be_visible(timeout=10_000)

    # Нажать на «глаз» первого заказа (именно просмотр, не PDF/избранное)
    rows.first.locator(ORDER_VIEW_BTN).click()

    # Открывается модалка с деталями заказа
    details = page.locator(ORDER_DETAILS_MODAL).filter(has_text="Заказ")
    expect(details).to_be_visible(timeout=10_000)
    expect(details).to_contain_text("Статус")


# ===========================================================================
# Кейс 291: Закрытие деталей заказа
# ===========================================================================
def test_close_order_details(page: Page):
    """Открыть детали → закрыть — пользователь остаётся на странице
    «История заказов»."""
    rows = page.locator(ORDER_ROW)
    expect(rows.first).to_be_visible(timeout=10_000)

    # Открыть детали («глаз»)
    rows.first.locator(ORDER_VIEW_BTN).click()
    details = page.locator(ORDER_DETAILS_MODAL).filter(has_text="Заказ")
    expect(details).to_be_visible(timeout=10_000)

    # Закрыть по крестику
    details.locator(".btn__close").click()

    # Модалка закрыта, пользователь остаётся на «История заказов»
    expect(details).not_to_be_visible(timeout=10_000)
    expect(page).to_have_url(re.compile(r"account/history"), timeout=10_000)


# ===========================================================================
# Избранные заказы (функционал добавлен позже, кейсов в Testiny пока нет)
#
# Звезда в колонке «Действия» помечает заказ избранным
# (`POST /general/v2/order/<id>/toggle-favorite/`), а фильтр «Избранные заказы»
# сужает список до помеченных.
#
# Учётка на stage общая: помеченный заказ виден всем следующим тестам и
# прогонам. Поэтому каждый тест снимает свою отметку обратно в `finally` —
# иначе набор избранного растёт от прогона к прогону и ассерты «стало на 1
# больше» со временем перестают что-либо значить.
# ===========================================================================
def is_favorite(row) -> bool:
    """Отмечен ли заказ звёздочкой."""
    return row.locator(ORDER_FAV_ACTIVE).count() > 0


def find_unfavorited_row(page: Page):
    """Первый заказ БЕЗ отметки — на нём безопасно проверять включение."""
    rows = page.locator(ORDER_ROW)
    expect(rows.first).to_be_visible(timeout=15_000)

    for i in range(rows.count()):
        if not is_favorite(rows.nth(i)):
            return rows.nth(i)

    pytest.skip("Все заказы на странице уже в избранном — нечего отмечать")


def toggle_favorite(page: Page, row, expect_active: bool) -> None:
    """Кликнуть звезду и дождаться нового состояния."""
    row.locator(ORDER_FAV_BTN).click()
    star = row.locator(ORDER_FAV_ACTIVE)
    if expect_active:
        expect(star).to_have_count(1, timeout=15_000)
    else:
        expect(star).to_have_count(0, timeout=15_000)


def select_favorite_filter(page: Page, option: str) -> None:
    """Выбрать значение в выпадающем фильтре «Избранные заказы»."""
    item = page.locator(".account-table__filters-item").filter(
        has_text=FAV_FILTER_LABEL
    )
    item.locator(".vs__dropdown-toggle").click()
    page.get_by_role("option", name=option).click()
    # Список перезапрашивается с сервера — ждём, пока таблица перерисуется
    page.wait_for_timeout(2_000)


# ---------------------------------------------------------------------------
# Отметить заказ избранным и снять отметку
# ---------------------------------------------------------------------------
def test_toggle_order_favorite(page: Page):
    """Звезда включается, переживает перезагрузку и снимается обратно."""
    row = find_unfavorited_row(page)
    order_no = row.locator(f"{ORDER_ITEM}.--id-cell span").inner_text()

    try:
        toggle_favorite(page, row, expect_active=True)

        # Отметка сохраняется на сервере, а не только в состоянии Vue
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(TABLE)).to_be_visible(timeout=15_000)
        reloaded = page.locator(ORDER_ROW).filter(has_text=order_no).first
        expect(reloaded.locator(ORDER_FAV_ACTIVE)).to_have_count(1, timeout=15_000)
    finally:
        # Возвращаем заказ в исходное состояние в любом случае
        current = page.locator(ORDER_ROW).filter(has_text=order_no).first
        if current.count() and is_favorite(current):
            toggle_favorite(page, current, expect_active=False)


# ---------------------------------------------------------------------------
# Фильтр «Показать только избранные»
# ---------------------------------------------------------------------------
def test_favorite_filter_shows_only_favorites(page: Page):
    """Фильтр оставляет только отмеченные заказы, «Показать все» — возвращает список."""
    rows = page.locator(ORDER_ROW)
    expect(rows.first).to_be_visible(timeout=15_000)
    total_before = rows.count()

    # Гарантируем хотя бы один избранный заказ: на чистой учётке фильтр иначе
    # вернул бы пусто, и тест «прошёл» бы, ничего не проверив.
    row = find_unfavorited_row(page)
    order_no = row.locator(f"{ORDER_ITEM}.--id-cell span").inner_text()

    try:
        toggle_favorite(page, row, expect_active=True)

        select_favorite_filter(page, FAV_FILTER_ONLY)

        filtered = page.locator(ORDER_ROW)
        count = filtered.count()
        assert count > 0, "Фильтр «только избранные» не показал ни одного заказа"
        assert count <= total_before, (
            f"После фильтрации заказов стало больше: {count} > {total_before}"
        )

        # Каждая строка в выдаче — действительно избранная
        assert filtered.locator(ORDER_FAV_ACTIVE).count() == count, (
            "В выдаче фильтра есть заказы без отметки «избранное»"
        )

        # Отмеченный заказ попал в выдачу
        expect(filtered.filter(has_text=order_no)).to_have_count(1)

        # «Показать все» возвращает полный список
        select_favorite_filter(page, FAV_FILTER_ALL)
        expect(page.locator(ORDER_ROW)).to_have_count(total_before, timeout=15_000)
    finally:
        current = page.locator(ORDER_ROW).filter(has_text=order_no).first
        if current.count() and is_favorite(current):
            toggle_favorite(page, current, expect_active=False)


# ===========================================================================
# Кейс 164: История заказов — повторить заказ
# ===========================================================================
def open_cart(page: Page):
    """Открыть корзину из шапки и вернуть локатор дровера."""
    page.locator(HEADER_CART_BTN).first.click()
    cart = page.locator(CART_MODAL)
    expect(cart).to_be_visible(timeout=15_000)
    return cart


def empty_the_cart(page: Page) -> None:
    """Очистить корзину, если в ней что-то есть, и закрыть дровер.

    Учётка на stage общая, и в корзине почти всегда лежит мусор от прошлых
    прогонов. Без очистки проверка «в корзине товары из заказа» ничего не
    доказывает: они могли быть там и до нажатия «Повторить заказ».
    """
    cart = open_cart(page)

    if page.locator(CART_PRODUCT).count():
        clear_btn = page.locator(BTN_CLEAR_CART).first
        expect(clear_btn).to_be_visible(timeout=10_000)
        clear_btn.click()
        expect(page.locator(CART_PRODUCT)).to_have_count(0, timeout=15_000)

    cart.locator(".btn__close").first.click()
    expect(page.locator(f"{CART_MODAL}.show")).to_have_count(0, timeout=15_000)


def open_order_details(page: Page):
    """Открыть детали первого заказа («глаз») и вернуть модалку."""
    rows = page.locator(ORDER_ROW)
    expect(rows.first).to_be_visible(timeout=15_000)
    rows.first.locator(ORDER_VIEW_BTN).click()

    details = page.locator(".modal__authentification__ecom-content").first
    expect(details).to_be_visible(timeout=15_000)
    expect(details.locator(ORDER_DETAILS_PRODUCT).first).to_be_visible(timeout=15_000)
    return details


def test_repeat_order_adds_products_to_cart(page: Page):
    """«Повторить заказ» кладёт товары заказа в корзину и показывает тост.

    Корзину сначала опустошаем — иначе «товар в корзине» может оказаться
    остатком прошлого прогона, а не результатом повтора.
    """
    empty_the_cart(page)

    details = open_order_details(page)

    # Запоминаем состав заказа — именно эти товары должны появиться в корзине
    product_names = [
        name.strip()
        for name in details.locator(f"{ORDER_DETAILS_PRODUCT} h4").all_inner_texts()
    ]
    assert product_names, "В деталях заказа нет товаров — повторять нечего"

    details.get_by_role("button", name=BTN_REPEAT_ORDER).click()

    # 1. Уведомление о добавлении
    toast = page.locator(CART_NOTIFICATION)
    expect(toast).to_be_visible(timeout=15_000)
    expect(toast).to_contain_text(re.compile("добавлен.* в корзину", re.I))

    # 2. Корзина содержит товары из заказа.
    # Сверяем по НАЗВАНИЯМ, а не по сумме: цена в заказе может быть за упаковку
    # («6 791.50 MDL /упаковка 10 пар»), а в корзину товар кладётся поштучно —
    # ассерт на равенство сумм давал бы ложное падение.
    open_cart(page)
    expect(page.locator(CART_PRODUCT).first).to_be_visible(timeout=15_000)
    cart_text = page.locator(CART_MODAL).inner_text()

    for name in product_names:
        assert name in cart_text, (
            f"Товара «{name}» из заказа нет в корзине после повтора. "
            f"В корзине: {cart_text[:300]}"
        )
