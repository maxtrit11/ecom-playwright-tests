"""Итоги прогона — сообщением в Telegram-канал, HTML-отчёт — файлом к нему.

Вызывается последним шагом workflow (`if: always()`):

    python tools/notify_telegram.py results.json,report.html [results2.json,report2.html ...]

Каждая пара — один этап прогона (основная суита, корзина Вид 2 …). Итоги этап
пишет сам через reporting.py, если ему задан `QA_RESULTS_JSON`. Этапа нет
(не запускался, упал до pytest) — пара пропускается, сообщение всё равно уходит:
молчание бота нельзя путать с «всё хорошо».

Окружение: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (секреты репозитория) и
стандартные GITHUB_* для ссылки на прогон. Без токена/чата — предупреждение
и выход с кодом 0: уведомление не должно ронять прогон.
"""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

API = "https://api.telegram.org/bot{token}/{method}"
MAX_BROKEN = 15          # дальше — «и ещё N», полный список в отчёте
TG_FILE_LIMIT = 50 * 1024 * 1024


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 3600:
        return f"{seconds // 60} мин"
    return f"{seconds // 3600} ч {(seconds % 3600) // 60:02d} мин"


def _call(token: str, method: str, fields: dict, file: Path | None = None) -> dict:
    url = API.format(token=token, method=method)
    if file is None:
        body = json.dumps(fields).encode()
        headers = {"Content-Type": "application/json"}
    else:
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{file.name}"\r\n'
            f"Content-Type: text/html\r\n\r\n".encode()
        )
        parts.append(file.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(parts)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def _stage_block(res: dict) -> list[str]:
    e = html.escape
    broken = res["broken"]
    icon = "❌" if broken else ("⚠️" if res["flaky"] else "✅")
    lines = [
        f"{icon} <b>{e(res['title'])}</b>",
        f"✅ {res['passed']}  ❌ {res['failed']}  🔥 {res['error']}  ⏭ {res['skipped']}"
        + (f"  🔁 {res['flaky']}" if res["flaky"] else "")
        + f"  · {res['total']} за {_fmt_duration(res['duration'])}",
    ]
    for b in broken[:MAX_BROKEN]:
        mark = "🔥" if b["outcome"] == "error" else "•"
        suite = f" <i>({e(b['suite'])})</i>" if b["suite"] else ""
        lines.append(f"{mark} {e(b['label'])}{suite}")
        if b["error"]:
            lines.append(f"   <code>{e(b['error'][:160])}</code>")
    if len(broken) > MAX_BROKEN:
        lines.append(f"… и ещё {len(broken) - MAX_BROKEN} — в отчёте")
    return lines


def main(pairs: list[str]) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("::warning title=Telegram::TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не заданы — уведомление не отправлено")
        return 0

    stages, reports = [], []
    for pair in pairs:
        res_path, _, rep_path = pair.partition(",")
        if Path(res_path).is_file():
            stages.append(json.loads(Path(res_path).read_text(encoding="utf-8")))
        if rep_path and Path(rep_path).is_file():
            reports.append(Path(rep_path))

    workflow = os.environ.get("GITHUB_WORKFLOW", "E2E")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else ""

    lines = [f"<b>{html.escape(workflow)}</b>"]
    if not stages:
        lines.append("🔥 Тесты не дошли до конца — итогов нет. Смотреть лог прогона.")
    for res in stages:
        lines.append("")
        lines.extend(_stage_block(res))
    if run_url:
        lines.append("")
        lines.append(f'<a href="{run_url}">Прогон в GitHub Actions</a>')

    text = "\n".join(lines)[:4000]
    ok = True
    try:
        r = _call(token, "sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML",
                                         "disable_web_page_preview": True})
        ok = r.get("ok", False)
        if not ok:
            print(f"::warning title=Telegram::sendMessage: {r}")
    except Exception as exc:
        print(f"::warning title=Telegram::sendMessage не ушёл: {exc}")
        return 0

    for rep in reports:
        if rep.stat().st_size > TG_FILE_LIMIT:
            print(f"::warning title=Telegram::{rep.name} больше 50 МБ — не отправлен, он есть в артефактах")
            continue
        try:
            r = _call(token, "sendDocument", {"chat_id": chat, "disable_notification": "true"}, file=rep)
            if not r.get("ok"):
                print(f"::warning title=Telegram::sendDocument {rep.name}: {r}")
        except Exception as exc:
            print(f"::warning title=Telegram::{rep.name} не отправлен: {exc}")
    print("Telegram: уведомление отправлено" if ok else "Telegram: см. предупреждения выше")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
