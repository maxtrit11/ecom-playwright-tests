"""Тесты согласия на cookie: баннер, окно настроек и реальная блокировка трекеров.

Разметка и поведение проверены вживую 2026-10-12 (MCP-браузер + чистые
контексты Playwright):

- БАННЕР `.cookie-banner` (role=dialog) внизу экрана у каждого нового
  посетителя: заголовок «Мы используем cookie», ссылка на
  `/ru/cookie-policy`, кнопки с атрибутом `data-consent-action` =
  `accept` («Принять все») / `reject` («Отклонить все») / `settings`
  («Настройки»).
  После выбора и перезагрузки баннер ОСТАЁТСЯ в DOM, но со `display: none`,
  поэтому проверяем видимость, а не наличие.

- ОКНО НАСТРОЕК `.cookie-settings`: четыре строки `.cookie-settings__row`
  — «Необходимые» (включено и заблокировано, `is-locked`), «Аналитика»,
  «Маркетинг», «Функциональные» (по умолчанию выключены). Переключатель —
  `label.cookie-settings__toggle` с чекбоксом внутри. Кнопки «Сохранить
  настройки», «Отклонить все», «Принять все» и крестик
  `.cookie-settings__close`. В футере кнопка `.footer__cookie-settings-btn`
  («Настройки cookie») открывает то же окно повторно.

- ВЫБОР хранится в localStorage и в cookie `cookie_consent` одинаково:
  `{"categories": {"necessary", "analytics", "marketing", "functional"},
  "version": "1", "ts": ...}`.

- БЛОКИРОВКА РЕАЛЬНАЯ: до согласия и после «Отклонить все» запросов к Clarity
  нет ни одного; после «Принять все» грузится clarity.js и ставятся `_clck`,
  `MUID`. Тест «после согласия трекеры грузятся» — контрольный: без него
  проверки «трекеров нет» оставались бы зелёными и при сломанном
  перехвате запросов.

ВАЖНО: conftest прячет `.cookie-banner` во всех тестах (он перекрывал кнопки
сайдбара корзины). Здесь баннер — предмет проверки, поэтому фикстура
`_suppress_overlays` переопределена: прячем только виджет Bitrix24 и
промо-попап.
"""

import json
import re
from urllib.parse import unquote

import pytest
from playwright.sync_api import Page, expect

from conftest import _HIDE_OVERLAYS_SCRIPT, _OVERLAY_SELECTORS

HOME_URL = "/ru"
OTHER_URL = "/ru/brands"

# Баннер
BANNER = ".cookie-banner"
BANNER_TITLE = f"{BANNER} .cookie-banner__title"
BANNER_POLICY_LINK = f"{BANNER} a.cookie-banner__link"
BTN_ACCEPT = f'{BANNER} [data-consent-action="accept"]'
BTN_REJECT = f'{BANNER} [data-consent-action="reject"]'
BTN_SETTINGS = f'{BANNER} [data-consent-action="settings"]'

# Окно настроек
SETTINGS = ".cookie-settings"
SETTINGS_DIALOG = f"{SETTINGS} .cookie-settings__dialog"
SETTINGS_ROW = f"{SETTINGS} .cookie-settings__row"
ROW_NAME = ".cookie-settings__row-name"
ROW_TOGGLE = "label.cookie-settings__toggle"
SETTINGS_CLOSE = f"{SETTINGS} .cookie-settings__close"
SETTINGS_BTN = f"{SETTINGS} .cookie-settings__btn"
# В футере две такие кнопки (десктопная и скрытый мобильный дубль) — берём видимую.
FOOTER_SETTINGS_BTN = ".footer__cookie-settings-btn:visible"

CONSENT_KEY = "cookie_consent"
CATEGORIES = {
    "Необходимые": "necessary",
    "Аналитика": "analytics",
    "Маркетинг": "marketing",
    "Функциональные": "functional",
}

