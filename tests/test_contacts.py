"""Тесты страницы «Контакты» (`/ru/contacts`, «Наши магазины»).

Магазины НЕ зашиты: эталон — данные страницы `window.__NUXT__.state.contacts.shops`
(то, что пришло с бэкенда), и вёрстку сверяем с ними. Так тесты переживают
правку магазинов в админке, но ловят потерю или искажение данных при выводе.

Разметка проверена вживую 2026-10-12:

- Аккордеон `#accordionShop`: `h1` «Наши магазины», пункты `.accordion__item`
  (открытый — `.open`). Шапка пункта — `button.accordion__shop` с городом
  (`.city`) и адресом (`.location`); содержимое `.accordion__shop__content`:
  ссылка «Построить маршрут» (`a.shop__link`, Google Maps
  `dir/?api=1&destination=<lat>,<lng>`, новая вкладка), график
  (`.accordion__shop__schedule span`), телефоны
  (`.accordion__shop__phones a[href^="tel:"]`).
- Открыт всегда ровно один магазин: выбор другого закрывает прежний,
  повторный клик по открытому его НЕ сворачивает.
- Карта справа — `.shops__map iframe`, переключается вслед за выбранным
  магазином: у магазина с координатами — embed `place?...&q=<lat>,<lng>`, у
  магазина без координат — iframe, вставленный в админке (поле `iframe`).
- Ссылка «Контакты» в ВЕРХНЕМ меню ведёт на прод `jblstore.md` (настройка
  админки) — по ней не ходим, вход на страницу проверяем через футер.

НЕ БАГ (решение юзера 12.10.2026): у магазина без координат («vadvoda»,
тестовые данные) «Построить маршрут» строится с `destination=0,0`. Так
задумано — ссылку маршрута проверяем только у магазинов с координатами, на
магазин без координат проверку не добавлять.
"""

import html
import re
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

CONTACTS_URL = "/ru/contacts"
HOME_URL = "/ru"

ACCORDION = "#accordionShop"
TITLE = f"{ACCORDION} h1"
ITEM = f"{ACCORDION} .accordion__item"
ITEM_OPEN = f"{ITEM}.open"
ITEM_BUTTON = "button.accordion__shop"
ITEM_LOCATION = ".shop__address .location"
ROUTE_LINK = "a.shop__link"
SCHEDULE_LINE = ".accordion__shop__schedule span"
PHONE_LINK = '.accordion__shop__phones a[href^="tel:"]'
MAP_IFRAME = ".shops__map iframe"
BREADCRUMB_ITEM = ".breadcrumb .breadcrumb__item"
FOOTER_CONTACTS = 'footer a[href$="/contacts"]'

SHOPS_JS = "() => window.__NUXT__?.state?.contacts?.shops ?? []"


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _shops(page: Page) -> list[dict]:
    return page.evaluate(SHOPS_JS)


def _has_coords(shop: dict) -> bool:
    c = shop.get("coordinates") or {}
    return bool(c.get("lat")) and bool(c.get("lng"))


def _admin_iframe_src(shop: dict) -> str | None:
    """src из iframe, вставленного в админке (поле `iframe` — HTML-строка)."""
    m = re.search(r'src="([^"]+)"', shop.get("iframe") or "")
    return html.unescape(m.group(1)) if m else None


def _item(page: Page, index: int):
    return page.locator(ITEM).nth(index)


def _open_shop(page: Page, index: int) -> None:
    """Раскрыть магазин; повтор — на случай клика до гидрации (см. conftest).

    Повторный клик по уже открытому пункту его не сворачивает, поэтому
    повтор безопасен."""
    item = _item(page, index)
    for attempt in range(3):
        item.locator(ITEM_BUTTON).click()
        try:
            expect(item).to_have_class(re.compile(r"\bopen\b"), timeout=5_000)
            return
        except AssertionError:
            if attempt == 2:
                raise


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


@pytest.fixture
def contacts(page: Page) -> Page:
    page.goto(CONTACTS_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(ITEM).first).to_be_visible(timeout=30_000)
    # Аккордеон магазинов на странице уже есть — значит, пустые данные означают
    # сломанный путь в __NUXT__, а не «магазинов нет». Раньше это давало skip
    # всех тестов файла.
    assert _shops(page), (
        "Аккордеон магазинов отрисован, а в __NUXT__ (contacts.shops) магазинов нет"
    )
    return page


# ===========================================================================
# Тесты
# ===========================================================================
def test_contacts_page_lists_all_shops(contacts: Page):
    """Заголовок, крошки «Главная / Контакты», и в аккордеоне столько
    магазинов, сколько пришло с бэкенда, — с тем же адресом."""
    page = contacts
    shops = _shops(page)

    expect(page.locator(TITLE)).to_have_text(re.compile(r"Наши магазины"))
    crumbs = page.locator(BREADCRUMB_ITEM)
    expect(crumbs).to_have_count(2)
    expect(crumbs.last).to_have_text(re.compile(r"Контакты", re.I))

    expect(page.locator(ITEM)).to_have_count(len(shops))
    for i, shop in enumerate(shops):
        address = ((shop.get("addresses") or {}).get("address") or "").strip()
        if address:
            expect(_item(page, i).locator(ITEM_LOCATION)).to_have_text(address)


