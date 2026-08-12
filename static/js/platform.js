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

// ═══ MODAL ═══
/** One reusable dialog. `fields` render the form; `onSubmit` returns a string
 *  to keep the dialog open showing that result (a one-time password), or
 *  nothing to close it. */
function openModal({ title, fields, submitLabel, onSubmit, danger }) {
    $('modal-title').textContent = title;
    $('modal').hidden = false;
    $('modal-scrim').hidden = false;

    const form = $('modal-form');
    form.innerHTML = fields.map((f) => `
        <label class="field">
            <span>${esc(f.label)}</span>
            ${f.type === 'select'
                ? `<select id="m-${f.name}">${f.options.map((o) =>
                    `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('')}</select>`
                : `<input type="${f.type || 'text'}" id="m-${f.name}"
                     ${f.required === false ? '' : 'required'}
                     placeholder="${esc(f.placeholder || '')}"
                     value="${esc(f.value || '')}">`}
        </label>`).join('')
        + `<p class="login-err" id="m-err"></p>
           <button type="submit" class="btn ${danger ? 'btn-red' : 'btn-green'} w-full" id="m-go">${esc(submitLabel)}</button>`;

    form.onsubmit = async (e) => {
        e.preventDefault();
        const btn = $('m-go');
        const err = $('m-err');
        err.textContent = '';
        btn.disabled = true;
        const values = Object.fromEntries(fields.map((f) => [f.name, $(`m-${f.name}`).value]));
        try {
            const result = await onSubmit(values);
            if (result) {
                form.innerHTML = `<p style="font-size:13px;color:var(--fg-2)">${result.text}</p>
                    <code class="reveal">${esc(result.reveal)}</code>
                    <p class="modal-note">${esc(result.note || '')}</p>
                    <button type="button" class="btn w-full" style="margin-top:14px" id="m-done">Yopish</button>`;
                $('m-done').onclick = closeModal;
            } else {
                closeModal();
            }
        } catch (e2) {
            err.textContent = e2.message;
            btn.disabled = false;
        }
    };
}

function closeModal() {
    $('modal').hidden = true;
    $('modal-scrim').hidden = true;
}
$('modal-close').addEventListener('click', closeModal);
$('modal-scrim').addEventListener('click', closeModal);

// ═══ NAVIGATSIYA ═══
const VIEW_NAMES = {
    home: 'Umumiy holat', plans: 'Tariflar', payments: 'To\'lovlar',
    admins: 'Adminlar', audit: 'Audit',
};
let payFilter = 'pending';

function goto(view) {
    document.querySelectorAll('.nav').forEach((n) => n.classList.toggle('on', n.dataset.view === view));
    Object.keys(VIEW_NAMES).forEach((v) => { $(`view-${v}`).hidden = v !== view; });
    $('crumb').textContent = VIEW_NAMES[view];
    if (view === 'plans') loadPlans();
    if (view === 'payments') loadPayments();
    if (view === 'admins') loadAdmins();
    if (view === 'audit') loadAudit();
}

// ═══ TO'LOVLAR ═══
const PAY_KIND = { topup: 'To\'ldirish', subscription: 'Tarif', adjustment: 'Tuzatish' };
const PAY_STATE = { pending: ['warn', 'Kutilmoqda'], confirmed: ['ok', 'Tasdiqlangan'], rejected: ['bad', 'Rad etilgan'] };

/** Pending count on the sidebar, so money waiting to be confirmed is visible
 *  from anywhere in the panel rather than only on its own page. */
async function refreshPendingCount() {
    try {
        const n = (await api('/api/platform/payments?status=pending')).length;
        const badge = $('nav-pay');
        badge.textContent = n;
        badge.hidden = n === 0;
    } catch { /* ignore — the badge is never worth an error */ }
}

async function loadPayments() {
    const rows = await api(`/api/platform/payments?status=${payFilter}&limit=200`);
    const body = $('plat-pay-rows');
    if (!rows.length) {
        body.innerHTML = `<tr><td colspan="7" class="empty">${
            payFilter === 'pending' ? 'Tasdiqlash kutayotgan to\'lov yo\'q.' : 'To\'lov yo\'q.'}</td></tr>`;
        return;
    }
    body.innerHTML = rows.map((p) => {
        const [cls, label] = PAY_STATE[p.status] || ['idle', p.status];
        const sign = p.amount >= 0 ? '+' : '';
        return `
        <tr>
            <td class="cell-dim num" style="white-space:nowrap">${esc(p.created_at)}</td>
            <td><span class="biz-name">${esc(p.business_name)}</span></td>
            <td class="cell-dim">${esc(PAY_KIND[p.kind] || p.kind)}</td>
            <td class="num" style="font-weight:600">${sign}${fmt(p.amount)}</td>
            <td class="cell-dim">${esc(p.note || '—')}</td>
            <td><span class="state ${cls}">${label}</span>${
                t.sub_status === 'expired' ? ' <span class="state bad">Muddati tugagan</span>'
                : t.sub_status === 'frozen' ? ' <span class="state idle">Muzlatilgan</span>' : ''}</td>
            <td class="num">${fmt(t.balance)}<div class="cell-dim">${
                t.days_left != null ? Math.round(t.days_left) + ' kun' : '—'}</div></td>
            <td style="text-align:right;white-space:nowrap">
                ${p.status === 'pending' && p.kind === 'topup' ? `
                    <button class="btn btn-green" data-ok="${esc(p.id)}">Tasdiqlash</button>
                    <button class="btn btn-red" data-no="${esc(p.id)}">Rad etish</button>` : ''}
            </td>
        </tr>`;
    }).join('');

    body.querySelectorAll('[data-ok]').forEach((b) =>
        b.addEventListener('click', () => decide(b.dataset.ok, 'confirm', 'Tasdiqlandi')));
    body.querySelectorAll('[data-no]').forEach((b) =>
        b.addEventListener('click', () => {
            if (confirm('To\'lov rad etilsinmi? Biznes hisobiga hech narsa tushmaydi.')) {
                decide(b.dataset.no, 'reject', 'Rad etildi');
            }
        }));
}

async function decide(id, action, okMsg) {
    try {
        await api(`/api/platform/payments/${id}/${action}`, { method: 'POST' });
        toast(okMsg);
        await Promise.all([loadPayments(), loadTenants(), refreshPendingCount()]);
    } catch (e) { toast(e.message, 'err'); }
}

document.querySelectorAll('[data-pay]').forEach((b) =>
    b.addEventListener('click', () => {
        payFilter = b.dataset.pay;
        document.querySelectorAll('[data-pay]').forEach((x) => x.classList.toggle('on', x === b));
        loadPayments();
    }));

// ═══ YANGI BIZNES ═══
$('btn-new-tenant').addEventListener('click', () => openModal({
    title: 'Yangi biznes',
    submitLabel: 'Yaratish',
    fields: [
        { name: 'business_name', label: 'Biznes nomi' },
        { name: 'email', label: 'Egasining emaili', type: 'email' },
        { name: 'password', label: 'Boshlang\'ich parol', type: 'text',
          value: Math.random().toString(36).slice(2, 12) },
        { name: 'plan', label: 'Tarif', type: 'select',
          options: PLANS.map((p) => ({ value: p.name, label: p.title })) },
    ],
    onSubmit: async (v) => {
        await api('/api/platform/tenants', { method: 'POST', body: JSON.stringify(v) });
        await Promise.all([loadTenants(), loadStats()]);
        return {
            text: `"${v.business_name}" yaratildi. Egasiga shu ma'lumotlarni bering:`,
            reveal: `${v.email}\n${v.password}`,
            note: 'Parol boshqa ko\'rsatilmaydi. Egasi kirgach o\'zgartirishi kerak.',
        };
    },
}));

