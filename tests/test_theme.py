"""Тесты переключателя тёмной / светлой темы (шапка, «Тёмная тема»).

Поведение проверено вживую 2026-10-12 (MCP-браузер + чистые контексты):

- Переключатель `.switch__theme`: скрытый `input#checkbox` и
  `label.switch__label` с подписью «Тёмная тема» / «Светлая тема» (подпись
  называет тему, В КОТОРУЮ переключит клик). Кликаем по label.
- Тема — класс на `<body>`: `light-theme` / `dark-theme`. Выбор хранится в
  cookie `user-theme` (ставится сразу при первом визите = `light-theme`).
- Светлая: фон body rgb(255,255,255). Тёмная: фон rgb(41,41,41), текст белый,
  логотип в шапке подменяется на светлый вариант.
- Системную тему сайт НЕ учитывает: при `prefers-color-scheme: dark` новый
  посетитель всё равно получает светлую. Это решение дизайна, не баг.

Особенности, из-за которых проверки устроены именно так:
- Тему применяет клиентский JS, а не сервер: после перезагрузки страница
  сначала рисуется светлой и становится тёмной после гидрации (1-3 с).
  Поэтому тему после reload ЖДЁМ, а не читаем сразу.
- После перезагрузки `input#checkbox` снят, хотя тема тёмная, — внутреннее
  состояние чекбокса с темой расходится. На поведение это не влияет (клик
  всё равно переключает тему), поэтому чекбокс не проверяем, а отдельный тест
  убеждается, что ОДИН клик после перезагрузки возвращает светлую тему.
"""

import re

import pytest
from playwright.sync_api import Page, expect

HOME_URL = "/ru"
OTHER_PAGES = ["/ru/brands", "/ro"]

SWITCH = ".switch__theme"
SWITCH_LABEL = f"{SWITCH} label.switch__label"
SWITCH_TEXT = f"{SWITCH_LABEL} span"
HEADER_LOGO = "header img, .header img"

THEME_COOKIE = "user-theme"
LIGHT, DARK = "light-theme", "dark-theme"

# Порог яркости фона: светлая тема ~255, тёмная ~41.
DARK_LUMINANCE_MAX = 80
LIGHT_LUMINANCE_MIN = 200

# Тема после reload применяется после гидрации — даём запас под медленный CI.
THEME_APPLY_TIMEOUT = 20_000


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _theme_class(theme: str) -> re.Pattern:
    return re.compile(rf"(^|\s){theme}(\s|$)")


def _expect_theme(page: Page, theme: str, timeout: int = THEME_APPLY_TIMEOUT) -> None:
    """На body нужный класс темы и нет противоположного."""
    other = DARK if theme == LIGHT else LIGHT
    body = page.locator("body")
    expect(body).to_have_class(_theme_class(theme), timeout=timeout)
    expect(body).not_to_have_class(_theme_class(other))


def _body_luminance(page: Page) -> float:
    """Яркость фона body по формуле ITU-R BT.601 (0 — чёрный, 255 — белый)."""
    return page.evaluate(
        """() => {
            const [r, g, b] = getComputedStyle(document.body).backgroundColor
                .match(/\\d+/g).map(Number);
            return 0.299 * r + 0.587 * g + 0.114 * b;
        }"""
    )


def _theme_cookie(page: Page) -> str | None:
    for c in page.context.cookies():
        if c["name"] == THEME_COOKIE:
            return c["value"]
    return None


def _toggle(page: Page, to: str) -> None:
    """Клик по переключателю, пока тема не станет `to`.

    Первый клик сразу после загрузки может потеряться в гонке с гидрацией
    (см. conftest): label виден, а обработчика ещё нет. Повторяем только
    пока тема НЕ сменилась — лишний клик вернул бы её обратно."""
    for attempt in range(3):
        page.locator(SWITCH_LABEL).first.click()
        try:
            expect(page.locator("body")).to_have_class(_theme_class(to), timeout=5_000)
            return
        except AssertionError:
            if attempt == 2:
                raise


def _open(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(SWITCH_LABEL).first).to_be_visible(timeout=20_000)