def test_first_shop_open_by_default(contacts: Page):
    """При входе раскрыт ровно один магазин — первый."""
    page = contacts

    expect(page.locator(ITEM_OPEN)).to_have_count(1)
    expect(_item(page, 0)).to_have_class(re.compile(r"\bopen\b"))
    expect(_item(page, 0).locator(SCHEDULE_LINE).first).to_be_visible()


def test_opening_shop_closes_previous(contacts: Page):
    """Выбор другого магазина раскрывает его и закрывает прежний."""
    page = contacts
    if page.locator(ITEM).count() < 2:
        pytest.skip("На странице один магазин — переключать нечего")

    _open_shop(page, 1)

    expect(page.locator(ITEM_OPEN)).to_have_count(1)
    expect(_item(page, 0)).not_to_have_class(re.compile(r"\bopen\b"))
    expect(_item(page, 0).locator(SCHEDULE_LINE).first).to_be_hidden()


def test_shop_schedule_and_phones_match_backend(contacts: Page):
    """У каждого магазина график и телефоны — ровно те, что в данных, а
    телефоны кликабельны (`tel:` с теми же цифрами)."""
    page = contacts
    shops = _shops(page)

    problems = []
    for i, shop in enumerate(shops):
        _open_shop(page, i)
        item = _item(page, i)

        schedule = [s.strip() for s in item.locator(SCHEDULE_LINE).all_text_contents()]
        if schedule != shop.get("schedule", []):
            problems.append(f"#{i} график {schedule} ≠ {shop.get('schedule')}")

        links = item.locator(PHONE_LINK)
        shown = [t.strip() for t in links.all_text_contents()]
        if shown != shop.get("phones", []):
            problems.append(f"#{i} телефоны {shown} ≠ {shop.get('phones')}")
        for j in range(links.count()):
            href = links.nth(j).get_attribute("href") or ""
            if _digits(href) != _digits(shown[j]):
                problems.append(f"#{i} ссылка {href!r} не совпадает с номером {shown[j]!r}")

    assert not problems, "Данные магазинов выведены с ошибками: " + "; ".join(problems)


def test_map_follows_selected_shop(contacts: Page):
    """Карта показывает выбранный магазин: по координатам, а если их нет —
    iframe из админки."""
    page = contacts
    checked = 0

    for i, shop in enumerate(_shops(page)):
        if _has_coords(shop):
            c = shop["coordinates"]
            expected = f"q={c['lat']},{c['lng']}"
        else:
            expected = _admin_iframe_src(shop)
        if not expected:
            continue

        _open_shop(page, i)
        expect(page.locator(MAP_IFRAME)).to_have_attribute(
            "src", re.compile(re.escape(expected)), timeout=10_000
        )
        checked += 1

    if not checked:
        pytest.skip("Ни у одного магазина нет ни координат, ни iframe карты")


def test_route_link_points_to_shop(contacts: Page):
    """«Построить маршрут» ведёт в Google Maps на координаты магазина и
    открывается в новой вкладке.

    Только магазины с координатами — см. «ИЗВЕСТНОЕ» в шапке файла."""
    page = contacts
    with_coords = [(i, s) for i, s in enumerate(_shops(page)) if _has_coords(s)]
    if not with_coords:
        pytest.skip("Ни у одного магазина нет координат")

    for i, shop in with_coords:
        _open_shop(page, i)
        link = _item(page, i).locator(ROUTE_LINK)
        expect(link).to_be_visible()
        expect(link).to_have_attribute("target", "_blank")

        url = urlparse(link.get_attribute("href") or "")
        assert url.netloc.endswith("google.com") and url.path.startswith("/maps/dir"), (
            f"#{i}: маршрут ведёт не в Google Maps: {link.get_attribute('href')}"
        )
        destination = parse_qs(url.query).get("destination", [""])[0]
        c = shop["coordinates"]
        assert destination == f"{c['lat']},{c['lng']}", (
            f"#{i}: маршрут на {destination!r}, а координаты магазина {c['lat']},{c['lng']}"
        )


def test_footer_link_opens_contacts(page: Page):
    """Ссылка «Контакты» в футере ведёт на страницу магазинов."""
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    link = page.locator(f"{FOOTER_CONTACTS}:visible", has_text="Контакты").first
    link.scroll_into_view_if_needed()

    link.click()

    expect(page).to_have_url(re.compile(r"/ru/contacts/?$"), timeout=30_000)
    expect(page.locator(TITLE)).to_be_visible(timeout=20_000)


def test_contacts_in_romanian(contacts: Page):
    """`/ro/contacts` — те же магазины, что и на /ru."""
    page = contacts
    ids_ru = [s["shopId"] for s in _shops(page)]

    page.goto("/ro/contacts", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_function("() => document.documentElement.lang === 'ro'", timeout=20_000)
    expect(page.locator(ITEM).first).to_be_visible(timeout=30_000)

    ids_ro = [s["shopId"] for s in _shops(page)]
    assert ids_ro == ids_ru, f"Магазины на /ro {ids_ro} ≠ на /ru {ids_ru}"
    expect(page.locator(ITEM)).to_have_count(len(ids_ro))
