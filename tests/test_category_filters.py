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
import time

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
# Поля цены приходят асинхронно, отдельно от остальных групп: заголовок
# «Preț 0 - 2380 MDL» уже есть, а на месте полей пустые `<!---->`. Замер
# 09.10.2026: 2-13 с, изредка дольше 15 с. С общими 10 с мобильный прайс-фильтр
# уходил в ложный skip «нет полей ценового фильтра» в каждом прогоне.
PRICE_INPUTS_TIMEOUT = 25_000
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
    """Дождаться, пока бекенд ответит на смену фильтра.

    Раньше здесь была ещё пауза 500 мс «на такт Vue». Её не хватало (счётчик
    отстаёт от сети до ~3 с), а читать число сразу после неё — значит читать
    прежнее значение. Актуальность счётчика тесты ждут сами, по факту:
    `_wait_found_count` / `_wait_found_count_changed`.
    """
    page.wait_for_load_state("networkidle", timeout=15_000)


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

    # Счётчик обновляется заметно позже ответа сети. Прочитай мы его сразу —
    # получили бы прежнее число, и «не вырос» выполнялось бы вхолостую, даже
    # если фильтр раздувает выдачу. Ждём смену (на этой категории первая
    # опция её даёт: 31 → 21); если смены нет — читаем после потолка.
    count_after = _wait_found_count_changed(page, count_before, timeout=10_000)
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
    # Ждём, пока счётчик реально отразит фильтр; пауза 800 мс «на state»
    # после этого была лишней — снятие ниже само ждёт URL и счётчик.
    _wait_found_count_changed(page, initial_count)

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

    # Не мгновенное чтение: счётчик отстаёт от сети, и прежнее число давало бы
    # «не выросло» вхолостую. Ждём смену; нет смены (всё в наличии) — читаем
    # после потолка.
    count_after = _wait_found_count_changed(page, count_before, timeout=10_000)
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

    first_label = group.locator(CHECKBOX_LABEL).first
    first_id = first_label.get_attribute("for")
    assert first_id, "У label чекбокса не оказалось for-атрибута"
    # Опция обещает столько товаров — «20 Hz - 20 kHz (1)»
    promised = re.search(r"\((\d+)\)\s*$", first_label.text_content() or "")
    count_initial = _found_count(page)

    page.locator(f'label[for="{first_id}"]').first.click()
    page.wait_for_url(re.compile(r"filters="), timeout=10_000)
    _wait_after_filter(page)
    # Вторую опцию выбираем только из ОБНОВЛЁННОГО сайдбара. Счётчик и опции
    # приходят одним ответом, а Vue отрисовывает их через ~3 с после сети.
    # 15.10.2026 тест брал опцию из сайдбара ДО первого фильтра: после
    # «20 Hz - 20 kHz (1)» группы «Drivere» уже нет, но в старом DOM была
    # активная «32 mm (7)» — AND дал 0 товаров, сайдбар пропал вместе с выдачей.
    if promised:
        count_one = _wait_found_count(page, int(promised.group(1)))
    else:
        count_one = _wait_found_count_changed(page, count_initial)

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

    url_one = page.url
    page.locator(f'label[for="{second_id}"]').first.click()
    # Второй фильтр должен попасть в URL — без этого читали бы выдачу первого
    page.wait_for_function("(before) => location.href !== before", arg=url_one,
                           timeout=10_000)
    _wait_after_filter(page)
    # При 0 товаров страница рисует только плитки подкатегорий — без сайдбара
    # и счётчика. Опция была активной, значит бэкенд обещал >0: падаем с
    # понятным сообщением, а не по таймауту чтения счётчика.
    assert _present(_sidebar(page)), (
        f"После второго фильтра выдача пустая (сайдбар пропал): {page.url}"
    )
    # Счётчик отстаёт от сети; AND двух групп может законно оставить то же
    # число (1 → 1), поэтому ждём смену недолго и читаем, что есть.
    count_two = _wait_found_count_changed(page, count_one, timeout=5_000)

    assert count_two <= count_one, (
        f"С двумя фильтрами выдача больше, чем с одним: {count_one} → {count_two}"
    )


