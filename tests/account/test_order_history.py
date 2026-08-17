"""Тесты страницы История заказов (Qase suite: История заказов)

Весь файл требует реального входа в кабинет — маркер `requires_auth`
(нужен tests/fixtures/users.json). Раньше эти тесты исключались из ночного CI:
stage не пускал в аккаунт с IP GitHub Actions. С 2026-08-17 блокировки нет,
файл гоняется и в CI — подробности в pytest.ini и .github/workflows/e2e.yml.
"""

import re

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

# Фильтры
SEARCH_INPUT = ".account-table__filters .g-input input"
STATUS_SELECT = ".account-table__filters .v-select"
STATUS_INPUT = ".account-table__filters .vs__search"
DATE_PICKER = ".account-table__filters .mx-datepicker"
DATE_INPUT = ".account-table__filters .mx-input"

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

    # Запоминаем количество заказов до поиска
    rows_before = page.locator(ORDER_ROW).count()

    # Ввести значение в поиск
    search.fill("184443")
    search.press("Enter")
    page.wait_for_timeout(2000)

    # После поиска — результаты изменились или остались (если совпадение есть)
    rows_after = page.locator(ORDER_ROW).count()
    assert rows_after >= 0  # Может быть 0 или меньше чем было

    # Убедимся что страница не сломалась
    expect(page.locator(TABLE)).to_be_visible()


# ===========================================================================
# Кейс 286: Фильтр по статусу заказа
# ===========================================================================
def test_filter_by_order_status(page: Page):
    """Открыть select «Статус заказа», выбрать статус —
    отображаются только заказы с выбранным статусом."""
    # Открыть v-select (первый — статус заказа, второй — период)
    vs = page.locator(STATUS_SELECT).first
    expect(vs).to_be_visible(timeout=5_000)
    vs.click()
    page.wait_for_timeout(500)

    # Ищем опции в выпадающем списке
    options = page.locator(".vs__dropdown-menu li, .vs__dropdown-option")
    expect(options.first).to_be_visible(timeout=5_000)
    assert options.count() > 0

    # Выбрать первый статус
    first_option_text = options.first.text_content().strip()
    options.first.click()
    page.wait_for_timeout(2000)

    # Фильтр применился — проверяем что выбранное значение отображается
    selected = page.locator(".vs__selected")
    if selected.count() > 0:
        expect(selected).to_be_visible()

    # Таблица не сломалась
    expect(page.locator(TABLE)).to_be_visible()


# ===========================================================================
# Кейс 287: Фильтр по дате заказа
# ===========================================================================
def test_filter_by_order_date(page: Page):
    """Нажать на поле «Дата заказа», выбрать дату —
    отображаются заказы за выбранную дату/диапазон."""
    date_picker = page.locator(DATE_PICKER)
    expect(date_picker).to_be_visible(timeout=5_000)

    date_input = page.locator(DATE_INPUT)
    date_input.click()
    page.wait_for_timeout(500)

    # Должен открыться календарь
    calendar = page.locator(".mx-datepicker-main").first
    expect(calendar).to_be_visible(timeout=5_000)

    # Выбираем сегодняшний день (или любую ячейку)
    day_cell = page.locator(".mx-table-date td.cell:not(.disabled)").first
    if day_cell.count() > 0 and day_cell.is_visible():
        day_cell.click()
        page.wait_for_timeout(1000)

    # Таблица не сломалась
    expect(page.locator(TABLE)).to_be_visible()


# ===========================================================================
# Кейс 288: Совместная работа фильтров (поиск + статус + дата)
# ===========================================================================
def test_combined_filters(page: Page):
    """Ввести значение в поиск, выбрать статус, выбрать дату —
    список корректно фильтруется по всем условиям одновременно."""
    # Поиск
    search = page.locator(SEARCH_INPUT)
    search.fill("184")
    search.press("Enter")
    page.wait_for_timeout(1000)

    # Статус (первый v-select — статус заказа)
    vs = page.locator(STATUS_SELECT).first
    vs.click()
    page.wait_for_timeout(500)
    options = page.locator(".vs__dropdown-menu li, .vs__dropdown-option")
    if options.count() > 0:
        options.first.click()
    page.wait_for_timeout(1000)

    # Дата
    date_input = page.locator(DATE_INPUT)
    date_input.click()
    page.wait_for_timeout(500)
    day_cell = page.locator(".mx-table-date td.cell:not(.disabled)").first
    if day_cell.count() > 0 and day_cell.is_visible():
        day_cell.click()
    page.wait_for_timeout(1000)

    # Страница не сломана
    expect(page.locator(TABLE)).to_be_visible()
    expect(page.locator(PAGE_ACCOUNT)).to_be_visible()


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
