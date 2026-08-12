/* Sotuvchi AI — platform operator's panel.
   Talks only to /api/platform/*, behind a session cookie the business panel
   never sees. Kept apart from app.js so the two cannot share state. */

const $ = (id) => document.getElementById(id);
let TENANTS = [];
let PLANS = [];
let SERIES = [];
let chartMetric = 'orders';
let signalFilter = null;

/* The alert bar returns on every sign-in and can be dismissed for the rest of
   the session. sessionStorage, not localStorage: dismissing means "read it",
   not "never show me problems again". */
const DISMISS_KEY = 'plat.alerts.dismissed';
let alertsDismissed = sessionStorage.getItem(DISMISS_KEY) === '1';

const fmt = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString('uz-UZ'));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const cap = (v) => (v === null || v === undefined ? '∞' : fmt(v));
const initials = (s) => (s || '?').trim().charAt(0).toUpperCase();

/** Long sums are unreadable in a card: 51 600 000 becomes 51.6M. */
function short(n) {
    const v = Number(n) || 0;
    if (v >= 1e9) return (v / 1e9).toFixed(1).replace(/\.0$/, '') + ' mlrd';
    if (v >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + ' mln';
    if (v >= 1e3) return (v / 1e3).toFixed(0) + ' ming';
    return fmt(v);
}

function toast(msg, kind = '') {
    const t = $('plat-toast');
    t.textContent = msg;
    t.className = `toast ${kind}`;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.hidden = true; }, 3000);
}

/** Single gate for every call, so a session that lapsed mid-shift returns to
 *  the login screen instead of quietly rendering an empty panel. */
async function api(url, options = {}) {
    const resp = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
    if (resp.status === 401) { showLogin(); throw new Error('unauthorized'); }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `Xatolik (${resp.status})`);
    return data;
}

// ═══ KIRISH ═══
function showLogin() {
    $('plat-login').hidden = false;
    $('plat-app').hidden = true;
}

