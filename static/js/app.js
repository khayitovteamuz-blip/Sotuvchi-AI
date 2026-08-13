// Sotuvchi AI - Dashboard, Categories & Product Engine Logic

let currentProducts = [];
let currentCategories = [];
let selectedCategoryFilter = null;
let modalImages = []; 
let activeImageIndex = 0;

// ════════════════════════════════════════════════════════
// AUTH — Login, Register, Logout
// ════════════════════════════════════════════════════════

function showAuthOverlay() {
    document.getElementById('auth-overlay').style.display = 'flex';
    document.getElementById('app-container').style.display = 'none';
}

function showAppDashboard(tenant) {
    document.getElementById('auth-overlay').style.display = 'none';
    document.getElementById('app-container').style.display = 'flex';
    // Show tenant info in sidebar
    if (tenant) {
        currentTenant = tenant;
        document.getElementById('tenant-biz-name').textContent = tenant.business_name || '—';
        document.getElementById('tenant-email').textContent = tenant.email || '—';
    }
}

function showLoginPanel() {
    document.getElementById('auth-login-panel').style.display = 'block';
    document.getElementById('auth-register-panel').style.display = 'none';
    document.getElementById('auth-error').style.display = 'none';
    return false;
}

function showRegisterPanel() {
    document.getElementById('auth-login-panel').style.display = 'none';
    document.getElementById('auth-register-panel').style.display = 'block';
    document.getElementById('register-error').style.display = 'none';
    return false;
}

async function doLogin() {
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    const errEl = document.getElementById('auth-error');
    const btn = document.getElementById('login-btn');

    if (!email || !password) {
        errEl.textContent = 'Email va parolni to\'liq kiriting.';
        errEl.style.display = 'block';
        return;
    }

    btn.textContent = 'Kirish...';
    btn.style.opacity = '0.7';
    errEl.style.display = 'none';

    try {
        const resp = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await resp.json();

        if (!resp.ok) {
            errEl.textContent = data.detail || 'Xatolik yuz berdi.';
            errEl.style.display = 'block';
            return;
        }

        showAppDashboard(data.tenant);
        bootApp();
    } catch (e) {
        errEl.textContent = 'Server bilan bog\'lanishda xatolik.';
        errEl.style.display = 'block';
    } finally {
        btn.textContent = 'Kirish →';
        btn.style.opacity = '1';
    }
}

async function doRegister() {
    const business_name = document.getElementById('reg-biz-name').value.trim();
    const email = document.getElementById('reg-email').value.trim();
    const password = document.getElementById('reg-password').value;
    const errEl = document.getElementById('register-error');
    const btn = document.getElementById('register-btn');

    if (!business_name || !email || !password) {
        errEl.textContent = 'Barcha maydonlarni to\'ldiring.';
        errEl.style.display = 'block';
        return;
    }
    if (password.length < 6) {
        errEl.textContent = 'Parol kamida 6 ta belgidan iborat bo\'lishi kerak.';
        errEl.style.display = 'block';
        return;
    }

    btn.textContent = 'Ro\'yxatdan o\'tilmoqda...';
    btn.style.opacity = '0.7';
    errEl.style.display = 'none';

    try {
        const resp = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ business_name, email, password })
        });
        const data = await resp.json();

        if (!resp.ok) {
            errEl.textContent = data.detail || 'Ro\'yxatdan o\'tishda xatolik.';
            errEl.style.display = 'block';
            return;
        }

        // Auto-login after register
        document.getElementById('login-email').value = email;
        document.getElementById('login-password').value = password;
        showLoginPanel();
        await doLogin();
    } catch (e) {
        errEl.textContent = 'Server bilan bog\'lanishda xatolik.';
        errEl.style.display = 'block';
    } finally {
        btn.textContent = 'Ro\'yxatdan O\'tish →';
        btn.style.opacity = '1';
    }
}

async function doLogout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
    } finally {
        showAuthOverlay();
        showLoginPanel();
    }
}

// ════════════════════════════════════════════════════════
// INIT — Check auth on page load
// ════════════════════════════════════════════════════════
let navReady = false;
let currentTenant = null;

/** Boot everything after auth: nav + the data the default screen (Inbox) needs. */
function bootApp() {
    if (!navReady) { initNavigation(); navReady = true; initCustomerSearch(); }
    loadCategories();     // needed by the product modal's category select
    loadProducts();
    loadSettings();
    startInboxPolling();
    restoreActiveTab();
}

/** Reopen the section the operator was last on; Inbox is the first-visit default. */
function restoreActiveTab() {
    const saved = localStorage.getItem('sotuvchi_active_tab');
    const navItem = saved && document.querySelector(`.nav-item[data-tab="${saved}"]`);
    if (navItem) {
        navItem.click();   // click also loads that tab's data and sets the header
    } else {
        loadInbox();
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const resp = await fetch('/api/auth/me');
        if (resp.ok) {
            currentTenant = await resp.json();
            showAppDashboard(currentTenant);
            bootApp();
        } else {
            showAuthOverlay();
            showLoginPanel();
        }
    } catch (e) {
        showAuthOverlay();
        showLoginPanel();
    }
});

// Navigation Tabs
const TAB_META = {
    'tab-inbox':        { title: 'Inbox', sub: 'Jonli suhbatlar — AI va operator', btn: false, load: loadInbox },
    'tab-overview':     { title: 'Dashboard', sub: 'AI KPI va sotuv ko\'rsatkichlari', btn: false, load: loadDashboardStats },
    'tab-ai-agent':     { title: 'AI Agent', sub: 'Xarakter, qoidalar va sinov', btn: false, load: loadSettings },
    'tab-products':     { title: 'Katalog', sub: 'Mahsulotlar, narx va ombor qoldig\'i', btn: true, load: loadCatalog },
    'tab-orders':       { title: 'Buyurtmalar', sub: 'Barcha buyurtmalar va status workflow', btn: false, load: loadOrders },
    'tab-customers':    { title: 'Mijozlar', sub: 'Kim nima olgan va qachon yozgan', btn: false, load: loadCustomers },
    'tab-integrations': { title: 'Integratsiyalar', sub: 'Telegram bot va operator bildirishnomasi', btn: false, load: loadIntegrations },
    'tab-billing':      { title: 'Hisobim', sub: 'Balans, tarif va to\'lovlar', btn: false, load: loadBilling },
    'tab-settings':     { title: 'Sozlamalar', sub: 'Biznes profili, xodimlar va tarif', btn: false, load: loadAccountSettings }
};

function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const tabViews = document.querySelectorAll('.tab-view');
    const headerTitle = document.getElementById('page-title');
    const headerSubtitle = document.getElementById('page-subtitle');
    const headerActionGroup = document.getElementById('header-action-group');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.getAttribute('data-tab');
            const meta = TAB_META[targetTab];

            navItems.forEach(i => i.classList.remove('active'));
            tabViews.forEach(v => v.classList.remove('active'));

            item.classList.add('active');
            document.getElementById(targetTab).classList.add('active');

            if (meta) {
                document.querySelector('.top-header').style.display = 'flex';
                headerTitle.textContent = meta.title;
                headerSubtitle.textContent = meta.sub;
                headerActionGroup.style.display = meta.btn ? 'flex' : 'none';
                const mobileTitle = document.getElementById('mobile-page-title');
                if (mobileTitle) mobileTitle.textContent = meta.title;
                if (typeof meta.load === 'function') meta.load();
            }

            // On a phone the drawer covers the content — close it after choosing
            toggleSidebar(false);

            // Remember the section so a reload returns here instead of Inbox
            localStorage.setItem('sotuvchi_active_tab', targetTab);
        });
    });
}

/** Slide the sidebar drawer in/out on phones. `force` overrides the toggle. */
function toggleSidebar(force) {
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    if (!sidebar) return;
    const open = force === undefined ? !sidebar.classList.contains('open') : force;
    sidebar.classList.toggle('open', open);
    if (backdrop) backdrop.classList.toggle('open', open);
    document.body.style.overflow = open ? 'hidden' : '';
}

function switchToTab(targetTab) {
    const navItem = document.querySelector(`.nav-item[data-tab="${targetTab}"]`);
    if (navItem) {
        navItem.click();
    }
}

// Categories now only feed the filter chips and the product form's dropdown
async function loadCategories() {
    try {
        const resp = await fetch('/api/admin/categories');
        currentCategories = await resp.json();

        const badge = document.getElementById('categories-count-text');
        if (badge) badge.textContent = `${currentCategories.length} ta kategoriya`;
        populateCategoryDropdown();
    } catch (e) {
        console.error('Kategoriyalarni yuklashda xatolik:', e);
    }
}

/** Catalog screen = products + their category filter. */
async function loadCatalog() {
    await loadCategories();
    await loadProducts();
}





// Category Modal & Real Image Upload Handlers
function openAddCategoryModal() {
    document.getElementById('cat-edit-mode').value = 'add';
    document.getElementById('cat-id-val').value = '';
    document.getElementById('cat-image-url-val').value = '';
    document.getElementById('cat-name').value = '';
    document.getElementById('cat-modal-title').textContent = "Yangi Kategoriya Qo'shish";
    document.getElementById('cat-save-btn').textContent = "Saqlash";
    
    // Reset image preview
    document.getElementById('cat-image-preview-container').style.display = 'none';
    document.getElementById('cat-upload-hint-text').style.display = 'block';
    
    document.getElementById('category-modal').style.display = 'flex';
}

function openEditCategoryModal(catId, event) {
    if (event) event.stopPropagation();
    const cat = currentCategories.find(c => c.id === catId);
    if (!cat) return;

    document.getElementById('cat-edit-mode').value = 'edit';
    document.getElementById('cat-id-val').value = cat.id;
    document.getElementById('cat-image-url-val').value = cat.image_url || '';
    document.getElementById('cat-name').value = cat.name;
    document.getElementById('cat-modal-title').textContent = "Kategoriyani Tahrirlash";
    document.getElementById('cat-save-btn').textContent = "O'zgarishlarni Saqlash";

    if (cat.image_url) {
        document.getElementById('cat-image-preview').src = cat.image_url;
        document.getElementById('cat-image-preview-container').style.display = 'block';
        document.getElementById('cat-upload-hint-text').style.display = 'none';
    } else {
        document.getElementById('cat-image-preview-container').style.display = 'none';
        document.getElementById('cat-upload-hint-text').style.display = 'block';
    }

    document.getElementById('category-modal').style.display = 'flex';
}

function closeCategoryModal() {
    document.getElementById('category-modal').style.display = 'none';
}

function triggerCatFileInput() {
    document.getElementById('cat-file-input').click();
}

