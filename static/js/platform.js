/* Platform operator's panel.
   Kept apart from app.js: this page talks only to /api/platform/* and carries a
   different session cookie, so sharing state with the business panel would only
   create ways to confuse the two. */

const $ = (id) => document.getElementById(id);
let TENANTS = [];
let PLANS = [];

const fmt = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString('uz-UZ'));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(msg, kind = 'ok') {
    const t = $('plat-toast');
    t.textContent = msg;
    t.className = `plat-toast ${kind}`;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.hidden = true; }, 3200);
}

/** Every call goes through here so a session that expired mid-session drops
 *  straight back to the login screen instead of rendering an empty panel. */
async function api(url, options = {}) {
    const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    if (resp.status === 401) {
        showLogin();
        throw new Error('unauthorized');
    }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `Xatolik (${resp.status})`);
    return data;
}

// ─── Auth ────────────────────────────────────────────────────────────────────
function showLogin() {
    $('plat-login').style.display = 'flex';
    $('plat-app').hidden = true;
}

function showPanel(admin) {
    $('plat-login').style.display = 'none';
    $('plat-app').hidden = false;
    $('plat-admin-email').textContent = admin.full_name
        ? `${admin.full_name} · ${admin.email}` : admin.email;
    loadAll();
}

$('plat-login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('plat-login-btn');
    const err = $('plat-login-error');
    err.textContent = '';
    btn.disabled = true;
    btn.textContent = 'Tekshirilmoqda...';
    try {
        const d = await api('/api/platform/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email: $('plat-email').value, password: $('plat-password').value }),
        });
        $('plat-password').value = '';
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

// ─── Tabs ────────────────────────────────────────────────────────────────────
document.querySelectorAll('.plat-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.plat-tab').forEach((t) => t.classList.toggle('is-active', t === tab));
        ['businesses', 'plans', 'audit'].forEach((v) => {
            $(`view-${v}`).hidden = v !== tab.dataset.view;
        });
        if (tab.dataset.view === 'plans') loadPlans();
        if (tab.dataset.view === 'audit') loadAudit();
    });
});

// ─── Load ────────────────────────────────────────────────────────────────────
async function loadAll() {
    await Promise.all([loadStats(), loadTenants(), loadPlans()]);
}

async function loadStats() {
    const s = await api('/api/platform/stats');
    const cost = s.cost || {};
    const money = cost.configured && cost.rate_configured
        ? `${fmt(cost.uzs)} <small>UZS</small>` : `$${cost.usd ?? 0}`;
    $('plat-kpis').innerHTML = [
        ['Bizneslar', fmt(s.tenants), `${s.tenants_active} faol`],
        ['Buyurtmalar', fmt(s.orders), `${fmt(s.revenue)} UZS`],
        ['Suhbatlar', fmt(s.conversations), ''],
        ['AI tokenlari', fmt(s.tokens), `${fmt(s.prompt_tokens)} / ${fmt(s.output_tokens)}`],
        ['AI xarajati', money, cost.configured ? '' : '.env da narx sozlanmagan'],
    ].map(([label, value, sub]) => `
        <div class="plat-kpi">
            <div class="plat-kpi-label">${label}</div>
            <div class="plat-kpi-value">${value}</div>
            <div class="plat-kpi-sub">${sub}</div>
        </div>`).join('');
}

async function loadTenants() {
    TENANTS = await api('/api/platform/tenants');
    renderTenants();
}

/** Usage against a cap. Null limit means unlimited, which is a different thing
 *  from "zero used" and must not render as a full bar. */
function meter(used, limit) {
    if (limit === null || limit === undefined) {
        return `<div class="plat-meter"><div class="plat-meter-top"><span>${fmt(used)}</span>
                <span style="color:var(--plat-text-dim)">∞</span></div></div>`;
    }
    const pct = Math.min(100, Math.round((used / limit) * 100));
    const cls = pct >= 100 ? 'over' : pct >= 80 ? 'near' : '';
    return `<div class="plat-meter">
        <div class="plat-meter-top"><span>${fmt(used)}</span><span>${fmt(limit)}</span></div>
        <div class="plat-meter-track"><div class="plat-meter-fill ${cls}" style="width:${pct}%"></div></div>
    </div>`;
}

