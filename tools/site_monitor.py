"""Мониторинг продов: сайт отвечает и открывается быстро. В Telegram пишет только о проблемах.

Три режима, каждый — отдельная задача в Планировщике:

    python tools/site_monitor.py http      # каждые 5 мин: коды ответа (500/502/503/504, нет ответа), SSL;
                                           # коды ответа — только сайты из http_on_pc, остальные 24/7 смотрит Cloudflare
    python tools/site_monitor.py speed     # каждые 15 мин: настоящий браузер, время открытия страниц
    python tools/site_monitor.py summary   # раз в день: сводка за сутки (заодно видно, что бот жив)

    --dry-run — сообщения только в консоль, состояние не меняется.

Что и как проверяется — tools/site_monitor.json (сайты по темам группы, пороги).

Скорость: компьютер 1920×1080 на обычной сети, чистый браузер (как новый посетитель).
Меряется LCP — когда появилось главное содержимое страницы. Рекламные поп-апы и модалки
не в счёт: на farmacie.md поп-ап с картинкой выскакивает через ~3.5 с и иначе выдавался
бы за «медленную страницу». Один медленный заход — не тревога (промах кэша сервера бывает):
страница медленнее порога → ещё 2 открытия, тревога по медиане трёх.

Когда пишет в чат: новая проблема; напоминание, пока не прошла (remind_every_min);
одно сообщение, когда прошла. Всё в порядке — молчит (кроме утренней сводки).

ВАЖНО, где запускать: прод режет IP дата-центров (с GitHub Actions — 403), такой ответ
здесь честно считается сбоем. Запускать с адреса, который прод пускает.

Окружение: TELEGRAM_BOT_TOKEN, MONITOR_CHAT_ID — из переменных или файла .env в корне
репозитория (он в .gitignore). Без них — как --dry-run.
"""

from __future__ import annotations

import html
import json
import os
import random
import socket
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(os.environ.get("MONITOR_CONFIG") or Path(__file__).with_name("site_monitor.json"))
DATA_DIR = Path(os.environ.get("MONITOR_DATA") or ROOT / "monitor-data")
API = "https://api.telegram.org/bot{token}/sendMessage"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

HTTP_TIMEOUT_S = 30
HTTP_RETRIES = 3
HTTP_RETRY_PAUSE_S = 20
SSL_WARN_DAYS = 14
NAV_TIMEOUT_MS = 30000
SPEED_CONFIRM_RUNS = 3
LOG_KEEP_DAYS = 8

PAGE_TITLES = {"home": "Главная", "category": "Категория", "product": "Карточка товара", "search": "Поиск"}
PAGE_ORDER = ["home", "category", "product", "search"]

# Последний кандидат LCP вне поп-апов/модалок/cookie-баннера. Наблюдатель ставится до загрузки
# страницы. Оверлеи ещё и прячутся CSS-ом: крупный баннер, показанный первым, иначе «съедает» LCP —
# более мелкое содержимое после него браузер кандидатом уже не считает (поиск luminaled.md).
# html/body не в счёт: alcohall.md на время проверки возраста вешает на body класс popup-open.
OVERLAY = '[class*="popup"], [class*="modal"], [class*="cookie-banner"], [role="dialog"]'
LCP_INIT = """(() => {
window.__lcp = {t: 0, el: ''};
const OVERLAY = '%s';
const css = document.createElement('style');
css.textContent = OVERLAY.split(', ').map(x => 'body ' + x).join(', ') + ' { display: none !important; }';
// Скрипт выполняется до разбора HTML — корня документа может ещё не быть.
const addCss = () => { const root = document.head || document.documentElement; root ? root.appendChild(css) : setTimeout(addCss, 0); };
addCss();
const isOverlay = el => {
  for (let n = el; n && n !== document.body && n !== document.documentElement; n = n.parentElement)
    if (n.matches(OVERLAY)) return true;
  return false;
};
new PerformanceObserver(list => {
  for (const e of list.getEntries()) {
    const el = e.element;
    if (el && isOverlay(el)) continue;
    const cls = el && typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(' ')[0] : '';
    window.__lcp = {t: e.startTime, el: el ? el.tagName.toLowerCase() + cls : ''};
  }
}).observe({type: 'largest-contentful-paint', buffered: true});
})();""" % OVERLAY
LCP_READ = """() => {
  const n = performance.getEntriesByType('navigation')[0] || {};
  const l = window.__lcp || {t: 0, el: ''};
  return {lcp: Math.round(l.t), el: l.el, ttfb: Math.round(n.responseStart || 0)};
}"""