async function handleCatFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/admin/upload', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (data.status === 'success' && data.image_url) {
            document.getElementById('cat-image-url-val').value = data.image_url;
            document.getElementById('cat-image-preview').src = data.image_url;
            document.getElementById('cat-image-preview-container').style.display = 'block';
            document.getElementById('cat-upload-hint-text').style.display = 'none';
        }
    } catch (e) {
        console.error('Kategoriya rasmini yuklashda xatolik:', e);
        alert('Rasm yuklashda xatolik yuz berdi!');
    }
}

async function saveCategoryForm() {
    const mode = document.getElementById('cat-edit-mode').value;
    const catId = document.getElementById('cat-id-val').value || `cat-${Date.now()}`;
    const name = document.getElementById('cat-name').value.trim();
    const imageUrl = document.getElementById('cat-image-url-val').value.trim();

    if (!name) {
        alert('Iltimos, kategoriya nomini kiriting!');
        return;
    }

    const payload = {
        id: catId,
        name: name,
        icon: '📁',
        image_url: imageUrl || null
    };

    try {
        const url = mode === 'edit' ? `/api/admin/categories/${catId}` : '/api/admin/categories';
        const resp = await fetch(url, {
            method: mode === 'edit' ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        // fetch does not throw on 4xx — without this check a rejected save
        // closed the modal and looked like it had worked.
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            toast(err.detail || 'Kategoriyani saqlab bo\'lmadi', 'error');
            return;
        }
        closeCategoryModal();
        loadCategories();
        toast(mode === 'edit' ? 'Kategoriya yangilandi' : 'Kategoriya qo\'shildi');
    } catch (e) {
        console.error('Kategoriyani saqlashda xatolik:', e);
        toast('Tarmoq xatosi — kategoriya saqlanmadi', 'error');
    }
}

function populateCategoryDropdown() {
    const select = document.getElementById('prod-category');
    if (!select) return;

    select.innerHTML = '';
    currentCategories.forEach(cat => {
        const opt = document.createElement('option');
        opt.value = cat.name;
        opt.textContent = `${cat.icon} ${cat.name}`;
        select.appendChild(opt);
    });

    if (currentCategories.length === 0) {
        const opt = document.createElement('option');
        opt.value = 'Umumiy';
        opt.textContent = '📁 Umumiy';
        select.appendChild(opt);
    }
}

async function deleteCategory(catId, catName, event) {
    if (event) event.stopPropagation();
    if (!confirm(`"${catName}" kategoriyasini o'chirmoqchimisiz?`)) return;
    try {
        await fetch(`/api/admin/categories/${catId}`, { method: 'DELETE' });
        loadCategories();
    } catch (e) {
        console.error('O\'chirishda xatolik:', e);
    }
}

// ════════════════════════════════════════════════════════
// DASHBOARD — AI KPI cards
// ════════════════════════════════════════════════════════
/** Uzbek number format: 45 700 000 (spaces, not commas). */
function fmtNum(n) {
    return Math.round(Number(n) || 0).toLocaleString('ru-RU').replace(/ /g, ' ');
}

/**
 * One KPI tile. Pass `tab` to make it drill down into that section —
 * a number you can't act on is decoration, so every tile that has a
 * matching screen links to it.
 */
function kpiCard(icon, color, label, value, hint, tab, action, growth) {
    const go = action || (tab ? `switchToTab('${tab}')` : '');
    const clickable = go ? ` kpi-card--link" onclick="${go}" role="button" tabindex="0"` : '"';
    return `<div class="kpi-card${clickable}>
        <div class="kpi-top">
            <span class="kpi-icon" style="background:${color}1a; color:${color};">${icon}</span>
            <span class="kpi-label">${label}</span>
        </div>
        <div class="kpi-value">${value}${growthBadge(growth)}</div>
        <div class="kpi-foot">
            <span class="kpi-hint">${hint || ''}</span>
            ${go ? '<span class="kpi-arrow">→</span>' : ''}
        </div>
    </div>`;
}

/** Change against the previous period. null means there was no baseline —
 *  rendering "+100%" against zero would read as growth that never happened. */
function growthBadge(pct) {
    if (pct === null || pct === undefined) return '';
    const up = pct >= 0;
    return `<span class="kpi-growth ${up ? 'is-up' : 'is-down'}">${up ? '▲' : '▼'} ${Math.abs(pct)}%</span>`;
}

// Which window the dashboard is showing. Persisted so a reload does not
// silently drop the owner back to a different period than they left on.
let dashPeriod = localStorage.getItem('dashPeriod') || 'month';

function initPeriodPicker() {
    const box = document.getElementById('dashboard-period');
    if (!box || box.dataset.bound) return;
    box.dataset.bound = '1';
    box.querySelectorAll('button').forEach(btn => {
        btn.classList.toggle('is-active', btn.dataset.period === dashPeriod);
        btn.addEventListener('click', () => {
            dashPeriod = btn.dataset.period;
            localStorage.setItem('dashPeriod', dashPeriod);
            box.querySelectorAll('button').forEach(b => b.classList.toggle('is-active', b === btn));
            loadDashboardStats();
        });
    });
}

/** Placeholders in the real layout while the figures are on their way.
 *
 *  Switching period takes about a second against a database in Frankfurt, and
 *  for that second the panels stood empty with only their titles — which reads
 *  as a broken page rather than a loading one. Shapes also keep the grid from
 *  jumping when the numbers arrive.
 */
function showDashboardSkeleton() {
    const set = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };

    set('dashboard-kpis', Array.from({ length: 6 }, () => `
        <div class="skel-kpi">
            <div class="skel-kpi-top">
                <span class="skel skel-ico"></span>
                <span class="skel skel-line skel-w60" style="flex:1"></span>
            </div>
            <span class="skel skel-val"></span>
            <span class="skel skel-foot"></span>
        </div>`).join(''));

    set('dashboard-status-bars', Array.from({ length: 3 }, () => `
        <div class="skel-row">
            <span class="skel skel-line" style="width:78px"></span>
            <span class="skel skel-line" style="flex:1"></span>
            <span class="skel skel-line" style="width:26px"></span>
        </div>`).join(''));

    set('dashboard-cost', Array.from({ length: 4 }, (_, i) => `
        <div class="skel-row" style="justify-content:space-between">
            <span class="skel skel-line" style="width:${[120, 96, 132, 110][i]}px"></span>
            <span class="skel skel-line" style="width:64px"></span>
        </div>`).join(''));

    set('recent-orders-tbody', Array.from({ length: 4 }, () => `
        <tr>${Array.from({ length: 6 }, () =>
            '<td><span class="skel skel-line skel-w75"></span></td>').join('')}</tr>`).join(''));
}

async function loadDashboardStats() {
    initPeriodPicker();
    showDashboardSkeleton();
    try {
        const q = `?period=${encodeURIComponent(dashPeriod)}`;
        const [statsResp, anResp] = await Promise.all([
            fetch('/api/admin/stats' + q),
            fetch('/api/admin/analytics' + q)
        ]);
        const data = await statsResp.json();
        const an = await anResp.json();
        const g = data.growth || {};

        // AI-attributed revenue leads: that is what this product produced.
        // The shop's overall revenue is context, shown as a hint underneath.
        document.getElementById('dashboard-kpis').innerHTML =
            kpiCard('🤖', '#00b87c', 'AI orqali tushum', fmtNum(data.ai_revenue) + ' <small>UZS</small>',
                    `butun davr: ${fmtNum(data.all_time_revenue)}`, 'tab-orders', null, g.ai_revenue) +
            kpiCard('🧾', '#06b6d4', 'AI buyurtmalari', fmtNum(data.ai_order_count),
                    `jami: ${fmtNum(data.total_orders)} ta`, 'tab-orders', null, g.ai_order_count) +
            kpiCard('💬', '#f59e0b', 'Suhbatlar', fmtNum(an.total_conversations),
                    fmtNum(an.total_messages) + ' xabar', 'tab-inbox', null,
                    (an.growth || {}).total_conversations) +
            kpiCard('📈', '#a855f7', 'Konversiya', an.conversion_rate + '<small>%</small>',
                    'suhbat → buyurtma') +
            kpiCard('⚡️', '#0ea5e9', "O'rtacha javob", fmtNum(an.avg_latency_ms) + ' <small>ms</small>',
                    'AI javob tezligi') +
            kpiCard('🙋', '#e11d48', 'Eskalatsiya', an.escalation_rate + '<small>%</small>',
                    'operatorga uzatildi', null, 'openInboxOperator()');

        renderStatusBars(an);
        renderUsagePanel(data);
        renderRecentOrders(data.recent_orders);
    } catch (e) {
        console.error('Stats yuklashda xatolik:', e);
        // The skeleton must not outlive the request. Left shimmering after a
        // failure it promises data that is never coming.
        document.getElementById('dashboard-kpis').innerHTML = `
            <div class="load-fail">
                <p>Ma'lumotlarni yuklab bo'lmadi.</p>
                <button class="btn-primary" onclick="loadDashboardStats()">Qayta urinish</button>
            </div>`;
        ['dashboard-status-bars', 'dashboard-cost', 'recent-orders-tbody'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '';
        });
    }
}

/** Where conversations stand: how many the AI still owns vs handed over. */
function renderStatusBars(an) {
    const box = document.getElementById('dashboard-status-bars');
    if (!box) return;
    const total = Math.max(an.total_conversations, 1);
    const bar = (label, val, color) => `
        <div class="stat-bar-row">
            <span class="stat-bar-label">${label}</span>
            <div class="stat-bar-track"><div class="stat-bar-fill" style="width:${(val / total * 100).toFixed(1)}%; background:${color};"></div></div>
            <span class="stat-bar-val">${val}</span>
        </div>`;
    box.innerHTML =
        bar('🤖 AI', an.by_status.ai, '#00b87c') +
        bar('👨‍💼 Operator', an.by_status.operator, '#f59e0b') +
        bar('✅ Yopilgan', an.by_status.closed, '#64748b');
}

/** Google Sheets state. The card used to read "tez orada" while the integration
 *  was in fact built — so a silent misconfiguration looked like a missing
 *  feature, and the owner had no way to tell which of the two it was. */
async function loadSheetsStatus() {
    const label = document.getElementById('sheets-status');
    const reason = document.getElementById('sheets-reason');
    const card = document.getElementById('sheets-card');
    if (!label) return;
    try {
        const d = await (await fetch('/api/admin/integrations/status')).json();
        label.textContent = d.google_sheets ? '🟢 Ulangan' : '⚪️ Ulanmagan';
        reason.textContent = d.google_sheets ? '' : (d.google_sheets_reason || '');
        card.classList.toggle('disabled', !d.google_sheets);
    } catch (e) {
        label.textContent = 'Holatni aniqlab bo\'lmadi';
    }
}

