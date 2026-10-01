"""Эмуляция телефона для мобильной суиты.

Мобильная вёрстка stage включается по ширине (`visible-is-under-and-equal-1024`),
но одной ширины мало: без `is_mobile`/`has_touch` браузер остаётся десктопным —
нет touch-событий, `tap()` недоступен, user-agent десктопный. Поэтому берём
готовый профиль устройства целиком.

Запуск: `pytest tests/mobile` (обычный `pytest` эту папку пропускает — см.
корневой conftest).
"""

import pytest

DEVICE = "Pixel 7"

# Папка — пакет (есть __init__.py) намеренно. Иначе этот conftest грузится под
# именем `conftest` и перекрывает корневой, а десктопные файлы делают
# `from conftest import ...` — импорт ломается. Пакет же заставляет pytest
# положить в sys.path саму tests/, и мобильные тесты переиспользуют хелперы
# десктопных (`from test_cart_block import ...`): логика корзины, ожиданий и
# повторов одна, отличается лишь то, где лежат кнопки.


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, playwright, browser_name):
    # Firefox не поддерживает `is_mobile` — контекст просто не создастся.
    if browser_name == "firefox":
        pytest.skip("Эмуляция мобильного устройства в Firefox не поддерживается")
    device = dict(playwright.devices[DEVICE])
    # Ключ описывает, в каком браузере запускать профиль, — в new_context он
    # не принимается.
    device.pop("default_browser_type", None)
    return {**browser_context_args, **device}