function renderTenants() {
    const q = ($('plat-search').value || '').toLowerCase().trim();
    const planFilter = $('plat-plan-filter').value;
    const rows = TENANTS.filter((t) => {
        if (planFilter && t.plan !== planFilter) return false;
        if (!q) return true;
        return (t.business_name || '').toLowerCase().includes(q)
            || (t.owner_email || '').toLowerCase().includes(q);
    });

    const body = $('plat-tenants-body');
    if (!rows.length) {
        body.innerHTML = '<tr><td colspan="8" class="plat-empty">Biznes topilmadi.</td></tr>';
        return;
    }
    body.innerHTML = rows.map((t) => `
        <tr data-id="${esc(t.id)}">
            <td>
                <div class="plat-biz-name">${esc(t.business_name)}</div>
                <div class="plat-biz-email">${esc(t.owner_email || '—')}</div>
            </td>
            <td><span class="plat-badge plan-${esc(t.plan)}">${esc(t.plan_title)}</span></td>
            <td><span class="plat-badge ${t.is_active ? 'ok' : 'off'}">${t.is_active ? 'Faol' : 'To\'xtatilgan'}</span></td>
            <td>${meter(t.products, t.product_limit)}</td>
            <td>${meter(t.ai_messages_month, t.ai_limit)}</td>
            <td>${fmt(t.orders)}</td>
            <td>${t.telegram_connected
                ? `<span class="plat-badge ok">@${esc(t.telegram_username || 'ulangan')}</span>`
                : '<span class="plat-badge off">yo\'q</span>'}</td>
            <td style="color:var(--plat-text-dim)">${esc(t.last_activity || '—')}</td>
        </tr>`).join('');

    body.querySelectorAll('tr[data-id]').forEach((tr) => {
        tr.addEventListener('click', () => openTenant(tr.dataset.id));
    });
}

$('plat-search').addEventListener('input', renderTenants);
$('plat-plan-filter').addEventListener('change', renderTenants);

// ─── Drawer ──────────────────────────────────────────────────────────────────
function closeDrawer() {
    $('plat-drawer').hidden = true;
    $('plat-drawer-backdrop').hidden = true;
}
$('drawer-close').addEventListener('click', closeDrawer);
$('plat-drawer-backdrop').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

