"""Прод: ежедневная проверка «только чтение» — jblstore.md и alo.md.

Зачем, если суита гоняет stage: прод ломается не только кодом, но и данными
и настройками, которых на stage нет. Так жили мёртвая кнопка подарка на проде
(ecom-5273) и фид Google Ads, который 12 дней не перегенерировался (BUG_001).

ПРАВИЛО ФАЙЛА — ТОЛЬКО ПРОСМОТР. Никаких заказов, предзаказов, кредитных
заявок, «купить в 1 клик», регистрации, подписки, логина и даже корзины:
добавление в корзину пишет на сервер и попадает в аналитику магазина. Тест
здесь — это посетитель, который открыл страницы и ничего не нажал.

Обычный `pytest` эту папку не собирает (см. корневой conftest), запуск явный:
    pytest tests/prod
    pytest tests/prod -k alo

Вёрстка у обоих магазинов общая (платформа ecom), различаются только адреса —
они в SITES. Категория — именно листовая (с товарами), а не родительская:
у родительской вместо карточек плитки подкатегорий.
"""

import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, expect

SITES = {
    "jblstore": {
        "base": "https://jblstore.md",
        "category": "/ru/serie-partybox",
        "query": "jbl",
        "google_ads_feed": True,
    },
    "alo": {
        "base": "https://alo.md",
        "category": "/ru/smartfony",
        "query": "samsung",
        # Фид Google Ads у alo не используется: файл есть, но пустой (08.10).
        "google_ads_feed": False,
    },
}

CARD = ".product__item"
CARD_PRICES = ".product__prices"
CARD_LINK = 'a[href*="/product/"]'
PDP_PRICE = ".price.new__price"

_PAYLOAD_JS = """() => {
  const p = window.__NUXT__?.state?.product?.product;
  return p ? {price: p.price, stock: p.stock, available: p.available} : null;
}"""

_AMOUNT_RE = re.compile(r"(\d[\d\s ]*(?:[.,]\d{1,2})?)")
# Слово кириллицей от 4 букв: на /ro его быть не должно. Короче — ловит
# «шум» вроде единиц измерения, а 4+ буквы уже точно непереведённый текст.
_CYRILLIC_WORD_RE = re.compile(r"[А-Яа-яЁё]{4,}")


def _bani(text: str) -> int:
    """Первая сумма из текста в банах. «12 999 MDL» → 1299900."""
    match = _AMOUNT_RE.search(text or "")
    assert match, f"В строке {text!r} не нашли суммы"
    normalized = re.sub(r"[\s ]", "", match.group(1)).replace(",", ".")
    return int(round(float(normalized) * 100))


@pytest.fixture(params=list(SITES), ids=list(SITES))
def site(request) -> dict:
    return {"name": request.param, **SITES[request.param]}


def _open(page: Page, url: str) -> None:
    response = page.goto(url, wait_until="domcontentloaded")
    assert response is not None and response.status < 400, (
        f"{url} ответил {response.status if response else 'без ответа'}"
    )


def _scroll_through(page: Page) -> None:
    """Карусели и картинки монтируются лениво — без прокрутки их нет в DOM."""
    page.evaluate(
        """async () => {
          for (let y = 0; y < document.body.scrollHeight; y += 700) {
            window.scrollTo(0, y);
            await new Promise(r => setTimeout(r, 150));
          }
          window.scrollTo(0, 0);
        }"""
    )


def _priced_cards(page: Page):
    cards = page.locator(CARD)
    expect(cards.first).to_be_visible(timeout=20_000)
    return cards.filter(has=page.locator(CARD_PRICES).filter(has_text=re.compile(r"\d")))


# ---------------------------------------------------------------------------
# Страницы витрины
# ---------------------------------------------------------------------------
def test_home_opens_with_products(page: Page, site):
    """Главная открывается, на ней шапка и хотя бы одна карточка товара."""
    _open(page, site["base"] + "/ru")
    expect(page.locator("header").first).to_be_visible()
    _scroll_through(page)
    expect(page.locator(CARD_LINK).first).to_be_attached(timeout=15_000)


def test_category_shows_priced_products(page: Page, site):
    """В листовой категории есть товары с ценой, и ни одна цена не нулевая."""
    _open(page, site["base"] + site["category"])
    expect(page.locator("h1").first).to_be_visible()

    priced = _priced_cards(page)
    assert priced.count() > 0, (
        f"{site['category']}: ни у одной карточки нет цены — "
        "либо всё не в наличии, либо цены не выводятся"
    )
    prices = [_bani(t) for t in priced.locator(CARD_PRICES).all_inner_texts()]
    assert all(p > 0 for p in prices), f"Нулевая цена на листинге: {prices}"