// ═══ ADMINLAR ═══
async function loadAdmins() {
    const rows = await api('/api/platform/admins');
    const me = $('who-mail').textContent;
    $('plat-admins-rows').innerHTML = rows.map((a) => `
        <tr>
            <td>
                <div class="biz">
                    <span class="biz-av">${esc(initials(a.full_name || a.email))}</span>
                    <div>
                        <div class="biz-name">${esc(a.full_name || 'Administrator')}</div>
                        <div class="biz-mail">${esc(a.email)}${a.email === me ? ' · siz' : ''}</div>
                    </div>
                </div>
            </td>
            <td><span class="state ${a.is_active ? 'ok' : 'idle'}">${a.is_active ? 'Faol' : 'O\'chirilgan'}</span></td>
            <td class="cell-dim">${esc(a.created_at || '—')}</td>
            <td class="cell-dim">${esc(a.last_login_at || 'hech qachon')}</td>
            <td style="text-align:right">
                ${a.email === me ? ''
                    : `<button class="btn ${a.is_active ? 'btn-red' : 'btn-ghost'}"
                          data-admin="${esc(a.id)}" data-to="${a.is_active ? '0' : '1'}">
                        ${a.is_active ? 'O\'chirish' : 'Yoqish'}</button>`}
            </td>
        </tr>`).join('');

    $('plat-admins-rows').querySelectorAll('[data-admin]').forEach((b) =>
        b.addEventListener('click', async () => {
            try {
                await api(`/api/platform/admins/${b.dataset.admin}`, {
                    method: 'PATCH', body: JSON.stringify({ is_active: b.dataset.to === '1' }),
                });
                toast('Saqlandi');
                loadAdmins();
            } catch (e) { toast(e.message, 'err'); }
        }));
}

