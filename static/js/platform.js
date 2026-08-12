/* Sotuvchi AI — Dispetcher console.
   Talks only to /api/platform/*, and carries a session cookie the business
   panel never sees. Kept apart from app.js so the two cannot share state. */

const $ = (id) => document.getElementById(id);
let TENANTS = [];
let PLANS = [];
let signalFilter = null;   // set by an alert chip: show only flagged rows

const fmt = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString('uz-UZ'));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(msg, kind = '') {
    const t = $('plat-toast');
    t.textContent = msg;
    t.className = `toast ${kind}`;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.hidden = true; }, 3000);
}

/** Single gate for every call, so a session that lapsed mid-shift drops to the
 *  login screen instead of quietly rendering an empty board. */
async function api(url, options = {}) {
    const resp = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
    if (resp.status === 401) { showLogin(); throw new Error('unauthorized'); }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `Xatolik (${resp.status})`);
    return data;
}

// ─── Kirish ──────────────────────────────────────────────────────────────────
function showLogin() {
    $('plat-login').hidden = false;
    $('plat-app').hidden = true;
}

function showConsole(admin) {
    $('plat-login').hidden = true;
    $('plat-app').hidden = false;
    $('plat-admin-email').textContent = admin.email;
    loadAll();
}

$('plat-login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('plat-login-btn');
    const err = $('plat-login-error');
    err.textContent = '';
    btn.disabled = true;
    btn.textContent = 'Tekshirilmoqda';
    try {
        const d = await api('/api/platform/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email: $('plat-email').value, password: $('plat-password').value }),
        });
        $('plat-password').value = '';
        showConsole(d.admin);
    } catch (e2) {
        err.textContent = e2.message === 'unauthorized' ? 'Email yoki parol noto\'g\'ri.' : e2.message;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Kirish';
    }
});

$('plat-logout').addEventListener('click', async () => {
    await fetch('/api/platform/auth/logout', { method: 'POST' });
    showLogin();
});

// ─── Bo'limlar ───────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t === tab));
        ['businesses', 'plans', 'audit'].forEach((v) => {
            $(`view-${v}`).hidden = v !== tab.dataset.view;
        });
        if (tab.dataset.view === 'plans') loadPlans();
        if (tab.dataset.view === 'audit') loadAudit();
    });
});

// ─── Yuklash ─────────────────────────────────────────────────────────────────
async function loadAll() {
    await Promise.all([loadStats(), loadTenants(), loadPlans()]);
}

async function loadStats() {
    const s = await api('/api/platform/stats');
    const c = s.cost || {};
    const spend = c.configured
        ? (c.rate_configured ? `${fmt(c.uzs)}<small>UZS</small>` : `$${c.usd ?? 0}`)
        : '—';
    $('plat-stats').innerHTML = [
        [fmt(s.tenants), 'Biznes', `${s.tenants_active} faol`],
        [fmt(s.orders), 'Buyurtma', `${fmt(s.revenue)} UZS`],
        [fmt(s.conversations), 'Suhbat', ''],
        [fmt(s.tokens), 'Token', `${fmt(s.prompt_tokens)} / ${fmt(s.output_tokens)}`],
        [spend, 'AI xarajati', c.configured ? '' : 'narx sozlanmagan'],
    ].map(([val, label, note]) => `
        <div class="stat">
            <div class="stat-val">${val}</div>
            <div class="stat-label">${label}</div>
            <div class="stat-note">${note}</div>
        </div>`).join('');
}

async function loadTenants() {
    TENANTS = await api('/api/platform/tenants');
    renderAlerts();
    renderRows();
}

/** What a business's worst problem is, or null when it has none.
 *  This drives both the row rail and the alert strip, so the two can never
 *  disagree about who needs attention. */
function signalOf(t) {
    if (!t.is_active) return 'off';
    const over = (used, cap) => cap != null && used >= cap;
    const near = (used, cap) => cap != null && used >= cap * 0.8;
    if (over(t.products, t.product_limit) || over(t.ai_messages_month, t.ai_limit)) return 'alert';
    if (near(t.products, t.product_limit) || near(t.ai_messages_month, t.ai_limit)) return 'warn';
    return null;
}

/** The strip exists only when something is wrong — a calm board is the healthy
 *  state, so its absence is as meaningful as its contents. */
