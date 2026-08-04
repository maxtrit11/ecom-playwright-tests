"""Тесты фильтрации на странице категории (category-agnostic).

Не привязаны к конкретной категории и не зависят от конкретных значений
фильтров (брендов, цветов, цен и т.д.). URL категории передаётся через
переменную окружения `CATEGORY_URL` (по умолчанию `/ro/jbl-tune`).

Запуск на другой категории:
    CATEGORY_URL=/ro/some-category pytest tests/test_category_filters.py
    или (Windows PowerShell)
    $env:CATEGORY_URL='/ro/some-category'; pytest tests/test_category_filters.py

Все тесты опираются на структурные селекторы вёрстки (.filters-vertical*,
.product__item, счётчик «Produse găsite / Найдено товаров») и должны работать
на любой категории с этой же шаблонной разметкой. Тип фильтра, отсутствующий
на конкретной категории (например, прайс-слайдер или тоггл «В наличии»),
вызывает `pytest.skip` — это нормально.
"""

import os
import re

import pytest
from playwright.sync_api import Locator, Page, expect


# URL категории — можно переопределить через env var.
CATEGORY_URL = os.environ.get("CATEGORY_URL", "/ro/jbl-tune")


# ---------------------------------------------------------------------------
# Селекторы (структурные — не зависят от категории и значений фильтров)
# ---------------------------------------------------------------------------
# Класс `.filters-vertical` переиспользован на странице ДВАЖДЫ: настоящий
# сайдбар фильтров и блок ссылок на подкатегории
# (`.filters-vertical filters-vertical--subcategory`). Из-за этого
# `page.locator(".filters-vertical")` даёт strict mode violation. Отсекаем
# блок подкатегорий по модификатору, а все внутренние элементы ищем ОТ
# сайдбара (см. `_sidebar`), а не от страницы: BEM-префикс у обоих блоков
# один и тот же, поэтому `.first` от страницы может зацепить не тот блок.
FILTERS_SIDEBAR = ".filters-vertical:not(.filters-vertical--subcategory)"
FILTER_GROUP = ".filters-vertical__content__params__item"
GROUP_TITLE = ".filters-vertical__content__params__item__header__title"
GROUP_CONTENT = ".filters-vertical__content__params__item__content"
CHECKBOX_ITEM = ".filters-vertical__content__params__item__content__checkboxes__item"
CHECKBOX_LABEL = f"{CHECKBOX_ITEM} label"
PRICE_CONTENT = ".filters-vertical__content__params__item__content__price"
PRICE_INPUTS = f"{PRICE_CONTENT}__inputs input"
IN_STOCK_TOGGLE = ".filters-vertical__in-stock"
FOUND_GOODS = ".filters-vertical__header__found-goods"

PRODUCT_CARD = ".product__item"


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _sidebar(page: Page) -> Locator:
    """Настоящий сайдбар фильтров (не блок ссылок на подкатегории)."""
    return page.locator(FILTERS_SIDEBAR)


def _present(loc: Locator, count: int = 1, timeout: int = 10_000) -> bool:
    """Дождаться, что элементов `loc` стало >= `count`.

    Голый `.count()` ничего не ждёт, а сайдбар догружает часть параметров уже
    ПОСЛЕ гидрации. Мгновенная проверка давала ложный skip («на категории нет
    прайс-фильтра»), из-за которого тест молча не проверял ничего: в изоляции
    он проходит, а в полном прогоне скипается."""
    try:
        loc.nth(count - 1).wait_for(state="attached", timeout=timeout)
        return True
    except Exception:
        return False


def _found_count(page: Page) -> int:
    """Прочитать число из «Produse găsite: N» / «Найдено товаров: N»."""
    text = _sidebar(page).locator(FOUND_GOODS).text_content() or ""
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else -1


def _first_group_with_checkboxes(page: Page, min_options: int = 1) -> Locator | None:
    """Возвращает локатор первой группы фильтров с >=`min_options` чекбоксами,
    или None если такой нет."""
    if not _present(_sidebar(page).locator(CHECKBOX_ITEM), min_options):
        return None
    groups = _sidebar(page).locator(FILTER_GROUP)
    for i in range(groups.count()):
        g = groups.nth(i)
        if g.locator(CHECKBOX_ITEM).count() >= min_options:
            return g
    return None