$('btn-new-admin').addEventListener('click', () => openModal({
    title: 'Yangi platforma admini',
    submitLabel: 'Yaratish',
    fields: [
        { name: 'full_name', label: 'To\'liq ism', required: false },
        { name: 'email', label: 'Email', type: 'email' },
        { name: 'password', label: 'Parol (kamida 10 belgi)', type: 'text',
          value: Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 8) },
    ],
    onSubmit: async (v) => {
        await api('/api/platform/admins', { method: 'POST', body: JSON.stringify(v) });
        loadAdmins();
        return {
            text: 'Admin yaratildi. Kirish ma\'lumotlari:',
            reveal: `${v.email}\n${v.password}`,
            note: 'Parol boshqa ko\'rsatilmaydi.',
        };
    },
}));

document.querySelectorAll('.nav').forEach((n) =>
    n.addEventListener('click', () => goto(n.dataset.view)));
document.querySelectorAll('[data-goto]').forEach((b) =>
    b.addEventListener('click', () => goto(b.dataset.goto)));

// ═══ YUKLASH ═══
async function loadAll() {
    await Promise.all([loadStats(), loadTenants(), loadPlans(), loadSeries(), refreshPendingCount()]);
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
        body.innerHTML = '<tr><td colspan="9" class="empty">Bu shartlarga mos biznes yo\'q.</td></tr>';
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
            <td><span class="state ${cls}">${label}</span>${
                t.sub_status === 'expired' ? ' <span class="state bad">Muddati tugagan</span>'
                : t.sub_status === 'frozen' ? ' <span class="state idle">Muzlatilgan</span>' : ''}</td>
            <td class="num">${fmt(t.balance)}<div class="cell-dim">${
                t.days_left != null ? Math.round(t.days_left) + ' kun' : '—'}</div></td>
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
            <div class="block-t">Hisob va obuna</div>
            <div class="kv"><span>Balans</span><b>${fmt(d.billing.balance)} so'm</b></div>
            <div class="kv"><span>Holat</span><b>${esc({
                active: 'Faol', frozen: 'Muzlatilgan', expired: 'Muddati tugagan', free: 'Bepul tarif',
            }[d.billing.status] || d.billing.status)}</b></div>
            <div class="kv"><span>Tugaydi</span><b>${esc(d.billing.expires_at || '—')}</b></div>
            <div class="kv"><span>Qolgan kun</span><b>${
                d.billing.days_left != null ? d.billing.days_left : '—'}</b></div>
            <div class="acts">
                <button class="btn" id="dr-balance">Balansni tuzatish</button>
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
            <div class="block-t">Bilimlar bazasi</div>
            <label class="field"><span>Ish vaqti</span>
                <input type="text" id="dr-hours" value="${esc(d.knowledge_base.working_hours || '')}"></label>
            <label class="field"><span>To'lov</span>
                <input type="text" id="dr-pay" value="${esc(d.knowledge_base.payment_info || '')}"></label>
            <label class="field"><span>Kafolat</span>
                <input type="text" id="dr-warranty" value="${esc(d.knowledge_base.warranty_info || '')}"></label>
            <label class="field"><span>Qaytarish</span>
                <input type="text" id="dr-return" value="${esc(d.knowledge_base.return_policy || '')}"></label>
            <div class="acts"><button class="btn btn-green" id="dr-save-kb">Bilimlar bazasini saqlash</button></div>
        </div>

        <div class="block">
            <div class="block-t">Foydalanuvchilar</div>
            ${d.users.map((x) => `
                <div class="kv">
                    <span>${esc(x.email)} · ${esc(x.role)}${x.is_active ? '' : ' · o\'chirilgan'}</span>
                    <span style="display:flex;gap:6px">
                        <button class="btn btn-ghost" data-reset="${esc(x.id)}">Parol</button>
                        <button class="btn ${x.is_active ? 'btn-red' : 'btn-ghost'}"
                                data-user="${esc(x.id)}" data-to="${x.is_active ? '0' : '1'}">
                            ${x.is_active ? 'O\'chirish' : 'Yoqish'}</button>
                    </span>
                </div>`).join('') || '<p class="empty">Yo\'q</p>'}
            <div class="acts">
                <button class="btn btn-ghost" id="dr-unlock">Kirish qulfini ochish</button>
                <button class="btn btn-ghost" id="dr-logout-all">Barcha sessiyani yopish</button>
            </div>
        </div>

        <div class="block">
            <div class="block-t">Xavfli hudud</div>
            <p style="font-size:12.5px;color:var(--fg-3);line-height:1.6">
                Biznes va unga tegishli barcha narsa — mahsulotlar, buyurtmalar, suhbatlar —
                butunlay o'chadi. Qaytarib bo'lmaydi.
            </p>
            <div class="acts"><button class="btn btn-red" id="dr-delete">Biznesni o'chirish</button></div>
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

    $('dr-balance').addEventListener('click', () => openModal({
        title: 'Balansni tuzatish',
        submitLabel: 'Saqlash',
        fields: [
            { name: 'amount', label: 'Summa (manfiy — yechish)', type: 'number' },
            { name: 'note', label: 'Sabab' },
        ],
        onSubmit: async (v) => {
            await api(`/api/platform/tenants/${id}/balance`, {
                method: 'POST',
                body: JSON.stringify({ amount: Number(v.amount), note: v.note }),
            });
            toast('Balans yangilandi');
            await loadTenants();
            openTenant(id);
        },
    }));

    $('dr-save-kb').addEventListener('click', async () => {
        try {
            const r = await api(`/api/platform/tenants/${id}/kb`, {
                method: 'PATCH',
                body: JSON.stringify({
                    working_hours: $('dr-hours').value,
                    payment_info: $('dr-pay').value,
                    warranty_info: $('dr-warranty').value,
                    return_policy: $('dr-return').value,
                }),
            });
            toast(r.status === 'unchanged' ? 'O\'zgarish yo\'q' : 'Bilimlar bazasi saqlandi');
        } catch (e) { toast(e.message, 'err'); }
    });

    $('drawer-body').querySelectorAll('[data-reset]').forEach((b) =>
        b.addEventListener('click', () => openModal({
            title: 'Parolni tiklash',
            submitLabel: 'Yangi parol yaratish',
            fields: [],
            onSubmit: async () => {
                const r = await api(
                    `/api/platform/tenants/${id}/users/${b.dataset.reset}/reset-password`,
                    { method: 'POST' });
                return {
                    text: `${r.email} uchun yangi parol:`,
                    reveal: r.password,
                    note: 'Parol boshqa ko\'rsatilmaydi. Eski sessiyalar yopildi va kirish qulfi olindi.',
                };
            },
        })));

    $('drawer-body').querySelectorAll('[data-user]').forEach((b) =>
        b.addEventListener('click', async () => {
            try {
                await api(`/api/platform/tenants/${id}/users/${b.dataset.user}`, {
                    method: 'PATCH', body: JSON.stringify({ is_active: b.dataset.to === '1' }),
                });
                toast('Saqlandi');
                openTenant(id);
            } catch (e) { toast(e.message, 'err'); }
        }));

    $('dr-unlock').addEventListener('click', async () => {
        try {
            const r = await api(`/api/platform/tenants/${id}/unlock`, { method: 'POST' });
            toast(`Qulf olindi (${r.users} foydalanuvchi)`);
        } catch (e) { toast(e.message, 'err'); }
    });

    $('dr-logout-all').addEventListener('click', async () => {
        try {
            const r = await api(`/api/platform/tenants/${id}/logout-all`, { method: 'POST' });
            toast(`${r.revoked} ta sessiya yopildi`);
        } catch (e) { toast(e.message, 'err'); }
    });

    $('dr-delete').addEventListener('click', () => openModal({
        title: 'Biznesni o\'chirish',
        submitLabel: 'Butunlay o\'chirish',
        danger: true,
        // Typing the name back is the guard: a tenant id in a URL is easy to
        // mistype and everything the business owns goes with it.
        fields: [{ name: 'confirm', label: `Tasdiqlash uchun "${d.business_name}" deb yozing` }],
        onSubmit: async (v) => {
            await api(`/api/platform/tenants/${id}?confirm=${encodeURIComponent(v.confirm)}`,
                      { method: 'DELETE' });
            closeDrawer();
            toast('Biznes o\'chirildi');
            await Promise.all([loadTenants(), loadStats()]);
        },
    }));

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
