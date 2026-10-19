// Мониторинг продов из Cloudflare: каждые 5 минут, 24/7 — сайт отвечает (500/502/503/504, нет ответа).
// Скорость в браузере меряет tools/site_monitor.py с компьютера QA — здесь только ответ сервера.
//
// Сайты и страницы — из tools/site_monitor.json (один список на оба бота), кроме http_on_pc —
// их коды ответа проверяет компьютер QA (alo.md режет запросы Cloudflare 403).
// Товар — первая ссылка /product/ из HTML категории (если сайт отдаёт её сервером).
// Тревога — после 3 неудачных попыток подряд с паузой 20 с: разовый сбой сети не алерт.
// Состояние сбоев — в KV (пишем только при изменении: бесплатный лимит 1000 записей в сутки).
// Секреты: TELEGRAM_BOT_TOKEN, MONITOR_CHAT_ID (wrangler secret put).
// BYPASS_TOKEN (необязательно) — уходит заголовком X-QA-Monitor; админы сайта могут пропускать запросы с ним
// мимо защиты. Без их согласия защиту не обходим: 403 просто не считается сбоем.
//
// Вручную: GET /run?key=<RUN_KEY> — прогон без отправки в Telegram, ответ JSON (проверить, пускает ли прод).

import config from "../tools/site_monitor.json";

const TIMEOUT_MS = 30000;
const SLOW_MS = 10000;
const RETRIES = 3;
const RETRY_PAUSE_MS = 20000;
const SUBREQUEST_BUDGET = 45; // бесплатный тариф — 50 запросов на запуск, оставляем на Telegram
const REMIND_MS = (config.remind_every_min || 120) * 60 * 1000;
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";
const TITLES = { home: "Главная", category: "Категория", product: "Карточка товара", search: "Поиск" };
const ORDER = ["home", "category", "product", "search"];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const span = (ms) => {
  const m = Math.floor(ms / 60000);
  return m < 60 ? `${m} мин` : `${Math.floor(m / 60)} ч ${String(m % 60).padStart(2, "0")} мин`;
};

function pages() {
  const out = [];
  for (const g of Object.values(config.groups)) {
    for (const [site, paths] of Object.entries(g.sites)) {
      if ((config.http_on_pc || []).includes(site)) continue; // проверяет компьютер QA
      for (const kind of ORDER) if (paths[kind]) out.push({ site, kind, path: paths[kind] });
    }
  }
  return out;
}