# Трекеры из описаний категорий «Аналитика» / «Маркетинг» в самом окне
# настроек (Google Analytics, Hotjar, Clarity, Meta Pixel, Google Ads, TikTok).
TRACKERS = re.compile(
    r"clarity\.ms|google-analytics\.com|googletagmanager\.com|static\.hotjar\.com"
    r"|connect\.facebook\.net|facebook\.com/tr|analytics\.tiktok\.com"
    r"|googleadservices\.com|doubleclick\.net"
)
# Сколько слушать сеть после загрузки. Clarity на стенде стартует через
# 1-3 с после domcontentloaded; 8 с — с запасом под медленный CI.
TRACKER_WINDOW_MS = 8_000


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _suppress_overlays(page: Page):
    """Как в conftest, но БЕЗ `.cookie-banner` — его здесь и проверяем."""
    selectors = ", ".join(
        s.strip() for s in _OVERLAY_SELECTORS.split(",") if "cookie" not in s
    )
    page.add_init_script(_HIDE_OVERLAYS_SCRIPT.replace(_OVERLAY_SELECTORS, selectors))
    yield


@pytest.fixture
def fresh_visit(page: Page) -> Page:
    """Новый посетитель на главной: согласия ещё нет, баннер на экране.

    Контекст у каждого теста свой, и cookie/localStorage в нём пустые."""
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(BANNER)).to_be_visible(timeout=20_000)
    return page


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _consent_cookie(page: Page) -> dict | None:
    """Категории из cookie `cookie_consent` (None, если cookie нет)."""
    for c in page.context.cookies():
        if c["name"] == CONSENT_KEY:
            return json.loads(unquote(c["value"]))["categories"]
    return None


def _consent_storage(page: Page) -> dict | None:
    """Категории из localStorage `cookie_consent` (None, если записи нет)."""
    raw = page.evaluate(f"() => localStorage.getItem('{CONSENT_KEY}')")
    return json.loads(raw)["categories"] if raw else None


def _assert_consent(page: Page, expected: dict) -> None:
    """Выбор записан одинаково и в cookie, и в localStorage."""
    cookie, storage = _consent_cookie(page), _consent_storage(page)
    assert cookie == expected, f"cookie {CONSENT_KEY}: {cookie}, ждали {expected}"
    assert storage == expected, f"localStorage {CONSENT_KEY}: {storage}, ждали {expected}"


def _all(value: bool) -> dict:
    """Все необязательные категории = value, «Необходимые» всегда true."""
    return {"necessary": True, "analytics": value, "marketing": value, "functional": value}


def _click_until_hidden(page: Page, button: str, target: str = BANNER) -> None:
    """Клик по кнопке, пока `target` не скроется.

    Первый клик сразу после загрузки может потеряться в гонке с гидрацией
    (см. conftest) — тогда кнопка видна, а обработчика ещё нет."""
    for attempt in range(3):
        page.locator(button).first.click()
        try:
            expect(page.locator(target)).to_be_hidden(timeout=5_000)
            return
        except AssertionError:
            if attempt == 2:
                raise


def _open_settings_from_banner(page: Page) -> None:
    for attempt in range(3):
        page.locator(BTN_SETTINGS).click()
        try:
            expect(page.locator(SETTINGS_DIALOG)).to_be_visible(timeout=5_000)
            return
        except AssertionError:
            if attempt == 2:
                raise


def _row(page: Page, name: str):
    return page.locator(SETTINGS_ROW).filter(
        has=page.locator(ROW_NAME, has_text=name)
    )


def _toggle_states(page: Page) -> dict:
    """{ключ категории: включена?} по чекбоксам окна настроек."""
    states = {}
    for name, key in CATEGORIES.items():
        states[key] = _row(page, name).locator("input").is_checked()
    return states


def _settings_button(page: Page, text: str):
    return page.locator(SETTINGS_BTN, has_text=text)


def _tracker_requests(page: Page, action) -> list[str]:
    """Выполнить `action` и вернуть запросы к трекерам за окно ожидания."""
    hits: list[str] = []
    page.on("request", lambda r: hits.append(r.url) if TRACKERS.search(r.url) else None)
    action()
    page.wait_for_timeout(TRACKER_WINDOW_MS)
    return sorted({h.split("?")[0] for h in hits})