@pytest.fixture
def home(page: Page) -> Page:
    """Новый посетитель на главной (свой контекст — cookie темы ещё нет)."""
    _open(page, HOME_URL)
    return page


@pytest.fixture
def home_dark(home: Page) -> Page:
    """Главная, тёмная тема включена переключателем."""
    _toggle(home, DARK)
    return home


# ===========================================================================
# Тесты
# ===========================================================================
def test_default_theme_is_light(home: Page):
    """Новый посетитель видит светлую тему; переключатель предлагает «Тёмная тема»."""
    page = home

    _expect_theme(page, LIGHT)
    assert _body_luminance(page) >= LIGHT_LUMINANCE_MIN, (
        f"Светлая тема, а фон тёмный: яркость {_body_luminance(page):.0f}"
    )
    expect(page.locator(SWITCH_TEXT).first).to_have_text(re.compile(r"Т[её]мная тема"))
    assert _theme_cookie(page) == LIGHT, f"cookie {THEME_COOKIE} = {_theme_cookie(page)!r}"


def test_toggle_switches_to_dark(home: Page):
    """Клик включает тёмную тему: класс, фон, подпись, cookie и логотип."""
    page = home
    logo_light = page.locator(HEADER_LOGO).first.get_attribute("src")

    _toggle(page, DARK)

    _expect_theme(page, DARK)
    assert _body_luminance(page) <= DARK_LUMINANCE_MAX, (
        f"Класс dark-theme есть, а фон светлый: яркость {_body_luminance(page):.0f}"
    )
    expect(page.locator(SWITCH_TEXT).first).to_have_text("Светлая тема")
    assert _theme_cookie(page) == DARK, f"cookie {THEME_COOKIE} = {_theme_cookie(page)!r}"
    logo_dark = page.locator(HEADER_LOGO).first.get_attribute("src")
    assert logo_dark != logo_light, (
        f"Логотип в шапке не сменился под тёмную тему: {logo_dark}"
    )


def test_dark_theme_persists_after_reload(home_dark: Page):
    """Тёмная тема сохраняется после перезагрузки."""
    page = home_dark

    page.reload(wait_until="domcontentloaded", timeout=60_000)

    _expect_theme(page, DARK)
    assert _body_luminance(page) <= DARK_LUMINANCE_MAX
    assert _theme_cookie(page) == DARK


@pytest.mark.parametrize("url", OTHER_PAGES, ids=["brands", "ro_home"])
def test_dark_theme_kept_on_other_pages(home_dark: Page, url: str):
    """Тёмная тема держится при переходе на другие страницы и на другую локаль."""
    page = home_dark

    _open(page, url)

    _expect_theme(page, DARK)
    assert _body_luminance(page) <= DARK_LUMINANCE_MAX


def test_one_click_after_reload_returns_light(home_dark: Page):
    """После перезагрузки в тёмной теме ОДИН клик возвращает светлую.

    Страховка от рассинхрона: после reload скрытый чекбокс снят, хотя тема
    тёмная. Сейчас клик всё равно переключает тему верно; если обработчик
    начнёт читать чекбокс, первый клик оставит тёмную — тест это поймает."""
    page = home_dark
    page.reload(wait_until="domcontentloaded", timeout=60_000)
    _expect_theme(page, DARK)

    page.locator(SWITCH_LABEL).first.click()

    _expect_theme(page, LIGHT, timeout=10_000)
    assert _theme_cookie(page) == LIGHT, f"cookie {THEME_COOKIE} = {_theme_cookie(page)!r}"
    expect(page.locator(SWITCH_TEXT).first).to_have_text(re.compile(r"Т[её]мная тема"))


def test_theme_from_cookie_on_first_visit(page: Page, base_url: str):
    """Сохранённый выбор (cookie `user-theme=dark-theme`) применяется с первой
    же загрузки — как у вернувшегося посетителя."""
    page.context.add_cookies(
        [{"name": THEME_COOKIE, "value": DARK, "url": base_url}]
    )

    _open(page, HOME_URL)

    _expect_theme(page, DARK)
    assert _body_luminance(page) <= DARK_LUMINANCE_MAX
