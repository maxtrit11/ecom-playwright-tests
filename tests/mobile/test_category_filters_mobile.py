"""Фильтры на странице категории — мобильная версия (зеркало
tests/test_category_filters.py).

На телефоне бокового сайдбара фильтров нет вовсе (проверено в MCP-браузере):
  * рядом с сортировкой — кнопка «Filtre» (`.filter-btn`), она открывает
    полноэкранный поп-ап `.modal__sort` (рендерится только открытым, v-if);
  * внутри те же группы, чекбоксы, прайс и тоггл «Doar în stoc», что и в
    десктопном сайдбаре, — селекторы содержимого берём из десктопного файла;
  * счётчик — `.found-goods` в шапке поп-апа («Produse găsite: N»);
  * фильтр применяется СРАЗУ по тапу (URL и выдача меняются под поп-апом);
    внизу «EFECTUAT» — закрыть поп-ап, «RESETARE» — сбросить все фильтры.
"""

import re

import pytest
from playwright.sync_api import Locator, Page, expect

from test_category_filters import (
    CATEGORY_URL,
    CHECKBOX_ITEM,
    CHECKBOX_LABEL,
    FILTER_GROUP,
    IN_STOCK_TOGGLE,
    PRICE_INPUTS,
    PRODUCT_CARD,
    _commit_price_input,
    _present,
    _visible_prices_bani,
)

# Селекторы мобильного поп-апа фильтров
FILTER_BTN = ".filter-btn"
FILTERS_MODAL = ".modal__sort.show"
FOUND_GOODS = ".found-goods"
BTN_CLOSE = f"{FILTERS_MODAL} .btn__close"
BTN_APPLY = ".modal__sort__btns__ready"  # «EFECTUAT»
BTN_RESET = ".modal__sort__btns__reset"  # «RESETARE»

_FOUND_JS = """
    () => {
        const el = document.querySelector('.modal__sort.show .found-goods');
        const m = el && (el.textContent || '').match(/\\d+/);
        return m ? parseInt(m[0]) : null;
    }
"""


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _wait_after_filter(page: Page) -> None:
    """Дать бекенду пересчитать выдачу. В отличие от десктопного хелпера,
    networkidle здесь не обязателен: на мобильной странице (особенно со 2-й
    страницы пагинации) сеть бывает не затихает за 15 с, а сам факт
    применения фильтра тесты и так ждут по счётчику/URL."""
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass
    page.wait_for_timeout(500)


def _panel(page: Page) -> Locator:
    return page.locator(FILTERS_MODAL)


def _open_filters(page: Page) -> Locator:
    """Тапнуть «Filtre» и дождаться поп-апа с группами фильтров.

    Тап с повтором, пока поп-ап не открылся: первый тап сразу после загрузки
    может потеряться (гонка с гидрацией).
    """
    panel = _panel(page)
    for _ in range(3):
        if panel.count():
            break
        page.locator(FILTER_BTN).tap()
        try:
            panel.wait_for(state="visible", timeout=5_000)
            break
        except Exception:
            continue
    expect(panel).to_be_visible()
    expect(panel.locator(FILTER_GROUP).first).to_be_visible(timeout=15_000)
    return panel


def _found_count(page: Page) -> int:
    """Число из «Produse găsite: N» в шапке поп-апа."""
    text = _panel(page).locator(FOUND_GOODS).text_content() or ""
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else -1


def _wait_found_count(page: Page, expected: int, timeout: int = 15_000) -> int:
    """Дождаться, пока счётчик покажет `expected` (без исключения — падать
    должен ассерт теста). Зачем ждать — см. десктопный `_wait_found_count`."""
    try:
        page.wait_for_function(
            f"(expected) => ({_FOUND_JS})() === expected", arg=expected, timeout=timeout
        )
    except Exception:
        pass
    return _found_count(page)


