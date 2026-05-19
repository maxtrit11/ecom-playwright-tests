"""Тесты поп-апа Восстановление пароля"""

import pytest
from playwright.sync_api import Page, expect


# ---------------------------------------------------------------------------
# Хелпер: открыть поп-ап восстановления пароля
# ---------------------------------------------------------------------------
def open_recovery_popup(page: Page) -> None:
    page.locator(".btn__action.btn__auth").click(force=True)
    page.locator(".modal__authentification__ecom-content").first.wait_for(
        state="visible", timeout=10_000
    )
    page.get_by_text("Восстановить").first.click()
    expect(
        page.get_by_role("heading", name="Восстановление")
    ).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# Фикстура: перейти на главную перед каждым тестом
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def navigate_home(page: Page):
    page.goto("/ru")
    page.wait_for_load_state("networkidle")


# ===========================================================================
# Кейс 1: Открыть поп-ап Восстановление пароля
# ===========================================================================
def test_open_recovery_popup(page: Page):
    """Открытие поп-апа восстановления пароля."""
    page.locator(".btn__action.btn__auth").click(force=True)
    page.locator(".modal__authentification__ecom-content").first.wait_for(
        state="visible", timeout=10_000
    )

    # Нажать на кнопку «Восстановить»
    page.get_by_text("Восстановить").first.click()

    # Открывается поп-ап восстановления пароля
    expect(
        page.get_by_role("heading", name="Восстановление")
    ).to_be_visible(timeout=10_000)


# ===========================================================================
# Кейс 2: Отображение ошибки для пустого поля
# ===========================================================================
def test_empty_email_shows_validation_error(page: Page):
    """Отображение ошибки для пустого поля Email."""
    open_recovery_popup(page)

    # Нажать на кнопку «Отправить» не заполняя данные
    page.get_by_text("Отправить").click()

    # Отображается сообщение «Это обязательное поле»
    modal = page.locator(".modal__authentification__ecom-content").first
    validations = modal.locator(".validation:visible")
    expect(validations).to_have_count(1)
    expect(validations).to_contain_text("Это обязательное поле")


# ===========================================================================
# Кейс 3: Закрыть поп-ап нажатием на кнопку X
# ===========================================================================
def test_close_recovery_popup_by_x_button(page: Page):
    """Закрытие поп-апа восстановления пароля нажав на кнопку X."""
    open_recovery_popup(page)

    # Нажать на кнопку «X»
    modal = page.locator(".modal__authentification__ecom-content").first
    modal.locator(".btn__close").first.click()

    # Поп-ап закрывается
    expect(modal).not_to_be_visible()


# ===========================================================================
# Кейс 4: Положительный сценарий восстановления пароля
# ===========================================================================
def test_successful_password_recovery(page: Page):
    """Успешная отправка письма для восстановления пароля."""
    open_recovery_popup(page)

    # Ввести почту зарегистрированного пользователя
    page.locator('input[placeholder="Введи e-mail адрес"]').first.fill(
        "maxim.turcan1@gmail.com"
    )

    # Нажать на кнопку «Отправить»
    page.get_by_text("Отправить").click()

    # Отображается сообщение об отправке письма
    expect(
        page.get_by_text("отправлено письмо с инструкциями для восстановления пароля")
    ).to_be_visible(timeout=10_000)