async function probe(ctx, url, wantHtml = false) {
  ctx.used++;
  const started = Date.now();
  try {
    const resp = await fetch(url, {
      // Пропуск через защиту сайта — только если админы сайта согласились (см. README в шапке).
      headers: { "User-Agent": UA, ...(ctx.bypass ? { "X-QA-Monitor": ctx.bypass } : {}) },
      redirect: "follow",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const body = wantHtml ? await resp.text() : (await resp.arrayBuffer(), "");
    const ms = Date.now() - started;
    // 403 — защита сайта не пустила адрес Cloudflare (alo.md режет «чужие» IP). Сайт при этом работает —
    // это не сбой и не тревога; видно в /run и в логах (wrangler tail).
    if (resp.status === 403) return { ok: true, blocked: true, ms, body };
    if (resp.status >= 400) return { problem: `HTTP ${resp.status}`, ms };
    if (ms > SLOW_MS) return { problem: `сервер отвечает ${(ms / 1000).toFixed(0)} с`, ms };
    return { ok: true, ms, body };
  } catch (e) {
    const timeout = e && (e.name === "TimeoutError" || e.name === "AbortError");
    return { problem: timeout ? `нет ответа за ${TIMEOUT_MS / 1000} с` : `нет ответа: ${e.message || e}`, ms: Date.now() - started };
  }
}

async function check(env) {
  const ctx = { used: 0, bypass: env.BYPASS_TOKEN || "" };
  const list = pages();
  // Первый проход — параллельно; категории читаем целиком, чтобы взять из них товар.
  const first = await Promise.all(list.map((p) => probe(ctx, `https://${p.site}${p.path}`, p.kind === "category")));
  const results = list.map((p, i) => ({ ...p, ...first[i] }));
  for (const r of results.filter((r) => r.kind === "category" && r.ok && !r.blocked)) {
    const m = r.body.match(/href="(\/[a-z]{2}\/product\/[^"#?]+)"/);
    if (m) {
      const res = await probe(ctx, `https://${r.site}${m[1]}`);
      results.push({ site: r.site, kind: "product", path: m[1], ...res });
    }
  }
  for (const r of results) delete r.body;
  // Повторы — только упавшим, пока хватает лимита запросов.
  for (let attempt = 1; attempt < RETRIES; attempt++) {
    const failed = results.filter((r) => !r.ok);
    if (!failed.length || ctx.used + failed.length > SUBREQUEST_BUDGET) break;
    await sleep(RETRY_PAUSE_MS);
    const again = await Promise.all(failed.map((r) => probe(ctx, `https://${r.site}${r.path}`)));
    failed.forEach((r, i) => { if (again[i].ok) { delete r.problem; r.ok = true; r.ms = again[i].ms; } else r.problem = again[i].problem; });
  }
  return results;
}

function messages(results, state, now) {
  const bySite = {};
  let changed = false;
  for (const r of results) {
    const key = `${r.site}|${r.kind}`;
    const b = (bySite[r.site] ??= { new: [], still: [], fixed: [] });
    const prev = state[key];
    if (r.ok) {
      if (prev) {
        b.fixed.push(`• ${TITLES[r.kind]} — снова работает (длилось ~${span(now - prev.since)})`);
        delete state[key];
        changed = true;
      }
      continue;
    }
    const line = `• <b>${TITLES[r.kind]}</b>: ${esc(r.problem)}\n  ${esc(`https://${r.site}${r.path}`)}`;
    if (!prev) {
      state[key] = { since: now, notified: now };
      b.new.push(line);
      changed = true;
    } else if (now - prev.notified >= REMIND_MS) {
      prev.notified = now;
      b.still.push(`${line}\n  <i>уже ${span(now - prev.since)}</i>`);
      changed = true;
    }
  }
  const out = [];
  for (const [site, b] of Object.entries(bySite)) {
    const parts = [];
    if (b.new.length) parts.push(`🔴 <b>${esc(site)}</b> — не работает\n${b.new.join("\n")}`);
    if (b.still.length) parts.push(`🔁 <b>${esc(site)}</b> — всё ещё\n${b.still.join("\n")}`);
    if (b.fixed.length) parts.push(`🟢 <b>${esc(site)}</b>\n${b.fixed.join("\n")}`);
    if (parts.length) out.push(parts.join("\n\n"));
  }
  return { out, changed };
}

async function send(env, text) {
  const resp = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: env.MONITOR_CHAT_ID, text, parse_mode: "HTML", disable_web_page_preview: true }),
  });
  if (!resp.ok) throw new Error(`Telegram ${resp.status}: ${await resp.text()}`);
}

async function run(env) {
  const now = Date.now();
  const results = await check(env);
  const blocked = results.filter((r) => r.blocked).map((r) => `${r.site}${r.path}`);
  if (blocked.length) {
    const trace = await (await fetch("https://www.cloudflare.com/cdn-cgi/trace")).text().catch(() => "");
    const where = Object.fromEntries(trace.trim().split(/\r?\n/).map((l) => l.split("=")));
    console.log(`403 (защита сайта) с ${where.ip} / ${where.colo} / ${where.loc}: ${blocked.join(", ")}`);
  }
  const state = (await env.STATE.get("state", "json")) || {};
  const { out, changed } = messages(results, state, now);
  for (const text of out) await send(env, text);
  // Состояние — после отправки: не ушло сообщение — повторим в следующий раз.
  if (changed) await env.STATE.put("state", JSON.stringify(state));
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(run(env));
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/run" || !env.RUN_KEY || url.searchParams.get("key") !== env.RUN_KEY) {
      return new Response("not found", { status: 404 });
    }
    const results = await check(env);
    return Response.json(results.map(({ site, kind, path, ok, blocked, problem, ms }) => ({ site, kind, path, ok: !!ok, blocked: !!blocked, problem, ms })));
  },
};