# ===========================================================================
# 8. Прайс-фильтр (если есть): уменьшение max не увеличивает выдачу
# ===========================================================================
def test_price_filter_narrows_results(page: Page):
    """В прайс-блоке уменьшить значение max — счётчик не вырос."""
    inputs = _sidebar(page).locator(PRICE_INPUTS)
    if not _present(inputs, 2, timeout=PRICE_INPUTS_TIMEOUT):
        pytest.skip("На этой категории нет полей ценового фильтра")

    count_before = _found_count(page)
    max_input = inputs.last
    initial = (max_input.input_value() or "").strip()

    # Берём половину текущего max, либо 1 если не получилось распарсить
    try:
        new_max = str(max(1, int(re.sub(r"[^\d]", "", initial)) // 2))
    except ValueError:
        new_max = "1"

    # Ввод и ожидание применения — общим хелпером: URL обновляется через
    # pushState и с заметной задержкой, см. `_commit_price_input`.
    _commit_price_input(page, max_input, new_max, "max")

    count_after = _found_count(page)
    assert count_after <= count_before, (
        f"После сужения цены выдача выросла: {count_before} → {count_after}"
    )


# ===========================================================================
# 9. Прайс-фильтр: цены в выдаче реально попадают в заданный интервал
# ===========================================================================
def _visible_prices_bani(page: Page) -> list[int]:
    """Цены видимых товаров В БАНАХ (товары без стока пропускаем).

    Без стока в карточке вообще нет блока `.product__prices` — цена не
    отображается (проверено вживую, подтверждено владельцем стенда), так что
    проверять по ним попадание в интервал нечего.

    Считаем в банах: на витрине соседствуют «1 899 MDL» и «1 529.15 MDL», и
    наивное «вырезать всё, кроме цифр» даёт 1899 и 152915 — числа из разных
    масштабов, сравнивать их с границей фильтра бессмысленно.
    """
    return page.evaluate(
        """() => {
            const toBani = (text) => {
                const m = (text || '').match(/([\\d\\s.,]+)\\s*MDL/);
                if (!m) return null;
                const v = parseFloat(m[1].replace(/\\s/g, '').replace(',', '.'));
                return isNaN(v) ? null : Math.round(v * 100);
            };
            return [...document.querySelectorAll('.product__items .product__item')]
                .filter(c => !c.querySelector('.product__out-of-stock-label'))
                .map(c => {
                    const el = c.querySelector(
                        '.product__prices .price:not(.old__price):not(.discount-value)'
                    );
                    return el ? toBani(el.textContent) : null;
                })
                .filter(v => v != null);
        }"""
    )


def _commit_price_input(page: Page, field: Locator, value: str, bound: str) -> None:
    """Вписать границу цены (`bound`: "min" или "max") и дождаться применения.

    Фильтр применяется только по native blur, поэтому: реальный фокус кликом
    → ввод → Tab. Паузы между шагами обязательны, иначе debounce v-model
    заглатывает изменение.

    Дальше обязательно ЖДЁМ саму границу в URL. Глухая пауза не годится:
    вживую (2026-08-19, /ro/jbl-tune) вторая граница применяется через ~9.7 с
    после Tab, и URL, счётчик «найдено» и карточки переключаются одним тактом.
    Проверка `location.search.includes('filters=price')` тоже бесполезна —
    после ПЕРВОЙ границы `filters=price` в URL уже есть, условие выполняется
    мгновенно, и тест читает выдачу от предыдущего состояния фильтра. Именно
    это уронило ночной прогон 32209900055 («в выдаче товары дороже максимума»)
    на полностью исправном фильтре.
    """
    # Ввод повторяем: применение ПЕРВОЙ границы перерисовывает панель фильтров,
    # и ввод второй, попавший в этот такт, теряется вместе со старым узлом
    # инпута — значение в поле есть, а blur уже некому обработать. Так тест и
    # падал в CI («граница max не применилась за 25 с»), проходя при этом с
    # ретрая (прогон 32338373909). Ждём границу в URL — единственный надёжный
    # признак применения (почему не `includes('filters=price')` — ниже).
    grid_before = _visible_prices_bani(page)

    attempts = 3
    for attempt in range(1, attempts + 1):
        field.click()
        page.wait_for_timeout(300)
        field.fill(value)
        page.wait_for_timeout(500)
        field.press("Tab")
        try:
            page.wait_for_function(
                """([value, isMax]) => {
                    const m = decodeURIComponent(location.search)
                        .match(/filters=price:(\\d+),(\\d+)/);
                    return !!m && m[isMax ? 2 : 1] === value;
                }""",
                arg=[value, bound == "max"],
                timeout=15_000,
            )
            break
        except Exception:
            if attempt == attempts:
                pytest.fail(
                    f"Граница цены {bound}={value} не применилась за "
                    f"{attempts} попытки, URL остался {page.url}"
                )
    _wait_after_filter(page)

    # URL — признак того, что фильтр ПРИНЯТ, но не того, что выдача уже
    # пересобрана: карточки заметно отстают от смены адреса. Читая цены сразу,
    # тест видел старую сетку и падал на «в выдаче товары дороже максимума»
    # при исправном фильтре. Ждём, пока набор цен реально изменится.
    #
    # Ждём именно ИЗМЕНЕНИЯ, а не попадания в интервал: «ждать, пока станет
    # правильно» — это ассерт, вывернутый в ожидание, и настоящий баг фильтра
    # он бы замаскировал. Не дождались — идём дальше, пусть падает ассерт
    # теста со своим текстом.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _visible_prices_bani(page) != grid_before:
            break
        page.wait_for_timeout(500)


def test_price_filter_keeps_prices_within_range(page: Page):
    """Задать интервал цен — все товары в выдаче попадают в этот интервал.

    Прошлая проверка прайс-фильтра смотрела только на СЧЁТЧИК («не вырос»).
    Такой ассерт проходит и в случае, когда фильтр просто игнорируется частью
    товаров: количество не растёт, а в выдаче лежат товары дороже максимума.
    Здесь сверяем сами цены.
    """
    inputs = _sidebar(page).locator(PRICE_INPUTS)
    if not _present(inputs, 2, timeout=PRICE_INPUTS_TIMEOUT):
        pytest.skip("На этой категории нет полей ценового фильтра")

    prices_before = _visible_prices_bani(page)
    if len(prices_before) < 3:
        pytest.skip("Слишком мало товаров с ценой, чтобы резать интервал")

    # Интервал строим от реальных цен категории, а не от круглых чисел:
    # иначе на одной категории он пустой, на другой — не сужает ничего.
    lo, hi = min(prices_before), max(prices_before)
    min_mdl = (lo + (hi - lo) // 4) // 100
    max_mdl = (hi - (hi - lo) // 4) // 100
    if min_mdl >= max_mdl:
        pytest.skip(f"Цены категории слишком близки: {lo}-{hi} бань")

    _commit_price_input(page, inputs.first, str(min_mdl), "min")
    _commit_price_input(page, inputs.last, str(max_mdl), "max")

    prices_after = _visible_prices_bani(page)
    lo_bani, hi_bani = min_mdl * 100, max_mdl * 100

    # Пустая выдача — повод для skip, только если в интервал и правда никто не
    # попадает. Раньше skip был безусловным: фильтр, обнуливший выдачу при
    # подходящих товарах, давал skip вместо падения, а «все в интервале» на
    # пустом списке истинно вхолостую.
    in_range_before = [p for p in prices_before if lo_bani <= p <= hi_bani]
    if not prices_after:
        assert not in_range_before, (
            f"Фильтр {min_mdl}-{max_mdl} MDL очистил выдачу, хотя до фильтра в "
            f"интервал попадали товары: {[p / 100 for p in in_range_before]}"
        )
        pytest.skip(f"В интервал {min_mdl}-{max_mdl} MDL не попал ни один товар")
    out_of_range = [p for p in prices_after if p < lo_bani or p > hi_bani]
    assert not out_of_range, (
        f"В выдаче есть товары вне интервала {min_mdl}-{max_mdl} MDL: "
        f"{[p / 100 for p in out_of_range]} (все цены: {[p / 100 for p in prices_after]})"
    )