function showPanel(admin) {
    $('plat-login').hidden = true;
    $('plat-app').hidden = false;
    $('who-name').textContent = admin.full_name || 'Administrator';
    $('who-mail').textContent = admin.email;
    $('who-av').textContent = initials(admin.full_name || admin.email);
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
        // A fresh sign-in is a fresh shift: whatever was dismissed last time
        // comes back, because this board has not been read yet today.
        sessionStorage.removeItem(DISMISS_KEY);
        alertsDismissed = false;
        showPanel(d.admin);
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

// ═══ NAVIGATSIYA ═══
const VIEW_NAMES = { home: 'Umumiy holat', plans: 'Tariflar', audit: 'Audit' };

function goto(view) {
    document.querySelectorAll('.nav').forEach((n) => n.classList.toggle('on', n.dataset.view === view));
    Object.keys(VIEW_NAMES).forEach((v) => { $(`view-${v}`).hidden = v !== view; });
    $('crumb').textContent = VIEW_NAMES[view];
    if (view === 'plans') loadPlans();
    if (view === 'audit') loadAudit();
}

document.querySelectorAll('.nav').forEach((n) =>
    n.addEventListener('click', () => goto(n.dataset.view)));
document.querySelectorAll('[data-goto]').forEach((b) =>
    b.addEventListener('click', () => goto(b.dataset.goto)));

// ═══ YUKLASH ═══
async function loadAll() {
    await Promise.all([loadStats(), loadTenants(), loadPlans(), loadSeries()]);
}

async function loadStats() {
    const s = await api('/api/platform/stats');
    const c = s.cost || {};
    const spend = c.configured
        ? (c.rate_configured ? `${short(c.uzs)}<small>UZS</small>` : `$${c.usd ?? 0}`)
        : '—';

    $('home-sub').textContent =
        `${s.tenants} biznes · ${s.conversations} suhbat · ${fmt(s.orders)} buyurtma`;

    $('plat-cards').innerHTML = `
        <div class="card hero">
            <div class="card-top">
                <span class="card-ico">◆</span>
                <div>
                    <div class="card-name">Umumiy tushum</div>
                    <div class="card-sub">Barcha bizneslar bo'yicha</div>
                </div>
            </div>
            <div class="card-val">${short(s.revenue)}<small>UZS</small></div>
            <div class="card-foot"><span>${fmt(s.orders)} buyurtma</span><span>→</span></div>
        </div>

        <div class="card" data-goto-card="home">
            <div class="card-top">
                <span class="card-ico">▤</span>
                <div>
                    <div class="card-name">Bizneslar</div>
                    <div class="card-sub">Servisdagi do'konlar</div>
                </div>
            </div>
            <div class="card-val">${fmt(s.tenants)}<span class="tag">${s.tenants_active} faol</span></div>
            <div class="card-foot"><span>Ro'yxatni ko'rish</span><span>→</span></div>
        </div>

        <div class="card" data-goto-card="plans">
            <div class="card-top">
                <span class="card-ico">◈</span>
                <div>
                    <div class="card-name">AI xarajati</div>
                    <div class="card-sub">${fmt(s.tokens)} token</div>
                </div>
            </div>
            <div class="card-val">${spend}</div>
            <div class="card-foot">
                <span>${c.configured ? 'Tariflarni ko\'rish' : '.env da narx sozlanmagan'}</span><span>→</span>
            </div>
        </div>`;

    $('plat-cards').querySelectorAll('[data-goto-card]').forEach((c2) => {
        c2.style.cursor = 'pointer';
        c2.addEventListener('click', () => {
            const v = c2.dataset.gotoCard;
            if (v === 'home') document.querySelector('#view-home .panel:last-child')
                .scrollIntoView({ behavior: 'smooth', block: 'start' });
            else goto(v);
        });
    });
}

async function loadTenants() {
    TENANTS = await api('/api/platform/tenants');
    renderAlerts();
    renderRows();
}

// ═══ SIGNALLAR ═══
/** A business's worst problem, or null. Drives the alert bar, the row avatar
 *  and the status pill, so the three can never disagree. */
function signalOf(t) {
    if (!t.is_active) return 'off';
    const over = (u, c) => c != null && u >= c;
    const near = (u, c) => c != null && u >= c * 0.8;
    if (over(t.products, t.product_limit) || over(t.ai_messages_month, t.ai_limit)) return 'alert';
    if (near(t.products, t.product_limit) || near(t.ai_messages_month, t.ai_limit)) return 'warn';
    return null;
}

function signalCounts() {
    const c = { alert: 0, warn: 0, off: 0 };
    TENANTS.forEach((t) => { const s = signalOf(t); if (s) c[s] += 1; });
    return c;
}

function renderAlerts() {
    const box = $('plat-alerts');
    const counts = signalCounts();
    const chips = [
        ['alert', counts.alert, 'limitdan oshgan'],
        ['warn', counts.warn, 'limitga yaqin'],
        ['off', counts.off, 'to\'xtatilgan'],
    ].filter(([, n]) => n > 0);

    const total = chips.reduce((a, [, n]) => a + n, 0);
    const badge = $('alerts-count');
    badge.textContent = total;
    badge.hidden = total === 0;

    if (!chips.length || alertsDismissed) { box.hidden = true; return; }

    box.hidden = false;
    box.innerHTML = `<span class="alerts-lead">E'tibor kerak</span>`
        + chips.map(([kind, n, label]) =>
            `<button class="alert-chip ${signalFilter === kind ? 'on' : ''}" data-signal="${kind}">
                <b>${n}</b> ${label}</button>`).join('')
        + `<button class="alerts-x" id="alerts-x" aria-label="Yopish" title="Yopish">✕</button>`;

    box.querySelectorAll('[data-signal]').forEach((chip) => {
        chip.addEventListener('click', () => {
            // Tapping the active chip clears the filter, so one control both
            // applies and undoes it.
            const next = chip.dataset.signal;
            signalFilter = next === signalFilter ? null : next;
            renderAlerts();
            renderRows();
            document.querySelector('#view-home .panel:last-child')
                .scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    });

    $('alerts-x').addEventListener('click', () => {
        alertsDismissed = true;
        sessionStorage.setItem(DISMISS_KEY, '1');
        signalFilter = null;
        box.hidden = true;
        renderRows();
    });
}

/* The bell reopens the bar after it has been dismissed. */
$('alerts-btn').addEventListener('click', () => {
    alertsDismissed = false;
    sessionStorage.removeItem(DISMISS_KEY);
    goto('home');
    renderAlerts();
});

// ═══ JADVAL ═══
/** Usage against a cap. A null cap is unlimited — a different thing from
 *  "nothing used", and it must not draw a full bar. */
function meter(used, capValue) {
    if (capValue === null || capValue === undefined) {
        return `<div class="meter"><div class="meter-nums"><span>${fmt(used)}</span>
                <span class="meter-inf">∞</span></div></div>`;
    }
    const pct = Math.min(100, Math.round((used / capValue) * 100));
    const cls = pct >= 100 ? 'over' : pct >= 80 ? 'warn' : '';
    return `<div class="meter">
        <div class="meter-nums"><span>${fmt(used)}</span><span class="cap">${fmt(capValue)}</span></div>
        <div class="meter-track"><div class="meter-fill ${cls}" style="width:${pct}%"></div></div>
    </div>`;
}

const STATE = {
    alert: ['bad', 'Limitdan oshgan'],
    warn: ['warn', 'Limitga yaqin'],
    off: ['idle', 'To\'xtatilgan'],
};

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
        const [cls, label] = STATE[sig] || ['ok', 'Faol'];
        return `
        <tr class="row ${sig ? `sig-${sig}` : ''}" data-id="${esc(t.id)}">
            <td>
                <div class="biz">
                    <span class="biz-av">${esc(initials(t.business_name))}</span>
                    <div>
                        <div class="biz-name">${esc(t.business_name)}</div>
                        <div class="biz-mail">${esc(t.owner_email || '—')}</div>
                    </div>
                </div>
            </td>
            <td><span class="plan-tag">${esc(t.plan_title)}</span></td>
            <td><span class="state ${cls}">${label}</span></td>
            <td>${meter(t.products, t.product_limit)}</td>
            <td>${meter(t.ai_messages_month, t.ai_limit)}</td>
            <td class="num">${fmt(t.orders)}</td>
            <td>${t.telegram_connected
                ? `<span class="state ok">@${esc(t.telegram_username || 'ulangan')}</span>`
                : '<span class="cell-dim">ulanmagan</span>'}</td>
            <td class="cell-dim">${esc(t.last_activity || '—')}</td>
        </tr>`;
    }).join('');

    body.querySelectorAll('tr[data-id]').forEach((tr) =>
        tr.addEventListener('click', () => openTenant(tr.dataset.id)));
}

