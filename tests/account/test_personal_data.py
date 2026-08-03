"""Тесты страницы Личные данные"""

import json
import re
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# Загрузка данных пользователей
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
USERS = json.loads((FIXTURES_DIR / "users.json").read_text(encoding="utf-8"))

NAME_INPUT = 'input[placeholder="Ваше имя"]'
SURNAME_INPUT = 'input[placeholder="Ваше фамилия"]'


def click_save_and_wait(page: Page) -> None:
    """Нажать «Изменить» и дождаться завершения сохранения."""
    btn = page.get_by_role("button", name="Изменить", exact=True)
    btn.scroll_into_view_if_needed()
    btn.click()
    # Ждём отправки запроса и обновления страницы
    page.wait_for_load_state("networkidle")
    # Ждём пока форма снова станет доступной
    expect(page.locator(NAME_INPUT)).to_be_enabled(timeout=15_000)


# ---------------------------------------------------------------------------
# Фикстура: логин и переход на страницу «Личные данные»
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def login_and_open_personal_data(page: Page, hydrated):
    # `load`/networkidle часто не достигаются на стейдже (фоновые запросы)
    page.goto("/ru", wait_until="domcontentloaded", timeout=60_000)
    page.locator(".btn__action.btn__auth").wait_for(state="visible", timeout=15_000)

    # Открыть поп-ап авторизации
    page.locator(".btn__action.btn__auth").click(force=True)
    page.locator(".modal__authentification__ecom-content").first.wait_for(
        state="visible", timeout=10_000
    )

    # Ввести email и пароль
    page.locator('input[placeholder="Введи e-mail адрес"]').first.fill(
        "turcan.maxim@alsodev.com"
    )
    page.locator(".modal__authentification__ecom-content").first.locator(
        'input[type="password"]'
    ).fill(USERS["validUser"]["password"])
    page.get_by_text("Войдите в аккаунт").first.click()

    # Ждём успешный логин — модалка закрывается
    expect(
        page.locator(".modal__authentification__ecom-content").first
    ).not_to_be_visible(timeout=10_000)
    expect(page.locator(".btn__action.btn__auth")).to_contain_text(
        "Кабинет", timeout=10_000
    )

    # Успешный логин делает полный редирект — шапка гидрируется заново, и клик
    # по «Кабинет» сразу после логина теряется (пункт «Личные данные» не всплывает).
    hydrated(page)

    # Переход в Личные данные
    page.locator(".btn__action.btn__auth").click()
    page.get_by_text("Личные данные").click()
    expect(page).to_have_url(re.compile(r"account"), timeout=10_000)

    # Ждём загрузки формы
    expect(page.locator(NAME_INPUT)).to_be_enabled(timeout=15_000)


# ===========================================================================
# Кейс 1: Сохранить личные данные не внося изменений
# ===========================================================================
def test_save_without_changes(page: Page):
    """Сохранить личные данные не внося изменений."""
    # Запоминаем текущие значения полей
    name_val = page.locator(NAME_INPUT).input_value()
    surname_val = page.locator(SURNAME_INPUT).input_value()

    # Кликаем «Изменить» без внесения изменений
    click_save_and_wait(page)

    # Проверяем что данные остались без изменений
    expect(page.locator(NAME_INPUT)).to_have_value(name_val)
    expect(page.locator(SURNAME_INPUT)).to_have_value(surname_val)


# ===========================================================================
# Кейс 2: Положительный сценарий — изменить личные данные
# ===========================================================================
def test_change_personal_data(page: Page):
    """Положительный сценарий — изменить личные данные."""
    # Запоминаем исходные значения для восстановления
    original_name = page.locator(NAME_INPUT).input_value()
    original_surname = page.locator(SURNAME_INPUT).input_value()

    suffix = str(int(time.time() * 1000))[-4:]
    new_name = f"TestName{suffix}"
    new_surname = f"TestSurname{suffix}"

    # Вносим изменения
    page.locator(NAME_INPUT).fill(new_name)
    page.locator(SURNAME_INPUT).fill(new_surname)

    # Проверяем что в полях отображаются введённые данные
    expect(page.locator(NAME_INPUT)).to_have_value(new_name)
    expect(page.locator(SURNAME_INPUT)).to_have_value(new_surname)

    # Кликаем «Изменить» и ждём ответа сервера
    click_save_and_wait(page)

    # Проверяем что новые значения отображаются после сохранения
    expect(page.locator(NAME_INPUT)).to_have_value(new_name, timeout=10_000)
    expect(page.locator(SURNAME_INPUT)).to_have_value(new_surname, timeout=10_000)

    # Обновляем страницу и проверяем что изменения сохранились
    page.reload()
    expect(page.locator(NAME_INPUT)).to_be_enabled(timeout=15_000)
    expect(page.locator(NAME_INPUT)).to_have_value(new_name)
    expect(page.locator(SURNAME_INPUT)).to_have_value(new_surname)

    # Восстанавливаем исходные данные
    page.locator(NAME_INPUT).fill(original_name)
    page.locator(SURNAME_INPUT).fill(original_surname)
    click_save_and_wait(page)


# ===========================================================================
# Кейс 3: Ошибка при сохранении с пустыми обязательными полями
# ===========================================================================
def test_empty_required_fields_show_error(page: Page):
    """Ошибка при сохранении с пустыми обязательными полями."""
    # Очищаем обязательные поля
    page.locator(NAME_INPUT).fill("")
    page.locator(SURNAME_INPUT).fill("")

    # Проверяем что поля отображаются пустыми
    expect(page.locator(NAME_INPUT)).to_have_value("")
    expect(page.locator(SURNAME_INPUT)).to_have_value("")

    # Кликаем «Изменить»
    btn = page.get_by_role("button", name="Изменить", exact=True)
    btn.scroll_into_view_if_needed()
    btn.click()

    # Под обязательными полями отображаются сообщения об ошибке
    validations = page.locator(".validation")
    expect(validations.first).to_be_visible(timeout=10_000)

    # Данные не сохраняются — после перезагрузки поля содержат прежние значения
    page.reload()
    expect(page.locator(NAME_INPUT)).to_be_enabled(timeout=15_000)
    assert page.locator(NAME_INPUT).input_value() != ""
    assert page.locator(SURNAME_INPUT).input_value() != ""