# ---------------------------------------------------------------- общее

def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _pages(config: dict):
    """(группа, сайт, тип страницы, путь); товар берётся из категории на прогоне speed."""
    for group, g in config["groups"].items():
        for site, paths in g["sites"].items():
            for kind in PAGE_ORDER:
                if kind in paths:
                    yield group, site, kind, paths[kind]


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _log(records: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    with open(DATA_DIR / f"log-{day}.jsonl", "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    cutoff = (datetime.now() - timedelta(days=LOG_KEEP_DAYS)).strftime("%Y%m%d")
    for old in DATA_DIR.glob("log-*.jsonl"):
        if old.stem[4:] < cutoff:
            old.unlink(missing_ok=True)


def _sec(ms: float) -> str:
    return f"{ms / 1000:.1f} с"


def _hhmm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _span(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes} мин" if minutes < 60 else f"{minutes // 60} ч {minutes % 60:02d} мин"


# ---------------------------------------------------------------- http

def _probe(url: str) -> str | None:
    """Одна попытка. None — сервер ответил нормально, иначе причина."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        return f"нет ответа: {getattr(e, 'reason', e)}"
    return None


def _http_check(url: str) -> str | None:
    error = None
    for attempt in range(HTTP_RETRIES):
        error = _probe(url)
        if error is None:
            return None
        if attempt < HTTP_RETRIES - 1:
            time.sleep(HTTP_RETRY_PAUSE_S)
    return error


def _ssl_days_left(host: str) -> int:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=HTTP_TIMEOUT_S) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            not_after = tls.getpeercert()["notAfter"]
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc)
    return (expires - datetime.now(timezone.utc)).days


def run_http(config: dict) -> list[dict]:
    products = _read_json(DATA_DIR / "products.json", {})
    pages = list(_pages(config))
    # Коды ответа остальных сайтов 24/7 проверяет monitor-cloudflare/worker.js — здесь только http_on_pc,
    # чтобы о сбое не приходило двух сообщений. SSL — по всем сайтам.
    on_pc = set(config.get("http_on_pc", []))
    pages = [p for p in pages if p[1] in on_pc]
    products = {site: path for site, path in products.items() if site in on_pc}
    for group, g in config["groups"].items():
        for site in g["sites"]:
            if site in products:
                pages.append((group, site, "product", products[site]))
    results = []
    for group, site, kind, path in pages:
        error = _http_check(f"https://{site}{path}")
        results.append({"group": group, "site": site, "page": kind, "path": path, "problem": error})
    for group, g in config["groups"].items():
        for site in g["sites"]:
            try:
                days = _ssl_days_left(site)
                error = f"SSL-сертификат истекает через {days} дн." if days < SSL_WARN_DAYS else None
            except (OSError, ssl.SSLError) as e:
                error = f"SSL: {e}"
            results.append({"group": group, "site": site, "page": "ssl", "path": "/", "problem": error})
    return results


# ---------------------------------------------------------------- speed

def _measure(browser, url: str, need_products: bool) -> dict:
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=UA)
    ctx.add_init_script(LCP_INIT)
    page = ctx.new_page()
    out: dict = {"url": url}
    try:
        resp = page.goto(url, wait_until="load", timeout=NAV_TIMEOUT_MS)
        out["status"] = resp.status if resp else None
        page.wait_for_timeout(1500)
        out.update(page.evaluate(LCP_READ))
        if need_products:
            try:
                page.wait_for_selector('a[href*="/product/"]', timeout=10000)
            except Exception:
                pass
            out["products"] = list(dict.fromkeys(
                page.eval_on_selector_all('a[href*="/product/"]', "e => e.map(a => a.getAttribute('href'))")))
    except Exception as e:
        out["error"] = "страница не открылась за 30 с" if "Timeout" in str(e) else str(e).splitlines()[0][:150]
    finally:
        ctx.close()
    return out


def _speed_one(browser, url: str, kind: str, limit: int, critical: int) -> tuple[dict, list[str]]:
    """Открывает страницу (при превышении — ещё раз до SPEED_CONFIRM_RUNS). Возвращает итог и товары."""
    need_products = kind in ("category", "search")
    runs = [_measure(browser, url, need_products)]
    products = runs[0].get("products") or []

    def verdict_input(r):
        return r.get("error") is None and (r.get("status") or 0) < 400 and r.get("lcp")

    if verdict_input(runs[0]) and runs[0]["lcp"] > limit:
        runs += [_measure(browser, url, False) for _ in range(SPEED_CONFIRM_RUNS - 1)]

    first = runs[0]
    rec = {"url": url, "status": first.get("status"), "runs": [r.get("lcp") for r in runs],
           "ttfb": [r.get("ttfb") for r in runs], "el": first.get("el")}
    if first.get("error"):
        rec["problem"] = first["error"]
        rec["level"] = "down"
    elif (first.get("status") or 0) >= 400:
        rec["problem"] = f"HTTP {first['status']}"
        rec["level"] = "down"
    elif not first.get("lcp"):
        rec["note"] = "не удалось измерить"
    else:
        good = [r["lcp"] for r in runs if r.get("lcp")]
        med = statistics.median(good)
        rec["lcp"] = med
        if med > limit:
            ttfb = statistics.median([t for t in rec["ttfb"] if t is not None] or [0])
            rec["problem"] = (f"открывается {_sec(med)} (порог {_sec(limit)})\n"
                              f"открыли {len(good)} раза: {', '.join(_sec(x) for x in good)} — в итог идёт средний\n"
                              f"из них ждали ответа сервера {_sec(ttfb)}, остальное — загрузка в браузере")
            rec["level"] = "critical" if med > critical else "slow"
    if need_products and not rec.get("problem") and not products:
        rec["problem"] = "на странице нет ни одного товара"
        rec["level"] = "down"
    return rec, products


def run_speed(config: dict) -> list[dict]:
    from playwright.sync_api import sync_playwright

    limits, critical = config["thresholds_ms"], config["critical_ms"]
    product_cache = _read_json(DATA_DIR / "products.json", {})
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for group, g in config["groups"].items():
                for site, paths in g["sites"].items():
                    base = f"https://{site}"
                    for kind in PAGE_ORDER:
                        if kind == "product":
                            path = product_cache.get(site)
                        else:
                            path = paths.get(kind)
                        if not path:
                            continue
                        rec, products = _speed_one(browser, base + path, kind, limits[kind], critical)
                        rec.update(group=group, site=site, page=kind, path=path)
                        results.append(rec)
                        if kind == "category" and products:
                            # Каждый раз другой товар из первых десяти: фиксированный однажды снимут с продажи.
                            product_cache[site] = random.choice(products[:10])
        finally:
            browser.close()
    _write_json(DATA_DIR / "products.json", product_cache)
    return results


# ---------------------------------------------------------------- сообщения

def _messages(results: list[dict], state: dict, now: float, mode: str, remind_s: float) -> dict[str, list[str]]:
    """{группа: [сообщение на сайт]}. Состояние: ключ «сайт|страница» → {since, notified, level}."""
    e = html.escape
    per_site: dict[tuple[str, str], dict[str, list[str]]] = {}
    for r in results:
        key = f"{mode}|{r['site']}|{r['page']}"
        title = "SSL" if r["page"] == "ssl" else PAGE_TITLES[r["page"]]
        bucket = per_site.setdefault((r["group"], r["site"]), {"new": [], "still": [], "fixed": []})
        prev = state.get(key)
        problem = r.get("problem")
        link = f"https://{r['site']}{r['path']}"
        if not problem:
            if prev:
                slow = prev.get("level") in ("slow", "critical")
                what = "снова открывается быстро" if slow else "снова работает"
                # Проверки идут раз в 5/15 мин: известно только, что проблема была на прошлых проверках
                # и её нет на этой — сама проблема могла длиться меньше.
                was = "медленно" if slow else "не работало"
                bucket["fixed"].append(f"• {title} — {what}\n  {was} на проверках с {_hhmm(prev['since'])}, "
                                       f"на проверке в {_hhmm(now)} уже в норме")
                state.pop(key)
            continue
        line = f"• <b>{title}</b>: {e(problem).replace(chr(10), chr(10) + "  ")}\n  {e(link)}"
        if not prev:
            state[key] = {"since": now, "notified": now, "level": r.get("level", "down")}
            bucket["new"].append(line)
        elif now - prev["notified"] >= remind_s:
            prev["notified"] = now
            bucket["still"].append(line + f"\n  <i>держится с {_hhmm(prev['since'])} (~{_span(now - prev['since'])})</i>")

    out: dict[str, list[str]] = {}
    for (group, site), b in per_site.items():
        parts = []
        if b["new"]:
            levels = [state.get(f"{mode}|{site}|{p}", {}).get("level") for p in PAGE_ORDER + ["ssl"]]
            head = "🔴" if "down" in levels or "critical" in levels else "🟠"
            label = "не работает" if mode == "http" else "проблемы"
            parts.append(f"{head} <b>{e(site)}</b> — {label}\n" + "\n".join(b["new"]))
        if b["still"]:
            parts.append(f"🔁 <b>{e(site)}</b> — всё ещё\n" + "\n".join(b["still"]))
        if b["fixed"]:
            parts.append(f"🟢 <b>{e(site)}</b>\n" + "\n".join(b["fixed"]))
        if parts:
            out.setdefault(group, []).append("\n\n".join(parts))
    return out


def _summary(config: dict) -> dict[str, list[str]]:
    since = time.time() - 24 * 3600
    rows = []
    for f in sorted(DATA_DIR.glob("log-*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("ts", 0) >= since:
                rows.append(r)
    out: dict[str, list[str]] = {}
    for group, g in config["groups"].items():
        lines = ["📊 <b>Сводка за сутки</b> (компьютер, обычная сеть; медиана / худшее)"]
        for site in g["sites"]:
            mine = [r for r in rows if r["site"] == site]
            speed = [r for r in mine if r["mode"] == "speed"]
            down = sum(1 for r in mine if r.get("level") == "down" or (r["mode"] == "http" and r.get("problem")))
            slow = sum(1 for r in speed if r.get("level") in ("slow", "critical"))
            checks = len({r["ts"] for r in mine})
            if not checks:
                lines.append(f"\n<b>{html.escape(site)}</b>: ⚠️ ни одной проверки — бот не запускался?")
                continue
            mark = "🟢" if not down and not slow else ("🔴" if down else "🟠")
            lines.append(f"\n{mark} <b>{html.escape(site)}</b> — проверок {checks}, сбоев {down}, медленно {slow}")
            for kind in PAGE_ORDER:
                vals = [r["lcp"] for r in speed if r["page"] == kind and r.get("lcp")]
                if vals:
                    lines.append(f"   {PAGE_TITLES[kind]}: {_sec(statistics.median(vals))} / {_sec(max(vals))}")
        out[group] = ["\n".join(lines)]
    return out


def _send(token: str, chat: str, thread: int | None, text: str) -> None:
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if thread:
        payload["message_thread_id"] = thread
    req = urllib.request.Request(API.format(token=token), data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        json.load(resp)


def main(argv: list[str]) -> int:
    mode = next((a for a in argv if a in ("http", "speed", "summary")), None)
    if sys.stdout is None:  # pythonw из Планировщика — без консоли
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(DATA_DIR / f"last-run-{mode}.txt", "w", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not mode:
        print(__doc__)
        return 2
    _load_env()
    config = _config()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("MONITOR_CHAT_ID", "")
    dry = "--dry-run" in argv or not (token and chat)
    now = time.time()

    state_file = DATA_DIR / f"state-{mode}.json"
    state = _read_json(state_file, {})
    if mode == "summary":
        messages = _summary(config)
    else:
        results = run_http(config) if mode == "http" else run_speed(config)
        for r in results:
            r.update(ts=now, mode=mode)
            status = "OK  " if not r.get("problem") else "FAIL"
            took = f" {_sec(r['lcp'])}" if r.get("lcp") else ""
            print(f"{status} {r['site']:18} {r['page']:9}{took}" + (f" — {r['problem']}" if r.get("problem") else ""))
        if not dry:
            _log(results)
        messages = _messages(results, state, now, mode, config["remind_every_min"] * 60)

    for group, texts in messages.items():
        thread = config["groups"][group].get("thread_id")
        for text in texts:
            if dry:
                print(f"--- сообщение в тему {group} ---\n{text}")
            else:
                _send(token, chat, thread, text)
    # Состояние — после отправки: не ушло сообщение — повторим в следующий раз.
    if not dry:
        _write_json(state_file, state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
