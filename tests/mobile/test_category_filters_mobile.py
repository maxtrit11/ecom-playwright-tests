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
    PRICE_INPUTS_TIMEOUT,
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
    применения фильтра тесты и так ждут по счётчику/URL.

    Паузы 500 мс «на такт» после этого нет: актуальное число тесты ждут по
    факту (`_wait_found_count` / `_wait_found_count_changed`)."""
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass


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


def _close_filters_by_x(page: Page) -> None:
    """Закрыть поп-ап крестиком — как пользователь после фильтрации — и
    дождаться, что он закрылся, а под ним видна отфильтрованная выдача."""
    page.locator(BTN_CLOSE).tap()
    expect(_panel(page)).to_have_count(0)
    expect(page.locator(PRODUCT_CARD).first).to_be_visible()


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


def _option_badge(page: Page, option_id: str) -> int | None:
    """Число в скобках у опции («Doar livrare (15)») — сколько товаров даст
    выдача, если опцию отметить при ТЕКУЩИХ фильтрах (между группами — AND;
    замер в Pixel 7 12.10.2026: «Doar livrare (15)» → счётчик 32 → 15, а
    бейджи других групп после этого пересчитываются под новую выдачу)."""
    item = page.locator(f'{FILTERS_MODAL} {CHECKBOX_ITEM}:has([id="{option_id}"])').first
    m = re.search(r"\((\d+)\)\s*$", (item.text_content() or "").strip())
    return int(m.group(1)) if m else None


def _option_url_key(option_id: str) -> str:
    """Ключ опции в `filters=`: `sp-key-38-175` → `38:175`, `sp-key-fb_dm-1` → `fb_dm:1`."""
    m = re.match(r"^sp-key-(.+)-([^-]+)$", option_id)
    assert m, f"Неожиданный формат id опции фильтра: {option_id!r}"
    return f"{m.group(1)}:{m.group(2)}"


def _wait_filter_in_url(page: Page, key: str, present: bool = True,
                        timeout: int = 10_000) -> None:
    """Дождаться, что `key` появился в `filters=` URL (или исчез при present=False).

    Это доказательство, что фильтр реально применён: счётчик может законно не
    измениться (опция покрывает всю выдачу), и тогда `после <= до` выполнялось
    бы и при потерянном тапе. Исключение бросаем намеренно — без ключа в URL
    фильтр не применён, и тест обязан упасть.
    """
    page.wait_for_function(
        """([key, present]) => {
            const m = decodeURIComponent(location.search).match(/filters=([^&]*)/);
            const has = !!m && m[1].includes(key);
            return has === present;
        }""",
        arg=[key, present],
        timeout=timeout,
    )


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
    badge = _option_badge(page, option_id)
    for _ in range(3):
        if option.is_checked():
            break
        label.tap()
        try:
            page.wait_for_url(re.compile(r"filters="), timeout=5_000)
            break
        except Exception:
            continue
    # Факт применения: ключ опции в URL и отмеченный чекбокс
    _wait_filter_in_url(page, _option_url_key(option_id))
    expect(option).to_be_checked()
    _wait_after_filter(page)

    # Счётчик ждём до числа из бейджа опции — это точное ожидаемое значение.
    # Раньше ждали «любой смены» (с проглоченным таймаутом), и при
    # неприменённом фильтре вызывающие тесты сравнивали 32 <= 32 и зеленели.
    if badge is not None:
        after = _wait_found_count(page, badge)
        assert after == badge, (
            f"После фильтра «{option_id}» найдено {after}, а опция обещала {badge}"
        )
    else:
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
    # Ждём исчезновения ИМЕННО этого ключа: прежний шаблон `filters=\d` не
    # ловил ключи вида `fb_dm:1` и выполнялся ещё до снятия.
    _wait_filter_in_url(page, _option_url_key(option_id), present=False)
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

    # Сначала доказываем, что фильтр применён: тоггл включён и `inStock:true`
    # в URL. Без этого `после <= до` проходило и при потерянном тапе (32 <= 32).
    expect(toggle.locator("input[type=checkbox]")).to_be_checked(timeout=10_000)
    _wait_filter_in_url(page, "inStock:true")
    _wait_after_filter(page)

    # Счётчик отстаёт от сети: ждём смену. Если всё в наличии, число законно
    # не меняется — тогда читаем после потолка (применение доказано выше).
    after = _wait_found_count_changed(page, before, timeout=10_000)
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

    badge_two = _option_badge(page, second_id)
    page.locator(f'{FILTERS_MODAL} label[for="{second_id}"]').tap()

    # Факт применения второго фильтра: он отмечен, и в URL оба ключа.
    # Раньше ждали лишь «URL сменился» и читали счётчик сразу — при
    # неприменённом втором фильтре `count_one <= count_one` было истинно.
    expect(page.locator(f'[id="{second_id}"]')).to_be_checked(timeout=10_000)
    _wait_filter_in_url(page, _option_url_key(second_id))
    _wait_filter_in_url(page, _option_url_key(first_id))
    _wait_after_filter(page)

    # Бейдж второй опции уже посчитан под первый фильтр — это и есть
    # ожидаемая выдача по AND двух групп.
    if badge_two is not None:
        count_two = _wait_found_count(page, badge_two)
        assert count_two == badge_two, (
            f"С двумя фильтрами найдено {count_two}, а опция обещала {badge_two}"
        )
    else:
        count_two = _wait_found_count_changed(page, count_one, timeout=5_000)

    assert count_two <= count_one, (
        f"С двумя фильтрами выдача больше, чем с одним: {count_one} → {count_two}"
    )


# ===========================================================================
# 8 (моб.). Прайс-фильтр: уменьшение max не увеличивает выдачу
# ===========================================================================
def test_price_filter_narrows_results(page: Page):
    inputs = _panel(page).locator(PRICE_INPUTS)
    if not _present(inputs, 2, timeout=PRICE_INPUTS_TIMEOUT):
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

    # Закрываем поп-ап на «X» и смотрим уже на саму страницу: товары дороже
    # нового максимума остаться не должны.
    _close_filters_by_x(page)
    prices = _visible_prices_bani(page)
    # «Нет дороже максимума» истинно и на пустом списке — сначала убеждаемся,
    # что есть что проверять (половина максимума категории оставляет товары).
    assert prices, f"После фильтра до {new_max} MDL на странице нет ни одной цены"
    too_expensive = [p for p in prices if p > int(new_max) * 100]
    assert not too_expensive, (
        f"После закрытия фильтра на странице товары дороже {new_max} MDL: "
        f"{[p / 100 for p in too_expensive]}"
    )


# ===========================================================================
# 9 (моб.). Прайс-фильтр: цены в выдаче попадают в заданный интервал
# ===========================================================================
def test_price_filter_keeps_prices_within_range(page: Page):
    """Задать интервал цены, закрыть поп-ап на «X» и сверить цены товаров на
    странице. Почему сверяем цены, а не только счётчик, — см. десктопный тест."""
    inputs = _panel(page).locator(PRICE_INPUTS)
    if not _present(inputs, 2, timeout=PRICE_INPUTS_TIMEOUT):
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
    _close_filters_by_x(page)

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
