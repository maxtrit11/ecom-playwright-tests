"""Тесты удаления аккаунта (Testiny 150, 154)

Кейс 155 «Удаление аккаунта: подтверждение» здесь СОЗНАТЕЛЬНО НЕ автоматизирован:
кнопка «Да, хочу удалить» безвозвратно сносит учётку, а stage-аккаунт общий —
после первого же прогона отвалились бы все остальные тесты кабинета. Такой
кейс нужен либо одноразовый пользователь, либо ручная проверка.

Ниже проверяем всё, что можно проверить без разрушения: открытие подтверждения,
его текст, и что каждый способ ОТМЕНЫ действительно оставляет аккаунт на месте.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import login_via_popup, load_users, open_account_page

USERS, _USERS_SKIP = load_users()

pytestmark = [
    pytest.mark.requires_auth,
    pytest.mark.skipif(_USERS_SKIP is not None, reason=_USERS_SKIP or ""),
]

EMAIL = USERS["loginUser"]["email"]
PASSWORD = USERS["loginUser"]["password"]

MODAL = ".modal__authentification__ecom-content"
# Класс `request--delete-profile` носит и соседняя «Выйти со всех устройств»
# (у неё ещё `request--logout-all`) — без исключения селектор держался только
# на порядке кнопок в DOM.
BTN_DELETE_ACCOUNT = ".request--delete-profile:not(.request--logout-all)"
BTN_CONFIRM = "Да, хочу удалить"  # НИКОГДА не кликать в тестах
BTN_CANCEL = "Отменить"

# Модалка закрывается не мгновенно: замерено вживую — «Отменить» убирает её из
# DOM примерно за 4.3s. Дефолтные 5s expect'а дают флак на ровном месте.
CLOSE_TIMEOUT_MS = 20_000


@pytest.fixture
def account(page: Page):
    """Вход в кабинет + страница «Личные данные»."""
    assert login_via_popup(page, EMAIL, PASSWORD), f"Не удалось войти под {EMAIL}"

    open_account_page(page)
    expect(page).to_have_url(re.compile(r"account"), timeout=15_000)
    expect(page.locator(BTN_DELETE_ACCOUNT).first).to_be_visible(timeout=15_000)
    return page


def open_delete_confirmation(page: Page):
    """Нажать «Удалить аккаунт» и дождаться поп-апа подтверждения."""
    page.locator(BTN_DELETE_ACCOUNT).first.click()
    modal = page.locator(MODAL).first
    modal.wait_for(state="visible", timeout=15_000)
    expect(modal.locator("h2")).to_contain_text(
        re.compile("удаление аккаунта", re.I)
    )
    return modal


def assert_account_alive(page: Page) -> None:
    """Аккаунт на месте: страница кабинета открыта, пользователь авторизован.

    Проверяем ПОСЛЕ перезагрузки: без неё «всё хорошо» показывала бы просто
    незакрытая вкладка, даже если бы запрос на удаление всё-таки ушёл.
    """
    page.reload(wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(r"account"), timeout=15_000)
    expect(page.locator(".btn__action.btn__auth")).to_contain_text(
        "Кабинет", timeout=15_000
    )
    expect(page.locator('input[placeholder="Ваше имя"]')).to_be_enabled(
        timeout=15_000
    )


# ===========================================================================
# Кейс 150: Личные данные — переход к удалению аккаунта
# ===========================================================================
def test_delete_account_confirmation_opens(account: Page):
    """«Удалить аккаунт» открывает подтверждение с предупреждением и 2 кнопками."""
    page = account
    modal = open_delete_confirmation(page)

    # Текст предупреждения о безвозвратности
    expect(modal).to_contain_text(re.compile("точно хотите удалить", re.I))
    expect(modal).to_contain_text(re.compile("безвозвратн", re.I))

    # Обе кнопки на месте: подтверждение и отмена
    actions = modal.locator(".modal__authentification__ecom-content-form-actions")
    expect(actions.get_by_role("button", name=BTN_CONFIRM)).to_be_visible()
    expect(actions.get_by_role("button", name=BTN_CANCEL)).to_be_visible()

    # Уходим по «Отменить» — подтверждение не нажимаем никогда
    actions.get_by_role("button", name=BTN_CANCEL).click()


# ===========================================================================
# Кейс 154: Удаление аккаунта — отмена
# ===========================================================================
def test_delete_account_cancel(account: Page):
    """Клик «Отменить» закрывает поп-ап, аккаунт остаётся рабочим."""
    page = account
    modal = open_delete_confirmation(page)

    modal.get_by_role("button", name=BTN_CANCEL).click()

    expect(page.locator(MODAL)).to_have_count(0, timeout=CLOSE_TIMEOUT_MS)
    assert_account_alive(page)


# ===========================================================================
# Дополнительно: отмена крестиком (в Testiny кейса нет)
# ===========================================================================
def test_delete_account_close_by_x(account: Page):
    """Крестик закрывает подтверждение так же безопасно, как «Отменить»."""
    page = account
    modal = open_delete_confirmation(page)

    modal.locator(".btn__close").click()

    expect(page.locator(MODAL)).to_have_count(0, timeout=CLOSE_TIMEOUT_MS)
    assert_account_alive(page)


# ===========================================================================
# Дополнительно: отмена кликом вне поп-апа (в Testiny кейса нет)
# ===========================================================================
def test_delete_account_close_by_click_outside(account: Page):
    """Клик мимо поп-апа закрывает его и НЕ удаляет аккаунт.

    Самый опасный из способов закрытия: если бы клик по затемнению трактовался
    как подтверждение, учётка исчезала бы от случайного промаха.
    """
    page = account
    modal = open_delete_confirmation(page)

    # Кликаем слева от карточки поп-апа, по затемнённой области
    box = modal.bounding_box()
    page.mouse.click(max(box["x"] / 2, 10), box["y"] + box["height"] / 2)

    expect(page.locator(MODAL)).to_have_count(0, timeout=CLOSE_TIMEOUT_MS)
    assert_account_alive(page)