def _expect_banner_stays_hidden(page: Page) -> None:
    """Баннер на месте, но скрыт.

    Голый `to_be_hidden` сразу после reload/goto истинен и до монтирования
    баннера, и при переименованном классе. После выбора баннер остаётся в DOM
    со `display: none` (см. шапку) — поэтому сначала ждём его в DOM.
    """
    expect(page.locator(BANNER)).to_be_attached(timeout=10_000)
    expect(page.locator(BANNER)).to_be_hidden(timeout=10_000)


def _reload(page: Page) -> None:
    page.reload(wait_until="domcontentloaded", timeout=60_000)


# ===========================================================================
# Баннер
# ===========================================================================
def test_banner_shown_to_new_visitor(fresh_visit: Page):
    """Новому посетителю показан баннер с тремя кнопками и ссылкой на политику,
    а согласие ещё нигде не записано."""
    page = fresh_visit

    expect(page.locator(BANNER_TITLE)).to_have_text(re.compile(r"cookie", re.I))
    for button in (BTN_ACCEPT, BTN_REJECT, BTN_SETTINGS):
        expect(page.locator(button)).to_be_visible()
    expect(page.locator(BANNER_POLICY_LINK)).to_have_attribute(
        "href", re.compile(r"/cookie-policy$")
    )

    assert _consent_cookie(page) is None, "Согласие записано в cookie до выбора посетителя"
    assert _consent_storage(page) is None, "Согласие записано в localStorage до выбора посетителя"


def test_no_trackers_before_consent(page: Page):
    """До выбора в баннере не уходит ни одного запроса к аналитике и рекламе."""
    hits = _tracker_requests(
        page, lambda: page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    )
    expect(page.locator(BANNER)).to_be_visible(timeout=20_000)

    assert not hits, f"Трекеры загружены ДО согласия: {hits}"


def test_accept_all_saves_consent_and_hides_banner(fresh_visit: Page):
    """«Принять все»: все категории включены, баннер не возвращается ни после
    перезагрузки, ни на другой странице."""
    page = fresh_visit

    _click_until_hidden(page, BTN_ACCEPT)
    _assert_consent(page, _all(True))

    _reload(page)
    _expect_banner_stays_hidden(page)
    page.goto(OTHER_URL, wait_until="domcontentloaded", timeout=60_000)
    _expect_banner_stays_hidden(page)


def test_accept_all_enables_trackers(fresh_visit: Page):
    """После «Принять все» аналитика реально загружается.

    Контрольный тест: доказывает, что перехват запросов в тестах «трекеров
    нет» работает и они умеют краснеть."""
    page = fresh_visit
    _click_until_hidden(page, BTN_ACCEPT)

    hits = _tracker_requests(page, lambda: _reload(page))

    assert hits, "После «Принять все» не загрузился ни один трекер аналитики/рекламы"


def test_reject_all_saves_only_necessary_and_blocks_trackers(fresh_visit: Page):
    """«Отклонить все»: включены только «Необходимые», баннер скрыт, и после
    перезагрузки ни одного запроса к трекерам."""
    page = fresh_visit

    _click_until_hidden(page, BTN_REJECT)
    _assert_consent(page, _all(False))

    hits = _tracker_requests(page, lambda: _reload(page))

    _expect_banner_stays_hidden(page)
    assert not hits, f"После «Отклонить все» трекеры всё равно загружены: {hits}"


def test_banner_policy_link_opens_cookie_policy(fresh_visit: Page):
    """Ссылка из баннера открывает страницу политики cookie."""
    page = fresh_visit

    page.locator(BANNER_POLICY_LINK).click()

    expect(page).to_have_url(re.compile(r"/ru/cookie-policy/?$"), timeout=30_000)
    expect(page.locator("h1")).to_be_visible(timeout=20_000)


