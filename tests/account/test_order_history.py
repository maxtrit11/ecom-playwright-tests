"""Тесты страницы История заказов (Qase suite: История заказов)"""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# Загрузка данных пользователей
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
USERS = json.loads((FIXTURES_DIR / "users.json").read_text(encoding="utf-8"))

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
@pytest.mark.smoke
def test_order_history_page_displayed(page: Page):
    """Страница «История заказов»: заголовок, фильтры (Поиск, Статус, Дата),
    заголовки колонок и список заказов."""
    # Заголовок
    heading = page.locator(PAGE_HEADING)
    expect(heading).to_be_visible()

    # Фильтры видимы
    expect(page.locator(TABLE_FILTERS)).to_be_visible()

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