/** How much of the tariff is spent — the question an owner actually asks.
 *
 *  This card used to show the platform's own token cost and margin advice
 *  ("the tariff price must be above this cost"), which is the operator's
 *  number, not the shop's. The shop needs to know how close it is to its
 *  limits; the cost view lives in the operator panel.
 */
async function renderUsagePanel(data) {
    const box = document.getElementById('dashboard-usage');
    if (!box) return;

    let u;
    try {
        const resp = await fetch('/api/admin/usage');
        if (!resp.ok) throw new Error('usage');
        u = await resp.json();
    } catch (e) {
        box.innerHTML = '<p class="cost-hint">Tarif ma\'lumotini yuklab bo\'lmadi.</p>';
        return;
    }

    const cap = (v) => (v === null || v === undefined ? '∞' : fmtNum(v));
    const row = (label, m) => {
        const pct = m.pct === null || m.pct === undefined ? null : Math.min(m.pct, 100);
        // Red before the wall is hit, not after: at 90% the owner still has
        // time to upgrade, at 100% the AI has already stopped answering.
        const tone = pct === null ? '' : pct >= 90 ? ' is-danger' : pct >= 70 ? ' is-warn' : '';
        return `
        <div class="cost-row"><span>${label}</span><b>${fmtNum(m.used)} / ${cap(m.limit)}</b></div>
        ${pct === null ? '' : `<div class="usage-bar${tone}"><i style="width:${pct}%"></i></div>`}`;
    };

    box.innerHTML = `
        <div class="cost-row cost-row--lead"><span>Tarif</span><b>${escapeHtml(u.plan_title || u.plan)}</b></div>
        ${row('AI xabar, shu oy', u.ai_messages)}
        ${row('Mahsulot', u.products)}
        ${row('Operator', u.operators)}
        <div class="cost-row"><span>AI yopgan savdo</span><b>${fmtNum(data.ai_order_count)} ta</b></div>
        <p class="cost-hint">Limit tugasa AI javob bermay qo'yadi va suhbat operatorga uzatiladi.</p>`;
}

function renderRecentOrders(orders) {
    const tbody = document.getElementById('recent-orders-tbody');
    tbody.innerHTML = '';

    if (!orders || orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Hali buyurtmalar kelib tushmagan. Telegram bot orqali buyurtma bering!</td></tr>';
        return;
    }

    orders.forEach(o => {
        const tr = document.createElement('tr');
        const [day, time] = (o.created_at || '').split(' ');
        tr.innerHTML = `
            <td class="cell-nowrap"><code>${o.id}</code></td>
            <td><strong>${escapeHtml(o.customer_name)}</strong></td>
            <td class="cell-nowrap">${escapeHtml(o.customer_phone)}</td>
            <td class="cell-nowrap cell-num">${fmtNum(o.total_amount)} <small>UZS</small></td>
            <td><span class="badge badge-${o.status.toLowerCase().replace("'", "")}">${o.status}</span></td>
            <td class="cell-nowrap cell-date">${day || ''}<span>${time || ''}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

// Load Products
async function loadProducts() {
    try {
        const resp = await fetch('/api/admin/products');
        currentProducts = await resp.json();
        renderCategoryFilter();
        renderProductsTable();
    } catch (e) {
        console.error('Mahsulotlarni yuklashda xatolik:', e);
    }
}

/** Category chips above the table — a filter, not a separate screen. */
function renderCategoryFilter() {
    const row = document.getElementById('category-filter-row');
    if (!row) return;

    const counts = {};
    currentProducts.forEach(p => {
        const c = (p.category || '').trim() || '— kategoriyasiz';
        counts[c] = (counts[c] || 0) + 1;
    });
    const names = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);

    const chip = (label, value, n, active) =>
        `<button class="cat-chip${active ? ' active' : ''}" onclick="filterByCategory(${value === null ? 'null' : `'${value.replace(/'/g, "\\'")}'`})">
            ${escapeHtml(label)} <span>${n}</span>
        </button>`;

    row.innerHTML =
        chip('Barchasi', null, currentProducts.length, !selectedCategoryFilter) +
        names.map(n => chip(n, n, counts[n], selectedCategoryFilter === n)).join('');
}

function filterByCategory(name) {
    selectedCategoryFilter = name;
    renderCategoryFilter();
    renderProductsTable();
}

function renderProductsTable() {
    const tbody = document.getElementById('products-tbody');
    if (!tbody) return;

    const q = (document.getElementById('product-search')?.value || '').trim().toLowerCase();
    let list = currentProducts;

    if (selectedCategoryFilter) {
        const want = selectedCategoryFilter === '— kategoriyasiz';
        list = list.filter(p => want
            ? !(p.category || '').trim()
            : (p.category || '').toLowerCase() === selectedCategoryFilter.toLowerCase());
    }
    if (q) {
        list = list.filter(p =>
            p.name.toLowerCase().includes(q) ||
            (p.category || '').toLowerCase().includes(q) ||
            (p.description || '').toLowerCase().includes(q));
    }

    const foot = document.getElementById('catalog-foot');
    if (foot) {
        foot.textContent = list.length === currentProducts.length
            ? `${currentProducts.length} ta mahsulot`
            : `${list.length} / ${currentProducts.length} ta mahsulot`;
    }

    if (list.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="table-empty">
            ${currentProducts.length === 0
                ? 'Katalog bo\'sh. <b>Excel katalog yuklash</b> yoki <b>+ Mahsulot</b> bilan boshlang.'
                : 'Bu shartlarga mos mahsulot topilmadi.'}
        </td></tr>`;
        return;
    }

    tbody.innerHTML = list.map(p => {
        const img = (p.image_urls && p.image_urls[0]) || p.image_url || '/static/images/logo.svg';
        const qty = p.stock_quantity;
        const state = !p.in_stock || qty <= 0
            ? '<span class="stock-pill out">Tugagan</span>'
            : qty <= 3
                ? '<span class="stock-pill low">Kam qoldi</span>'
                : '<span class="stock-pill ok">Mavjud</span>';
        return `<tr>
            <td><img src="${escapeHtml(img)}" alt="" class="prod-thumb" loading="lazy"
                     onerror="this.src='/static/images/logo.svg'"></td>
            <td>
                <strong>${escapeHtml(p.name)}</strong>
                <div class="prod-desc">${escapeHtml(p.description || '')}</div>
            </td>
            <td class="cell-muted">${escapeHtml(p.category || '—')}</td>
            <td class="cell-nowrap cell-num">${fmtNum(p.price)} <small>${escapeHtml(p.currency)}</small></td>
            <td style="text-align:center;">${fmtNum(qty)}</td>
            <td style="text-align:center;">${state}</td>
            <td>
                <div class="row-actions">
                    <button onclick="openEditProductModal('${p.id}')" title="Tahrirlash">✏️</button>
                    <button onclick="deleteProduct('${p.id}')" title="O'chirish" class="danger">🗑</button>
                </div>
            </td>
        </tr>`;
    }).join('');
}

// Multi-Image Gallery Handlers & Clean Vector Trash Icon Logic
function triggerFileInput() {
    if (modalImages.length >= 5) {
        alert('Maksimal 5 ta rasm yuklash mumkin!');
        return;
    }
    document.getElementById('prod-file-input').click();
}

function renderGallery() {
    const badge = document.getElementById('image-count-badge');
    const previewContainer = document.getElementById('image-preview-container');
    const previewImg = document.getElementById('modal-image-preview');
    const hintText = document.getElementById('upload-hint-text');
    const addBtn = document.getElementById('btn-add-img');
    const grid = document.getElementById('gallery-thumbnails-grid');

    badge.textContent = `${modalImages.length} / 5`;
    addBtn.disabled = modalImages.length >= 5;

    if (modalImages.length > 0 && activeImageIndex < modalImages.length) {
        previewImg.src = modalImages[activeImageIndex];
        previewContainer.style.display = 'flex';
        hintText.style.display = 'none';
    } else {
        previewImg.src = '';
        previewContainer.style.display = 'none';
        hintText.style.display = 'block';
    }

    grid.innerHTML = '';
    modalImages.forEach((url, idx) => {
        const thumb = document.createElement('div');
        thumb.className = `gallery-thumb-wrapper ${idx === activeImageIndex ? 'active' : ''}`;
        thumb.onclick = () => {
            activeImageIndex = idx;
            renderGallery();
        };

        thumb.innerHTML = `
            <img src="${url}" alt="Thumb ${idx + 1}">
            <button type="button" class="btn-remove-image" title="O'chirish" onclick="removeImageAt(${idx}, event)">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="3 6 5 6 21 6"></polyline>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                </svg>
            </button>
        `;
        grid.appendChild(thumb);
    });
}

function removeActiveImage(event) {
    if (event) event.stopPropagation();
    removeImageAt(activeImageIndex, event);
}

function removeImageAt(index, event) {
    if (event) event.stopPropagation();
    if (index >= 0 && index < modalImages.length) {
        modalImages.splice(index, 1);
        if (activeImageIndex >= modalImages.length) {
            activeImageIndex = Math.max(0, modalImages.length - 1);
        }
        renderGallery();
    }
}

async function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (modalImages.length >= 5) {
        alert('Maksimal 5 ta rasm yuklashingiz mumkin.');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const resp = await fetch('/api/admin/upload', {
            method: 'POST',
            body: formData
        });
        const data = await resp.json();
        if (data.image_url) {
            modalImages.push(data.image_url);
            activeImageIndex = modalImages.length - 1;
            renderGallery();
        }
    } catch (err) {
        console.error('Rasm yuklashda xatolik:', err);
    }
    document.getElementById('prod-file-input').value = '';
}

// Product Add & Edit Modal Handlers
function openAddProductModal() {
    document.getElementById('prod-edit-mode').value = 'add';
    document.getElementById('modal-title').textContent = "Yangi Mahsulot Qo'shish";
    document.getElementById('modal-save-btn').textContent = "Saqlash";

    const idInput = document.getElementById('prod-id');
    idInput.value = 'PROD-' + Math.floor(Math.random() * 900 + 100);
    idInput.disabled = false;

    document.getElementById('prod-name').value = '';
    document.getElementById('prod-price').value = '';
    document.getElementById('prod-stock').value = '10';
    document.getElementById('prod-desc').value = '';

    if (selectedCategoryFilter) {
        document.getElementById('prod-category').value = selectedCategoryFilter;
    }

    modalImages = [];
    activeImageIndex = 0;
    renderGallery();

    document.getElementById('product-modal').style.display = 'flex';
}

function openEditProductModal(productId) {
    const p = currentProducts.find(item => item.id === productId);
    if (!p) return;

    document.getElementById('prod-edit-mode').value = 'edit';
    document.getElementById('modal-title').textContent = "Mahsulotni Tahrirlash";
    document.getElementById('modal-save-btn').textContent = "O'zgarishlarni Saqlash";

    const idInput = document.getElementById('prod-id');
    idInput.value = p.id;
    idInput.disabled = true;

    document.getElementById('prod-name').value = p.name || '';
    document.getElementById('prod-category').value = p.category || '';
    document.getElementById('prod-price').value = p.price || '';
    document.getElementById('prod-stock').value = p.stock_quantity || 10;
    document.getElementById('prod-desc').value = p.description || '';

    if (p.image_urls && p.image_urls.length > 0) {
        modalImages = [...p.image_urls];
    } else if (p.image_url) {
        modalImages = [p.image_url];
    } else {
        modalImages = [];
    }
    activeImageIndex = 0;
    renderGallery();

    document.getElementById('product-modal').style.display = 'flex';
}

function closeProductModal() {
    document.getElementById('product-modal').style.display = 'none';
}

async function saveProductForm() {
    const editMode = document.getElementById('prod-edit-mode').value;
    const productId = document.getElementById('prod-id').value;

    const mainImageUrl = modalImages.length > 0 ? modalImages[0] : null;

    const productData = {
        id: productId,
        name: document.getElementById('prod-name').value.trim(),
        category: document.getElementById('prod-category').value || 'Umumiy',
        price: parseFloat(document.getElementById('prod-price').value) || 0,
        currency: 'UZS',
        description: document.getElementById('prod-desc').value.trim() || '',
        image_url: mainImageUrl,
        image_urls: modalImages,
        in_stock: (parseInt(document.getElementById('prod-stock').value) || 0) > 0,
        stock_quantity: parseInt(document.getElementById('prod-stock').value) || 0
    };

    if (!productData.name || !productData.price) {
        alert('Iltimos, mahsulot nomi va narxini kiriting!');
        return;
    }

    try {
        // fetch only rejects on a network failure, so a 402 from the tariff
        // limit used to sail through here: the modal closed and the list
        // reloaded, which looked exactly like a save. The product was never
        // created and nothing said why.
        const resp = editMode === 'edit'
            ? await fetch(`/api/admin/products/${productId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(productData)
            })
            : await fetch('/api/admin/products', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(productData)
            });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            // 402 means the tariff is the obstacle, not the form — the modal
            // stays open so nothing the owner typed is lost.
            alert(err.detail || `Saqlab bo'lmadi (${resp.status})`);
            return;
        }

        closeProductModal();
        await loadProducts();
        await loadCategories();
    } catch (e) {
        console.error('Mahsulotni saqlashda xatolik:', e);
        alert('Tarmoqda muammo. Qaytadan urinib ko\'ring.');
    }
}