function renderAlerts() {
    const box = $('plat-alerts');
    const counts = { alert: 0, warn: 0, off: 0 };
    TENANTS.forEach((t) => { const s = signalOf(t); if (s) counts[s] += 1; });

    const chips = [
        ['alert', counts.alert, 'limitdan oshgan'],
        ['warn', counts.warn, 'limitga yaqin'],
        ['off', counts.off, 'to\'xtatilgan'],
    ].filter(([, n]) => n > 0);

    if (!chips.length) { box.hidden = true; return; }

    box.hidden = false;
    box.innerHTML = `<span class="alerts-lead">E'tibor kerak</span>` + chips.map(([kind, n, label]) =>
        `<button class="alert-chip" data-signal="${kind}"><b>${n}</b> ${label}</button>`).join('')
        + (signalFilter ? `<button class="alert-chip" data-signal="">Filtrni olib tashlash</button>` : '');

    box.querySelectorAll('[data-signal]').forEach((chip) => {
        chip.addEventListener('click', () => {
            signalFilter = chip.dataset.signal || null;
            renderAlerts();
            renderRows();
        });
    });
}

/** Usage against a cap. A null cap is unlimited, which is a different thing
 *  from "nothing used" and must not draw a full bar. */
function meter(used, cap) {
    if (cap === null || cap === undefined) {
        return `<div class="meter"><div class="meter-nums"><span>${fmt(used)}</span>
                <span class="meter-inf">∞</span></div></div>`;
    }
    const pct = Math.min(100, Math.round((used / cap) * 100));
    const cls = pct >= 100 ? 'over' : pct >= 80 ? 'warn' : '';
    return `<div class="meter">
        <div class="meter-nums"><span>${fmt(used)}</span><span class="cap">${fmt(cap)}</span></div>
        <div class="meter-track"><div class="meter-fill ${cls}" style="width:${pct}%"></div></div>
    </div>`;
}

function renderRows() {
    const q = ($('plat-search').value || '').toLowerCase().trim();
    const plan = $('plat-plan-filter').value;

    const rows = TENANTS.filter((t) => {
        if (plan && t.plan !== plan) return false;
        if (signalFilter && signalOf(t) !== signalFilter) return false;
        if (!q) return true;
        return (t.business_name || '').toLowerCase().includes(q)
            || (t.owner_email || '').toLowerCase().includes(q);
    });

    const body = $('plat-rows');
    if (!rows.length) {
        body.innerHTML = '<tr><td colspan="8" class="empty">Bu shartlarga mos biznes yo\'q.</td></tr>';
        return;
    }

    body.innerHTML = rows.map((t) => {
        const sig = signalOf(t);
        return `
        <tr class="row ${sig ? `sig-${sig}` : ''}" data-id="${esc(t.id)}">
            <td>
                <div class="biz-name">${esc(t.business_name)}</div>
                <div class="biz-mail">${esc(t.owner_email || '—')}</div>
            </td>
            <td><span class="plan-tag">${esc(t.plan_title)}</span></td>
            <td><span class="state ${t.is_active ? 'on' : 'off'}">${t.is_active ? 'faol' : 'to\'xtatilgan'}</span></td>
            <td>${meter(t.products, t.product_limit)}</td>
            <td>${meter(t.ai_messages_month, t.ai_limit)}</td>
            <td class="num">${fmt(t.orders)}</td>
            <td>${t.telegram_connected
                ? `<span class="tg"><span class="tg-dot"></span>@${esc(t.telegram_username || '')}</span>`
                : '<span class="tg-none">ulanmagan</span>'}</td>
            <td class="cell-dim">${esc(t.last_activity || '—')}</td>
        </tr>`;
    }).join('');

    body.querySelectorAll('tr[data-id]').forEach((tr) => {
        tr.addEventListener('click', () => openTenant(tr.dataset.id));
    });
}

$('plat-search').addEventListener('input', renderRows);
$('plat-plan-filter').addEventListener('change', renderRows);

// ─── Biznes kartasi ──────────────────────────────────────────────────────────
function closeDrawer() {
    $('plat-drawer').hidden = true;
    $('plat-scrim').hidden = true;
}
$('drawer-close').addEventListener('click', closeDrawer);
$('plat-scrim').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

const cap = (v) => (v === null || v === undefined ? '∞' : fmt(v));