def _wait_found_count_changed(page: Page, before: int, timeout: int = 15_000) -> int:
    try:
        page.wait_for_function(
            f"(before) => {{ const v = ({_FOUND_JS})(); return v !== null && v !== before; }}",
            arg=before,
            timeout=timeout,
        )
    except Exception:
        pass
    return _found_count(page)


def _first_group_with_checkboxes(page: Page, min_options: int = 1) -> Locator | None:
    panel = _panel(page)
    if not _present(panel.locator(CHECKBOX_ITEM), min_options):
        return None
    groups = panel.locator(FILTER_GROUP)
    for i in range(groups.count()):
        g = groups.nth(i)
        if g.locator(CHECKBOX_ITEM).count() >= min_options:
            return g
    return None


def _apply_first_checkbox(page: Page) -> tuple[str, int, int]:
    """Отметить первую опцию первой группы. Вернуть (id опции, счётчик до,
    счётчик после)."""
    group = _first_group_with_checkboxes(page)
    if group is None:
        pytest.skip("На этой категории нет чекбокс-фильтров")
    before = _found_count(page)
    label = group.locator(CHECKBOX_LABEL).first
    option_id = label.get_attribute("for")
    assert option_id, "У label чекбокса не оказалось for-атрибута"

    # Первый тап по свежему поп-апу изредка теряется (в полном прогоне файла
    # 1 раз из 12, изолированно 0 из 3): опция не отмечается, URL не меняется.
    # Повторяем, только пока опция НЕ отмечена — иначе второй тап снял бы её.
    option = page.locator(f'[id="{option_id}"]')
    for _ in range(3):
        if option.is_checked():
            break
        label.tap()
        try:
            page.wait_for_url(re.compile(r"filters="), timeout=5_000)
            break
        except Exception:
            continue
    page.wait_for_url(re.compile(r"filters="), timeout=10_000)
    _wait_after_filter(page)
    after = _wait_found_count_changed(page, before)
    return option_id, before, after


# ---------------------------------------------------------------------------
# Фикстура: открыть категорию и поп-ап фильтров
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def open_category_filters(page: Page):
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(PRODUCT_CARD).first).to_be_visible(timeout=20_000)
    expect(page.locator(FILTER_BTN)).to_be_visible(timeout=20_000)
    _open_filters(page)


# ===========================================================================
# 1 (моб.). Поп-ап фильтров открывается кнопкой «Filtre» и содержит группы
# ===========================================================================
def test_filters_modal_opens_with_groups(page: Page):
    """Кнопка «Filtre» открывает поп-ап на весь экран, групп фильтров > 0."""
    panel = _panel(page)
    expect(panel).to_be_in_viewport()
    assert panel.locator(FILTER_GROUP).count() > 0, "В поп-апе нет ни одной группы фильтров"


def test_filters_modal_closes_by_x(page: Page):
    """Крестик закрывает поп-ап, страница категории остаётся на месте."""
    page.locator(BTN_CLOSE).tap()

    expect(_panel(page)).to_have_count(0)
    expect(page.locator(PRODUCT_CARD).first).to_be_visible()
    expect(page.locator(FILTER_BTN)).to_be_visible()


# ===========================================================================
# 2 (моб.). Счётчик «Найдено товаров» виден и > 0
# ===========================================================================
@pytest.mark.smoke
def test_found_goods_counter_visible(page: Page):
    expect(_panel(page).locator(FOUND_GOODS)).to_be_visible()
    assert _found_count(page) > 0, "Счётчик равен 0 на дефолтной выдаче"


# ===========================================================================
# 3 (моб.). Тап по чекбоксу применяет фильтр (URL и счётчик меняются)
# ===========================================================================
def test_checkbox_filter_applies(page: Page):
    """Тап по опции — `filters=` в URL, счётчик не вырос, опция отмечена."""
    option_id, before, after = _apply_first_checkbox(page)

    assert after <= before, f"Счётчик после применения фильтра вырос: {before} → {after}"
    expect(page.locator(f'[id="{option_id}"]')).to_be_checked()