async function deleteProduct(productId) {
    if (!confirm('Ushbu mahsulotni katalogdan o\'chirmoqchimisiz?')) return;
    try {
        await fetch(`/api/admin/products/${productId}`, { method: 'DELETE' });
        await loadProducts();
        await loadCategories();    } catch (e) {
        console.error('O\'chirishda xatolik:', e);
    }
}

let currentOrders = [];
let selectedOrderStatusFilter = 'all';

// Load Orders
async function loadOrders() {
    try {
        const resp = await fetch('/api/admin/orders');
        currentOrders = await resp.json();
        renderOrdersTable();
    } catch (e) {
        console.error('Buyurtmalarni yuklashda xatolik:', e);
    }
}

function filterOrdersByStatus(status, el) {
    selectedOrderStatusFilter = status;
    if (el) {
        document.querySelectorAll('.filter-pill').forEach(btn => btn.classList.remove('active'));
        el.classList.add('active');
    }
    renderOrdersTable();
}

function renderOrdersTable() {
    const tbody = document.getElementById('orders-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    // Update Pill Count Badges
    const countAll = currentOrders.length;
    const countYangi = currentOrders.filter(o => o.status === 'Yangi').length;
    const countTasdiqlandi = currentOrders.filter(o => o.status === 'Tasdiqlandi').length;
    const countYolda = currentOrders.filter(o => o.status === "Yo'lda").length;
    const countYetkazildi = currentOrders.filter(o => o.status === 'Yetkazildi').length;
    const countBekor = currentOrders.filter(o => o.status === 'Bekor qilindi').length;

    if (document.getElementById('count-order-all')) document.getElementById('count-order-all').textContent = countAll;
    if (document.getElementById('count-order-yangi')) document.getElementById('count-order-yangi').textContent = countYangi;
    if (document.getElementById('count-order-tasdiqlandi')) document.getElementById('count-order-tasdiqlandi').textContent = countTasdiqlandi;
    if (document.getElementById('count-order-yolda')) document.getElementById('count-order-yolda').textContent = countYolda;
    if (document.getElementById('count-order-yetkazildi')) document.getElementById('count-order-yetkazildi').textContent = countYetkazildi;
    if (document.getElementById('count-order-bekor')) document.getElementById('count-order-bekor').textContent = countBekor;

    // Filter Logic
    const searchTerm = (document.getElementById('order-search-input')?.value || '').toLowerCase();
    const filtered = currentOrders.filter(o => {
        const matchesStatus = selectedOrderStatusFilter === 'all' || o.status === selectedOrderStatusFilter;
        const matchesSearch = !searchTerm || 
            o.id.toLowerCase().includes(searchTerm) || 
            o.customer_name.toLowerCase().includes(searchTerm) || 
            o.customer_phone.toLowerCase().includes(searchTerm);
        return matchesStatus && matchesSearch;
    });

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 36px;">Ushbu holatda buyurtmalar topilmadi.</td></tr>`;
        return;
    }

    filtered.forEach(o => {
        const itemsStr = o.items.map(i => `${i.product_name} (${i.quantity}x)`).join(', ');
        const badgeClass = o.status === 'Yangi' ? 'badge-yangi' :
                           o.status === 'Tasdiqlandi' ? 'badge-tasdiqlandi' :
                           o.status === "Yo'lda" ? 'badge-yolda' :
                           o.status === 'Yetkazildi' ? 'badge-yetkazildi' : 'badge-bekor';

        const statusSelected = (val) => o.status === val ? 'selected' : '';

        const tr = document.createElement('tr');

        // Every value below reaches us from a Telegram customer, so it is
        // escaped: an unescaped name let an outsider run script in the shop
        // owner's panel, with the owner's session attached.
        tr.innerHTML = `
            <td><code>${escapeHtml(o.id)}</code></td>
            <td style="font-size: 12px; color: var(--text-muted);">${escapeHtml(o.created_at)}</td>
            <td><strong>${escapeHtml(o.customer_name)}</strong></td>
            <td>${escapeHtml(o.customer_phone)}</td>
            <td style="max-width: 220px; font-size: 13px;">${escapeHtml(itemsStr)}</td>
            <td><strong>${o.total_amount.toLocaleString()} UZS</strong></td>
            <td>
                <select class="status-select ${badgeClass}" onchange="updateOrderStatus('${o.id}', this.value)">
                    <option value="Yangi" ${statusSelected('Yangi')}>🔥 Yangi</option>
                    <option value="Tasdiqlandi" ${statusSelected('Tasdiqlandi')}>⚡️ Tasdiqlandi</option>
                    <option value="Yo'lda" ${statusSelected("Yo'lda")}>🚚 Yo'lda</option>
                    <option value="Yetkazildi" ${statusSelected('Yetkazildi')}>✅ Yetkazildi</option>
                    <option value="Bekor qilindi" ${statusSelected('Bekor qilindi')}>❌ Bekor qilindi</option>
                </select>
            </td>
            <td>
                <button class="btn-detail" data-id="${o.id}" style="background: rgba(2,132,199,0.1); border: 1px solid rgba(2,132,199,0.25); color: #0284c7; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 700;">
                    👁 Tafsilotlar
                </button>
            </td>
        `;

        // Attach detail click using data attributes (avoids all quote issues)
        tr.querySelector('.btn-detail').addEventListener('click', function() {
            showOrderDetail(o);
        });

        tbody.appendChild(tr);
    });
}

function showOrderDetail(o) {
    const addr = o.delivery_address || 'Kiritilmagan';
    const note = o.notes || "Yo'q";
    alert(`Buyurtma: ${o.id}\nMijoz: ${o.customer_name}\nTelefon: ${o.customer_phone}\nManzil: ${addr}\nEslatma: ${note}`);
}