async function openTenant(id) {
    $('plat-drawer').hidden = false;
    $('plat-scrim').hidden = false;
    $('drawer-body').innerHTML = '<p class="empty">Yuklanmoqda</p>';

    const d = await api(`/api/platform/tenants/${id}`);
    $('drawer-title').textContent = d.business_name;
    $('drawer-sub').textContent = `${d.id} · ${d.created_at || ''}`;

    const u = d.usage;
    const opts = PLANS.map((p) =>
        `<option value="${esc(p.name)}" ${p.name === d.plan ? 'selected' : ''}>${esc(p.title)}</option>`).join('');

    $('drawer-body').innerHTML = `
        <div class="block">
            <span class="eyebrow">Tarif va sarf</span>
            <label class="field"><span>Tarif</span><select id="dr-plan">${opts}</select></label>
            <div class="kv"><span>Mahsulot</span><b>${fmt(u.products.used)} / ${cap(u.products.limit)}</b></div>
            <div class="kv"><span>AI xabar, shu oy</span><b>${fmt(u.ai_messages.used)} / ${cap(u.ai_messages.limit)}</b></div>
            <div class="kv"><span>Operator</span><b>${fmt(u.operators.used)} / ${cap(u.operators.limit)}</b></div>
            <div class="acts">
                <button class="btn" id="dr-save-plan">Tarifni saqlash</button>
                <button class="btn ${d.is_active ? 'btn-alert' : ''}" id="dr-toggle-active">
                    ${d.is_active ? 'Biznesni to\'xtatish' : 'Biznesni faollashtirish'}
                </button>
            </div>
        </div>

        <div class="block">
            <span class="eyebrow">Telegram</span>
            <div class="kv"><span>Bot</span><b>${d.telegram.connected ? '@' + esc(d.telegram.username || '') : 'ulanmagan'}</b></div>
            <div class="kv"><span>Webhook siri</span><b>${d.telegram.webhook_secret_set ? 'bor' : 'yo\'q'}</b></div>
            <div class="kv"><span>Buyurtmalar guruhi</span><b>${esc(d.telegram.orders_group || '—')}</b></div>
            ${d.telegram.connected ? `<div class="acts">
                <button class="btn btn-alert" id="dr-tg">Bot ulanishini tozalash</button></div>` : ''}
        </div>

        <div class="block">
            <span class="eyebrow">AI sozlamalari</span>
            <label class="field"><span>Model</span>
                <input type="text" id="dr-model" value="${esc(d.ai.model_name)}"></label>
            <label class="field"><span>Temperature</span>
                <input type="number" id="dr-temp" step="0.1" min="0" max="1" value="${d.ai.temperature}"></label>
            <label class="field"><span>Operatorga uzatishdan oldin</span>
                <input type="number" id="dr-handoff" min="1" max="10" value="${d.ai.auto_handoff_after ?? 3}"></label>
            <label class="field"><span>Tizim prompti</span>
                <textarea id="dr-prompt">${esc(d.ai.system_prompt)}</textarea></label>
            <div class="acts">
                <button class="btn" id="dr-save-ai">AI sozlamalarini saqlash</button>
                <button class="btn btn-quiet" id="dr-bot">${d.ai.bot_enabled ? 'Botni o\'chirish' : 'Botni yoqish'}</button>
            </div>
        </div>

        <div class="block">
            <span class="eyebrow">Foydalanuvchilar</span>
            ${d.users.map((x) => `<div class="kv"><span>${esc(x.email)}</span><b>${esc(x.role)}</b></div>`).join('')
              || '<p class="empty">Yo\'q</p>'}
        </div>`;

    $('dr-save-plan').addEventListener('click', () =>
        patchTenant(id, { plan: $('dr-plan').value }, 'Tarif saqlandi'));

    $('dr-toggle-active').addEventListener('click', () => {
        const stopping = d.is_active;
        if (stopping && !confirm(`"${d.business_name}" to'xtatilsinmi? Egasi panelga kira olmay qoladi.`)) return;
        patchTenant(id, { is_active: !d.is_active }, stopping ? 'Biznes to\'xtatildi' : 'Biznes faollashtirildi');
    });

    $('dr-save-ai').addEventListener('click', () => patchAi(id, {
        model_name: $('dr-model').value.trim(),
        temperature: parseFloat($('dr-temp').value),
        auto_handoff_after: parseInt($('dr-handoff').value, 10),
        system_prompt: $('dr-prompt').value,
    }));

    $('dr-bot').addEventListener('click', () => patchAi(id, { bot_enabled: !d.ai.bot_enabled }));

    const tg = $('dr-tg');
    if (tg) {
        tg.addEventListener('click', async () => {
            if (!confirm('Bot ulanishi tozalansinmi? Biznes o\'z panelidan qayta ulashi kerak bo\'ladi.')) return;
            try {
                await api(`/api/platform/tenants/${id}/telegram/disconnect`, { method: 'POST' });
                toast('Bot ulanishi tozalandi');
                await loadTenants();
                openTenant(id);
            } catch (e) { toast(e.message, 'err'); }
        });
    }
}