$('plat-search').addEventListener('input', renderRows);
$('plat-plan-filter').addEventListener('change', renderRows);

// ═══ DIAGRAMMA ═══
async function loadSeries() {
    SERIES = await api('/api/platform/series?months=7');
    renderChart();
}

function renderChart() {
    const box = $('plat-chart');
    const vals = SERIES.map((p) => p[chartMetric] || 0);
    const peak = Math.max(...vals, 1);

    // Four gridline labels, rounded so the axis reads in whole steps
    const step = Math.ceil(peak / 3);
    const ticks = [step * 3, step * 2, step, 0];

    box.innerHTML = `
        <div class="chart-y">${ticks.map((t) => `<span>${short(t)}</span>`).join('')}</div>
        <div class="chart-plot">
            ${SERIES.map((p) => {
                const v = p[chartMetric] || 0;
                const h = Math.max(2, Math.round((v / (step * 3 || 1)) * 100));
                return `
                <div class="bar-slot ${p.current ? 'now' : ''}">
                    <div class="tip">
                        <div class="tip-h">${esc(p.label)} ${p.year}</div>
                        <div class="tip-row"><span>Buyurtma</span><b>${fmt(p.orders)}</b></div>
                        <div class="tip-row"><span>Suhbat</span><b>${fmt(p.conversations)}</b></div>
                        <div class="tip-row up"><span>Tushum</span><b>${short(p.revenue)}</b></div>
                    </div>
                    <div class="bar" style="height:${Math.min(h, 100)}%"></div>
                    <div class="bar-x">${esc(p.label)}</div>
                </div>`;
            }).join('')}
        </div>`;
}

document.querySelectorAll('[data-metric]').forEach((b) => {
    b.addEventListener('click', () => {
        chartMetric = b.dataset.metric;
        document.querySelectorAll('[data-metric]').forEach((x) => x.classList.toggle('on', x === b));
        renderChart();
    });
});