async function updateOrderStatus(orderId, newStatus) {
    try {
        await fetch(`/api/admin/orders/${orderId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        await loadOrders();
        await loadDashboardStats();
    } catch (e) {
        console.error('Status o\'zgartirishda xatolik:', e);
    }
}

// ════════════════════════════════════════════════════════
// AI AGENT — persona + prompt settings
// ════════════════════════════════════════════════════════
const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v ?? ''; };

// Settings the simplified panel does not expose. Kept here so saving the
// visible fields never silently resets them.
let hiddenSettings = { ai_provider: 'gemini', model_name: 'gemini-3.5-flash-lite', auto_handoff_after: 3 };

async function loadSettings() {
    try {
        const resp = await fetch('/api/admin/settings');
        const data = await resp.json();

        hiddenSettings = {
            ai_provider: data.ai_provider || 'gemini',
            model_name: data.model_name || 'gemini-3.5-flash-lite',
            auto_handoff_after: data.auto_handoff_after || 3
        };

        setVal('setting-prompt', data.system_prompt);
        setVal('ai-name', data.ai_name || 'Sotuvchi AI');
        setVal('ai-tone', data.ai_tone || 'friendly');
        setVal('ai-language', data.ai_language || 'uz');
        setVal('ai-greeting', data.greeting_message);

        // Knowledge Base
        setVal('kb-fee-city', data.delivery_fee_city);
        setVal('kb-fee-regions', data.delivery_fee_regions);
        setVal('kb-free-from', data.free_delivery_from);
        setVal('kb-days-city', data.delivery_days_city);
        setVal('kb-days-regions', data.delivery_days_regions);
        setVal('kb-delivery', data.delivery_info);
        setVal('kb-payment', data.payment_info);
        setVal('kb-warranty', data.warranty_info);
        setVal('kb-return', data.return_policy);
        setVal('kb-hours', data.working_hours);
        setVal('kb-faq', data.faq);
        renderKbStatus(data);

        const badge = document.getElementById('ai-provider-badge');
        if (badge) badge.textContent = 'Model: ' + hiddenSettings.model_name;
    } catch (e) {
        console.error('Sozlamalarni yuklashda xatolik:', e);
    }
}

/** How complete the Knowledge Base is — an empty one means constant handoffs. */
function renderKbStatus(d) {
    const el = document.getElementById('kb-status');
    if (!el) return;
    const fields = [d.delivery_fee_city, d.payment_info, d.warranty_info,
                    d.return_policy, d.working_hours, d.faq];
    const filled = fields.filter(v => v !== null && v !== undefined && v !== '').length;
    el.classList.remove('is-ok', 'is-warn');
    if (filled === fields.length) {
        el.classList.add('is-ok');
        el.textContent = '✅ Bilimlar bazasi to\'liq — AI bu savollarga o\'zi javob beradi.';
    } else if (filled === 0) {
        el.classList.add('is-warn');
        el.textContent = '⚠️ Bo\'sh. AI to\'lov/kafolat/yetkazib berish savollarida operatorga uzatadi.';
    } else {
        el.classList.add('is-warn');
        el.textContent = `${filled}/${fields.length} to'ldirilgan. To'ldirmagan bo'limlarda AI operatorga uzatadi.`;
    }
}

async function saveSettings() {
    const gv = (id) => { const el = document.getElementById(id); return el ? el.value : null; };
    const num = (v) => (v === null || v === '' ? null : parseFloat(v));
    try {
        const resp = await fetch('/api/admin/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ...hiddenSettings,
                system_prompt: gv('setting-prompt') || '',
                ai_name: gv('ai-name'),
                ai_tone: gv('ai-tone'),
                ai_language: gv('ai-language'),
                greeting_message: gv('ai-greeting'),
                // Knowledge Base — empty means "not set", so the AI stays silent
                // on that topic rather than inventing an answer
                delivery_fee_city: num(gv('kb-fee-city')),
                delivery_fee_regions: num(gv('kb-fee-regions')),
                free_delivery_from: num(gv('kb-free-from')),
                delivery_days_city: gv('kb-days-city') || null,
                delivery_days_regions: gv('kb-days-regions') || null,
                delivery_info: gv('kb-delivery') || null,
                payment_info: gv('kb-payment') || null,
                warranty_info: gv('kb-warranty') || null,
                return_policy: gv('kb-return') || null,
                working_hours: gv('kb-hours') || null,
                faq: gv('kb-faq') || null
            })
        });
        if (!resp.ok) throw new Error('save failed');
        toast('Saqlandi ✅');
        loadSettings();
    } catch (e) {
        console.error('Saqlashda xatolik:', e);
        toast('Saqlashda xatolik', true);
    }
}

// ════════════════════════════════════════════════════════
// INBOX — live conversations, operator reply, handoff
// ════════════════════════════════════════════════════════
let inboxFilter = 'all';
let activeConvId = null;
let inboxPollTimer = null;

function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function toast(msg, isError) {
    let el = document.getElementById('app-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'app-toast';
        el.className = 'app-toast';
        document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.background = isError ? '#e11d48' : '#0f172a';
    el.classList.add('show');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('show'), 2200);
}

const CHANNEL_ICON = { telegram: '✈️', web: '🌐', instagram: '📸' };
const isSandbox = (c) => (c.external_id || '').startsWith('sandbox-');
const STATUS_LABEL = { ai: '🤖 AI', operator: '👨‍💼 Operator', closed: '✅ Yopilgan' };

async function loadInbox() {
    try {
        const resp = await fetch('/api/inbox/conversations?status=' + inboxFilter);
        const list = await resp.json();
        renderInboxList(list);
        updateInboxBadge(list);
    } catch (e) {
        console.error('Inbox yuklashda xatolik:', e);
    }
}

function updateInboxBadge(list) {
    const waitingIds = (list || []).filter(c => c.waiting_for_operator).map(c => c.id);
    const unread = (list || []).reduce((n, c) => n + (c.unread_count || 0), 0);
    // Waiting-for-operator wins: it is the number someone must act on
    const count = waitingIds.length || unread;
    for (const id of ['inbox-nav-badge', 'mobile-inbox-badge']) {
        const badge = document.getElementById(id);
        if (!badge) continue;
        badge.textContent = count;
        badge.style.display = count > 0 ? 'inline-flex' : 'none';
        badge.classList.toggle('urgent', waitingIds.length > 0);
    }
    // Keep the alert set in sync with what the operator is already looking at,
    // so switching tabs never re-announces the same conversation.
    notifiedWaiting = new Set(waitingIds);
}

function renderInboxList(list) {
    const box = document.getElementById('inbox-conversations');
    if (!box) return;
    if (!list || list.length === 0) {
        box.innerHTML = `<div class="inbox-empty-list">Hali suhbatlar yo'q.<br><span>Telegram botni ulang yoki Test rejimida sinab ko'ring.</span></div>`;
        return;
    }
    box.innerHTML = list.map(c => `
        <div class="conv-item ${c.id === activeConvId ? 'active' : ''} ${c.waiting_for_operator ? 'waiting' : ''}" onclick="openConversation('${c.id}')">
            <div class="conv-avatar">${isSandbox(c) ? '🧪' : (CHANNEL_ICON[c.channel] || '💬')}</div>
            <div class="conv-body">
                <div class="conv-top">
                    <span class="conv-name">${escapeHtml(c.customer_name)}${isSandbox(c) ? ' <span class="conv-sandbox">sinov</span>' : ''}</span>
                    <span class="conv-time">${c.last_message_at || ''}</span>
                </div>
                <div class="conv-preview">${escapeHtml(c.last_message)}</div>
                <div class="conv-tags">
                    <span class="conv-status status-${c.status}">${STATUS_LABEL[c.status] || c.status}</span>
                    ${c.waiting_for_operator ? '<span class="conv-waiting">⏳ javob kutmoqda</span>' : ''}
                    ${c.assigned_user_name ? `<span class="conv-assignee">👤 ${escapeHtml(c.assigned_user_name)}</span>` : ''}
                    ${c.unread_count > 0 ? `<span class="conv-unread">${c.unread_count}</span>` : ''}
                </div>
            </div>
        </div>
    `).join('');

    const waiting = list.filter(c => c.waiting_for_operator).length;
    renderHandoffBanner(waiting);
}

function renderHandoffBanner(waiting) {
    const banner = document.getElementById('handoff-banner');
    if (!banner) return;
    banner.style.display = waiting > 0 ? 'flex' : 'none';
    if (waiting > 0) {
        document.getElementById('handoff-banner-text').textContent =
            `${waiting} ta mijoz operator javobini kutmoqda`;
    }
}

function filterInboxTo(status) {
    const btn = document.querySelector(`.inbox-filter[data-status="${status}"]`);
    if (btn) filterInbox(status, btn);
}

/** Dashboard escalation tile: open the Inbox already filtered to handoffs. */
function openInboxOperator() {
    switchToTab('tab-inbox');
    setTimeout(() => filterInboxTo('operator'), 250);
}

function filterInbox(status, btn) {
    inboxFilter = status;
    document.querySelectorAll('.inbox-filter').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadInbox();
}

async function openConversation(convId) {
    activeConvId = convId;
    try {
        const resp = await fetch('/api/inbox/conversations/' + convId);
        if (!resp.ok) return;
        const data = await resp.json();

        document.getElementById('inbox-empty').style.display = 'none';
        document.getElementById('inbox-chat-active').style.display = 'flex';

        const c = data.conversation;
        document.getElementById('inbox-chat-header').innerHTML = `
            <div>
                <div class="chat-customer">${CHANNEL_ICON[c.channel] || '💬'} ${escapeHtml(c.customer_name)}</div>
                <div class="chat-meta">${escapeHtml(c.customer_phone || c.external_id || '')}${c.assigned_user_name ? ' · 👤 ' + escapeHtml(c.assigned_user_name) : ''}</div>
                ${c.status === 'operator' && c.handoff_reason ? `<div class="chat-reason">🔔 ${escapeHtml(c.handoff_reason)}</div>` : ''}
            </div>
            <div class="chat-actions">
                <span class="conv-status status-${c.status}">${STATUS_LABEL[c.status] || c.status}</span>
                ${c.status !== 'operator' ? `<button class="btn-mini" onclick="setConvStatus('${c.id}','operator')">👨‍💼 Men javob beraman</button>` : ''}
                ${c.status !== 'ai' ? `<button class="btn-mini" onclick="setConvStatus('${c.id}','ai')">🤖 AI'ga qaytar</button>` : ''}
                ${c.status !== 'closed' ? `<button class="btn-mini" onclick="setConvStatus('${c.id}','closed')">✅ Yopish</button>` : ''}
                <button class="btn-mini danger" onclick="deleteConversation('${c.id}')" title="Suhbatni o'chirish">🗑</button>
            </div>`;

        renderMessages('inbox-messages', data.messages);
        loadInbox();
    } catch (e) {
        console.error('Suhbatni ochishda xatolik:', e);
    }
}

function renderMessages(containerId, messages) {
    const box = document.getElementById(containerId);
    if (!box) return;
    box.innerHTML = (messages || []).map(m => {
        const side = m.sender === 'user' ? 'left' : 'right';
        const who = { user: 'Mijoz', assistant: '🤖 AI', operator: '👨‍💼 Operator', system: 'Tizim' }[m.sender] || m.sender;
        const meta = m.model_name && m.model_name !== 'fallback' ? ` · ${m.model_name}` : (m.model_name === 'fallback' ? ' · demo' : '');
        // Show the product images the AI sent, so the operator sees the full exchange
        const photos = (m.photos || []).map(p =>
            `<img src="${escapeHtml(p.url)}" class="msg-photo" loading="lazy"
                  onerror="this.style.display='none'" alt="">`).join('');
        return `<div class="msg msg-${side} sender-${m.sender}">
            <div class="msg-who">${who}${meta}</div>
            <div class="msg-bubble">${escapeHtml(m.text).replace(/\n/g, '<br>')}</div>
            ${photos ? `<div class="msg-photos">${photos}</div>` : ''}
            <div class="msg-time">${m.created_at || ''}</div>
        </div>`;
    }).join('');
    box.scrollTop = box.scrollHeight;
}

async function sendOperatorReply() {
    const input = document.getElementById('inbox-reply-text');
    const text = input.value.trim();
    if (!text || !activeConvId) return;
    input.value = '';
    try {
        const resp = await fetch(`/api/inbox/conversations/${activeConvId}/reply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        if (!resp.ok) throw new Error('reply failed');
        openConversation(activeConvId);
    } catch (e) {
        toast('Yuborishda xatolik', true);
    }
}