async function patchTenant(id, body, okMsg) {
    try {
        const r = await api(`/api/platform/tenants/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
        toast(r.status === 'unchanged' ? 'O\'zgarish yo\'q' : okMsg);
        await loadTenants();
        openTenant(id);
    } catch (e) { toast(e.message, 'err'); }
}

async function patchAi(id, body) {
    try {
        const r = await api(`/api/platform/tenants/${id}/ai`, { method: 'PATCH', body: JSON.stringify(body) });
        toast(r.status === 'unchanged' ? 'O\'zgarish yo\'q' : 'AI sozlamalari saqlandi');
        openTenant(id);
    } catch (e) { toast(e.message, 'err'); }
}

// ─── Tariflar ────────────────────────────────────────────────────────────────
async function loadPlans() {
    PLANS = await api('/api/platform/plans');

    const filter = $('plat-plan-filter');
    if (filter.options.length <= 1) PLANS.forEach((p) => filter.add(new Option(p.title, p.name)));

    $('plat-plans').innerHTML = PLANS.map((p) => `
        <div class="plan" data-plan="${esc(p.name)}">
            <h3>${esc(p.title)}</h3>
            <div class="plan-price">${fmt(p.price_uzs)} UZS / oy</div>
            <div class="plan-users">${p.tenants} biznes</div>
            <div class="plan-line"><span>Narx, UZS</span>
                <input type="number" data-f="price_uzs" value="${p.price_uzs}"></div>
            <div class="plan-line"><span>Mahsulot</span>
                <input type="number" data-f="max_products" value="${p.max_products ?? ''}" placeholder="∞"></div>
            <div class="plan-line"><span>AI xabar / oy</span>
                <input type="number" data-f="max_ai_messages_monthly" value="${p.max_ai_messages_monthly ?? ''}" placeholder="∞"></div>
            <div class="plan-line"><span>Operator</span>
                <input type="number" data-f="max_operators" value="${p.max_operators ?? ''}" placeholder="∞"></div>
            <div class="acts"><button class="btn" data-save="${esc(p.name)}">Saqlash</button></div>
            <p class="plan-note">Bo'sh maydon — cheksiz.</p>
        </div>`).join('');

    $('plat-plans').querySelectorAll('[data-save]').forEach((b) =>
        b.addEventListener('click', () => savePlan(b.dataset.save)));
}

async function savePlan(name) {
    const card = $('plat-plans').querySelector(`[data-plan="${name}"]`);
    const body = { unlimited: [] };
    card.querySelectorAll('input[data-f]').forEach((inp) => {
        const field = inp.dataset.f;
        const raw = inp.value.trim();
        // Blank means unlimited, which is null — and null cannot also stand for
        // "unchanged", so those fields are named explicitly instead.
        if (raw === '') {
            if (field !== 'price_uzs') body.unlimited.push(field);
        } else {
            body[field] = Number(raw);
        }
    });
    try {
        const r = await api(`/api/platform/plans/${name}`, { method: 'PATCH', body: JSON.stringify(body) });
        toast(r.status === 'unchanged' ? 'O\'zgarish yo\'q' : 'Tarif saqlandi');
        await Promise.all([loadPlans(), loadTenants()]);
    } catch (e) { toast(e.message, 'err'); }
}

// ─── Audit ───────────────────────────────────────────────────────────────────
async function loadAudit() {
    const rows = await api('/api/platform/audit?limit=200');
    const body = $('plat-audit-rows');
    if (!rows.length) {
        body.innerHTML = '<tr><td colspan="5" class="empty">Hali amal qilinmagan.</td></tr>';
        return;
    }
    const names = Object.fromEntries(TENANTS.map((t) => [t.id, t.business_name]));
    body.innerHTML = rows.map((r) => `
        <tr>
            <td class="cell-dim num" style="white-space:nowrap">${esc(r.created_at)}</td>
            <td>${esc(r.admin_email)}</td>
            <td><span class="act-name">${esc(r.action)}</span></td>
            <td>${esc(names[r.tenant_id] || r.tenant_id || '—')}</td>
            <td class="act-detail">${esc(r.details ? JSON.stringify(r.details) : '')}</td>
        </tr>`).join('');
}

// ─── Boshlash ────────────────────────────────────────────────────────────────
(async () => {
    try { showConsole(await api('/api/platform/auth/me')); }
    catch { showLogin(); }
})();
