"""Переключение вида корзины на stage через админку — для CI.

Вид корзины (Настройки сайта → «Вид страницы Корзины») глобальный: он общий
для автотестов и для ручной работы на стенде. Поэтому:

* переключать МОЖНО только из ночного прогона. Локально скрипт откажется
  работать без переменной ALLOW_CART_VIEW_SWITCH=1 — иначе он поменяет стенд
  под руками у того, кто в этот момент проверяет руками;
* после смены НЕ ждём вслепую: опрашиваем фронт, пока настройка реально не
  приедет в SSR-пейлоад. Момент применения наблюдаемый, поэтому угадывать не
  нужно. Замер 2026-08-18: сохранение ~15 c, сброс кэша ~6 c, применение на
  фронте ~8 c;
* возврат исходного вида — обязанность вызывающего (шаг workflow с
  `if: always()`), иначе стенд останется в чужом виде.

Использование:
    python tools/cart_view.py get
    python tools/cart_view.py set default        # Вид 1, поп-ап
    python tools/cart_view.py set casadeltabaco  # Вид 2, отдельная страница

Коды возврата: 0 — успех, 1 — ошибка (в т.ч. «не применилось за таймаут»).
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
USERS_FILE = ROOT / "tests" / "fixtures" / "users.json"

ADMIN = os.environ.get("ADMIN_URL", "https://stage.admin.ecom.md")
FRONT = os.environ.get("FRONT_URL", "https://stage.ecom.md")

SETTINGS_URL = (
    f"{ADMIN}/ru/admin/site_settings/sitesettings/1/change/"
    "?_changelist_filters=group__id__exact%3D1"
)
GROUP_LIST_URL = f"{ADMIN}/ru/admin/ver4/group/?q=jbl"
# «Вид страницы Корзины». Поле обёрнуто в Select2: нативный <select> скрыт,
# поэтому значение задаётся через JS, а не select_option.
SELECT_ID = "#id_blocks_view_settings-0-cart_button_catalog_view_type"
# Сброс кэша именно для JBL: у каждой строки списка сайтов своя ссылка.
CLEAR_CACHE_LINK = 'a.admin_site_action[data-id="1"]'

FRONT_JS = (
    "() => window.__NUXT__?.state?.global?.globalSettings"
    "?.mainUiInterface?.cart_button_catalog_view_type ?? null"
)

# Страница-проба для КЭША. `read_front_view` спрашивает фронт через
# `?dev_mode=true`, а он кэш обходит — то есть подтверждает, что настройка
# доехала, но ничего не говорит про закэшированные страницы. Разница не
# теоретическая: 2026-08-21 после переключения на Вид 2 `/ru/product/...`
# (X-Cache: MISS) отдавал уже `casadeltabaco`, а `/ru/acustica-portabila`
# (X-Cache: HIT, возраст 319 c) — всё ещё `default`. На такой странице кнопка
# корзины в шапке открывает поп-ап Вида 1 вместо перехода на /cart, и тест
# `test_header_cart_leads_to_cart_page` падал через раз. Обойти кэш запросом
# нельзя: любой лишний query-параметр на категории даёт 404. Поэтому пробуем
# ОБЫЧНЫЙ запрос к кэшируемой категории и, если вид старый, сбрасываем кэш ещё раз.
CACHE_PROBE_PATH = os.environ.get("CART_VIEW_CACHE_PROBE", "/ru/acustica-portabila")
CACHE_CLEAR_ATTEMPTS = 3

VIEWS = {
    "default": "Вид 1 (поп-ап)",
    "casadeltabaco": "Вид 2 (отдельная страница)",
    "farmacie": "Вид 3 (персонализировано)",
    "step_by_step": "Вид 4 (пошагово)",
}

APPLY_TIMEOUT_S = int(os.environ.get("CART_VIEW_TIMEOUT", "240"))
POLL_EVERY_S = 10


def log(message: str) -> None:
    print(f"[cart_view] {message}", flush=True)


def _admin_credentials() -> dict:
    if not USERS_FILE.exists():
        raise SystemExit(f"нет {USERS_FILE} — учётки не заданы")
    users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    admin = users.get("adminUser") or {}
    if not admin.get("username") or not admin.get("password"):
        raise SystemExit(
            "в users.json нет adminUser {username, password} — "
            "переключение вида корзины недоступно"
        )
    return admin


def read_front_view(browser) -> str | None:
    """Что реально отдаётся на фронте. `?dev_mode=true` обходит кэш страницы."""
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        page.goto(f"{FRONT}/ru?dev_mode=true&_={int(time.time())}",
                  wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(800)
        return page.evaluate(FRONT_JS)
    except Exception as error:
        log(f"опрос фронта не удался: {type(error).__name__}")
        return None
    finally:
        ctx.close()


def read_cached_view(browser, path: str = CACHE_PROBE_PATH) -> str | None:
    """Что отдаётся на КЭШИРУЕМОЙ странице обычным запросом, без обхода кэша."""
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        page.goto(f"{FRONT}{path}", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(800)
        return page.evaluate(FRONT_JS)
    except Exception as error:
        log(f"опрос кэшируемой страницы не удался: {type(error).__name__}")
        return None
    finally:
        ctx.close()


def _admin_login(page, admin: dict) -> None:
    page.goto(f"{ADMIN}/ru/admin/login/", wait_until="domcontentloaded", timeout=60_000)
    page.fill("#id_username", admin["username"])
    page.fill("#id_password", admin["password"])
    page.click("input[type=submit]")
    page.wait_for_load_state("domcontentloaded", timeout=30_000)
    if "login" in page.url:
        raise SystemExit("не удалось войти в админку — проверь adminUser")


def _save_view(page, value: str) -> None:
    page.goto(SETTINGS_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3500)

    applied = page.evaluate(
        """([selector, val]) => {
             const el = document.querySelector(selector);
             if (!el) return 'селект не найден';
             el.value = val;
             el.dispatchEvent(new Event('change', {bubbles: true}));
             const jq = window.django?.jQuery || window.jQuery;
             if (jq) jq(el).trigger('change');
             return el.value;
           }""",
        [SELECT_ID, value],
    )
    if applied != value:
        raise SystemExit(f"не удалось выставить значение в форме: {applied!r}")

    page.locator('input[name="_save"]').first.click()
    page.wait_for_load_state("domcontentloaded", timeout=60_000)
    page.wait_for_timeout(2000)


def _clear_cache(page) -> None:
    page.goto(GROUP_LIST_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(2000)
    link = page.locator(CLEAR_CACHE_LINK, has_text="Clear cache").first
    if not link.count():
        raise SystemExit("не нашли ссылку сброса кэша для JBL в списке сайтов")
    link.click()
    page.wait_for_timeout(3000)


def set_view(value: str) -> int:
    if value not in VIEWS:
        raise SystemExit(f"неизвестный вид {value!r}; доступны: {', '.join(VIEWS)}")
    if os.environ.get("ALLOW_CART_VIEW_SWITCH") != "1":
        raise SystemExit(
            "переключение запрещено: вид корзины общий для стенда, и смена "
            "поломает ручную работу. Запускать только из CI с "
            "ALLOW_CART_VIEW_SWITCH=1"
        )

    admin = _admin_credentials()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={"width": 1600, "height": 1000}).new_page()

        current = read_front_view(browser)
        log(f"сейчас на фронте: {current!r} ({VIEWS.get(current, '?')})")
        if current == value:
            log("нужный вид уже активен, ничего не делаем")
            browser.close()
            return 0

        _admin_login(page, admin)
        log(f"ставим {value!r} ({VIEWS[value]})")
        _save_view(page, value)
        _clear_cache(page)

        started = time.time()
        while time.time() - started < APPLY_TIMEOUT_S:
            actual = read_front_view(browser)
            elapsed = time.time() - started
            log(f"  проверка ({elapsed:.0f}c): {actual!r}")
            if actual == value:
                log(f"применилось за {elapsed:.0f}c")
                _wait_cache_purged(browser, page, value)
                browser.close()
                return 0
            time.sleep(POLL_EVERY_S)

        log(f"НЕ применилось за {APPLY_TIMEOUT_S}c — вероятно, кэш не сбросился")
        browser.close()
        return 1


def _wait_cache_purged(browser, page, value: str) -> None:
    """Добиться, чтобы новый вид отдавался и с КЭШИРУЕМОЙ страницы.

    Настройка уже применилась (это проверено выше запросом в обход кэша), так
    что упереться тут в старую копию — не повод валить прогон: шаг «Run cart
    view 2 tests» запускается только при `outcome == 'success'`, и возврат 1
    оставил бы Вид 2 непроверенным целиком. Поэтому пробуем сбросить кэш ещё
    раз, а если не помогло — громко предупреждаем и идём дальше. Тест, которому
    достанется устаревшая страница, скипнется сам с таким же объяснением.
    """
    for attempt in range(1, CACHE_CLEAR_ATTEMPTS + 1):
        cached = read_cached_view(browser)
        if cached == value:
            log(f"кэшируемая страница {CACHE_PROBE_PATH} отдаёт {value!r}")
            return
        log(
            f"  кэш ещё старый на {CACHE_PROBE_PATH}: {cached!r} вместо {value!r} "
            f"(попытка {attempt} из {CACHE_CLEAR_ATTEMPTS})"
        )
        if attempt < CACHE_CLEAR_ATTEMPTS:
            _clear_cache(page)
            time.sleep(POLL_EVERY_S)

    log(
        f"ВНИМАНИЕ: {CACHE_PROBE_PATH} по-прежнему отдаётся из кэша со старым "
        f"видом. Настройка применена, но тесты на кэшируемых страницах увидят "
        f"прошлый вид корзины и скипнутся."
    )


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"get", "set"}:
        print(__doc__)
        return 1

    if sys.argv[1] == "get":
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            value = read_front_view(browser)
            browser.close()
        print(value or "")
        log(f"активный вид: {value!r} ({VIEWS.get(value, 'неизвестный')})")
        return 0 if value else 1

    if len(sys.argv) < 3:
        raise SystemExit("укажите вид: " + ", ".join(VIEWS))
    return set_view(sys.argv[2])


if __name__ == "__main__":
    sys.exit(main())