async function setConvStatus(convId, status) {
    try {
        await fetch(`/api/inbox/conversations/${convId}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status })
        });
        openConversation(convId);
        toast(status === 'operator' ? 'Siz javob berasiz' : status === 'ai' ? "AI'ga qaytarildi" : 'Suhbat yopildi');
    } catch (e) {
        toast('Xatolik', true);
    }
}

async function deleteConversation(convId) {
    if (!confirm("Bu suhbat va uning barcha xabarlari o'chiriladi. Davom etamizmi?")) return;
    try {
        const resp = await fetch(`/api/inbox/conversations/${convId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('delete failed');
        activeConvId = null;
        document.getElementById('inbox-chat-header').innerHTML = '';
        document.getElementById('inbox-messages').innerHTML =
            '<div class="inbox-empty">Suhbatni tanlang</div>';
        await loadInbox();
        toast("Suhbat o'chirildi");
    } catch (e) {
        toast("O'chirishda xatolik", true);
    }
}

function startInboxPolling() {
    if (inboxPollTimer) clearInterval(inboxPollTimer);
    inboxPollTimer = setInterval(async () => {
        const inboxTab = document.getElementById('tab-inbox');
        if (inboxTab && inboxTab.classList.contains('active')) {
            loadInbox();
            if (activeConvId) refreshActiveConversation();
        } else {
            // Cheap check from any other tab so a waiting customer is never
            // invisible just because the operator is looking at the catalog.
            try {
                const d = await (await fetch('/api/inbox/waiting-count')).json();
                updateWaitingBadge(d.ids || []);
            } catch (e) { /* offline; try again next tick */ }
        }
    }, 8000);
}

// Conversations already announced. Alerting once per conversation is what stops
// the toast reappearing every poll after the operator has replied.
let notifiedWaiting = new Set();

function updateWaitingBadge(waitingIds) {
    for (const id of ['inbox-nav-badge', 'mobile-inbox-badge']) {
        const badge = document.getElementById(id);
        if (!badge) continue;
        badge.textContent = waitingIds.length;
        badge.style.display = waitingIds.length > 0 ? 'inline-flex' : 'none';
        badge.classList.toggle('urgent', waitingIds.length > 0);
    }

    const fresh = waitingIds.filter(id => !notifiedWaiting.has(id));
    if (fresh.length) {
        toast(fresh.length === 1
            ? '🔔 Mijoz operator javobini kutmoqda'
            : `🔔 ${fresh.length} ta mijoz operator kutmoqda`);
    }
    // Replying removes the id server-side, so it can alert again only when
    // that customer writes a new message.
    notifiedWaiting = new Set(waitingIds);
}

/** Re-render the open chat without stealing scroll if nothing changed. */
async function refreshActiveConversation() {
    try {
        const resp = await fetch('/api/inbox/conversations/' + activeConvId);
        if (!resp.ok) return;
        const data = await resp.json();
        const box = document.getElementById('inbox-messages');
        if (box && box.children.length !== data.messages.length) {
            renderMessages('inbox-messages', data.messages);
        }
    } catch (e) { /* ignore transient errors */ }
}

// ════════════════════════════════════════════════════════
// AI SANDBOX (test rejimi)
// ════════════════════════════════════════════════════════
// Reuse one sandbox conversation across reloads, otherwise every page refresh
// would spawn a new thread and clutter the Inbox.
let testSessionId = localStorage.getItem('sotuvchi_sandbox_id');
if (!testSessionId) {
    testSessionId = 'sandbox-' + Math.random().toString(36).slice(2, 10);
    localStorage.setItem('sotuvchi_sandbox_id', testSessionId);
}
let testMessages = [];

async function sendTestMessage() {
    const input = document.getElementById('test-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    testMessages.push({ sender: 'user', text, created_at: '' });
    renderMessages('test-messages', testMessages);

    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: testSessionId, message: text, user_name: 'Test mijoz' })
        });
        const data = await resp.json();
        testMessages.push({ sender: 'assistant', text: data.reply_text, created_at: '' });
        renderMessages('test-messages', testMessages);
    } catch (e) {
        toast('AI javob bermadi', true);
    }
}

// ════════════════════════════════════════════════════════
// KATALOG IMPORT (Excel / CSV)
// ════════════════════════════════════════════════════════
let importFile = null;

function openImportModal() {
    importFile = null;
    document.getElementById('import-file').value = '';
    document.getElementById('import-file-label').textContent = 'Fayl tanlash uchun bosing';
    document.getElementById('import-step-pick').style.display = 'block';
    document.getElementById('import-step-result').style.display = 'none';
    document.getElementById('import-confirm-btn').style.display = 'none';
    document.getElementById('import-modal').style.display = 'flex';
}

function closeImportModal() {
    document.getElementById('import-modal').style.display = 'none';
}

function handleImportFile(e) {
    const f = e.target.files[0];
    if (!f) return;
    importFile = f;
    document.getElementById('import-file-label').textContent = f.name;
    runImport(true);   // preview first — never write before the user sees the result
}

async function runImport(dryRun) {
    if (!importFile) return;
    const resultBox = document.getElementById('import-step-result');
    const confirmBtn = document.getElementById('import-confirm-btn');

    resultBox.style.display = 'block';
    resultBox.innerHTML = '<p style="font-size:13px;color:var(--text-muted);">Fayl o\'qilmoqda...</p>';
    confirmBtn.disabled = true;

    const fd = new FormData();
    fd.append('file', importFile);

    try {
        const resp = await fetch('/api/admin/products/import?dry_run=' + (dryRun ? 'true' : 'false'), {
            method: 'POST', body: fd
        });
        const d = await resp.json();

        if (!resp.ok) {
            resultBox.innerHTML = `<div class="import-errors">${escapeHtml(d.detail || 'Xatolik')}</div>`;
            confirmBtn.style.display = 'none';
            return;
        }
        if (d.success === false) {
            resultBox.innerHTML = `
                <div class="import-errors">
                    <b>${escapeHtml(d.error)}</b><br>
                    Faylda topilgan ustunlar: ${(d.found_columns || []).map(escapeHtml).join(', ') || '—'}<br>
                    Kutilgan: ${escapeHtml(d.expected || '')}
                </div>`;
            confirmBtn.style.display = 'none';
            return;
        }

        renderImportResult(d, dryRun);

        if (dryRun) {
            confirmBtn.style.display = (d.added + d.updated) > 0 ? 'inline-flex' : 'none';
            confirmBtn.disabled = false;
            confirmBtn.textContent = `Yuklash (${d.added + d.updated} ta)`;
        } else {
            confirmBtn.style.display = 'none';
            toast(`✅ ${d.added} ta qo'shildi, ${d.updated} ta yangilandi`);
            await loadProducts();
            await loadCategories();

            // A price list often has no category column — offer to fix that now,
            // while the user is still looking at the result.
            const uncategorized = (currentProducts || []).filter(p => !(p.category || '').trim()).length;
            if (uncategorized > 0) {
                document.getElementById('import-step-result').insertAdjacentHTML('beforeend', `
                    <div class="import-suggest">
                        <b>${uncategorized} ta mahsulotda kategoriya yo'q.</b>
                        AI ularni avtomatik ajratib bersinmi?
                        <button class="btn-mini" onclick="autoCategorize(); closeImportModal();">✨ Ha, ajrat</button>
                    </div>`);
            }
        }
    } catch (err) {
        resultBox.innerHTML = '<div class="import-errors">Serverga ulanishda xatolik.</div>';
        confirmBtn.style.display = 'none';
    }
}

function renderImportResult(d, dryRun) {
    const mapped = Object.values(d.matched_columns || {})
        .map(h => `<code>${escapeHtml(h)}</code>`).join(' ');
    const ignored = (d.ignored_columns || []).length
        ? `<br>E'tiborga olinmadi: ${d.ignored_columns.map(h => `<code>${escapeHtml(h)}</code>`).join(' ')}`
        : '';

    const errs = (d.errors || []).length
        ? `<div class="import-errors">
             <b>${d.error_count} ta qator o'tkazib yuborildi:</b><br>
             ${d.errors.map(e => `${e.row}-qator: ${escapeHtml(e.error)}${e.name ? ' (' + escapeHtml(e.name) + ')' : ''}`).join('<br>')}
             ${d.error_count > d.errors.length ? '<br>…' : ''}
           </div>`
        : '';

    document.getElementById('import-step-result').innerHTML = `
        <div style="font-size:13px;font-weight:700;margin-bottom:10px;">
            ${dryRun ? "👀 Oldindan ko'rish — hali saqlanmadi" : '✅ Yuklandi'}
        </div>
        <div class="import-summary">
            <div class="import-stat ok"><b>${d.added}</b><span>yangi</span></div>
            <div class="import-stat"><b>${d.updated}</b><span>yangilandi</span></div>
            <div class="import-stat ${d.skipped ? 'warn' : ''}"><b>${d.skipped}</b><span>o'tkazildi</span></div>
        </div>
        <div class="import-mapped">Tanildi: ${mapped || '—'}${ignored}</div>
        ${errs}`;
}

// ── AI auto-categorisation ──
async function autoCategorize(onlyUncategorized = true) {
    const btn = document.getElementById('ai-cat-btn');
    const original = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '✨ Ajratilmoqda...'; }

    try {
        const resp = await fetch('/api/admin/products/auto-categorize?only_uncategorized=' + onlyUncategorized, {
            method: 'POST'
        });
        const d = await resp.json();

        if (!d.success) {
            toast(d.error || 'Kategoriyalashda xatolik', true);
            return;
        }
        if (d.updated === 0) {
            toast(d.message || 'O\'zgarish yo\'q');
            return;
        }

        toast(`✨ ${d.updated} ta mahsulot ${d.categories.length} ta kategoriyaga ajratildi`);
        await loadProducts();
        await loadCategories();
    } catch (e) {
        toast('Serverga ulanishda xatolik', true);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = original; }
    }
}

// ════════════════════════════════════════════════════════
// MIJOZLAR
// ════════════════════════════════════════════════════════
const CH_LABEL = { telegram: 'Telegram', web: 'Sayt', instagram: 'Instagram', manual: 'Qo\'lda' };
let custSearchTimer = null;