# ===========================================================================
# Окно настроек
# ===========================================================================
def test_settings_modal_lists_categories(fresh_visit: Page):
    """«Настройки»: четыре категории; «Необходимые» включены и заблокированы,
    остальные по умолчанию выключены."""
    page = fresh_visit
    _open_settings_from_banner(page)

    names = [n.strip() for n in page.locator(f"{SETTINGS_ROW} {ROW_NAME}").all_text_contents()]
    assert names == list(CATEGORIES), f"Категории в окне настроек: {names}"

    necessary = _row(page, "Необходимые").locator("input")
    expect(necessary).to_be_checked()
    expect(necessary).to_be_disabled()

    assert _toggle_states(page) == _all(False), (
        f"Необязательные категории включены по умолчанию: {_toggle_states(page)}"
    )


def test_save_custom_settings_persists(fresh_visit: Page):
    """Включить только «Аналитику» → «Сохранить настройки»: записано именно это,
    и после перезагрузки окно из футера показывает тот же выбор."""
    page = fresh_visit
    _open_settings_from_banner(page)

    _row(page, "Аналитика").locator(ROW_TOGGLE).click()
    expect(_row(page, "Аналитика").locator("input")).to_be_checked()
    _click_until_hidden(page, f'{SETTINGS_BTN}:has-text("Сохранить")', SETTINGS_DIALOG)

    expected = {"necessary": True, "analytics": True, "marketing": False, "functional": False}
    expect(page.locator(BANNER)).to_be_hidden(timeout=10_000)
    _assert_consent(page, expected)

    _reload(page)
    _expect_banner_stays_hidden(page)
    page.locator(FOOTER_SETTINGS_BTN).first.click()
    expect(page.locator(SETTINGS_DIALOG)).to_be_visible(timeout=10_000)

    assert _toggle_states(page) == expected, (
        f"После перезагрузки окно показывает {_toggle_states(page)}, а сохраняли {expected}"
    )


@pytest.mark.parametrize(
    "button, expected",
    [("Принять все", True), ("Отклонить все", False)],
    ids=["accept_all", "reject_all"],
)
def test_settings_modal_bulk_buttons(fresh_visit: Page, button: str, expected: bool):
    """Кнопки «Принять все» / «Отклонить все» внутри окна настроек работают
    так же, как в баннере, и закрывают и окно, и баннер."""
    page = fresh_visit
    _open_settings_from_banner(page)

    _click_until_hidden(page, f'{SETTINGS_BTN}:has-text("{button}")', SETTINGS_DIALOG)

    expect(page.locator(BANNER)).to_be_hidden(timeout=10_000)
    _assert_consent(page, _all(expected))


def test_settings_close_without_saving_keeps_banner(fresh_visit: Page):
    """Крестик закрывает окно, ничего не сохраняя: баннер остаётся, согласия нет."""
    page = fresh_visit
    _open_settings_from_banner(page)

    _row(page, "Маркетинг").locator(ROW_TOGGLE).click()
    page.locator(SETTINGS_CLOSE).click()

    expect(page.locator(SETTINGS_DIALOG)).to_be_hidden(timeout=10_000)
    expect(page.locator(BANNER)).to_be_visible()
    assert _consent_cookie(page) is None, "Крестик сохранил выбор в cookie"
    assert _consent_storage(page) is None, "Крестик сохранил выбор в localStorage"


def test_footer_settings_changes_earlier_choice(fresh_visit: Page):
    """Передумать через «Настройки cookie» в футере: после «Принять все»
    выключить «Маркетинг» и сохранить — согласие обновилось."""
    page = fresh_visit
    _click_until_hidden(page, BTN_ACCEPT)

    page.locator(FOOTER_SETTINGS_BTN).first.click()
    expect(page.locator(SETTINGS_DIALOG)).to_be_visible(timeout=10_000)
    assert _toggle_states(page) == _all(True), (
        f"После «Принять все» окно показывает не всё включённым: {_toggle_states(page)}"
    )

    _row(page, "Маркетинг").locator(ROW_TOGGLE).click()
    _click_until_hidden(page, f'{SETTINGS_BTN}:has-text("Сохранить")', SETTINGS_DIALOG)

    _assert_consent(
        page, {"necessary": True, "analytics": True, "marketing": False, "functional": True}
    )
