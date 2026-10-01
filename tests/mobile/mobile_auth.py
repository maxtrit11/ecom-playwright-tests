"""Вход в кабинет на телефоне — общий хелпер для mobile/account/*.

Десктопный `login_via_popup` (корневой conftest) на телефоне не работает: он
ждёт видимую кнопку шапки `.btn__action.btn__auth`, а в мобильной вёрстке она
остаётся в DOM размером 0×0. Вход на телефоне — пункт «Войти» нижнего бара
`.mobile__bar`; после входа тот же пункт превращается в «Кабинет» (проверено
01.10.2026 в эмуляции Pixel 7). Поп-ап авторизации тот же
`.modal__authentification__ecom-content`, только во весь экран.

Контракт как у десктопного хелпера: True — вошли, False — вход не прошёл
(тестам смены пароля нужно утверждать, что старый пароль не подходит).
"""

import re

from playwright.sync_api import Page, expect

from conftest import AUTH_MODAL, EMAIL_INPUT, goto_resilient, wait_hydrated

BAR_ITEM = ".mobile__bar .bar__item"
RE_BAR_AUTH = re.compile(r"Войти|Кабинет|Intr|Cabinet", re.I)
RE_CABINET = re.compile(r"Кабинет|Cabinet", re.I)

_LOGIN_RESULT_JS = """
() => {
  const b = [...document.querySelectorAll('%s')].find(e => /Кабинет|Cabinet/i.test(e.textContent));
  if (b) return 'ok';
  const e = document.querySelector('%s-form-error');
  if (e && e.offsetParent !== null && e.innerText.trim()) return 'error';
  return null;
}
""" % (BAR_ITEM, AUTH_MODAL)


def bar_auth_item(page: Page):
    """Пункт нижнего бара «Войти» / «Кабинет»."""
    return page.locator(BAR_ITEM).filter(has_text=RE_BAR_AUTH).first


def open_auth_modal_mobile(page: Page):
    """Тапнуть «Войти» в нижнем баре и вернуть локатор поп-апа.

    С повтором: первый тап после гидрации регулярно теряется (как и клик по
    шапке на десктопе).
    """
    item = bar_auth_item(page)
    item.wait_for(state="visible", timeout=15_000)
    modal = page.locator(AUTH_MODAL).first
    for _ in range(3):
        item.tap()
        try:
            modal.wait_for(state="visible", timeout=5_000)
            return modal
        except Exception:
            continue
    modal.wait_for(state="visible", timeout=5_000)
    return modal


def login_via_bar(page: Page, email: str, password: str) -> bool:
    """Войти через нижний бар. True — вошли, False — вход не прошёл."""
    goto_resilient(page, "/ru")
    modal = open_auth_modal_mobile(page)

    page.locator(EMAIL_INPUT).first.fill(email)
    modal.locator('input[type="password"]').first.fill(password)
    modal.locator('button[type="submit"]').first.tap()

    try:
        outcome = page.wait_for_function(_LOGIN_RESULT_JS, timeout=20_000).json_value()
    except Exception:
        return False
    if outcome != "ok":
        return False

    # Успешный вход перезагружает страницу — ждём гидрацию, иначе следующий
    # тап по бару теряется.
    wait_hydrated(page)
    return True


BAR_CABINET_BTN = ".mobile__bar button.btn__auth.bar"
BAR_CABINET_MENU = ".mobile__bar .header__items__auth__list"


def _bar_says_cabinet(page: Page) -> bool:
    try:
        return bool(page.evaluate(
            "(sel) => [...document.querySelectorAll(sel)].some(e => /Кабинет|Cabinet/i.test(e.textContent))",
            BAR_ITEM,
        ))
    except Exception:
        return False


def open_cabinet_menu(page: Page):
    """Тапнуть «Кабинет» в баре и вернуть раскрытый список над баром.

    У залогиненного пункт бара — `div.bar__item` с кнопкой `.btn__auth.bar`;
    тап рисует (v-if) список «Личные данные / История заказов / Выйти»
    `.header__items__auth__list`. Первый тап после загрузки теряется (гонка с
    гидрацией, проверено 01.10.2026: 1-й — списка нет, 2-й — есть), поэтому
    повторяем, пока список не появится. Повторять вслепую нельзя: открытый
    список сам перекрывает кнопку, и лишний тап уходит в него.
    """
    menu = page.locator(BAR_CABINET_MENU)
    for _ in range(3):
        page.locator(BAR_CABINET_BTN).tap()
        try:
            expect(menu).to_be_visible(timeout=3_000)
            return menu
        except AssertionError:
            continue
    expect(menu).to_be_visible(timeout=3_000)
    return menu


def logout_via_bar(page: Page) -> bool:
    """Выйти через меню «Кабинет» нижнего бара. True — вышли."""
    try:
        open_cabinet_menu(page).get_by_role("button", name="Выйти", exact=True).tap(
            timeout=10_000
        )
        page.wait_for_function(
            "(sel) => [...document.querySelectorAll(sel)].some(e => /Войти|Intr/i.test(e.textContent))",
            arg=BAR_ITEM,
            timeout=15_000,
        )
        return True
    except Exception:
        return False


def logout_mobile(page: Page) -> None:
    """Гарантированно оставить браузер гостем (мобильный аналог `logout`).

    Сначала честный выход через бар; не вышло — сносим сессию принудительно:
    задача хелпера — состояние «гость», а не проверка выхода (её делает
    отдельный тест).
    """
    if not _bar_says_cabinet(page) or logout_via_bar(page):
        return
    page.context.clear_cookies()
    try:
        page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    except Exception:
        pass


def expect_logged_in(page: Page, timeout: int = 15_000) -> None:
    """В нижнем баре виден пункт «Кабинет» — сессия есть."""
    expect(page.locator(BAR_ITEM).filter(has_text=RE_CABINET).first).to_be_visible(
        timeout=timeout
    )