async function loadCustomers(q = '') {
    const tbody = document.getElementById('customers-tbody');
    if (!tbody) return;
    try {
        const resp = await fetch(`/api/admin/customers?q=${encodeURIComponent(q)}`);
        if (!resp.ok) throw new Error('yuklanmadi');
        const list = await resp.json();

        document.getElementById('cust-count').textContent =
            list.length ? `${list.length} ta mijoz` : '';

        if (!list.length) {
            tbody.innerHTML = `<tr><td colspan="6" class="table-empty">${
                q ? 'Bunday mijoz topilmadi.'
                  : 'Hali mijoz yo\'q. Birinchi suhbat boshlanishi bilan shu yerda paydo bo\'ladi.'
            }</td></tr>`;
            return;
        }

        tbody.innerHTML = list.map((c) => `
            <tr class="row-click" data-cust="${escapeHtml(c.id)}">
                <td><strong>${escapeHtml(c.customer_name)}</strong>${
                    c.telegram_username ? `<span class="cell-sub">@${escapeHtml(c.telegram_username)}</span>` : ''}</td>
                <td class="cell-nowrap">${escapeHtml(c.customer_phone) || '<span class="cell-dim">—</span>'}</td>
                <td>${c.channels.map((ch) =>
                    `<span class="chip">${escapeHtml(CH_LABEL[ch] || ch)}</span>`).join(' ')}</td>
                <td class="cell-num">${fmtNum(c.order_count)}</td>
                <td class="cell-num">${c.ltv ? fmtNum(c.ltv) + ' <small>so\'m</small>' : '<span class="cell-dim">—</span>'}</td>
                <td class="cell-nowrap cell-date">${escapeHtml(c.last_seen_at || '—')}</td>
            </tr>`).join('');

        tbody.querySelectorAll('[data-cust]').forEach((tr) =>
            tr.addEventListener('click', () => openCustomer(tr.dataset.cust)));
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="6" class="table-empty">Mijozlarni yuklab bo\'lmadi.</td></tr>';
        console.error('Mijozlarni yuklashda xatolik:', e);
    }
}

function initCustomerSearch() {
    const box = document.getElementById('cust-search');
    if (!box) return;
    // Debounced: every keystroke would otherwise be a query against a table
    // that grows with the shop.
    box.addEventListener('input', () => {
        clearTimeout(custSearchTimer);
        custSearchTimer = setTimeout(() => loadCustomers(box.value.trim()), 250);
    });
}

function closeCustomerModal() {
    document.getElementById('customer-modal').style.display = 'none';
}

async function openCustomer(id) {
    const modal = document.getElementById('customer-modal');
    const body = document.getElementById('cust-body');
    modal.style.display = 'flex';
    body.innerHTML = '<p class="table-empty">Yuklanmoqda…</p>';

    let d;
    try {
        const resp = await fetch(`/api/admin/customers/${encodeURIComponent(id)}`);
        if (!resp.ok) throw new Error('topilmadi');
        d = await resp.json();
    } catch (e) {
        body.innerHTML = '<p class="table-empty">Mijoz ma\'lumotini ochib bo\'lmadi.</p>';
        return;
    }

    document.getElementById('cust-name').textContent = d.name;
    document.getElementById('cust-sub').textContent =
        [d.phone, d.telegram_username ? '@' + d.telegram_username : '',
         d.channels.map((c) => CH_LABEL[c] || c).join(', ')].filter(Boolean).join(' · ');

    body.innerHTML = `
        <div class="cust-stats">
            <div><b>${fmtNum(d.orders_count)}</b><span>buyurtma</span></div>
            <div><b>${fmtNum(d.total_spent)}</b><span>jami xarid, so'm</span></div>
            <div><b>${escapeHtml(d.first_seen_at || '—')}</b><span>birinchi murojaat</span></div>
        </div>

        <label class="form-group">
            <span class="form-label">Izoh — sizga kerakli har qanday narsa</span>
            <textarea id="cust-note" class="form-control" rows="2"
                      placeholder="Masalan: kechqurun yetkazib berish qulay">${escapeHtml(d.note || '')}</textarea>
        </label>
        <button class="btn-secondary" id="cust-note-save">Izohni saqlash</button>

        <h4 class="cust-h">Buyurtmalar</h4>
        ${d.orders.length ? `<div class="cust-list">${d.orders.map((o) => `
            <div class="cust-order">
                <div class="cust-order-top">
                    <code>${escapeHtml(o.id)}</code>
                    <span class="badge badge-${o.status.toLowerCase().replace(/[^a-z]/g, '')}">${escapeHtml(o.status)}</span>
                    <span class="cust-order-sum">${fmtNum(o.total_amount)} so'm</span>
                </div>
                <div class="cust-order-items">${o.items.map((i) =>
                    `${escapeHtml(i.product_name)} × ${i.quantity}`).join(', ') || '—'}</div>
                <div class="cell-dim">${escapeHtml(o.created_at || '')}</div>
            </div>`).join('')}</div>`
          : '<p class="cell-dim">Hali buyurtma bermagan.</p>'}

        <h4 class="cust-h">Suhbatlar</h4>
        ${d.conversations.length ? `<div class="cust-list">${d.conversations.map((c) => `
            <div class="cust-conv" data-conv="${escapeHtml(c.id)}">
                <span class="chip">${escapeHtml(CH_LABEL[c.channel] || c.channel)}</span>
                <span>${escapeHtml(c.last_message_at || '')}</span>
                <span class="cell-dim">${escapeHtml(c.status)}</span>
            </div>`).join('')}</div>`
          : '<p class="cell-dim">Suhbat yo\'q.</p>'}`;

    document.getElementById('cust-note-save').addEventListener('click', async () => {
        try {
            const r = await fetch(`/api/admin/customers/${encodeURIComponent(id)}/note`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ note: document.getElementById('cust-note').value }),
            });
            if (!r.ok) throw new Error((await r.json()).detail || 'Saqlanmadi');
            toast('Izoh saqlandi');
        } catch (e) { toast(e.message, true); }
    });

    // Jumping straight into the chat is the whole point of seeing the history
    body.querySelectorAll('[data-conv]').forEach((el) =>
        el.addEventListener('click', () => {
            closeCustomerModal();
            document.querySelector('[data-tab="tab-inbox"]').click();
            setTimeout(() => openConversation(el.dataset.conv), 300);
        }));
}

// ════════════════════════════════════════════════════════
// INTEGRATSIYALAR — Telegram
// ════════════════════════════════════════════════════════
async function loadIntegrations() {
    loadOperatorPairing();
    loadGroups();
    loadSheetsStatus();
    try {
        const resp = await fetch('/api/integrations/telegram');
        const d = await resp.json();
        document.getElementById('tg-status-text').textContent = d.connected ? 'Ulangan' : 'Ulanmagan';
        document.getElementById('tg-connected').style.display = d.connected ? 'block' : 'none';
        document.getElementById('tg-disconnected').style.display = d.connected ? 'none' : 'block';
        if (d.connected) {
            document.getElementById('tg-username').textContent = '@' + (d.username || '—');
            const note = document.getElementById('tg-note');
            if (d.polling_enabled) {
                note.innerHTML = d.polling_active
                    ? "🟢 <b>Localhost rejimi faol</b> — Telegram'da botga yozing, xabar shu Inbox'ga tushadi."
                    : "🟡 Localhost rejimi yoqilgan, ulanish tayyorlanmoqda (~30 soniya)...";
            } else if (d.public_url_configured) {
                note.textContent = "🟢 Webhook faol — mijozlar xabarlari Inbox'ga tushadi.";
            } else {
                note.textContent = "⚠️ Na polling na public URL yoqilgan — xabarlar kelmaydi.";
            }
        }
    } catch (e) {
        console.error('Integratsiyalarni yuklashda xatolik:', e);
    }
}

// ── Team groups ──
const GROUP_META = {
    buyurtmalar: { icon: '🧾', label: 'Buyurtmalar guruhi', hint: 'Yangi buyurtma cheki + tasdiqlash tugmasi' },
    ishchi:      { icon: '📦', label: 'Ishchi guruh',       hint: 'Tasdiqlangan buyurtma yetkazish uchun' },
    operatorlar: { icon: '🙋', label: 'Operatorlar guruhi', hint: 'Mijoz operator so\'raganda xabar' },
};

async function loadGroups() {
    try {
        const d = await (await fetch('/api/integrations/groups')).json();
        const box = document.getElementById('groups-list');
        if (!box) return;

        box.innerHTML = Object.entries(GROUP_META).map(([key, m]) => {
            const g = (d.groups || {})[key] || {};
            return `<div class="group-row ${g.id ? 'connected' : ''}">
                <span class="group-icon">${m.icon}</span>
                <div class="group-body">
                    <div class="group-name">${m.label}</div>
                    <div class="group-sub">${g.id ? escapeHtml(g.title || 'Guruh') : m.hint}</div>
                </div>
                ${g.id
                    ? `<button class="btn-mini danger" onclick="disconnectGroup('${key}')">Uzish</button>`
                    : '<span class="group-pending">ulanmagan</span>'}
            </div>`;
        }).join('');

        const btn = document.getElementById('group-code-btn');
        const pair = document.getElementById('group-pair-box');
        if (!d.bot_connected) {
            btn.style.display = 'none';
            pair.style.display = 'none';
            box.insertAdjacentHTML('beforeend',
                '<p class="field-hint">Avval Telegram botni ulang — guruhlar shu bot orqali ishlaydi.</p>');
        } else if (d.pairing_code) {
            showGroupCode(d.pairing_code, d.bot_username);
        } else {
            pair.style.display = 'none';
            btn.style.display = 'inline-flex';
        }
    } catch (e) {
        console.error('Guruhlarni yuklashda xatolik:', e);
    }
}

function showGroupCode(code, botUsername) {
    document.getElementById('group-code').textContent = code;
    document.getElementById('group-cmd').textContent = `/guruh buyurtmalar ${code}`;
    document.getElementById('group-bot-name').textContent = botUsername ? '@' + botUsername : 'botingiz';
    document.getElementById('group-pair-box').style.display = 'block';
    document.getElementById('group-code-btn').style.display = 'none';
}

async function getGroupCode() {
    try {
        const r = await fetch('/api/integrations/groups/pair-code', { method: 'POST' });
        const d = await r.json();
        if (!r.ok) { toast(d.detail || 'Xatolik', true); return; }
        showGroupCode(d.pairing_code, d.bot_username);
    } catch (e) {
        toast('Kod olishda xatolik', true);
    }
}

async function disconnectGroup(kind) {
    if (!confirm('Bu guruhni uzmoqchimisiz?')) return;
    await fetch(`/api/integrations/groups/${kind}/disconnect`, { method: 'POST' });
    toast('Uzildi');
    loadGroups();
}