def _wait_after_filter(page: Page) -> None:
    """Дождаться, пока бекенд пересчитает выдачу и Vue ре-рендерит счётчик."""
    page.wait_for_load_state("networkidle", timeout=15_000)
    # Vue лениво обновляет счётчик после успешного ответа — даём ему такт
    page.wait_for_timeout(500)


# JS-чтение счётчика «найдено»: тот же селектор, что и у `_found_count`.
_FOUND_JS = """
    () => {
        const el = document.querySelector(
            '.filters-vertical:not(.filters-vertical--subcategory) '
            + '.filters-vertical__header__found-goods');
        const m = el && (el.textContent || '').match(/\\d+/);
        return m ? parseInt(m[0]) : null;
    }
"""


def _wait_found_count(page: Page, expected: int, timeout: int = 15_000) -> int:
    """Дождаться, пока счётчик «найдено» покажет `expected`, и вернуть его.

    `_wait_after_filter` (networkidle + пауза) НЕ гарантирует актуального
    числа: Vue пересчитывает счётчик заметно позже ответа сети — вживую
    31 → 21 занимает около 3 с. Из-за этого тест читал значение от
    ПРЕДЫДУЩЕГО состояния фильтров и падал на ночном прогоне
    («счётчик не вернулся: 31 → 1»), а локально проходил с ретрая.

    Таймаут не бросает исключение: возвращаем то, что реально в DOM, —
    падать должен ассерт теста со своим сообщением, а не хелпер."""
    try:
        page.wait_for_function(
            f"(expected) => ({_FOUND_JS})() === expected",
            arg=expected,
            timeout=timeout,
        )
    except Exception:
        pass
    return _found_count(page)


def _wait_found_count_changed(page: Page, before: int,
                              timeout: int = 15_000) -> int:
    """Дождаться, пока счётчик «найдено» станет отличным от `before`."""
    try:
        page.wait_for_function(
            f"(before) => {{ const v = ({_FOUND_JS})();"
            f" return v !== null && v !== before; }}",
            arg=before,
            timeout=timeout,
        )
    except Exception:
        pass
    return _found_count(page)


# ---------------------------------------------------------------------------
# Фикстура: открыть категорию
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def open_category(page: Page):
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(_sidebar(page)).to_be_visible(timeout=20_000)
    expect(page.locator(PRODUCT_CARD).first).to_be_visible(timeout=20_000)


# ===========================================================================
# 1. Сайдбар фильтров отрисован и содержит группы
# ===========================================================================
def test_filters_sidebar_renders_with_groups(page: Page):
    """Сайдбар виден, групп фильтров > 0."""
    expect(_sidebar(page)).to_be_visible()

    groups = _sidebar(page).locator(FILTER_GROUP)
    assert groups.count() > 0, "В сайдбаре не отрисовано ни одной группы фильтров"


# ===========================================================================
# 2. Счётчик «Найдено товаров» виден и > 0
# ===========================================================================
@pytest.mark.smoke
def test_found_goods_counter_visible(page: Page):
    """Заголовок сайдбара содержит счётчик «Найдено товаров: N» (N > 0)."""
    counter = _sidebar(page).locator(FOUND_GOODS)
    expect(counter).to_be_visible()
    assert _found_count(page) > 0, "Счётчик равен 0 на дефолтной выдаче"


# ===========================================================================
# 3. Клик по чекбоксу применяет фильтр (URL и счётчик меняются)
# ===========================================================================
def test_checkbox_filter_applies(page: Page):
    """Выбор любой опции чекбокс-фильтра:
    — добавляет `filters=` в URL,
    — счётчик «Найдено товаров» не вырос."""
    group = _first_group_with_checkboxes(page, min_options=1)
    if group is None:
        pytest.skip("На этой категории нет чекбокс-фильтров")

    count_before = _found_count(page)

    group.locator(CHECKBOX_LABEL).first.click()
    page.wait_for_url(re.compile(r"filters="), timeout=10_000)
    _wait_after_filter(page)

    count_after = _found_count(page)
    assert count_after <= count_before, (
        f"Счётчик после применения фильтра вырос: {count_before} → {count_after}"
    )