// ═══ BIZNES KARTASI ═══
function closeDrawer() {
    $('plat-drawer').hidden = true;
    $('plat-scrim').hidden = true;
}
$('drawer-close').addEventListener('click', closeDrawer);
$('plat-scrim').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

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
            <div class="block-t">Tarif va sarf</div>
            <label class="field"><span>Tarif</span><select id="dr-plan">${opts}</select></label>
            <div class="kv"><span>Mahsulot</span><b>${fmt(u.products.used)} / ${cap(u.products.limit)}</b></div>
            <div class="kv"><span>AI xabar, shu oy</span><b>${fmt(u.ai_messages.used)} / ${cap(u.ai_messages.limit)}</b></div>
            <div class="kv"><span>Operator</span><b>${fmt(u.operators.used)} / ${cap(u.operators.limit)}</b></div>
            <div class="acts">
                <button class="btn btn-green" id="dr-save-plan">Tarifni saqlash</button>
                <button class="btn ${d.is_active ? 'btn-red' : ''}" id="dr-toggle-active">
                    ${d.is_active ? 'Biznesni to\'xtatish' : 'Biznesni faollashtirish'}
                </button>
            </div>
        </div>

        <div class="block">
            <div class="block-t">Telegram</div>
            <div class="kv"><span>Bot</span><b>${d.telegram.connected ? '@' + esc(d.telegram.username || '') : 'ulanmagan'}</b></div>
            <div class="kv"><span>Webhook siri</span><b>${d.telegram.webhook_secret_set ? 'bor' : 'yo\'q'}</b></div>
            <div class="kv"><span>Buyurtmalar guruhi</span><b>${esc(d.telegram.orders_group || '—')}</b></div>
            ${d.telegram.connected
                ? `<div class="acts"><button class="btn btn-red" id="dr-tg">Bot ulanishini tozalash</button></div>`
                : ''}
        </div>

        <div class="block">
            <div class="block-t">AI sozlamalari</div>
            <label class="field"><span>Model</span>
                <input type="text" id="dr-model" value="${esc(d.ai.model_name)}"></label>
            <label class="field"><span>Temperature</span>
                <input type="number" id="dr-temp" step="0.1" min="0" max="1" value="${d.ai.temperature}"></label>
            <label class="field"><span>Operatorga uzatishdan oldin</span>
                <input type="number" id="dr-handoff" min="1" max="10" value="${d.ai.auto_handoff_after ?? 3}"></label>
            <label class="field"><span>Tizim prompti</span>
                <textarea id="dr-prompt">${esc(d.ai.system_prompt)}</textarea></label>
            <div class="acts">
                <button class="btn btn-green" id="dr-save-ai">AI sozlamalarini saqlash</button>
                <button class="btn btn-ghost" id="dr-bot">${d.ai.bot_enabled ? 'Botni o\'chirish' : 'Botni yoqish'}</button>
            </div>
        </div>

        <div class="block">
            <div class="block-t">Foydalanuvchilar</div>
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
        await Promise.all([loadTenants(), loadStats()]);
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

// ═══ TARIFLAR ═══
async function loadPlans() {
    PLANS = await api('/api/platform/plans');

    const filter = $('plat-plan-filter');
    if (filter.options.length <= 1) PLANS.forEach((p) => filter.add(new Option(p.title, p.name)));

    $('plat-mini-plans').innerHTML = PLANS.map((p) => `
        <div class="mini">
            <div class="mini-top">
                <span class="mini-dot"></span>
                <span class="mini-name">${esc(p.title)}</span>
            </div>
            <div class="mini-val">${short(p.price_uzs)}<small> UZS</small></div>
            <div class="mini-meta">${p.max_products === null ? 'Cheksiz' : fmt(p.max_products)} mahsulot ·
                ${p.max_ai_messages_monthly === null ? '∞' : fmt(p.max_ai_messages_monthly)} AI/oy</div>
            <div class="mini-state ${p.tenants ? '' : 'idle'}">${p.tenants} ta biznes</div>
        </div>`).join('');

    $('plat-plans').innerHTML = PLANS.map((p) => `
        <div class="plan-card" data-plan="${esc(p.name)}">
            <h3>${esc(p.title)}</h3>
            <div class="plan-price">${fmt(p.price_uzs)} UZS / oy</div>
            <div class="plan-users">${p.tenants} ta biznes shu tarifda</div>
            <div class="plan-line"><span>Narx, UZS</span>
                <input type="number" data-f="price_uzs" value="${p.price_uzs}"></div>
            <div class="plan-line"><span>Mahsulot</span>
                <input type="number" data-f="max_products" value="${p.max_products ?? ''}" placeholder="∞"></div>
            <div class="plan-line"><span>AI xabar / oy</span>
                <input type="number" data-f="max_ai_messages_monthly" value="${p.max_ai_messages_monthly ?? ''}" placeholder="∞"></div>
            <div class="plan-line"><span>Operator</span>
                <input type="number" data-f="max_operators" value="${p.max_operators ?? ''}" placeholder="∞"></div>
            <div class="acts"><button class="btn btn-green" data-save="${esc(p.name)}">Saqlash</button></div>
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

// ═══ AUDIT ═══
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
            <td><span class="state idle">${esc(r.action)}</span></td>
            <td>${esc(names[r.tenant_id] || r.tenant_id || '—')}</td>
            <td class="cell-dim">${esc(r.details ? JSON.stringify(r.details) : '')}</td>
        </tr>`).join('');
}

// ═══ BOSHLASH ═══
(async () => {
    try { showPanel(await api('/api/platform/auth/me')); }
    catch { showLogin(); }
})();