// ── Operator alert pairing ──
async function loadOperatorPairing() {
    try {
        const d = await (await fetch('/api/integrations/operator')).json();
        document.getElementById('op-status-text').textContent = d.paired ? 'Ulangan' : 'Ulanmagan';
        document.getElementById('op-paired').style.display = d.paired ? 'block' : 'none';
        document.getElementById('op-unpaired').style.display = d.paired ? 'none' : 'block';

        if (d.paired) {
            document.getElementById('op-name').textContent = d.operator_name || 'Operator';
            document.getElementById('op-notify-handoff').checked = !!d.notify_on_handoff;
            document.getElementById('op-notify-order').checked = !!d.notify_on_order;
        } else {
            const btn = document.getElementById('op-get-code-btn');
            const box = document.getElementById('op-code-box');
            if (d.pairing_code) {
                showPairCode(d.pairing_code, d.bot_username);
            } else {
                box.style.display = 'none';
                btn.style.display = d.bot_connected ? 'inline-flex' : 'none';
                if (!d.bot_connected) {
                    document.getElementById('op-unpaired').querySelector('p').textContent =
                        'Avval Telegram botni ulang — bildirishnomalar shu bot orqali yuboriladi.';
                }
            }
        }
    } catch (e) {
        console.error('Operator holatini yuklashda xatolik:', e);
    }
}

function showPairCode(code, botUsername) {
    document.getElementById('op-code').textContent = code;
    document.getElementById('op-cmd').textContent = '/operator ' + code;
    document.getElementById('op-bot-name').textContent = botUsername ? '@' + botUsername : 'botga';
    document.getElementById('op-code-box').style.display = 'block';
    document.getElementById('op-get-code-btn').style.display = 'none';
}

async function getPairingCode() {
    try {
        const r = await fetch('/api/integrations/operator/pair-code', { method: 'POST' });
        const d = await r.json();
        if (!r.ok) { toast(d.detail || 'Xatolik', true); return; }
        showPairCode(d.pairing_code, d.bot_username);
    } catch (e) {
        toast('Kod olishda xatolik', true);
    }
}

async function unpairOperator() {
    if (!confirm('Operator bildirishnomasini uzmoqchimisiz?')) return;
    await fetch('/api/integrations/operator/unpair', { method: 'POST' });
    toast('Uzildi');
    loadOperatorPairing();
}

async function saveOperatorNotifications() {
    await fetch('/api/integrations/operator/notifications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            notify_on_handoff: document.getElementById('op-notify-handoff').checked,
            notify_on_order: document.getElementById('op-notify-order').checked
        })
    });
    toast('Saqlandi');
}

async function connectTelegram() {
    const token = document.getElementById('tg-token-input').value.trim();
    if (!token) { toast('Token kiriting', true); return; }
    try {
        const resp = await fetch('/api/integrations/telegram/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token })
        });
        const d = await resp.json();
        if (!resp.ok) { toast(d.detail || 'Ulanmadi', true); return; }
        toast('Bot ulandi: @' + d.username);
        document.getElementById('tg-token-input').value = '';
        loadIntegrations();
    } catch (e) {
        toast('Ulashda xatolik', true);
    }
}

async function disconnectTelegram() {
    if (!confirm('Telegram botni uzmoqchimisiz?')) return;
    try {
        await fetch('/api/integrations/telegram/disconnect', { method: 'POST' });
        toast('Bot uzildi');
        loadIntegrations();
    } catch (e) {
        toast('Xatolik', true);
    }
}

// ════════════════════════════════════════════════════════
// ANALITIKA
// ════════════════════════════════════════════════════════

// ════════════════════════════════════════════════════════
// SOZLAMALAR (biznes profili)
// ════════════════════════════════════════════════════════
const PLAN_LABEL = { start: 'Start', business: 'Business', pro: 'Pro' };

async function loadAccountSettings() {
    try {
        if (!currentTenant) {
            const r = await fetch('/api/auth/me');
            if (r.ok) currentTenant = await r.json();
        }
        if (!currentTenant) return;
        setVal('set-biz-name', currentTenant.business_name);
        setVal('set-email', currentTenant.email);
        setVal('set-plan', PLAN_LABEL[currentTenant.plan] || currentTenant.plan || 'Start');
    } catch (e) {
        console.error('Hisob sozlamalarini yuklashda xatolik:', e);
    }
}

// ═══════════════ HISOBIM ═══════════════
const BILL_KIND = { topup: 'To\'ldirish', subscription: 'Tarif', adjustment: 'Tuzatish' };
const BILL_STATE = {
    pending: ['⏳', 'Tasdiqlanmoqda'], confirmed: ['✅', 'Tasdiqlangan'], rejected: ['❌', 'Rad etilgan'],
};
const SUB_STATE = {
    active: 'Faol', trial: 'Sinov davri', grace: 'Muddat tugadi',
    frozen: 'Muzlatilgan', expired: 'To\'xtatilgan', free: 'Bepul tarif',
};

async function loadBilling() {
    try {
        const d = await (await fetch('/api/admin/billing')).json();

        document.getElementById('bill-balance').innerHTML =
            `${fmtNum(d.balance)} <small>so'm</small>`;

        // The subscription line says what happens next, not just what is true
        const left = d.days_left;
        let note;
        if (d.status === 'free') {
            note = 'Bepul tarifda muddat yo\'q. Limitlar past — kengaytirish uchun tarif tanlang.';
        } else if (d.status === 'frozen') {
            note = `Hisob to'xtatilgan. Qolgan ${Math.round(left)} kun saqlanib turibdi.`;
        } else if (d.status === 'grace') {
            note = `Muddat ${d.expires_at} da tugadi. Bot yana ${d.grace_days} kun ishlaydi — `
                 + 'shundan keyin javob bermay qo\'yadi.';
        } else if (d.status === 'expired') {
            note = 'Muddat tugadi va bot to\'xtadi. Tarifni yangilasangiz darhol qayta ishlaydi.';
        } else if (d.status === 'trial') {
            note = `Sinov davri ${d.expires_at} gacha — ${Math.round(left)} kun qoldi. `
                 + 'Tugagunga qadar tarif tanlang, aks holda bot to\'xtaydi.';
        } else {
            note = `${d.expires_at} gacha — ${Math.round(left)} kun qoldi.`
                 + (d.can_auto_renew ? ' Hisobda mablag\' bor, tarif avtomatik yangilanadi.' : '');
        }
        document.getElementById('bill-sub').innerHTML = `
            <div class="bill-sub-plan">${escapeHtml(d.plan_title)}</div>
            <div class="bill-sub-state bill-${d.status}">${SUB_STATE[d.status] || d.status}</div>
            <p class="bill-sub-note">${escapeHtml(note)}</p>
            ${d.status === 'free' ? '' : `
            <label class="bill-renew">
                <input type="checkbox" id="bill-auto" ${d.auto_renew ? 'checked' : ''}>
                <span>Muddat tugaganda hisobdagi mablag'dan avtomatik yangilansin</span>
            </label>`}`;

        const auto = document.getElementById('bill-auto');
        if (auto) auto.addEventListener('change', async () => {
            try {
                const r = await fetch('/api/admin/billing/auto-renew', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: auto.checked }),
                });
                if (!r.ok) throw new Error((await r.json()).detail || 'Saqlanmadi');
                toast(auto.checked ? 'Avtomatik yangilash yoqildi' : 'Avtomatik yangilash o\'chirildi');
            } catch (e) {
                auto.checked = !auto.checked;   // put the switch back where it was
                toast(e.message, true);
            }
        });

        document.getElementById('bill-plans').innerHTML = d.plans.map((p) => `
            <div class="bill-plan ${p.current ? 'is-current' : ''}">
                <h4>${escapeHtml(p.title)}</h4>
                <div class="bill-plan-price">${fmtNum(p.price_uzs)} <small>so'm / ${p.duration_days} kun</small></div>
                <ul class="bill-plan-list">
                    <li>${p.max_products === null ? 'Cheksiz' : fmtNum(p.max_products)} mahsulot</li>
                    <li>${p.max_ai_messages_monthly === null ? 'Cheksiz' : fmtNum(p.max_ai_messages_monthly)} AI xabar / oy</li>
                    <li>${p.max_operators === null ? 'Cheksiz' : fmtNum(p.max_operators)} operator</li>
                </ul>
                ${p.price_uzs > 0 ? `<button class="btn-primary" data-plan="${escapeHtml(p.name)}">
                    ${p.current ? 'Muddatni uzaytirish' : 'Shu tarifni olish'}</button>`
                  : '<span class="bill-plan-free">Boshlang\'ich tarif</span>'}
            </div>`).join('');

        document.getElementById('bill-plans').querySelectorAll('[data-plan]').forEach((b) =>
            b.addEventListener('click', () => buyPlan(b.dataset.plan, d.balance)));

        const tb = document.getElementById('bill-history');
        tb.innerHTML = d.history.length ? d.history.map((h) => {
            const [icon, label] = BILL_STATE[h.status] || ['', h.status];
            return `<tr>
                <td>${escapeHtml(h.created_at || '')}</td>
                <td>${escapeHtml(BILL_KIND[h.kind] || h.kind)}</td>
                <td style="font-weight:700">${h.amount >= 0 ? '+' : ''}${fmtNum(h.amount)}</td>
                <td>${escapeHtml(h.note || '—')}</td>
                <td>${icon} ${label}</td>
            </tr>`;
        }).join('')
          : '<tr><td colspan="5" style="text-align:center;color:var(--text-dim);padding:28px;">Hali to\'lov yo\'q.</td></tr>';
    } catch (e) {
        console.error('Hisobni yuklashda xatolik:', e);
    }
}

document.getElementById('bill-topup-btn')?.addEventListener('click', async () => {
    const raw = prompt('Qancha summa o\'tkazdingiz? (so\'m)');
    if (!raw) return;
    const amount = Number(String(raw).replace(/\s/g, ''));
    if (!amount || amount <= 0) return alert('Summa noto\'g\'ri.');
    const note = prompt('Izoh (qaysi karta/ilova orqali?)') || '';
    try {
        const r = await fetch('/api/admin/billing/topup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount, note }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || 'Xatolik');
        alert(d.message);
        loadBilling();
    } catch (e) { alert(e.message); }
});

async function buyPlan(plan, balance) {
    if (!confirm('Tarif hisobingizdagi mablag\'dan yechiladi. Davom etamizmi?')) return;
    try {
        const r = await fetch('/api/admin/billing/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || 'Xatolik');
        alert(`Tarif faollashtirildi: ${d.plan_title}. ${Math.round(d.days_left)} kun.`);
        loadBilling();
    } catch (e) { alert(e.message); }
}