# ===========================================================================
# 4 (моб.). Повторный тап снимает фильтр — счётчик возвращается к исходному
# ===========================================================================
def test_uncheck_returns_counter_to_initial(page: Page):
    option_id, initial, _ = _apply_first_checkbox(page)

    page.locator(f'{FILTERS_MODAL} label[for="{option_id}"]').tap()
    page.wait_for_function("() => !location.search.match(/filters=\\d/)", timeout=10_000)
    _wait_after_filter(page)

    after = _wait_found_count(page, initial)
    assert after == initial, f"После снятия фильтра счётчик не вернулся: {initial} → {after}"


# ===========================================================================
# 5 (моб.). Тоггл «В наличии» (если есть)
# ===========================================================================
def test_in_stock_toggle_filters_results(page: Page):
    toggle = _panel(page).locator(IN_STOCK_TOGGLE)
    if not _present(toggle):
        pytest.skip("На этой категории нет тоггла «В наличии»")

    before = _found_count(page)
    # Сам input скрыт — тапаем видимый переключатель, как пользователь.
    toggle.locator(".ui-switch-toggler__switch").tap()
    _wait_after_filter(page)

    after = _found_count(page)
    assert after <= before, f"После «В наличии» выдача выросла: {before} → {after}"


# ===========================================================================
# 6 (моб.). Состояние фильтра сохраняется при перезагрузке страницы
# ===========================================================================
def test_filter_persists_on_reload(page: Page):
    """Применить фильтр → reload → снова открыть поп-ап: опция отмечена,
    счётчик тот же."""
    option_id, _, count_with_filter = _apply_first_checkbox(page)

    page.reload(wait_until="domcontentloaded", timeout=60_000)
    assert "filters=" in page.url, f"После reload параметр filters потерян: {page.url}"

    _open_filters(page)
    expect(page.locator(f'[id="{option_id}"]')).to_be_checked()
    assert _wait_found_count(page, count_with_filter) == count_with_filter, (
        "После reload счётчик не совпадает с тем, что был до перезагрузки"
    )


# ===========================================================================
# 7 (моб.). Два фильтра из разных групп сужают выдачу не меньше, чем один
# ===========================================================================
def test_multiple_filters_narrow_results(page: Page):
    """Почему именно разные группы (AND) — см. десктопный тест."""
    first_id, _, count_one = _apply_first_checkbox(page)

    second_id = page.evaluate(
        """(firstId) => {
            const GROUP = '.filters-vertical__content__params__item';
            const root = document.querySelector('.modal__sort.show');
            if (!root) return null;
            const first = document.querySelector('[id="' + firstId + '"]');
            const firstGroup = first && first.closest(GROUP);
            const inputs = [...root.querySelectorAll(
              GROUP + '__content__checkboxes__item input'
            )];
            const ok = inputs.find(i => !i.disabled && i.id && i.id !== firstId
                && (!firstGroup || !firstGroup.contains(i)));
            return ok ? ok.id : null;
        }""",
        first_id,
    )
    if not second_id:
        pytest.skip("После первого фильтра не осталось активных опций в другой группе")

    url_before = page.url
    page.locator(f'{FILTERS_MODAL} label[for="{second_id}"]').tap()
    page.wait_for_function("(u) => location.href !== u", arg=url_before, timeout=10_000)
    _wait_after_filter(page)
    count_two = _found_count(page)

    assert count_two <= count_one, (
        f"С двумя фильтрами выдача больше, чем с одним: {count_one} → {count_two}"
    )