def test_product_price_matches_backend(page: Page, site):
    """Цена на странице товара = цене из SSR-данных, главное фото загрузилось.

    Товар берём с листинга (первый с ценой), а не зашиваем: на проде товары
    уходят из наличия, и зашитый адрес однажды стал бы ложным падением.
    """
    _open(page, site["base"] + site["category"])
    href = _priced_cards(page).first.locator(CARD_LINK).first.get_attribute("href")
    assert href, "У карточки с ценой нет ссылки на товар"
    url = href if href.startswith("http") else site["base"] + href
    _open(page, url)

    expect(page.locator("h1").first).to_be_visible()
    data = page.evaluate(_PAYLOAD_JS)
    assert data, f"{url}: в window.__NUXT__ нет данных товара"
    shown = page.locator(PDP_PRICE).first
    expect(shown).to_be_visible()
    assert _bani(shown.inner_text()) == _bani(str(data["price"])), (
        f"{url}: на странице {shown.inner_text()!r}, в данных сайта {data['price']}"
    )

    broken = page.evaluate(
        """() => [...document.querySelectorAll('main img, .product img')]
             .filter(i => i.complete && i.getBoundingClientRect().width > 150)
             .filter(i => i.naturalWidth === 0)
             .map(i => i.currentSrc || i.src)"""
    )
    assert not broken, f"{url}: битые крупные картинки товара: {broken[:3]}"


def test_search_returns_results(page: Page, site):
    """Поиск по ходовому запросу находит товары (только страница выдачи)."""
    _open(page, f"{site['base']}/ru/search?query={site['query']}")
    expect(page.locator(CARD).first).to_be_visible(timeout=20_000)


# Видимый текст страницы, кроме отзывов покупателей: их пишут люди на своём
# языке, и русский отзыв на /ro — это контент, а не непереведённый интерфейс.
_UI_TEXT_JS = """() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const el = node.parentElement;
    if (!el || el.closest('[class*="review"], script, style, noscript')) continue;
    if (!el.getClientRects().length) continue;
    out.push(node.textContent);
  }
  return out.join(' ');
}"""


def test_romanian_home_has_no_russian_text(page: Page, site):
    """/ro отдаётся на румынском: lang=ro и в интерфейсе главной нет русских слов."""
    _open(page, site["base"] + "/ro")
    expect(page.locator("html")).to_have_attribute("lang", "ro")
    _scroll_through(page)
    words = sorted(set(_CYRILLIC_WORD_RE.findall(page.evaluate(_UI_TEXT_JS))))
    assert not words, f"На /ro русский текст в интерфейсе: {words[:15]}"


# ---------------------------------------------------------------------------
# Технические файлы: то, что после выкладки ломается молча
# ---------------------------------------------------------------------------
def _robots_blocks_all(robots: str) -> bool:
    """Есть ли `Disallow: /` (весь сайт) в группе, где перечислен `User-agent: *`."""
    in_star_group = False
    seen_rule = False
    for raw in robots.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if seen_rule:  # началась новая группа
                in_star_group, seen_rule = False, False
            in_star_group = in_star_group or value == "*"
        elif key in ("allow", "disallow"):
            seen_rule = True
            if in_star_group and key == "disallow" and value == "/":
                return True
    return False


def test_robots_and_sitemap(page: Page, site):
    """robots.txt не закрывает сайт от поисковиков, sitemap.xml с адресами."""
    robots = page.request.get(site["base"] + "/robots.txt")
    if robots.status == 503:
        # Файрвол прода режет голый запрос с IP GitHub Actions (alo, 09.10.2026):
        # страницы в браузере в том же прогоне открывались. Это не дефект сайта.
        pytest.skip(f"{site['base']}/robots.txt: 503 — запрос заблокирован файрволом")
    assert robots.ok, f"robots.txt ответил {robots.status}"
    assert not _robots_blocks_all(robots.text()), (
        "robots.txt закрывает ВЕСЬ сайт (`Disallow: /` для `User-agent: *`) — "
        "похоже, на прод уехала настройка со stage"
    )

    sitemap = page.request.get(site["base"] + "/sitemap.xml")
    assert sitemap.ok, f"sitemap.xml ответил {sitemap.status}"
    assert "<loc>" in sitemap.text(), "В sitemap.xml нет ни одного <loc>"


@pytest.mark.parametrize(
    "site", [name for name, cfg in SITES.items() if cfg["google_ads_feed"]], indirect=True
)
def test_google_ads_feed_not_empty(page: Page, site):
    """Фид Google Ads содержит товары этого магазина (кейс BUG_001)."""
    url = site["base"] + "/feed/google-ads.csv"
    resp = page.request.get(url)
    assert resp.ok, f"{url} ответил {resp.status}"

    lines = [ln for ln in resp.text().splitlines() if ln.strip()]
    assert lines and lines[0].startswith("ID,"), f"{url}: не CSV фида: {lines[:1]}"
    rows = lines[1:]
    assert rows, f"{url}: в фиде только заголовок, ни одного товара"

    host = urlsplit(site["base"]).hostname
    foreign = [r for r in rows[:50] if f"://{host}/" not in r]
    assert not foreign, f"{url}: строки со ссылками не на {host}: {foreign[:2]}"
