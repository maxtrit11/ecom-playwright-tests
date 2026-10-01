"""История заказов — мобильная версия (зеркало tests/account/test_order_history.py).

Что на телефоне иначе (проверено 01.10.2026 в эмуляции Pixel 7):

- вход — через «Войти» нижнего бара (mobile/mobile_auth.py);
- над разделом h1 «Личные данные» и меню кабинета `.account-sidebar` столбиком,
  ниже h2 «История заказов»; фильтры те же (Поиск, Статус заказа, Дата заказа,
  Избранные заказы), но в один столбец на всю ширину;
- ТАБЛИЦЫ НЕТ: шапка `.account-table__content__table__header` скрыта
  (`display: none`), каждая строка — карточка, поля в столбик, подпись поля
  рисуется через `::before` из `data-label` ячейки; в последней строке
  карточки — звезда, глаз, PDF (иконки 24×24);
- календарь «Дата заказа» — два месяца друг под другом;
- детали заказа — во весь экран, «Повторить заказ» под товарами; корзина —
  тот же `.modal__cart`, кнопка корзины в мобильной шапке.

Импортированы все кейсы, кроме 283: десктопный требует видимую шапку таблицы,
которой на телефоне нет по задумке. Вместо него — мобильный 283 (карточки с
подписями полей). Десктопный `_orders()` теперь читает ячейки по `data-label`
и одинаково работает на обеих вёрстках.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import load_users, open_account_page
from account.test_order_history import (  # noqa: F401 — тесты собирает pytest
    test_search_order_by_product_name,
    test_filter_by_order_status,
    test_filter_by_order_date,
    test_combined_filters,
    test_empty_search_result,
    test_open_order_details,
    test_close_order_details,
    test_toggle_order_favorite,
    test_favorite_filter_shows_only_favorites,
    test_repeat_order_adds_products_to_cart,
)
from account.test_order_history import (
    ORDER_FAV_BTN,
    ORDER_ITEM,
    ORDER_ROW,
    ORDER_VIEW_BTN,
    PAGE_HEADING,
    TABLE,
    TABLE_FILTERS,
    TABLE_HEADER,
    _orders,
)
from mobile.mobile_auth import login_via_bar

USERS, _USERS_SKIP = load_users()

pytestmark = [
    pytest.mark.requires_auth,
    pytest.mark.skipif(_USERS_SKIP is not None, reason=_USERS_SKIP or ""),
]

ORDER_PDF_BTN = "button:has(svg):not(:has(svg.open)):not(:has(use[href*='i-icon-favorite']))"
LABELS = ("Номер", "Дата оформления", "Статус заказа")


@pytest.fixture(autouse=True)
def login_and_open_order_history(page: Page):
    """Вход через нижний бар и «История заказов» прямой ссылкой."""
    user = USERS["loginUser"]
    assert login_via_bar(page, user["email"], user["password"]), (
        f"Не удалось войти под {user['email']}"
    )
    open_account_page(page, "/ru/account/history")
    expect(page).to_have_url(re.compile(r"account/history"), timeout=15_000)
    expect(page.locator(TABLE)).to_be_visible(timeout=15_000)
    expect(page.locator(ORDER_ROW).first).to_be_visible(timeout=15_000)


# ===========================================================================
# Кейс 283 (моб.): Отображение страницы «История заказов»
# ===========================================================================
def test_order_history_page_displayed(page: Page):
    """Заголовок, фильтры (Поиск, Статус, Дата) и список заказов карточками:
    у каждой карточки поля номера, даты и статуса подписаны и заполнены."""
    expect(page.locator(PAGE_HEADING)).to_be_visible()
    expect(page.get_by_role("heading", name="История заказов")).to_be_visible()

    filters_text = " ".join(
        f.inner_text() for f in page.locator(TABLE_FILTERS).all() if f.is_visible()
    ).upper()
    for label in ("ПОИСК", "СТАТУС", "ДАТА"):
        assert label in filters_text, f"В фильтрах нет «{label}»: {filters_text.strip()}"

    # Шапки таблицы на телефоне нет — подписи живут в самих карточках.
    expect(page.locator(TABLE_HEADER)).to_be_hidden()

    orders = _orders(page)
    assert orders, "В истории нет ни одной карточки заказа"
    empty = [o for o in orders if not all(o.values())]
    assert not empty, f"Карточки заказов с пустым номером/датой/статусом: {empty[:3]}"

    # Подпись поля — псевдоэлемент из data-label: без неё карточка — столбик
    # значений без смысла.
    unlabeled = page.evaluate(
        """([row, item, labels]) => {
             const r = document.querySelector(row);
             return labels.filter(l => {
               const c = [...r.querySelectorAll(item)].find(e => e.dataset.label === l);
               if (!c || !c.getBoundingClientRect().height) return true;
               return !getComputedStyle(c, '::before').content.includes(l);
             });
           }""",
        [ORDER_ROW, ORDER_ITEM, list(LABELS)],
    )
    assert not unlabeled, f"В карточке заказа нет подписей полей: {unlabeled}"


# ===========================================================================
# Моб. Карточки в ширину экрана, кнопки действий тапаются
# ===========================================================================
def test_order_cards_fit_screen_and_actions_tappable(page: Page):
    """Карточки не вылезают за край, идут столбиком; у первой карточки звезда,
    глаз и PDF внутри экрана и сверху по точке касания — сами кнопки."""
    vw = page.viewport_size["width"]
    layout = page.evaluate(
        """(sel) => ({
             scroll: document.documentElement.scrollWidth,
             boxes: [...document.querySelectorAll(sel)].map(e => {
               const r = e.getBoundingClientRect();
               return {x: r.left, right: r.right, top: r.top + scrollY, bottom: r.bottom + scrollY};
             })})""",
        ORDER_ROW,
    )
    boxes = layout["boxes"]
    assert layout["scroll"] <= vw + 1, (
        f"История заказов шире экрана: scrollWidth={layout['scroll']} при {vw}"
    )
    outside = [i for i, b in enumerate(boxes) if b["x"] < 0 or b["right"] > vw + 1]
    assert not outside, f"Карточки #{outside} выходят за край экрана {vw}: {boxes[:3]}"
    stacked = [i for i in range(1, len(boxes)) if boxes[i]["top"] < boxes[i - 1]["bottom"] - 1]
    assert not stacked, f"Карточки #{stacked} не под предыдущей: {boxes[:3]}"

    row = page.locator(ORDER_ROW).first
    actions = {
        "звезда": row.locator(ORDER_FAV_BTN).first,
        "глаз": row.locator(ORDER_VIEW_BTN).first,
        "PDF": row.locator(ORDER_PDF_BTN).last,
    }
    problems = []
    for label, btn in actions.items():
        expect(btn).to_be_visible(timeout=10_000)
        btn.scroll_into_view_if_needed()
        b = btn.bounding_box()
        if b["x"] < 0 or b["x"] + b["width"] > vw + 1:
            problems.append(f"«{label}» за краем экрана: {b}")
            continue
        on_top = btn.evaluate(
            """(el) => { const r = el.getBoundingClientRect();
                const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                return (t && (t === el || el.contains(t))) ? null
                    : (t ? (t.className && t.className.baseVal !== undefined
                            ? t.className.baseVal : t.className || t.tagName).toString() : 'пусто'); }"""
        )
        if on_top:
            problems.append(f"«{label}» перекрыта: {on_top}")

    assert not problems, "Кнопки действий карточки заказа не тапаются: " + "; ".join(problems)
