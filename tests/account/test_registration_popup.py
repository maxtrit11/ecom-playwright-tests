"""Тесты поп-апа Регистрация"""

import time

import pytest
from playwright.sync_api import Page, expect


# ---------------------------------------------------------------------------
# Хелпер: открыть поп-ап регистрации
# ---------------------------------------------------------------------------
def open_registration_popup(page: Page) -> None:
    page.locator(".btn__action.btn__auth").click(force=True)
    page.locator(".modal__authentification__ecom-content").first.wait_for(
        state="visible", timeout=10_000
    )

    page.get_by_text("Зарегистрироваться").first.click()
    expect(
        page.get_by_role("heading", name="Регистрация")
    ).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# Фикстура: перейти на главную перед каждым тестом
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def navigate_home(page: Page):
    # wait_until="load" зависает на /ru из-за фоновых ресурсов
    # (чат-виджет и т.д.) — используем domcontentloaded
    page.goto("/ru", wait_until="domcontentloaded", timeout=60_000)
    # networkidle тоже зачастую не достигается — ждём наличия шапки
    page.locator(".btn__action.btn__auth").wait_for(state="visible", timeout=15_000)


# ===========================================================================
# Кейс 1: Переход на поп-ап Регистрации
# ===========================================================================
def test_open_registration_popup_with_all_elements(page: Page):
    """Открытие поп-апа регистрации с проверкой всех элементов."""
    page.locator(".btn__action.btn__auth").click(force=True)
    page.locator(".modal__authentification__ecom-content").first.wait_for(
        state="visible", timeout=10_000
    )

    # Нажать на кнопку «Зарегистрироваться»
    page.get_by_text("Зарегистрироваться").first.click()

    # Открывается поп-ап регистрации
    expect(
        page.get_by_role("heading", name="Регистрация")
    ).to_be_visible(timeout=10_000)

    # По умолчанию выбран тип «Физическое лицо»
    active_tab = page.locator(
        ".modal__authentification__ecom-content-form-tabs button.active"
    )
    expect(active_tab).to_contain_text("Физическое лицо")

    # Отображаются все поля формы
    expect(page.locator('input[placeholder="Ваше имя"]')).to_be_visible()
    expect(page.locator('input[placeholder="Ваше фамилия"]')).to_be_visible()
    expect(
        page.locator('input[placeholder="Введи e-mail адрес"]').first
    ).to_be_visible()
    # На stage в форме два <input type=tel id="phone"> (оригинальный .phone +
    # сгенерированный плагином intl-tel-input .iti__tel-input). Видимое
    # пользователю поле — именно .iti__tel-input, его и проверяем/заполняем,
    # иначе strict-mode падает на 2 совпадениях.
    expect(page.locator('input[type="tel"].iti__tel-input')).to_be_visible()

    password_fields = page.locator('input[type="password"]')
    expect(password_fields).to_have_count(2)
    for i in range(2):
        expect(password_fields.nth(i)).to_be_visible()


# ===========================================================================
# Кейс 2: Отображение ошибки при вводе пустых полей
# ===========================================================================
def test_empty_fields_show_validation_errors(page: Page):
    """Отображение ошибок при отправке пустых обязательных полей."""
    open_registration_popup(page)

    modal = page.locator(".modal__authentification__ecom-content")

    # Нажать кнопку «Зарегистрироваться» не заполняя поля
    modal.locator('button[type="submit"]').first.click()

    # Под обязательными полями отображаются сообщения об ошибке
    visible_validations = modal.locator(".validation:visible")
    assert visible_validations.count() >= 3

    # Регистрация не выполняется — поп-ап остаётся открытым
    expect(page.get_by_role("heading", name="Регистрация")).to_be_visible()


# ===========================================================================
# Кейс 3: Показать / Скрыть пароль (иконка глаза)
# ===========================================================================
def test_toggle_password_visibility(page: Page):
    """Показать и скрыть пароль по клику на иконку глаза."""
    open_registration_popup(page)

    password_input = page.locator('input[placeholder="********"]').first

    # Ввести пароль
    password_input.fill("TestPassword123")

    # Символы отображаются в виде точек (type=password)
    expect(password_input).to_have_attribute("type", "password")

    # Кликаем на иконку глаза — пароль виден
    page.locator("button.show__password").first.click()
    expect(password_input).to_have_attribute("type", "text")

    # Повторный клик — пароль снова скрыт
    page.locator("button.show__password").first.click()
    expect(password_input).to_have_attribute("type", "password")