async function openTenant(id) {
    $('plat-drawer').hidden = false;
    $('plat-drawer-backdrop').hidden = false;
    $('drawer-body').innerHTML = '<p class="plat-empty">Yuklanmoqda...</p>';

    const d = await api(`/api/platform/tenants/${id}`);
    $('drawer-title').textContent = d.business_name;
    $('drawer-sub').textContent = `${d.id} · ${d.created_at || ''}`;

    const u = d.usage;
    const planOptions = PLANS.map((p) =>
        `<option value="${esc(p.name)}" ${p.name === d.plan ? 'selected' : ''}>${esc(p.title)}</option>`).join('');

    $('drawer-body').innerHTML = `
        <div class="plat-section">
            <h3>Tarif va holat</h3>
            <label class="plat-field" style="margin-bottom:10px;">
                <span>Tarif</span>
                <select id="dr-plan">${planOptions}</select>
            </label>
            <div class="plat-rows">
                <div class="plat-row"><span>Mahsulotlar</span><b>${fmt(u.products.used)} / ${u.products.limit === null ? '∞' : fmt(u.products.limit)}</b></div>
                <div class="plat-row"><span>AI xabarlari (shu oy)</span><b>${fmt(u.ai_messages.used)} / ${u.ai_messages.limit === null ? '∞' : fmt(u.ai_messages.limit)}</b></div>
                <div class="plat-row"><span>Operatorlar</span><b>${fmt(u.operators.used)} / ${u.operators.limit === null ? '∞' : fmt(u.operators.limit)}</b></div>
            </div>
            <div class="plat-actions">
                <button class="plat-btn primary" id="dr-save-plan">Tarifni saqlash</button>
                <button class="plat-btn ${d.is_active ? 'danger' : ''}" id="dr-toggle-active">
                    ${d.is_active ? 'Biznesni to\'xtatish' : 'Biznesni faollashtirish'}
                </button>
            </div>
        </div>

        <div class="plat-section">
            <h3>Telegram</h3>
            <div class="plat-rows">
                <div class="plat-row"><span>Bot</span><b>${d.telegram.connected ? '@' + esc(d.telegram.username || '') : 'ulanmagan'}</b></div>
                <div class="plat-row"><span>Webhook siri</span><b>${d.telegram.webhook_secret_set ? 'bor' : 'yo\'q'}</b></div>
                <div class="plat-row"><span>Buyurtmalar guruhi</span><b>${esc(d.telegram.orders_group || '—')}</b></div>
            </div>
            ${d.telegram.connected ? `<div class="plat-actions">
                <button class="plat-btn danger" id="dr-tg-disconnect">Bot ulanishini tozalash</button>
            </div>` : ''}
        </div>

        <div class="plat-section">
            <h3>AI sozlamalari</h3>
            <label class="plat-field" style="margin-bottom:10px;">
                <span>Model</span>
                <input type="text" id="dr-model" value="${esc(d.ai.model_name)}">
            </label>
            <label class="plat-field" style="margin-bottom:10px;">
                <span>Temperature (0–1)</span>
                <input type="number" id="dr-temp" step="0.1" min="0" max="1" value="${d.ai.temperature}">
            </label>
            <label class="plat-field" style="margin-bottom:10px;">
                <span>Operatorga uzatishdan oldingi urinishlar</span>
                <input type="number" id="dr-handoff" min="1" max="10" value="${d.ai.auto_handoff_after ?? 3}">
            </label>
            <label class="plat-field">
                <span>Tizim prompti</span>
                <textarea id="dr-prompt">${esc(d.ai.system_prompt)}</textarea>
            </label>
            <div class="plat-actions">
                <button class="plat-btn primary" id="dr-save-ai">AI sozlamalarini saqlash</button>
                <button class="plat-btn" id="dr-toggle-bot">${d.ai.bot_enabled ? 'Botni o\'chirish' : 'Botni yoqish'}</button>
            </div>
        </div>

        <div class="plat-section">
            <h3>Foydalanuvchilar</h3>
            <div class="plat-rows">
                ${d.users.map((x) => `<div class="plat-row"><span>${esc(x.email)}</span><b>${esc(x.role)}</b></div>`).join('') || '<p class="plat-empty">Yo\'q</p>'}
            </div>
        </div>`;

    $('dr-save-plan').addEventListener('click', async () => {
        await patchTenant(id, { plan: $('dr-plan').value }, 'Tarif yangilandi');
    });
    $('dr-toggle-active').addEventListener('click', async () => {
        const stopping = d.is_active;
        if (stopping && !confirm(`"${d.business_name}" to'xtatilsinmi? Panelga kira olmay qoladi.`)) return;
        await patchTenant(id, { is_active: !d.is_active }, stopping ? 'Biznes to\'xtatildi' : 'Biznes faollashtirildi');
    });
    $('dr-save-ai').addEventListener('click', async () => {
        await patchAi(id, {
            model_name: $('dr-model').value.trim(),
            temperature: parseFloat($('dr-temp').value),
            auto_handoff_after: parseInt($('dr-handoff').value, 10),
            system_prompt: $('dr-prompt').value,
        });
    });
    $('dr-toggle-bot').addEventListener('click', async () => {
        await patchAi(id, { bot_enabled: !d.ai.bot_enabled });
    });
    const tgBtn = $('dr-tg-disconnect');
    if (tgBtn) {
        tgBtn.addEventListener('click', async () => {
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

// ─── Plans ───────────────────────────────────────────────────────────────────
async function loadPlans() {
    PLANS = await api('/api/platform/plans');

    const filter = $('plat-plan-filter');
    if (filter.options.length <= 1) {
        PLANS.forEach((p) => filter.add(new Option(p.title, p.name)));
    }

    $('plat-plans').innerHTML = PLANS.map((p) => `
        <div class="plat-plan-card" data-plan="${esc(p.name)}">
            <h3>${esc(p.title)}</h3>
            <div class="plat-plan-price">${fmt(p.price_uzs)} UZS / oy</div>
            <div class="plat-plan-count">${p.tenants} ta biznes</div>
            <div class="plat-plan-fields">
                <div class="plat-plan-field"><span>Narx (UZS)</span>
                    <input type="number" data-f="price_uzs" value="${p.price_uzs}"></div>
                <div class="plat-plan-field"><span>Mahsulot</span>
                    <input type="number" data-f="max_products" value="${p.max_products ?? ''}" placeholder="∞"></div>
                <div class="plat-plan-field"><span>AI xabar / oy</span>
                    <input type="number" data-f="max_ai_messages_monthly" value="${p.max_ai_messages_monthly ?? ''}" placeholder="∞"></div>
                <div class="plat-plan-field"><span>Operator</span>
                    <input type="number" data-f="max_operators" value="${p.max_operators ?? ''}" placeholder="∞"></div>
            </div>
            <div class="plat-actions">
                <button class="plat-btn primary" data-save="${esc(p.name)}">Saqlash</button>
            </div>
            <p class="plat-hint" style="margin-top:10px;">Bo'sh qoldirilsa — cheksiz.</p>
        </div>`).join('');

    $('plat-plans').querySelectorAll('[data-save]').forEach((btn) => {
        btn.addEventListener('click', () => savePlan(btn.dataset.save));
    });
}

async function savePlan(name) {
    const card = $('plat-plans').querySelector(`[data-plan="${name}"]`);
    const body = { unlimited: [] };
    card.querySelectorAll('input[data-f]').forEach((inp) => {
        const field = inp.dataset.f;
        const raw = inp.value.trim();
        // Blank means unlimited, which is null — and null cannot double as
        // "unchanged", so the field is named explicitly instead.
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
    const body = $('plat-audit-body');
    if (!rows.length) {
        body.innerHTML = '<tr><td colspan="5" class="plat-empty">Hali amal qilinmagan.</td></tr>';
        return;
    }
    const names = Object.fromEntries(TENANTS.map((t) => [t.id, t.business_name]));
    body.innerHTML = rows.map((r) => `
        <tr style="cursor:default">
            <td style="white-space:nowrap;color:var(--plat-text-dim)">${esc(r.created_at)}</td>
            <td>${esc(r.admin_email)}</td>
            <td><span class="plat-badge plan-business">${esc(r.action)}</span></td>
            <td>${esc(names[r.tenant_id] || r.tenant_id || '—')}</td>
            <td style="color:var(--plat-text-dim);font-size:12px">${esc(r.details ? JSON.stringify(r.details) : '')}</td>
        </tr>`).join('');
}

// ─── Boot ────────────────────────────────────────────────────────────────────
(async () => {
    try {
        showPanel(await api('/api/platform/auth/me'));
    } catch {
        showLogin();
    }
})();