# ===========================================================================
# 4. Повторный клик снимает фильтр — счётчик возвращается к исходному
# ===========================================================================
def test_uncheck_returns_counter_to_initial(page: Page):
    """Применить → снять тот же фильтр — счётчик возвращается к исходному.

    После применения фильтра сайдбар может перестроиться (активная опция
    уезжает наверх или меняется порядок групп), поэтому ловим стабильный
    идентификатор `for=...` у label'а до первого клика и используем его
    для второго клика."""
    group = _first_group_with_checkboxes(page, min_options=1)
    if group is None:
        pytest.skip("На этой категории нет чекбокс-фильтров")

    initial_count = _found_count(page)
    label_first = group.locator(CHECKBOX_LABEL).first
    label_id = label_first.get_attribute("for")
    assert label_id, "У label чекбокса не оказалось for-атрибута"

    # Используем JS-`.click()` — это надёжнее, чем Playwright mouse-event:
    # на этом фронте label обёрнут декорирующими спанами, и реальный
    # mouse-click промахивается мимо обработчика тогла.
    label_first.evaluate("el => el.click()")
    page.wait_for_function(
        "() => location.search.includes('filters=')", timeout=10_000
    )
    _wait_after_filter(page)
    # Ждём, пока счётчик реально отразит фильтр, а не покажет прежнее число
    _wait_found_count_changed(page, initial_count)
    page.wait_for_timeout(800)  # дать Vue время устаканить state

    # Снимаем тот же чекбокс — ищем по стабильному id
    page.locator(f'label[for="{label_id}"]').first.evaluate("el => el.click()")
    page.wait_for_function(
        "() => !location.search.match(/filters=\\d/)", timeout=10_000
    )
    _wait_after_filter(page)

    after_count = _wait_found_count(page, initial_count)
    assert after_count == initial_count, (
        f"После снятия фильтра счётчик не вернулся: {initial_count} → {after_count}"
    )


# ===========================================================================
# 5. Тоггл «В наличии» (если есть)
# ===========================================================================
def test_in_stock_toggle_filters_results(page: Page):
    """Тоггл «В наличии» обновляет выдачу (счётчик меняется или не растёт)."""
    toggle = _sidebar(page).locator(IN_STOCK_TOGGLE)
    if not _present(toggle):
        pytest.skip("На этой категории нет тоггла «В наличии»")

    count_before = _found_count(page)

    # Чекбокс внутри тоггла скрыт (display:none) — клик через DOM API,
    # чтобы не упасть на проверке видимости в Playwright.
    toggle.locator("input").first.dispatch_event("click")
    _wait_after_filter(page)

    count_after = _found_count(page)
    assert count_after <= count_before, (
        f"После «В наличии» выдача выросла: {count_before} → {count_after}"
    )


# ===========================================================================
# 6. Состояние фильтра сохраняется при перезагрузке страницы
# ===========================================================================
def test_filter_persists_on_reload(page: Page):
    """Применить фильтр → reload — фильтр всё ещё активен,
    счётчик совпадает с тем, что был до перезагрузки."""
    group = _first_group_with_checkboxes(page, min_options=1)
    if group is None:
        pytest.skip("На этой категории нет чекбокс-фильтров")

    initial_count = _found_count(page)
    group.locator(CHECKBOX_LABEL).first.click()
    page.wait_for_url(re.compile(r"filters="), timeout=10_000)
    _wait_after_filter(page)
    # Без этого ожидания читалось число ДО фильтра (31), а после reload
    # приходило настоящее (1) — тест падал на ровном месте.
    count_with_filter = _wait_found_count_changed(page, initial_count)

    # Стейдж иногда отвечает 504 первой попытке — даём один ретрай
    for attempt in range(2):
        try:
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            break
        except Exception:
            if attempt == 0:
                page.wait_for_timeout(1500)
                continue
            raise
    expect(_sidebar(page)).to_be_visible(timeout=20_000)
    _wait_after_filter(page)

    assert "filters=" in page.url, (
        f"После reload параметр filters потерян: {page.url}"
    )
    assert _wait_found_count(page, count_with_filter) == count_with_filter, (
        "После reload счётчик не совпадает с тем, что был до перезагрузки"
    )