# ===========================================================================
# 8 (моб.). Прайс-фильтр: уменьшение max не увеличивает выдачу
# ===========================================================================
def test_price_filter_narrows_results(page: Page):
    inputs = _panel(page).locator(PRICE_INPUTS)
    if not _present(inputs, 2):
        pytest.skip("На этой категории нет полей ценового фильтра")

    before = _found_count(page)
    max_input = inputs.last
    initial = (max_input.input_value() or "").strip()
    try:
        new_max = str(max(1, int(re.sub(r"[^\d]", "", initial)) // 2))
    except ValueError:
        new_max = "1"

    _commit_price_input(page, max_input, new_max, "max")

    after = _found_count(page)
    assert after <= before, f"После сужения цены выдача выросла: {before} → {after}"


# ===========================================================================
# 9 (моб.). Прайс-фильтр: цены в выдаче попадают в заданный интервал
# ===========================================================================
def test_price_filter_keeps_prices_within_range(page: Page):
    """Карточки под поп-апом перестраиваются сразу — цены читаем оттуда.
    Почему сверяем цены, а не только счётчик, — см. десктопный тест."""
    inputs = _panel(page).locator(PRICE_INPUTS)
    if not _present(inputs, 2):
        pytest.skip("На этой категории нет полей ценового фильтра")

    prices_before = _visible_prices_bani(page)
    if len(prices_before) < 3:
        pytest.skip("Слишком мало товаров с ценой, чтобы резать интервал")

    lo, hi = min(prices_before), max(prices_before)
    min_mdl = (lo + (hi - lo) // 4) // 100
    max_mdl = (hi - (hi - lo) // 4) // 100
    if min_mdl >= max_mdl:
        pytest.skip(f"Цены категории слишком близки: {lo}-{hi} бань")

    _commit_price_input(page, inputs.first, str(min_mdl), "min")
    _commit_price_input(page, inputs.last, str(max_mdl), "max")

    prices_after = _visible_prices_bani(page)
    if not prices_after:
        pytest.skip(f"В интервал {min_mdl}-{max_mdl} MDL не попал ни один товар")

    lo_bani, hi_bani = min_mdl * 100, max_mdl * 100
    out_of_range = [p for p in prices_after if p < lo_bani or p > hi_bani]
    assert not out_of_range, (
        f"В выдаче есть товары вне интервала {min_mdl}-{max_mdl} MDL: "
        f"{[p / 100 for p in out_of_range]} (все цены: {[p / 100 for p in prices_after]})"
    )


# ===========================================================================
# 10 (моб.). «EFECTUAT» закрывает поп-ап, фильтр остаётся применённым
# ===========================================================================
def test_apply_button_closes_modal_keeps_filter(page: Page):
    option_id, _, count_with_filter = _apply_first_checkbox(page)

    page.locator(BTN_APPLY).tap()

    expect(_panel(page)).to_have_count(0)
    assert "filters=" in page.url, f"После «EFECTUAT» фильтр пропал из URL: {page.url}"
    # Выдача отфильтрована: карточек не больше, чем насчитал фильтр (на
    # странице может быть меньше — пагинация).
    cards = page.locator(f".product__items {PRODUCT_CARD}")
    expect(cards.first).to_be_visible()
    assert cards.count() <= count_with_filter, (
        f"Под фильтром на {count_with_filter} товаров показано {cards.count()} карточек"
    )
    _open_filters(page)
    expect(page.locator(f'[id="{option_id}"]')).to_be_checked()


# ===========================================================================
# 11 (моб.). «RESETARE» сбрасывает все фильтры
# ===========================================================================
def test_reset_button_clears_filters(page: Page):
    option_id, initial, _ = _apply_first_checkbox(page)
    expect(page.locator(BTN_RESET)).not_to_have_class(re.compile(r"\bdisabled\b"))

    page.locator(BTN_RESET).tap()

    page.wait_for_function("() => !location.search.includes('filters=')", timeout=10_000)
    after = _wait_found_count(page, initial)
    assert after == initial, f"После «RESETARE» счётчик не вернулся: {initial} → {after}"
    expect(page.locator(f'[id="{option_id}"]')).not_to_be_checked()
    # Сбрасывать больше нечего — кнопки гаснут
    expect(page.locator(BTN_RESET)).to_have_class(re.compile(r"\bdisabled\b"))