# ===========================================================================
# Кейс 4: Ввести неправильный повторный пароль
# ===========================================================================
def test_password_mismatch_shows_error(page: Page):
    """Отображение ошибки при несовпадении паролей."""
    open_registration_popup(page)

    form = page.locator(".modal__authentification__ecom-content-form")

    # Заполнить все поля
    form.locator('input[placeholder="Ваше имя"]').fill("Тест")
    form.locator('input[placeholder="Ваше фамилия"]').fill("Тестов")
    form.locator('input[placeholder="Введи e-mail адрес"]').first.fill(
        "testuser_random@test.com"
    )
    form.locator('input[type="tel"].iti__tel-input').fill("60123456")

    # Ввести разные пароли
    password_fields = form.locator('input[placeholder="********"]')
    password_fields.nth(0).fill("Password123!")
    expect(password_fields.nth(0)).to_have_attribute("type", "password")

    password_fields.nth(1).fill("DifferentPass456!")

    # Нажать кнопку «Зарегистрироваться»
    form.locator('button[type="submit"]').first.click()

    # Отображается сообщение о несовпадении паролей
    modal = page.locator(".modal__authentification__ecom-content")
    validation_messages = modal.locator(".validation:visible")
    expect(validation_messages).to_contain_text("Пароли не совпадают")

    # Поп-ап остаётся открытым
    expect(page.get_by_role("heading", name="Регистрация")).to_be_visible()


# ===========================================================================
# Кейс 5: Ошибка при вводе почты уже зарегистрированного пользователя
# ===========================================================================
def test_duplicate_email_shows_error(page: Page):
    """Отображение ошибки при вводе уже зарегистрированного email."""
    open_registration_popup(page)

    form = page.locator(".modal__authentification__ecom-content-form")

    # Заполнить форму валидными данными
    form.locator('input[placeholder="Ваше имя"]').fill("Тест")
    form.locator('input[placeholder="Ваше фамилия"]').fill("Тестов")
    form.locator('input[type="tel"].iti__tel-input').fill("60123456")

    password_fields = form.locator('input[placeholder="********"]')
    password_fields.nth(0).fill("Password123!")
    password_fields.nth(1).fill("Password123!")

    checkbox = form.locator('input[type="checkbox"]')
    checkbox.dispatch_event("click")

    # Валидация не отображается
    expect(form.locator(".validation:visible")).to_have_count(0)

    # Ввести e-mail уже зарегистрированного пользователя
    form.locator('input[placeholder="Введи e-mail адрес"]').first.fill(
        "maxim.turcan1@gmail.com"
    )

    # Нажать кнопку «Зарегистрироваться»
    form.locator('button[type="submit"]').first.click()

    # Отображается сообщение, что Email уже используется
    modal = page.locator(".modal__authentification__ecom-content")
    expect(modal.locator(".validation:visible")).to_contain_text(
        "Пользователь с указанным адресом электронной почты уже существует",
        timeout=10_000,
    )

    # Поп-ап остаётся открытым
    expect(page.get_by_role("heading", name="Регистрация")).to_be_visible()


# ===========================================================================
# Кейс 6: Переключатели — Юридическое лицо
# ===========================================================================
def test_switch_to_legal_entity_shows_extra_fields(page: Page):
    """Переключение на тип Юридическое лицо с отображением доп. полей."""
    open_registration_popup(page)

    form = page.locator(".modal__authentification__ecom-content-form")

    # Нажать на «Юридическое лицо»
    page.get_by_text("Юридическое лицо").click()

    # Проверить активную вкладку
    active_tab = page.locator(
        ".modal__authentification__ecom-content-form-tabs button.active"
    )
    expect(active_tab).to_contain_text("Юридическое лицо")

    # Проверить дополнительные поля
    for label_text in [
        "Название компании",
        "ИДНО",
        "Физический адрес",
        "Юридический адрес",
        "Район",
        "Город",
        "Название Банка",
        "Cont/IBAN",
    ]:
        expect(form.locator("label", has_text=label_text)).to_be_visible()


# ===========================================================================
# Кейс 7: Положительный сценарий регистрации
# ===========================================================================
def test_successful_registration(page: Page):
    """Успешная регистрация нового пользователя."""
    open_registration_popup(page)

    form = page.locator(".modal__authentification__ecom-content-form")
    unique = int(time.time() * 1000)
    unique_email = f"testqa_{unique}@mailinator.com"
    unique_phone = str(unique)[-6:]

    # Заполнить все поля
    form.locator('input[placeholder="Ваше имя"]').fill("Тест")
    form.locator('input[placeholder="Ваше фамилия"]').fill("Тестов")
    form.locator('input[placeholder="Введи e-mail адрес"]').first.fill(
        unique_email
    )
    form.locator('input[type="tel"].iti__tel-input').fill(f"60{unique_phone}")

    password_fields = form.locator('input[placeholder="********"]')
    password_fields.nth(0).fill("TestPass123!")
    password_fields.nth(1).fill("TestPass123!")

    # Отметить чекбокс согласия
    checkbox = form.locator('input[type="checkbox"]')
    checkbox.dispatch_event("click")

    # Валидация не отображается
    expect(form.locator(".validation:visible")).to_have_count(0)

    # Нажать кнопку «Зарегистрироваться»
    form.locator('button[type="submit"]').first.click()

    # Отображается сообщение об отправке ссылки активации
    expect(
        page.get_by_text("была отправлена ссылка")
    ).to_be_visible(timeout=15_000)