# ===========================================================================
# 7. Два фильтра вместе сужают выдачу не меньше, чем один
# ===========================================================================
def test_multiple_filters_narrow_results(page: Page):
    """Применить чекбоксы из двух разных групп — выдача не больше, чем после первого.

    Применяем первый фильтр, затем берём ВТОРУЮ опцию среди оставшихся
    АКТИВНЫХ: бэкенд дизейблит опции, которые дали бы 0 товаров (badge «(0)»),
    и кликать по такому чекбоксу нельзя — Playwright ждёт enabled и падает по
    таймауту. После сужения до одного товара активными остаются только опции,
    совпадающие с ним, поэтому ищем второй фильтр уже ПОСЛЕ первого клика."""
    group = _first_group_with_checkboxes(page, min_options=1)
    if group is None:
        pytest.skip("На этой категории нет чекбокс-фильтров")

    first_id = group.locator(CHECKBOX_LABEL).first.get_attribute("for")
    assert first_id, "У label чекбокса не оказалось for-атрибута"

    page.locator(f'label[for="{first_id}"]').first.click()
    page.wait_for_url(re.compile(r"filters="), timeout=10_000)
    _wait_after_filter(page)
    count_one = _found_count(page)

    # Ищем вторую опцию, которая осталась активной (input не disabled),
    # отличается от первой И ЛЕЖИТ В ДРУГОЙ ГРУППЕ.
    #
    # Группа обязательна: подтверждено в браузере 2026-07-30 на /ro/jbl-tune —
    # опции ОДНОЙ группы уходят в URL одним ключом через запятую
    # (`filters=38:175,219`) и комбинируются по OR, поэтому выдача законно
    # РАСТЁТ (1 → 4). Разные группы дают отдельные ключи
    # (`filters=38:175,74:224`) и комбинируются по AND — сужают (1 → 1).
    # Без фильтра по группе тест падал на корректном поведении сайта.
    second_id = page.evaluate(
        """(firstId) => {
            const GROUP = '.filters-vertical__content__params__item';
            const root = document.querySelector(
              '.filters-vertical:not(.filters-vertical--subcategory)'
            );
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
        pytest.skip(
            "После первого фильтра не осталось активных опций в другой группе"
        )

    page.locator(f'label[for="{second_id}"]').first.click()
    _wait_after_filter(page)
    count_two = _found_count(page)

    assert count_two <= count_one, (
        f"С двумя фильтрами выдача больше, чем с одним: {count_one} → {count_two}"
    )


# ===========================================================================
# 8. Прайс-фильтр (если есть): уменьшение max не увеличивает выдачу
# ===========================================================================
def test_price_filter_narrows_results(page: Page):
    """В прайс-блоке уменьшить значение max — счётчик не вырос."""
    inputs = _sidebar(page).locator(PRICE_INPUTS)
    if not _present(inputs, 2):
        pytest.skip("На этой категории нет полей ценового фильтра")

    count_before = _found_count(page)
    max_input = inputs.last
    initial = (max_input.input_value() or "").strip()

    # Берём половину текущего max, либо 1 если не получилось распарсить
    try:
        new_max = str(max(1, int(re.sub(r"[^\d]", "", initial)) // 2))
    except ValueError:
        new_max = "1"

    # Прайс-инпут коммитит фильтр только по native blur. Чтобы это сработало
    # надёжно: реальный фокус через клик → ввод → Tab (реальный keyboard-blur).
    # URL обновляется через pushState — wait_for_url его не ловит,
    # поэтому опрашиваем через wait_for_function. Между шагами небольшие
    # паузы, иначе Vue v-model debounce заглатывает изменения.
    max_input.click()
    page.wait_for_timeout(300)
    max_input.fill(new_max)
    page.wait_for_timeout(500)
    max_input.press("Tab")
    page.wait_for_function(
        "() => location.search.includes('filters=price')", timeout=15_000
    )
    _wait_after_filter(page)

    count_after = _found_count(page)
    assert count_after <= count_before, (
        f"После сужения цены выдача выросла: {count_before} → {count_after}"
    )
