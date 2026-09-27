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

/* ── Mavzu ───────────────────────────────────────────────────────────────────
   Uch holat: 'auto' tizim sozlamasiga ergashadi, 'light'/'dark' majburiy.
   Dastlabki qiymat <head> dagi inline skriptda qo'yiladi (chaqnashning
   oldini olish uchun); bu yerda faqat almashtirish va tugmalar holati. */
function applyTheme(mode) {
    const dark = mode === 'auto'
        ? !window.matchMedia('(prefers-color-scheme: light)').matches
        : mode === 'dark';
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    document.querySelectorAll('[data-theme-set]').forEach(b =>
        b.classList.toggle('is-on', b.getAttribute('data-theme-set') === mode));
}

function setTheme(mode) {
    try { localStorage.setItem('theme', mode); } catch (e) { /* shaxsiy rejim */ }
    applyTheme(mode);
}

function initTheme() {
    let saved = 'auto';
    try { saved = localStorage.getItem('theme') || 'auto'; } catch (e) { /* shaxsiy rejim */ }
    applyTheme(saved);
    /* 'Avto' tanlangan bo'lsa, tizim mavzusi almashganda panel ham darhol
       ergashsin — foydalanuvchi sahifani qayta yuklashi shart emas. */
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
        let cur = 'auto';
        try { cur = localStorage.getItem('theme') || 'auto'; } catch (e) { /* shaxsiy rejim */ }
        if (cur === 'auto') applyTheme('auto');
    });
}

function showAppDashboard(tenant) {
    document.getElementById('auth-overlay').style.display = 'none';
    document.getElementById('app-container').style.display = 'flex';
    // Show tenant info in sidebar
    if (tenant) {
        currentTenant = tenant;
        document.getElementById('tenant-biz-name').textContent = tenant.business_name || '—';
        document.getElementById('tenant-email').textContent = tenant.email || '—';
        renderTenantLogo(tenant.logo_url);
    }
}

/** Shows the uploaded logo if there is one, else the building emoji. */
function renderTenantLogo(url) {
    const img = document.getElementById('tenant-logo-img');
    const fallback = document.getElementById('tenant-logo-fallback');
    if (!img || !fallback) return;
    if (url) {
        img.src = url;
        img.style.display = 'block';
        fallback.style.display = 'none';
    } else {
        img.style.display = 'none';
        fallback.style.display = '';
    }
}

async function uploadTenantLogo(event) {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch('/api/admin/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (!res.ok || data.status !== 'success') throw new Error(data.detail || 'Yuklanmadi');

        const r = await fetch('/api/admin/profile/logo', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ logo_url: data.image_url }),
        });
        const saved = await r.json();
        if (!r.ok) throw new Error(saved.detail || 'Saqlanmadi');

        renderTenantLogo(saved.logo_url);
        if (currentTenant) currentTenant.logo_url = saved.logo_url;
        toast('Logotip yangilandi');
    } catch (e) {
        toast(e.message || 'Logotipni yuklab bo\'lmadi', true);
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
    if (password.length < 8) {
        errEl.textContent = 'Parol kamida 8 ta belgidan iborat bo\'lishi kerak.';
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
    if (!navReady) { initNavigation(); initCustomerSearch(); navReady = true; }
    loadCategories();     // needed by the product modal's category select
    loadProducts();
    loadSettings();
    loadSidebarPlan();
    startInboxPolling();
    checkNotificationRoute();
    restoreActiveTab();
}

/** Warn — on every tab, not just Integratsiyalar — when the bot is connected
 *  but nothing is paired to receive alerts: the AI still creates orders in
 *  that state, it just tells nobody. Independent of the onboarding card's
 *  dismiss state on purpose — that card can be closed permanently, this risk
 *  can't be. */
async function checkNotificationRoute() {
    const banner = document.getElementById('no-route-banner');
    if (!banner) return;
    try {
        const data = await (await fetch('/api/admin/onboarding')).json();
        const bot = data.steps.find((s) => s.key === 'bot');
        const group = data.steps.find((s) => s.key === 'group');
        banner.style.display = (bot && bot.done && group && !group.done) ? 'flex' : 'none';
    } catch (e) {
        // A failed check should not itself alarm the owner.
    }
}

/** Reopen the section the operator was last on. First visit ever (nothing
 *  saved yet) lands on Dashboard instead of Inbox — that's the only screen
 *  showing the "Boshlash uchun" setup checklist, and a brand-new account's
 *  Inbox has no conversations to show anyway. Once any tab is chosen it's
 *  remembered, so this only affects the very first login. */
function restoreActiveTab() {
    const saved = localStorage.getItem('sotuvchi_active_tab');
    const navItem = saved && document.querySelector(`.nav-item[data-tab="${saved}"]`);
    if (navItem) {
        navItem.click();   // click also loads that tab's data and sets the header
    } else if (typeof activateTab === 'function') {
        activateTab('tab-overview');
    } else {
        loadInbox();
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    initTheme();
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
    'tab-settings':     { title: 'Sozlamalar', sub: 'Biznes profili va Telegram bot', btn: false, load: loadSettingsTab }
};

function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const tabViews = document.querySelectorAll('.tab-view');
    const headerTitle = document.getElementById('page-title');
    const headerSubtitle = document.getElementById('page-subtitle');
    const headerActionGroup = document.getElementById('header-action-group');

    /* Bo'limni ochish menyu elementidan ajratilgan. Sabab: menyu Stitch
       dizayniga qisqartirilgach, ba'zi bo'limlarga (Integratsiyalar,
       Mijozlar) menyu elementi qolmadi, lekin ular Sozlamalar ichidan
       ochilishi kerak. Ilgari bu mantiq click ichida yopiq edi va
       menyusiz bo'lim umuman ochilmasdi. */
    activateTab = function (targetTab) {
        const view = document.getElementById(targetTab);
        if (!view) return;
        const meta = TAB_META[targetTab];

        navItems.forEach(i => i.classList.remove('active'));
        tabViews.forEach(v => v.classList.remove('active'));

        const navItem = document.querySelector(`.nav-item[data-tab="${targetTab}"]`);
        if (navItem) navItem.classList.add('active');
        view.classList.add('active');

        if (meta) {
            document.querySelector('.top-header').style.display = 'flex';
            headerTitle.textContent = meta.title;
            if (headerSubtitle) headerSubtitle.textContent = meta.sub;
            // Show/hide action groups based on active tab
            if (headerActionGroup) headerActionGroup.style.display = meta.btn ? 'flex' : 'none';
            const mobileTitle = document.getElementById('mobile-page-title');
            if (mobileTitle) mobileTitle.textContent = meta.title;
            if (typeof meta.load === 'function') meta.load();
        }

        // On a phone the drawer covers the content — close it after choosing
        toggleSidebar(false);

        // Remember the section so a reload returns here instead of Inbox
        localStorage.setItem('sotuvchi_active_tab', targetTab);
    };

    navItems.forEach(item => {
        item.addEventListener('click', () => activateTab(item.getAttribute('data-tab')));
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

/* Menyuda elementi bo'lmagan bo'limlar ham ochilishi uchun to'g'ridan-to'g'ri
   activateTab chaqiriladi. */
let activateTab = null;

function switchToTab(targetTab) {
    if (typeof activateTab === 'function') {
        activateTab(targetTab);
        return;
    }
    const navItem = document.querySelector(`.nav-item[data-tab="${targetTab}"]`);
    if (navItem) navItem.click();
}

// Categories now only feed the filter chips and the product form's dropdown
async function loadCategories() {
    try {
        const resp = await fetch('/api/admin/categories');
        currentCategories = await resp.json();
        populateCategoryDropdown();
    } catch (e) {
        console.error('Kategoriyalarni yuklashda xatolik:', e);
    }
}

/** Catalog screen = products + their category filter. */
async function loadCatalog() {
    /* Ikkalasi bir-biriga bog'liq emas. Ketma-ket kutish bazagacha borish
       vaqtini ikki barobar qiladi — birga jo'natamiz. */
    await Promise.all([loadCategories(), loadProducts()]);
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


// ════════════════════════════════════════════════════════
// DASHBOARD — AI KPI cards
// ════════════════════════════════════════════════════════
/** Uzbek number format: 45 700 000 (spaces, not commas). */
function fmtNum(n) {
    return Math.round(Number(n) || 0).toLocaleString('ru-RU').replace(/ /g, ' ');
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

    set('dashboard-kpis', `
        <div class="skel-kpi">
            <div class="skel-kpi-top">
                <span class="skel skel-ico"></span>
                <span class="skel skel-line skel-w60" style="flex:1"></span>
            </div>
            <span class="skel skel-val"></span>
            <span class="skel skel-foot"></span>
        </div>`);

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

    set('revenue-chart', '<div class="skel" style="height:140px; border-radius:12px;"></div>');

    set('recent-orders-tbody', Array.from({ length: 4 }, () => `
        <tr>${Array.from({ length: 6 }, () =>
            '<td><span class="skel skel-line skel-w75"></span></td>').join('')}</tr>`).join(''));
}

async function loadDashboardStats() {
    initPeriodPicker();
    showDashboardSkeleton();
    loadOnboarding();
    try {
        const q = `?period=${encodeURIComponent(dashPeriod)}`;
        const [statsResp, anResp] = await Promise.all([
            fetch('/api/admin/stats' + q),
            fetch('/api/admin/analytics' + q)
        ]);
        const data = await statsResp.json();
        const an = await anResp.json();
        const g = data.growth || {};

        // Render top cards
        /* onAccent = yashil kartochka ustida: u yerda shishasimon nishon
           ishlatiladi (.kpi-growth), qorong'i kartochkalarda esa oddiy matn. */
        const growthBadgeHTML = (pct, onAccent) => {
            if (pct === null || pct === undefined) return '';
            const up = pct >= 0;
            const icon = `<span class="ico ico-trending-${up ? 'up' : 'down'}" style="font-size:14px;"></span>`;
            const text = `${up ? '+' : ''}${pct}%`;
            if (onAccent) return `<span class="kpi-growth">${icon} ${text}</span>`;
            return `<span style="font-size:12px; font-weight:600; color:${up ? 'var(--primary)' : 'var(--accent-danger)'}; display:flex; align-items:center; gap:2px;">${icon} ${text}</span>`;
        };

        const aiRevenue = data.ai_revenue;
        const kpisHTML = `
            <!-- AI daromadi -->
            <div class="kpi-hero">
                <span class="kpi-hero-pattern" aria-hidden="true"></span>
                <span class="kpi-hero-glow" aria-hidden="true"></span>
                <div class="kpi-hero-layer" style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <div style="width:32px; height:32px; background:rgba(255,255,255,0.18); border:1px solid rgba(255,255,255,0.12); border-radius:10px; display:flex; align-items:center; justify-content:center;">
                            <span class="ico ico-wallet" style="font-size:16px; color:#fff;"></span>
                        </div>
                        <div>
                            <div style="font-family:var(--font-display); font-size:13px; font-weight:800;">AI daromadi</div>
                            <div style="font-size:11px; opacity:0.8;">${escapeHtml(data.period_label || '')}</div>
                        </div>
                    </div>
                    <button style="background:transparent; border:none; color:#fff; cursor:pointer;"><span class="ico ico-ellipsis" style="font-size:18px;"></span></button>
                </div>
                <div class="kpi-hero-layer" style="display:flex; align-items:baseline; gap:10px;">
                    <div style="font-family:var(--font-mono); font-size:22px; font-weight:700;">${fmtNum(aiRevenue)} <span style="font-size:14px; font-weight:500; font-family:var(--font-body); opacity:0.9;">so'm</span></div>
                    ${growthBadgeHTML(g.ai_revenue, true)}
                </div>
            </div>
        `;
        document.getElementById('dashboard-kpis').innerHTML = kpisHTML;

        // Render Status Grid
        /* Backend suhbat holatlarini beradi (ai / operator / closed).
           Stitch dizaynidagi "Buyurtmalar Holati" boshqa narsa: u buyurtma
           bosqichlarini ko'rsatadi va bunday sanoq API da hali yo'q.
           Shuning uchun bu blok mavjud HAQIQIY ma'lumotni ko'rsatadi. */
        const bs = an.by_status || {};
        const statusHTML = [
            ['status-delivered', 'ico-bot', 'AI hal qilgan', bs.ai ?? 0, 'var(--status-delivered)'],
            ['status-confirmed', 'ico-headphones', 'Operatorda', bs.operator ?? 0, 'var(--text-main)'],
            ['status-new', 'ico-check-check', 'Yopilgan', bs.closed ?? 0, 'var(--text-main)'],
        ].map(([dotVar, icon, label, val, valColor]) => `
            <div style="background:var(--surface); border:1px solid var(--border); border-radius:var(--r-lg); padding:11px; display:flex; flex-direction:column; justify-content:space-between; gap:8px;">
                <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                    <div style="width:7px; height:7px; border-radius:50%; background:var(--${dotVar});"></div>
                    <span class="ico ${icon}" style="font-size:14px; color:var(--text-muted);"></span>
                </div>
                <div>
                    <div style="font-size:11px; color:var(--text-muted); margin-bottom:2px;">${label}</div>
                    <div style="font-family:var(--font-display); font-size:17px; font-weight:700; color:${valColor};">${val}</div>
                </div>
            </div>`).join('');
        document.getElementById('dashboard-status-bars').innerHTML = statusHTML;

        renderRecentOrders(data.recent_orders);
        loadActivitySummary(an);
        renderUsagePanel(data);   // "Tarif sarfi" bloki: ilgari hech qachon chaqirilmasdi
        renderAiEffectiveness(an);
        loadRevenueChart();
    } catch (e) {
        console.error('Stats yuklashda xatolik:', e);
        document.getElementById('dashboard-kpis').innerHTML = `
            <div class="load-fail">
                <p>Ma'lumotlarni yuklab bo'lmadi.</p>
                <button class="btn-primary" onclick="loadDashboardStats()">Qayta urinish</button>
            </div>`;
        ['dashboard-status-bars', 'recent-orders-tbody'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '';
        });
    }
}

// ─── Boshlash checklisti ────────────────────────────────────────────────────
const ONBOARD_DISMISS_KEY = 'sotuvchi_onboard_dismissed';

async function loadOnboarding() {
    const card = document.getElementById('onboard-card');
    if (!card || localStorage.getItem(ONBOARD_DISMISS_KEY) === '1') return;
    try {
        const data = await (await fetch('/api/admin/onboarding')).json();
        if (data.all_done) {
            // Nothing left to do — no reason to keep asking, same as a manual dismiss.
            localStorage.setItem(ONBOARD_DISMISS_KEY, '1');
            card.hidden = true;
            return;
        }
        document.getElementById('onboard-steps').innerHTML = data.steps.map((s) => `
            <div class="onboard-step ${s.done ? 'is-done' : ''}" ${s.done ? '' : `onclick="goToOnboardStep('${s.tab}')"`}>
                <span class="onboard-step-dot">${s.done ? '✓' : ''}</span>
                <span class="onboard-step-title">${escapeHtml(s.title)}</span>
            </div>`).join('');
        card.hidden = false;
    } catch (e) {
        console.error('Onboarding holatini yuklashda xatolik:', e);
    }
}

// A real function declaration (not the `let activateTab` closure) so inline
// onclick can resolve it unambiguously as a global.
function goToOnboardStep(tab) {
    if (typeof activateTab === 'function') activateTab(tab);
}

function dismissOnboarding() {
    localStorage.setItem(ONBOARD_DISMISS_KEY, '1');
    const card = document.getElementById('onboard-card');
    if (card) card.hidden = true;
}

// ════════════════════════════════════════════════════════
// AI FAOLIYATI — tanlangan davr bo'yicha suhbatlar soni.
// Ilgari bu kartochka doim "shu oy"ni ko'rsatardi, tepada esa alohida
// "AI Suhbatlar" KPI kartochkasi davr tanlagichga mos raqamni takrorlardi —
// ikkalasi birlashtirildi: davrga mos son shu yerda, "Bugun" esa doimiy
// solishtirish nuqtasi sifatida qoladi (davr "Bugun" bo'lmasa).
// ════════════════════════════════════════════════════════
async function loadActivitySummary(an) {
    const el = document.getElementById('ai-activity-summary');
    if (!el) return;
    try {
        const d = await (await fetch('/api/admin/analytics/series?span=oy')).json();
        const today = d.focus != null ? d.values[d.focus] : 0;
        const periodLabel = an.period_label || 'Suhbat';
        const tiles = [[`${periodLabel} suhbat`, fmtNum(an.total_conversations)]];
        if (dashPeriod !== 'today') tiles.push(['Bugun suhbat', fmtNum(today)]);
        // "Suhbatlar holati" doimo 3 ta plitka — bu karta 2 tasi bilan
        // qolsa, ustunlar notekis kenglikda ko'rinardi. "Butun davr"da
        // taqqoslanadigan oldingi davr yo'q, o'shanda 2 tada qoladi.
        const gr = (an.growth || {}).total_conversations;
        if (gr !== null && gr !== undefined) {
            const up = gr >= 0;
            const color = up ? 'var(--status-delivered)' : 'var(--accent-danger)';
            tiles.push(['O\'sish', `<span style="color:${color}">${up ? '+' : ''}${gr}%</span>`]);
        }
        el.className = 'activity-summary' + (tiles.length === 3 ? ' activity-summary--3col' : '');
        const wide = tiles.length === 1 ? ' style="grid-column:1/-1;"' : '';
        el.innerHTML = tiles.map(([label, val]) => `
            <div class="activity-tile"${wide}>
                <div class="activity-tile-value">${val}</div>
                <div class="activity-tile-label">${label}</div>
            </div>`).join('');
        syncActivityCardHeights();
    } catch (e) {
        el.innerHTML = '<div class="chart-empty">Ma\'lumotni yuklab bo\'lmadi</div>';
    }
}

/** "Suhbatlar holati" va "AI Faoliyati" plitkalari tarkibi turlicha (biri
 *  nishon qatoriga ega, ikkinchisi yo'q), shuning uchun CSS'dagi grid
 *  cho'zilishiga suyanish o'rniga aniq balandlikni o'lchab tenglashtiramiz —
 *  bu ikkala holatda ham ishonchli ishlaydi. */
function syncActivityCardHeights() {
    const a = document.getElementById('dashboard-status-bars');
    const b = document.getElementById('ai-activity-summary');
    if (!a || !b) return;
    a.style.minHeight = '';
    b.style.minHeight = '';
    requestAnimationFrame(() => {
        const h = Math.max(a.offsetHeight, b.offsetHeight);
        a.style.minHeight = h + 'px';
        b.style.minHeight = h + 'px';
    });
}

// ════════════════════════════════════════════════════════
// AI DAROMADI DINAMIKASI — shu oy, kun kesimida. Tashqi kutubxonasiz,
// inline SVG (build-step yo'q loyihada bog'liqlik qo'shmaslik uchun).
// Ma'lumot activity_series() dan — dashboard_stats.ai_revenue bilan bir
// xil ta'rif (bekor qilinmagan, AI suhbatidan kelgan buyurtmalar).
// ════════════════════════════════════════════════════════
async function loadRevenueChart() {
    const box = document.getElementById('revenue-chart');
    const periodEl = document.getElementById('revenue-chart-period');
    if (!box) return;
    if (periodEl) periodEl.textContent = 'Shu oy, kun kesimida';
    try {
        const d = await (await fetch('/api/admin/analytics/series?span=oy')).json();
        renderRevenueChart(d);
    } catch (e) {
        box.innerHTML = '<div class="chart-empty" style="height:140px;">Ma\'lumotni yuklab bo\'lmadi</div>';
    }
}

function renderRevenueChart(d) {
    const box = document.getElementById('revenue-chart');
    if (!box) return;
    const values = d.revenue || [];
    const labels = d.labels || [];
    if (values.length < 2) {
        box.innerHTML = '<div class="chart-empty" style="height:140px;">Grafik uchun ma\'lumot hali yetarli emas</div>';
        return;
    }

    const W = 600, H = 140, PAD = 10;
    const max = Math.max(...values, 1);
    const n = values.length;
    const stepX = W / (n - 1);
    const points = values.map((v, i) => [
        i * stepX,
        H - PAD - (v / max) * (H - PAD * 2),
    ]);

    const line = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const area = `${line} L${points[n - 1][0].toFixed(1)},${H} L0,${H} Z`;
    const focus = d.focus != null && d.focus < n ? d.focus : n - 1;
    const [fx, fy] = points[focus];

    box.innerHTML = `
        <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="width:100%; height:140px; display:block;">
            <defs>
                <linearGradient id="revChartGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="#00b87c" stop-opacity="0.3"/>
                    <stop offset="100%" stop-color="#00b87c" stop-opacity="0"/>
                </linearGradient>
            </defs>
            <path d="${area}" fill="url(#revChartGrad)" stroke="none"/>
            <path d="${line}" fill="none" stroke="#00b87c" stroke-width="2"/>
            <circle cx="${fx.toFixed(1)}" cy="${fy.toFixed(1)}" r="3.5" fill="#00b87c" stroke="#fff" stroke-width="1.5"/>
        </svg>
        <div style="display:flex; justify-content:space-between; margin-top:4px; font-size:10.5px; color:var(--text-muted);">
            <span>${escapeHtml(labels[0] || '')}-kun</span>
            <span>${escapeHtml(labels[n - 1] || '')}-kun</span>
        </div>`;
}

/** Google Sheets state. Syncing itself happens from the Katalog bo'limi's
 *  import modal — this card only reports whether a link is connected and,
 *  clicked, sends the owner there instead of duplicating the input here. */
async function loadSheetsStatus() {
    const label = document.getElementById('sheets-status');
    const reason = document.getElementById('sheets-reason');
    const card = document.getElementById('sheets-card');
    if (!label) return;
    try {
        const d = await (await fetch('/api/admin/settings')).json();
        const connected = !!d.google_sheet_url;
        label.textContent = connected ? '🟢 Ulangan' : '⚪️ Ulanmagan';
        reason.textContent = connected
            ? `${fmtNum(d.google_sheet_product_count)} ta mahsulot · oxirgi sinxronlash: ${fmtDateShort((d.google_sheet_synced_at || '').slice(0, 10))}`
            : 'Ulash uchun Katalog bo\'limiga o\'ting';
        card.classList.toggle('disabled', !connected);
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
        const tone = pct === null ? '' : pct >= 90 ? ' is-danger' : pct >= 70 ? ' is-warn' : '';
        return `
        <div class="cost-row"><span>${label}</span><b>${fmtNum(m.used)} / ${cap(m.limit)}</b></div>
        ${pct === null ? '' : `<div class="usage-bar${tone}"><i style="width:${pct}%"></i></div>`}`;
    };

    box.innerHTML = `
        <div class="cost-row cost-row--lead"><span>Tarif</span><b>${escapeHtml(u.plan_title || u.plan)}</b></div>
        ${row('AI xabar, shu oy', u.ai_messages)}
        ${row('Mahsulot', u.products)}
        <div class="cost-row"><span>AI yopgan savdo</span><b>${fmtNum(data.ai_order_count)} ta</b></div>
        <p class="cost-hint">Limit tugasa AI javob bermay qo'yadi va suhbat operatorga uzatiladi.</p>`;
}

/** "AI qanchalik yaxshi ishlayapti" savoliga javob — Inbox'ni bitta-bitta o'qish
 *  o'rniga, tarixiy sabab yig'indisidan chiqarilgan haqiqiy ko'rsatkichlar.
 *  Ma'lumot /api/admin/analytics'dan keladi (allaqachon loadDashboardStats'da
 *  bir marta so'ralgan — bu yerda qayta so'rov yubormaydi). */
function renderAiEffectiveness(an) {
    const periodEl = document.getElementById('ai-effectiveness-period');
    const tilesEl = document.getElementById('ai-effectiveness-tiles');
    const reasonsEl = document.getElementById('ai-handoff-reasons');
    if (!tilesEl) return;

    if (periodEl) periodEl.textContent = an.period_label || '';

    const latency = an.avg_latency_ms ? `${(an.avg_latency_ms / 1000).toFixed(1)}s` : '—';
    tilesEl.innerHTML = [
        ['Operatorga uzatildi', `${fmtNum(an.escalation_rate)}%`],
        ["AI yolg'iz yopdi", `${fmtNum(an.ai_alone_rate)}%`],
        ['Javob tezligi', latency],
    ].map(([label, val]) => `
        <div class="activity-tile">
            <div class="activity-tile-value">${val}</div>
            <div class="activity-tile-label">${label}</div>
        </div>`).join('');

    if (!reasonsEl) return;
    const reasons = an.handoff_reasons || [];
    if (!reasons.length) {
        reasonsEl.innerHTML = '<p class="cost-hint">Bu davrda operatorga uzatilgan suhbat bo\'lmagan.</p>';
        return;
    }
    const top = Math.max(...reasons.map((r) => r.count));
    reasonsEl.innerHTML = reasons.map((r) => `
        <div class="cost-row"><span>${escapeHtml(r.reason)}</span><b>${fmtNum(r.count)} ta</b></div>
        <div class="usage-bar"><i style="width:${top ? Math.round(r.count / top * 100) : 0}%"></i></div>
    `).join('');
}

const RECENT_ORDERS_AVATAR_COLORS = ['#388BFD', '#A371F7', '#00b87c', '#f59e0b', '#f0883e', '#e11d48'];

function renderRecentOrders(orders) {
    const tbody = document.getElementById('recent-orders-tbody');
    if (!tbody) return;

    if (!orders || orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="ro-empty">Hali buyurtmalar kelib tushmagan.</td></tr>';
        return;
    }

    const monthNames = ['Yan', 'Fev', 'Mar', 'Apr', 'May', 'Iyun', 'Iyul', 'Avg', 'Sen', 'Okt', 'Noy', 'Dek'];

    tbody.innerHTML = orders.map((o, idx) => {
        const d = new Date(o.created_at);
        const dateStr = isNaN(d)
            ? (o.created_at || '—')
            : `${d.getDate()} ${monthNames[d.getMonth()]}, ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;

        const avatarColor = RECENT_ORDERS_AVATAR_COLORS[idx % RECENT_ORDERS_AVATAR_COLORS.length];
        const initials = (o.customer_name || 'MI').substring(0, 2).toUpperCase();
        const shortId = '#INV-' + String(o.id).replace(/[^0-9]/g, '').substring(0, 4).padStart(4, '0');
        const [statusColor, statusBg] = orderStatusColors(o.status);

        return `
        <tr>
            <td class="ro-id">${shortId}</td>
            <td>
                <div class="ro-customer">
                    <span class="ro-avatar" style="--av:${avatarColor}">${initials}</span>
                    <span class="ro-name">${escapeHtml(o.customer_name || '—')}</span>
                </div>
            </td>
            <td class="col-phone ro-phone">${escapeHtml(o.customer_phone || '—')}</td>
            <td class="ro-amount">${fmtNum(o.total_amount)} <small>so'm</small></td>
            <td>
                <span class="ro-status" style="--sc:${statusColor}; --sb:${statusBg}">
                    <span class="ro-status-dot"></span>${escapeHtml(o.status || '—')}
                </span>
            </td>
            <td class="col-date ro-date">${dateStr}</td>
        </tr>`;
    }).join('');
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

let catalogViewMode = 'grid'; // 'grid' or 'table'


/** Category chips in Stitch design */
function renderCategoryFilter() {
    const row = document.getElementById('category-filter-row');
    if (!row) return;

    const counts = {};
    currentProducts.forEach(p => {
        const c = (p.category || '').trim() || '— kategoriyasiz';
        counts[c] = (counts[c] || 0) + 1;
    });
    const names = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);

    const chip = (label, value, n, active) => {
        const bg = active ? 'background:var(--primary-glow); border:1px solid var(--primary); color:var(--primary); font-weight:600;'
                          : 'background:var(--card-bg); border:1px solid var(--border); color:var(--text-muted); font-weight:400;';
        const badgeBg = active ? 'background:var(--primary); color:#fff;' : 'background:var(--surface); color:var(--text-muted);';
        const escapedValue = value === null ? 'null' : `'${value.replace(/'/g, "\\'")}'`;

        return `<button onclick="filterByCategory(${escapedValue})" style="${bg} border-radius:100px; padding:6px 14px; font-size:13px; font-family:var(--font-body); display:inline-flex; align-items:center; gap:6px; cursor:pointer; white-space:nowrap; transition:all 0.15s;">
            ${escapeHtml(label)}
            <span style="${badgeBg} font-size:11px; padding:1px 7px; border-radius:100px; font-family:var(--font-mono); font-weight:600;">${n}</span>
        </button>`;
    };

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
    const gridEl = document.getElementById('products-grid-view');
    if (!gridEl) return;

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
            ? `Jami ${currentProducts.length} ta mahsulot`
            : `${list.length} / ${currentProducts.length} ta mahsulot ko'rsatilmoqda`;
    }

    // --- GRID CARDS VIEW ---
    if (gridEl) {
        if (list.length === 0) {
            gridEl.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:48px; color:var(--text-muted); background:var(--card-bg); border:1px solid var(--border); border-radius:var(--r-xl); box-shadow:var(--shadow-1);">
                ${currentProducts.length === 0
                    ? 'Katalog bo\'sh. <b>Excel yuklash</b> yoki <b>+ Mahsulot qo\'shish</b> bilan boshlang.'
                    : 'Ushbu shartlarga mos mahsulot topilmadi.'}
            </div>`;
        } else {
            gridEl.innerHTML = list.map(p => {
                const img = (p.image_urls && p.image_urls[0]) || p.image_url || '';
                const qty = p.stock_quantity || 0;
                const inStock = p.in_stock && qty > 0;
                const stockBadge = inStock
                    ? `<span style="background:rgba(0,184,124,0.12); color:#00b87c; border:1px solid rgba(0,184,124,0.3); font-size:11px; font-weight:700; padding:3px 10px; border-radius:100px; display:inline-flex; align-items:center; gap:4px;"><span style="width:6px; height:6px; border-radius:50%; background:#00b87c;"></span> ${qty} ta bor</span>`
                    : `<span style="background:rgba(239,68,68,0.12); color:#ef4444; border:1px solid rgba(239,68,68,0.3); font-size:11px; font-weight:700; padding:3px 10px; border-radius:100px;">Tugagan</span>`;

                const catName = (p.category || '—').toUpperCase();

                const imgHTML = img
                    ? `<img src="${escapeHtml(img)}" alt="${escapeHtml(p.name)}" style="width:100%; height:180px; object-fit:cover; display:block;" onerror="this.onerror=null; this.parentNode.innerHTML='<div style=\\'width:100%; height:180px; background:var(--surface); display:flex; align-items:center; justify-content:center;\\'><span class=\\'ico ico-package\\' style=\\'font-size:36px; color:var(--text-muted);\\'></span></div>';">`
                    : `<div style="width:100%; height:180px; background:var(--surface); display:flex; align-items:center; justify-content:center;">
                        <span class="ico ico-package" style="font-size:36px; color:var(--text-muted);"></span>
                       </div>`;

                return `
                <div class="prod-card" style="background:var(--card-bg); border:1px solid var(--border); border-radius:var(--r-xl); box-shadow:var(--shadow-1); overflow:hidden; display:flex; flex-direction:column; transition:transform 0.2s, box-shadow 0.2s; position:relative;">
                    <div style="position:relative; width:100%; overflow:hidden;">
                        ${imgHTML}
                        <div style="position:absolute; top:10px; right:10px;">${stockBadge}</div>
                    </div>
                    <div style="padding:16px; display:flex; flex-direction:column; flex:1;">
                        <div style="font-family:var(--font-mono); font-size:10px; font-weight:600; color:var(--text-dim); letter-spacing:0.05em; margin-bottom:4px;">${escapeHtml(catName)}</div>
                        <h3 style="font-family:var(--font-display); font-size:15px; font-weight:600; color:var(--text-main); margin:0 0 8px; line-height:1.3; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">${escapeHtml(p.name)}</h3>
                        <p style="font-size:12px; color:var(--text-muted); margin:0 0 12px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; flex:1;">${escapeHtml(p.description || '')}</p>
                        
                        <div style="display:flex; justify-content:space-between; align-items:center; padding-top:12px; border-top:1px solid var(--border); margin-top:auto;">
                            <div style="font-family:var(--font-mono); font-size:15px; font-weight:700; color:var(--primary);">${fmtNum(p.price)} <span style="font-size:11px; font-weight:400; color:var(--text-muted);">${escapeHtml(p.currency || "so'm")}</span></div>
                            <div style="display:flex; gap:6px;">
                                <button onclick="openEditProductModal('${p.id}')" title="Tahrirlash" style="background:var(--surface); border:1px solid var(--border); border-radius:6px; color:var(--text-main); width:30px; height:30px; display:flex; align-items:center; justify-content:center; cursor:pointer;">
                                    <span class="ico ico-square-pen" style="font-size:16px;"></span>
                                </button>
                                <button onclick="deleteProduct('${p.id}')" title="O'chirish" style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.2); border-radius:6px; color:#ef4444; width:30px; height:30px; display:flex; align-items:center; justify-content:center; cursor:pointer;">
                                    <span class="ico ico-trash-2" style="font-size:16px;"></span>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>`;
            }).join('');
        }
    }
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
        await Promise.all([loadProducts(), loadCategories()]);
    } catch (e) {
        console.error('Mahsulotni saqlashda xatolik:', e);
        alert('Tarmoqda muammo. Qaytadan urinib ko\'ring.');
    }
}

async function deleteProduct(productId) {
    if (!confirm('Ushbu mahsulotni katalogdan o\'chirmoqchimisiz?')) return;
    try {
        await fetch(`/api/admin/products/${productId}`, { method: 'DELETE' });
        await Promise.all([loadProducts(), loadCategories()]);
    } catch (e) {
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
        renderOrdersStatsCards();
        renderOrdersTable();
    } catch (e) {
        console.error('Buyurtmalarni yuklashda xatolik:', e);
    }
}

function renderOrdersStatsCards() {
    const row = document.getElementById('orders-stats-row');
    if (!row) return;

    const yangi    = currentOrders.filter(o => o.status === 'Yangi').length;
    const tasdiq   = currentOrders.filter(o => o.status === 'Tasdiqlandi').length;
    const yolda    = currentOrders.filter(o => o.status === "Yo'lda").length;
    const yetkazil = currentOrders.filter(o => o.status === 'Yetkazildi').length;

    const card = (icon, iconColor, iconBg, label, count, badge, badgeColor) => `
        <div style="background:var(--card-bg); border:1px solid var(--border); border-radius:var(--r-xl); box-shadow:var(--shadow-1); padding:20px; display:flex; flex-direction:column; gap:12px;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div style="display:flex; align-items:center; gap:10px;">
                    <div style="width:36px; height:36px; background:${iconBg}; border-radius:8px; display:flex; align-items:center; justify-content:center;">
                        <span class="ico ico-${icon}" style="font-size:18px; color:${iconColor};"></span>
                    </div>
                    <span style="font-size:13px; color:var(--text-muted); font-weight:500;">${label}</span>
                </div>
                <span style="font-size:11px; font-weight:600; padding:3px 8px; border-radius:100px; background:${badgeColor}22; color:${badgeColor};">${badge}</span>
            </div>
            <div style="font-family:var(--font-mono); font-size:32px; font-weight:700; color:var(--text-main);">${count}</div>
        </div>`;

    row.innerHTML =
        card('circle-plus', 'var(--status-new)', 'var(--status-new-bg)', 'Yangi (New)', yangi, 'NEW', 'var(--status-new)') +
        card('circle-check', 'var(--status-delivered)', 'var(--status-delivered-bg)', 'Tasdiqlandi', tasdiq, 'CONFIRMED', 'var(--status-delivered)') +
        card('truck', 'var(--status-shipped)', 'var(--status-shipped-bg)', "Yo'lda", yolda, 'SHIPPING', 'var(--status-shipped)') +
        card('check-check', '#A371F7', 'rgba(163,113,247,0.12)', 'Yetkazildi', yetkazil, 'DONE', '#A371F7');
}

/**
 * Holat bo'yicha saralash. Ikkinchi marta bosilsa, filtr o'chadi va
 * ro'yxat to'liq holatiga qaytadi.
 *
 * Ilgari bu funksiya `.o-filter-tab` klassini tozalardi, lekin markupda
 * bunday klass yo'q edi: shuning uchun bosilgan chiplar hech qachon
 * o'chmasdi va vaqt o'tib hammasi yashil bo'lib qolardi. Endi holat
 * inline uslub bilan emas, `active` klassi bilan boshqariladi.
 */
function filterOrdersByStatus(status, el) {
    const alreadyOn = selectedOrderStatusFilter === status && status !== 'all';
    selectedOrderStatusFilter = alreadyOn ? 'all' : status;

    document.querySelectorAll('.orders-filter-bar .filter-pill')
        .forEach(b => b.classList.remove('active'));

    if (alreadyOn || selectedOrderStatusFilter === 'all') {
        const allBtn = document.querySelector('.orders-filter-bar .filter-pill');
        if (allBtn) allBtn.classList.add('active');
    } else if (el) {
        el.classList.add('active');
    }

    renderOrdersTable();
}

let selectedOrderId = null;

function renderOrdersTable() {
    const tbody = document.getElementById('orders-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const COLORS = ['#388BFD','#A371F7','#00b87c','#f59e0b','#f0883e','#e11d48'];

    const searchTerm = (document.getElementById('order-search-input')?.value || '').toLowerCase();
    const filtered = currentOrders.filter(o => {
        const matchStatus = selectedOrderStatusFilter === 'all' || o.status === selectedOrderStatusFilter;
        const matchSearch = !searchTerm ||
            (o.id || '').toLowerCase().includes(searchTerm) ||
            (o.customer_name || '').toLowerCase().includes(searchTerm) ||
            (o.customer_phone || '').toLowerCase().includes(searchTerm);
        return matchStatus && matchSearch;
    });

    const footer = document.getElementById('orders-footer');
    if (footer) footer.textContent = `Showing 1 to ${Math.min(filtered.length, 50)} of ${filtered.length} orders`;

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:40px; color:var(--text-muted);">Buyurtmalar topilmadi.</td></tr>`;
        return;
    }

    filtered.slice(0, 50).forEach((o, idx) => {
        const d = new Date(o.created_at);
        const dateStr = isNaN(d) ? (o.created_at || '—') :
            `${monthNames[d.getMonth()]} ${d.getDate()}, ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;

        const initials = (o.customer_name || 'MI').substring(0, 2).toUpperCase();
        const avatarColor = COLORS[idx % COLORS.length];
        const shortId = '#ORD-' + String(o.id).replace(/[^0-9]/g, '').substring(0, 4).padStart(4, '0');

        const [sc, sb] = orderStatusColors(o.status);

        const isActive = selectedOrderId === o.id;
        const tr = document.createElement('tr');
        tr.style.cssText = `border-bottom:1px solid var(--border); cursor:pointer; transition:background 0.15s; ${isActive ? 'background:var(--primary-glow);' : ''}`;
        tr.onmouseenter = () => { if (!isActive) tr.style.background = 'var(--surface)'; };
        tr.onmouseleave = () => { if (!isActive) tr.style.background = ''; };

        tr.innerHTML = `
            <td style="padding:16px 20px; font-family:var(--font-mono); font-size:14.5px; font-weight:600; color:${isActive ? 'var(--primary)' : 'var(--text-main)'};">${shortId}</td>
            <td style="padding:14px 20px;">
                <div style="display:flex; align-items:center; gap:10px;">
                    <div style="width:36px; height:36px; border-radius:50%; background:${avatarColor}22; color:${avatarColor}; font-size:12px; font-weight:700; display:flex; align-items:center; justify-content:center; font-family:var(--font-mono); flex-shrink:0;">${initials}</div>
                    <span style="font-weight:500; font-size:15px; color:var(--text-main);">${escapeHtml(o.customer_name || '—')}</span>
                </div>
            </td>
            <td class="col-date" style="padding:16px 20px; color:var(--text-muted); font-size:14px;">${dateStr}</td>
            <td style="padding:16px 20px; text-align:right; font-family:var(--font-mono); font-size:14.5px; font-weight:600; color:var(--text-main);">${fmtNum(o.total_amount)} <span style="font-size:11px; color:var(--text-muted); font-weight:400;">so'm</span></td>
            <td style="padding:14px 20px;">
                <span style="display:inline-flex; align-items:center; gap:5px; padding:5px 12px; border-radius:100px; background:${sb}; border:1px solid ${sc}44; color:${sc}; font-size:13px; font-weight:600;">
                    <span style="width:5px; height:5px; border-radius:50%; background:${sc};"></span>
                    ${escapeHtml(o.status || '—')}
                </span>
            </td>
        `;
        tr.addEventListener('click', () => showOrderDetail(o));
        tbody.appendChild(tr);
    });
}

/** Buyurtma bosqichlari, tartib bo'yicha. Keyingi qadam shu ro'yxatdan olinadi. */
const ORDER_FLOW = ['Yangi', 'Tasdiqlandi', "Yo'lda", 'Yetkazildi'];

/* Bosqich sarlavhalari va hali bajarilmagan qadamning izohi. Matnlar Stitch
   dizaynidan olingan. */
const ORDER_STEP_LABEL = {
    'Yangi': 'Yangi (Order Placed)',
    'Tasdiqlandi': 'Tasdiqlandi (Confirmed)',
    "Yo'lda": "Yo'lda (Shipping)",
    'Yetkazildi': 'Yetkazildi (Delivered)',
};
const ORDER_STEP_PENDING = {
    'Yangi': 'Kutilmoqda',
    'Tasdiqlandi': 'Tasdiq kutilmoqda',
    "Yo'lda": 'Pending courier pickup',
    'Yetkazildi': 'Awaiting delivery',
};

/** Holat uchun rang juftligi. */
function orderStatusColors(status) {
    const st = (status || '').toLowerCase();
    if (st.includes('yangi'))       return ['var(--status-new)', 'var(--status-new-bg)'];
    if (st.includes('tasdiq'))      return ['var(--status-confirmed)', 'var(--status-confirmed-bg)'];
    if (st.includes("yo'lda") || st.includes('yolda')) return ['var(--status-shipped)', 'var(--status-shipped-bg)'];
    if (st.includes('yetkazildi'))  return ['var(--status-delivered)', 'var(--status-delivered-bg)'];
    if (st.includes('bekor'))       return ['var(--accent-danger)', 'rgba(255,180,171,0.12)'];
    return ['var(--text-muted)', 'var(--surface)'];
}

/**
 * O'ng tomondagi buyurtma tafsiloti.
 *
 * Panel ataylab skrollsiz: sarlavha, mijoz, mahsulotlar, hisob, bosqichlar va
 * tugmalar bitta ekranga sig'adigan qilib ixcham berilgan. Shuning uchun
 * bo'shliqlar kichik va bosqichlar ro'yxati bir qatorli.
 */
function showOrderDetail(o) {
    // O'sha qatorga qayta bosish panelni yopadi.
    if (selectedOrderId === o.id) {
        closeOrderDetail();
        return;
    }
    selectedOrderId = o.id;
    renderOrdersTable(); // re-render to highlight active row

    const panel = document.getElementById('order-detail-panel');
    const inner = document.getElementById('order-detail-inner');
    if (!panel || !inner) return;

    panel.style.width = '420px';

    const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const fmtDate = (value) => {
        const d = new Date(value);
        if (isNaN(d)) return value || '—';
        const hh = d.getHours().toString().padStart(2, '0');
        const mm = d.getMinutes().toString().padStart(2, '0');
        return `${monthNames[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()} at ${hh}:${mm}`;
    };

    const shortId = '#ORD-' + String(o.id).replace(/[^0-9]/g, '').substring(0, 4).padStart(4, '0');
    /* Panel belgisi Stitch dizaynida yashil tint bilan beriladi. */
    const [sc, sb] = ['var(--primary-text)', 'var(--primary-glow)'];
    const initials = (o.customer_name || 'MI').substring(0, 2).toUpperCase();

    /* Buyurtma qatorida faqat product_id bor. Rasmni katalogdan izlaymiz;
       katalog hali yuklanmagan bo'lsa, o'rniga belgi ko'rsatiladi. */
    const items = (o.items || []).map((it) => {
        const prod = (currentProducts || []).find(pr => pr.id === it.product_id);
        const img = prod && prod.image_url;
        const line = (Number(it.unit_price) || 0) * (Number(it.quantity) || 0);
        const thumb = img
            ? `<img src="${escapeHtml(img)}" alt="" class="od-thumb" loading="lazy">`
            : `<div class="od-thumb od-thumb--empty"><span class="ico ico-package"></span></div>`;
        return `
            <div class="od-item">
                ${thumb}
                <div class="od-item-text">
                    <div class="od-item-name">${escapeHtml(it.product_name || '—')}</div>
                    <div class="od-item-qty">${it.quantity} x ${fmtNum(it.unit_price)} so'm</div>
                </div>
                <div class="od-item-sum">${fmtNum(line)} <em>so'm</em></div>
            </div>`;
    }).join('');

    const doneIndex = ORDER_FLOW.indexOf(o.status);
    const timeline = ORDER_FLOW.map((step, i) => {
        const done = doneIndex >= 0 && i <= doneIndex;
        const isCurrent = i === doneIndex;
        const sub = isCurrent
            ? fmtDate(o.created_at)
            : (done ? fmtDate(o.created_at) : ORDER_STEP_PENDING[step]);
        return `
            <li class="od-step${done ? ' is-done' : ''}${isCurrent ? ' is-current' : ''}">
                <span class="od-step-dot"></span>
                <div>
                    <div class="od-step-name">${ORDER_STEP_LABEL[step] || step}</div>
                    <div class="od-step-sub">${sub}</div>
                </div>
            </li>`;
    }).join('');

    const next = doneIndex >= 0 && doneIndex < ORDER_FLOW.length - 1 ? ORDER_FLOW[doneIndex + 1] : null;

    inner.innerHTML = `
        <div class="od-head">
            <div class="od-head-text">
                <div class="od-title-row">
                    <h3>Order ${shortId}</h3>
                    <span class="od-badge" style="background:${sb}; border-color:${sc}44; color:${sc};">${escapeHtml((o.status || '').toUpperCase())}</span>
                </div>
                <div class="od-date">${fmtDate(o.created_at)}</div>
            </div>
            <button type="button" class="od-close" onclick="closeOrderDetail()" aria-label="Yopish">
                <span class="ico ico-x"></span>
            </button>
        </div>

        <div class="od-body">
            <div class="od-customer">
                <div class="od-avatar">${initials}</div>
                <div class="od-cust-text">
                    <div class="od-cust-name">${escapeHtml(o.customer_name || '—')}</div>
                    <div class="od-cust-row"><span class="ico ico-phone"></span>${escapeHtml(o.customer_phone || '—')}</div>
                    ${o.delivery_address ? `<div class="od-cust-row"><span class="ico ico-map-pin"></span>${escapeHtml(o.delivery_address)}</div>` : ''}
                </div>
            </div>

            <div class="od-label">Items (${(o.items || []).length})</div>
            <div class="od-items">${items || '<div class="od-empty">Mahsulot ma\'lumotlari yo\'q</div>'}</div>

            <div class="od-totals">
                <div class="od-total-row"><span>Subtotal</span><span>${fmtNum(o.total_amount)} so'm</span></div>
                <div class="od-total-row"><span>Shipping</span><span>0 so'm</span></div>
                <div class="od-total-row"><span>Tax</span><span>Included</span></div>
                <div class="od-total-row od-total-row--sum"><span>Total Sum</span><span>${fmtNum(o.total_amount)} so'm</span></div>
            </div>

            <div class="od-status-card">
                <div class="od-label">Order Status</div>
                <ol class="od-timeline">${timeline}</ol>
            </div>
        </div>

        <div class="od-foot">
            <button type="button" class="od-btn-ghost" onclick="updateOrderStatus('${o.id}', 'Bekor qilindi')">Reject</button>
            ${next
                ? `<button type="button" class="od-btn-primary" onclick="updateOrderStatus('${o.id}', '${next}')">Move to ${next} <span class="ico ico-arrow-right"></span></button>`
                : `<button type="button" class="od-btn-primary" disabled>Yakunlangan</button>`}
        </div>
    `;
}

function closeOrderDetail() {
    selectedOrderId = null;
    const panel = document.getElementById('order-detail-panel');
    if (panel) panel.style.width = '0';
    renderOrdersTable();
}

async function updateOrderStatus(orderId, newStatus) {
    try {
        await fetch(`/api/admin/orders/${orderId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        await loadOrders();
        // Re-open detail if same order
        if (selectedOrderId === orderId) {
            const updated = currentOrders.find(o => o.id === orderId);
            if (updated) showOrderDetail(updated);
        }
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
let hiddenSettings = { auto_handoff_after: 3 };

async function loadSettings() {
    try {
        const resp = await fetch('/api/admin/settings');
        const data = await resp.json();

        hiddenSettings = {
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
        setVal('kb-phone', data.contact_phone);
        setVal('kb-faq', data.faq);
        renderKbStatus(data);
    } catch (e) {
        console.error('Sozlamalarni yuklashda xatolik:', e);
    }
}

/** How complete the Knowledge Base is — an empty one means constant handoffs. */
function renderKbStatus(d) {
    const el = document.getElementById('kb-status');
    if (!el) return;
    const fields = [d.delivery_fee_city, d.delivery_fee_regions, d.free_delivery_from,
                    d.delivery_days_city, d.delivery_days_regions, d.delivery_info,
                    d.payment_info, d.warranty_info, d.return_policy, d.working_hours, d.faq,
                    d.contact_phone];
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

/** Drops 3 example Q&As into the FAQ box for the owner to edit/delete rather
 *  than have to remember the "S: / J:" convention from a placeholder alone.
 *  Appends after whatever is already there instead of overwriting it. */
function insertFaqTemplate() {
    const el = document.getElementById('kb-faq');
    if (!el) return;
    const sample = "S: Ish vaqtingiz qanday?\nJ: Har kuni 9:00 - 19:00\n\n"
        + "S: To'lovni qanday amalga oshiraman?\nJ: Naqd yoki kartaga o'tkazma orqali\n\n"
        + "S: Yetkazib berish qancha vaqt oladi?\nJ: Toshkent bo'ylab 1-2 kun";
    el.value = el.value.trim() ? `${el.value.trim()}\n\n${sample}` : sample;
    el.focus();
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
                contact_phone: gv('kb-phone') || null,
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

/* Barcha suhbatlar shu yerda saqlanadi. Saralash va qidiruv mijoz tomonida
   bajariladi: shunda har bir filtr yonidagi sanoqni ko'rsatish uchun
   qo'shimcha so'rov kerak bo'lmaydi. */
let inboxAll = [];

async function loadInbox() {
    try {
        const resp = await fetch('/api/inbox/conversations?status=all');
        inboxAll = await resp.json() || [];
        renderInboxList();
        updateInboxBadge(inboxAll);
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

/** Suhbat holati uchun yorliq: matn va rang sinfi. */
const CONV_BADGE = {
    ai:       { text: 'AI HAL QILDI',   cls: 'is-ai' },
    operator: { text: 'OPERATOR KERAK', cls: 'is-operator' },
    closed:   { text: 'YOPILGAN',       cls: 'is-closed' },
};

function renderInboxList() {
    const box = document.getElementById('inbox-conversations');
    if (!box) return;

    const term = (document.getElementById('inbox-search-input')?.value || '').trim().toLowerCase();

    /* Sanoqlar qidiruvdan oldin hisoblanadi: filtr yorlig'i qancha suhbat
       borligini ko'rsatishi kerak, qidiruv natijasini emas. */
    const counts = {
        all: inboxAll.length,
        ai: inboxAll.filter(c => c.status === 'ai').length,
        operator: inboxAll.filter(c => c.status === 'operator').length,
        closed: inboxAll.filter(c => c.status === 'closed').length,
    };
    for (const key of Object.keys(counts)) {
        const el = document.getElementById('inbox-count-' + key);
        if (el) el.textContent = counts[key];
    }

    const list = inboxAll.filter(c => {
        const byStatus = inboxFilter === 'all' || c.status === inboxFilter;
        const bySearch = !term ||
            (c.customer_name || '').toLowerCase().includes(term) ||
            (c.last_message || '').toLowerCase().includes(term) ||
            (c.customer_phone || '').toLowerCase().includes(term);
        return byStatus && bySearch;
    });

    if (list.length === 0) {
        box.innerHTML = term
            ? `<div class="inbox-empty-list">Topilmadi.<br><span>Boshqa so'z bilan qidirib ko'ring.</span></div>`
            : `<div class="inbox-empty-list">Hali suhbatlar yo'q.<br><span>Telegram botni ulang yoki Test rejimida sinab ko'ring.</span></div>`;
        renderHandoffBanner(inboxAll.filter(c => c.waiting_for_operator).length);
        return;
    }

    box.innerHTML = list.map(c => {
        const badge = CONV_BADGE[c.status] || { text: c.status, cls: '' };
        const initials = (c.customer_name || 'MI').substring(0, 2).toUpperCase();
        return `
        <div class="conv-item ${c.id === activeConvId ? 'active' : ''} ${c.waiting_for_operator ? 'waiting' : ''}" onclick="openConversation('${c.id}')">
            <div class="conv-avatar">
                ${initials}
                <span class="conv-channel">${isSandbox(c) ? '🧪' : (CHANNEL_ICON[c.channel] || '💬')}</span>
            </div>
            <div class="conv-body">
                <div class="conv-top">
                    <span class="conv-name">${escapeHtml(c.customer_name)}</span>
                    <span class="conv-time">${shortStamp(c.last_message_at)}</span>
                </div>
                <div class="conv-preview">${escapeHtml(c.last_message || '')}</div>
                <div class="conv-tags">
                    <span class="conv-badge ${badge.cls}">${badge.text}</span>
                    ${c.blocked ? '<span class="conv-badge is-blocked">BLOKLANGAN</span>' : ''}
                    ${c.unread_count > 0 ? `<span class="conv-unread">${c.unread_count}</span>` : ''}
                </div>
            </div>
        </div>`;
    }).join('');

    renderHandoffBanner(inboxAll.filter(c => c.waiting_for_operator).length);
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


function filterInbox(status, btn) {
    inboxFilter = status;
    document.querySelectorAll('.inbox-filter').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    renderInboxList();
}

/** Mobile only: the list and chat panes stack on top of each other there, so
 *  opening a conversation hides the list — this is the way back to it. */
function closeMobileChat() {
    document.querySelector('.inbox-layout')?.classList.remove('is-chat-open');
}

async function openConversation(convId) {
    activeConvId = convId;
    try {
        const resp = await fetch('/api/inbox/conversations/' + convId);
        if (!resp.ok) return;
        const data = await resp.json();

        document.getElementById('inbox-empty').style.display = 'none';
        document.getElementById('inbox-chat-active').style.display = 'flex';
        document.getElementById('inbox-chat-active').scrollIntoView({ behavior: 'smooth', block: 'start' });

        const c = data.conversation;
        const initials = (c.customer_name || 'MI').substring(0, 2).toUpperCase();
        const handle = c.external_id ? '@' + String(c.external_id).replace(/^@/, '') : '';

        /* Amallar ikonka tugmalarida: sarlavha tinch qolsin, lekin operator
           uchun kerakli to'rtta amal ham joyida bo'lsin. */
        document.querySelector('.inbox-layout')?.classList.add('is-chat-open');
        document.getElementById('inbox-chat-header').innerHTML = `
            <button class="chat-icon-btn inbox-back-btn" onclick="closeMobileChat()" title="Ro'yxatga qaytish" aria-label="Ro'yxatga qaytish">←</button>
            <div class="chat-who">
                <div class="chat-avatar">${initials}<span class="conv-channel">${CHANNEL_ICON[c.channel] || '💬'}</span></div>
                <div class="chat-who-text">
                    <div class="chat-customer">${escapeHtml(c.customer_name)}</div>
                    <div class="chat-meta">
                        <span class="ico ico-phone"></span>${escapeHtml(c.customer_phone || '—')}
                        ${handle ? `<span class="chat-dot"></span>${escapeHtml(handle)}` : ''}
                    </div>
                    ${c.status === 'operator' && c.handoff_reason ? `<div class="chat-reason">${escapeHtml(c.handoff_reason)}</div>` : ''}
                </div>
            </div>
            <div class="chat-actions">
                ${c.status !== 'operator' ? `<button class="chat-icon-btn" onclick="setConvStatus('${c.id}','operator')" title="Men javob beraman"><span class="ico ico-headset"></span></button>` : ''}
                ${c.status !== 'ai' ? `<button class="chat-icon-btn" onclick="setConvStatus('${c.id}','ai')" title="AI'ga qaytarish"><span class="ico ico-bot"></span></button>` : ''}
                ${c.status !== 'closed' ? `<button class="chat-icon-btn" onclick="setConvStatus('${c.id}','closed')" title="Suhbatni yopish"><span class="ico ico-circle-check"></span></button>` : ''}
                ${c.blocked ? `<button class="chat-icon-btn" onclick="unblockConversation('${c.id}')" title="Blokni bekor qilish"><span class="ico ico-lock-open"></span></button>` : ''}
                <button class="chat-icon-btn is-danger" onclick="deleteConversation('${c.id}')" title="O'chirish"><span class="ico ico-trash-2"></span></button>
            </div>`;

        /* Pastdagi izoh: suhbatni hozir kim boshqarayotgani. */
        const note = document.getElementById('inbox-mode-note');
        if (note) {
            const modes = {
                ai: ['is-ai', 'AI bu suhbatni boshqaryapti'],
                operator: ['is-operator', 'Siz javob beryapsiz'],
                closed: ['is-closed', 'Suhbat yopilgan'],
            };
            /* Blok statusdan ustun: yopilgan suhbat bilan bloklangan suhbat
               bir xil emas — birinchisiga operator yozsa bot davom etadi,
               ikkinchisiga umuman javob bo'lmaydi. */
            const [cls, text] = c.blocked
                ? ['is-blocked', 'Haqorat uchun bloklangan — bot javob bermaydi']
                : (modes[c.status] || ['', c.status]);
            note.className = 'inbox-mode ' + cls;
            note.textContent = text;
        }

        renderMessages('inbox-messages', data.messages);
        loadInbox();
    } catch (e) {
        console.error('Suhbatni ochishda xatolik:', e);
    }
}

/** Ro'yxatdagi vaqt: bugun bo'lsa soat, kecha bo'lsa "Kecha", aks holda
    "13-avg" ko'rinishi. To'liq sana ro'yxatda joy egallaydi va foyda bermaydi. */
const SHORT_MONTHS = ['yan','fev','mar','apr','may','iyn','iyl','avg','sen','okt','noy','dek'];
function shortStamp(value) {
    const { day, time } = splitStamp(value);
    if (!day) return time || '';
    const today = new Date();
    const iso = (d) => d.toISOString().slice(0, 10);
    if (day === iso(today)) return time;
    if (day === iso(new Date(today.getTime() - 86400000))) return 'Kecha';
    const [, m, d] = day.split('-');
    return `${Number(d)}-${SHORT_MONTHS[Number(m) - 1] || m}`;
}

/** "2026-08-13 10:10" dan sana va soatni ajratadi. */
function splitStamp(value) {
    const s = String(value || '');
    const m = s.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
    return m ? { day: m[1], time: m[2] } : { day: '', time: s };
}

/** Sana ajratgichi uchun yorliq: bugun va kecha alohida nomlanadi. */
function dayLabel(day) {
    if (!day) return '';
    const today = new Date();
    const iso = (d) => d.toISOString().slice(0, 10);
    const yesterday = new Date(today.getTime() - 86400000);
    if (day === iso(today)) return 'BUGUN';
    if (day === iso(yesterday)) return 'KECHA';
    return day;
}

/**
 * Suhbat oynasi.
 *
 * Tomonlar Stitch dizayni bo'yicha: MIJOZ o'ngda va yashil, AI bilan operator
 * chapda. Ilgari teskari edi. Sabab: operator o'z tomonini o'ngda ko'rishga
 * o'rgangan, lekin bu yerda "o'z tomoni" mijoz emas - suhbatni mijoz boshlaydi
 * va uning gapi asosiy.
 */
function renderMessages(containerId, messages) {
    const box = document.getElementById(containerId);
    if (!box) return;

    let lastDay = null;
    box.innerHTML = (messages || []).map(m => {
        const { day, time } = splitStamp(m.created_at);
        let divider = '';
        if (day && day !== lastDay) {
            lastDay = day;
            divider = `<div class="msg-daydiv"><span>${dayLabel(day)}</span></div>`;
        }

        /* Mijoz chapda avatar bilan, biz (AI/operator) o'ngda — odatiy
           messenjer tartibi: suhbatdoshning yuzi ko'rinadi, o'zimizniki yo'q. */
        const isCustomer = m.sender === 'user';
        const avatarIcon = 'user';
        const meta = m.model_name && m.model_name !== 'fallback'
            ? m.model_name
            : (m.model_name === 'fallback' ? 'demo' : '');

        const photos = (m.photos || []).map(ph =>
            `<img src="${escapeHtml(ph.url)}" class="msg-photo" loading="lazy"
                  onerror="this.style.display='none'" alt="">`).join('');

        return divider + `
        <div class="msg ${isCustomer ? 'msg-in' : 'msg-out'} sender-${m.sender}">
            ${isCustomer ? `<div class="msg-avatar"><span class="ico ico-${avatarIcon}"></span></div>` : ''}
            <div class="msg-col">
                <div class="msg-bubble">${escapeHtml(m.text || '').replace(/\n/g, '<br>')}</div>
                ${photos ? `<div class="msg-photos">${photos}</div>` : ''}
                <div class="msg-time">${time}${meta ? ' · ' + escapeHtml(meta) : ''}</div>
            </div>
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

async function unblockConversation(convId) {
    if (!confirm('Blok bekor qilinsinmi? Bot bu mijozga yana javob bera boshlaydi.')) return;
    try {
        const resp = await fetch(`/api/inbox/conversations/${convId}/unblock`, { method: 'POST' });
        if (!resp.ok) throw new Error('unblock failed');
        openConversation(convId);
        toast('Blok bekor qilindi');
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
    }, 15000);
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

/** Sinov suhbatini boshidan boshlash. */
function resetTestChat() {
    testMessages = [];
    renderMessages('test-messages', testMessages);
    testSessionId = 'sandbox-' + Math.random().toString(36).slice(2, 10);
}

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
        // Haqiqiy mijoz bu javobni olmaydi — sinov oynasi ham shuni ko'rsatishi
        // kerak, aks holda "nega mijozga bormadi" deb chalkashib qoladi.
        const text = data.suppress_send
            ? '_(bu javob mijozga yuborilmadi — ketma-ket mavzudan chiqish)_'
            : data.reply_text;
        testMessages.push({ sender: 'assistant', text, created_at: '' });
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
            await Promise.all([loadProducts(), loadCategories()]);

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

/** Maydon kalitining odam o'qiydigan nomi. */
const IMPORT_FIELD_LABEL = {
    name: 'Nomi', price: 'Narxi', category: 'Kategoriya', description: 'Tavsif',
    stock_quantity: 'Qoldiq', id: 'ID', currency: 'Valyuta', image_url: 'Rasm',
};

/** Katalogni .xlsx qilib yuklab olish. Fayl importer o'qiydigan shaklda:
    tahrirlab, qaytadan yuklash mumkin — ID ustuni tufayli nusxa emas,
    yangilanish bo'ladi. */
async function exportCatalog() {
    try {
        const r = await fetch('/api/admin/products/export');
        if (!r.ok) throw new Error('export failed');
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `katalog-${new Date().toISOString().slice(0, 10)}.xlsx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        toast('Katalog yuklab olindi');
    } catch (e) {
        console.error('Eksport xatosi:', e);
        toast('Yuklab bo\'lmadi', true);
    }
}

function renderImportResult(d, dryRun) {
    /* Qaysi ustun qaysi maydonga tushganini ko'rsatamiz. Faqat sarlavhalarni
       sanash yetarli emas: fayl "Стоимость" deb yozilgan bo'lsa, egasi uni
       narx deb tanilganini ko'rishi kerak. */
    const pairs = Object.entries(d.matched_columns || {})
        .map(([field, header]) => `
            <span class="imp-pair">
                <code>${escapeHtml(header)}</code>
                <span class="ico ico-arrow-right"></span>
                <b>${escapeHtml(IMPORT_FIELD_LABEL[field] || field)}</b>
            </span>`).join('');

    const ignored = (d.ignored_columns || []).length
        ? `<div class="imp-ignored">E'tiborga olinmadi:
             ${d.ignored_columns.map(h => `<code>${escapeHtml(h)}</code>`).join(' ')}</div>`
        : '';

    const notes = [];
    if (d.ai_mapping) notes.push('Ustunlar AI yordamida tanildi');
    if (d.images_saved) notes.push(`${d.images_saved} ta rasm fayldan olindi`);
    const noteBox = notes.length
        ? `<div class="imp-note">${notes.map(escapeHtml).join(' · ')}</div>` : '';

    const errs = (d.errors || []).length
        ? `<div class="import-errors">
             <b>${d.error_count} ta qator o'tkazib yuborildi:</b><br>
             ${d.errors.map(e => `${e.row}-qator: ${escapeHtml(e.error)}${e.name ? ' (' + escapeHtml(e.name) + ')' : ''}`).join('<br>')}
             ${d.error_count > d.errors.length ? '<br>…' : ''}
           </div>`
        : '';

    document.getElementById('import-step-result').innerHTML = `
        <div style="font-size:13px;font-weight:700;margin-bottom:10px;">
            ${dryRun ? "Oldindan ko'rish — hali saqlanmadi" : 'Yuklandi'}
        </div>
        <div class="import-summary">
            <div class="import-stat ok"><b>${d.added}</b><span>yangi</span></div>
            <div class="import-stat"><b>${d.updated}</b><span>yangilandi</span></div>
            <div class="import-stat ${d.skipped ? 'warn' : ''}"><b>${d.skipped}</b><span>o'tkazildi</span></div>
        </div>
        ${noteBox}
        <div class="imp-pairs">${pairs || '—'}</div>
        ${ignored}
        ${errs}`;
}

// ════════════════════════════════════════════════════════
// GOOGLE SHEETS — bitta havola, bitta tugma.
// Excel importdan ataylab sodda: oldindan ko'rish bosqichi yo'q, chunki
// jadval istalgan payt qayta "Ulash" bosib tuzatiladi — xato bo'lsa ham
// hech narsa yo'qolmaydi, faqat qayta urinasiz.
// ════════════════════════════════════════════════════════
function openSheetsModal() {
    document.getElementById('sheets-result').innerHTML = '';
    document.getElementById('sheets-sync-btn').disabled = false;
    document.getElementById('sheets-modal').style.display = 'flex';

    // Ulangan havola bo'lsa, uni qayta terib o'tirmasin.
    fetch('/api/admin/settings').then((r) => r.json()).then((d) => {
        if (d.google_sheet_url) document.getElementById('sheets-url-input').value = d.google_sheet_url;
    }).catch(() => {});
}

function closeSheetsModal() {
    document.getElementById('sheets-modal').style.display = 'none';
}

async function syncGoogleSheet() {
    const url = document.getElementById('sheets-url-input').value.trim();
    if (!url) { toast('Jadval havolasini kiriting', true); return; }

    const box = document.getElementById('sheets-result');
    const btn = document.getElementById('sheets-sync-btn');
    btn.disabled = true;
    box.innerHTML = '<p style="font-size:13px;color:var(--text-muted);margin-top:12px;">Ulanmoqda...</p>';

    try {
        const resp = await fetch('/api/admin/products/import-sheet?dry_run=false', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
        const d = await resp.json();

        if (!resp.ok) {
            box.innerHTML = `<div class="import-errors" style="margin-top:12px;">${escapeHtml(d.detail || 'Xatolik')}</div>`;
            btn.disabled = false;
            return;
        }
        if (d.success === false) {
            box.innerHTML = `
                <div class="import-errors" style="margin-top:12px;">
                    <b>${escapeHtml(d.error)}</b><br>
                    Jadvalda topilgan ustunlar: ${(d.found_columns || []).map(escapeHtml).join(', ') || '—'}
                </div>`;
            btn.disabled = false;
            return;
        }

        box.innerHTML = `
            <div class="import-summary" style="margin-top:12px;">
                <div class="import-stat ok"><b>${d.added}</b><span>yangi</span></div>
                <div class="import-stat"><b>${d.updated}</b><span>yangilandi</span></div>
                <div class="import-stat ${d.skipped ? 'warn' : ''}"><b>${d.skipped}</b><span>o'tkazildi</span></div>
            </div>`;
        btn.disabled = false;
        toast(`✅ Google Sheets bilan ulandi: ${d.added} ta qo'shildi, ${d.updated} ta yangilandi`);
        await Promise.all([loadProducts(), loadCategories()]);
    } catch (err) {
        box.innerHTML = '<div class="import-errors" style="margin-top:12px;">Serverga ulanishda xatolik.</div>';
        btn.disabled = false;
    }
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
        await Promise.all([loadProducts(), loadCategories()]);
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
                <td class="col-channel">${c.channels.map((ch) =>
                    `<span class="chip">${escapeHtml(CH_LABEL[ch] || ch)}</span>`).join(' ')}</td>
                <td class="cell-num">${fmtNum(c.order_count)}</td>
                <td class="cell-num">${c.ltv ? fmtNum(c.ltv) + ' <small>so\'m</small>' : '<span class="cell-dim">—</span>'}</td>
                <td class="col-lastactive cell-nowrap cell-date">${escapeHtml(c.last_seen_at || '—')}</td>
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

    // Jumping straight into the chat is the whole point of seeing the history.
    // Inbox has no sidebar entry of its own — switchToTab opens it directly.
    body.querySelectorAll('[data-conv]').forEach((el) =>
        el.addEventListener('click', () => {
            closeCustomerModal();
            switchToTab('tab-inbox');
            setTimeout(() => openConversation(el.dataset.conv), 300);
        }));
}

// ════════════════════════════════════════════════════════
// INTEGRATSIYALAR — Telegram
// ════════════════════════════════════════════════════════
async function loadIntegrations() {
    loadSheetsStatus();
    let d = null;
    try {
        const resp = await fetch('/api/integrations/telegram');
        d = await resp.json();
        const tgState = document.getElementById('tg-status-text');
        tgState.textContent = d.connected ? 'Ulangan' : 'Ulanmagan';
        /* Yorliq rangi ham holatga ergashsin, faqat matn emas. */
        tgState.classList.toggle('is-on', !!d.connected);
        document.getElementById('tg-connected').style.display = d.connected ? 'block' : 'none';
        document.getElementById('tg-disconnected').style.display = d.connected ? 'none' : 'block';

        // Sozlamalar sahifasidagi qisqa qator — oynani ochmasdan holat ko'rinsin.
        const summary = document.getElementById('tg-summary');
        if (summary) {
            summary.textContent = !d.connected
                ? 'Bot hali ulanmagan — mijozlar bilan gaplasha olishi uchun ulang.'
                : d.business_connected
                    ? `@${d.username} ulangan · AI shaxsiy profilingiz nomidan javob beradi`
                    : `@${d.username} ulangan · AI bot nomidan javob beradi`;
        }

        // 1-qadam holati
        setTgStepState('tg-step-1', d.connected, d.connected ? 'Ulangan' : 'Ulanmagan');

        // 2-qadam: bot ulanmasa, Business haqida gapirishning ma'nosi yo'q —
        // ulanmagan holatda instructionlar o'rniga "avval 1-qadam" ko'rsatiladi,
        // va qadamning o'zi ochilmaydigan qilib qulflanadi (is-locked).
        document.getElementById('tg-business-off').style.display = (d.connected && !d.business_connected) ? '' : 'none';
        document.getElementById('tg-business-on').style.display = (d.connected && d.business_connected) ? '' : 'none';
        document.getElementById('tg-step-2-locked').style.display = d.connected ? 'none' : '';
        document.getElementById('tg-step-2').classList.toggle('is-locked', !d.connected);
        if (!d.connected) document.getElementById('tg-step-2').open = false;
        setTgStepState('tg-step-2', d.business_connected, !d.connected
            ? 'Avval botni ulang' : d.business_connected ? 'Ulangan' : 'Ixtiyoriy');

        if (d.connected) {
            document.getElementById('tg-username').textContent = '@' + (d.username || '—');
            const note = document.getElementById('tg-note');
            if (d.polling_enabled) {
                note.innerHTML = d.polling_active
                    ? "🟢 <b>Localhost rejimi faol</b> — bot Telegramdan xabar olishga tayyor."
                    : "🟡 Localhost rejimi yoqilgan, ulanish tayyorlanmoqda (~30 soniya)...";
            } else if (d.public_url_configured) {
                note.textContent = "🟢 Webhook faol.";
            } else {
                note.textContent = "⚠️ Na polling na public URL yoqilgan — xabarlar kelmaydi.";
            }
            if (!d.business_connected) {
                document.getElementById('tg-business-botname').textContent = '@' + (d.username || 'bot');
            }
        }
    } catch (e) {
        console.error('Integratsiyalarni yuklashda xatolik:', e);
    }
    await loadNotifications();
    updateTgProgress();
    return d;
}

/** <details> ustidagi belgi va matn — qaysi qadam bajarilgan, qaysi qolgan. */
function setTgStepState(stepId, done, text) {
    const step = document.getElementById(stepId);
    const state = document.getElementById(stepId + '-state');
    if (!step || !state) return;
    step.classList.toggle('is-done', !!done);
    state.textContent = text;
}

/** Progress faqat MAJBURIY qadamlarni sanaydi (1 va 3). 2-qadam — ixtiyoriy
    yaxshilanish: ulamagan do'kon ham to'liq ishlaydi, shuning uchun uni
    hisoblash "nimadir buzuq" degan tuyg'u berardi. */
function updateTgProgress() {
    const required = ['tg-step-1', 'tg-step-3'];
    const done = required.filter((id) => document.getElementById(id)?.classList.contains('is-done')).length;
    const fill = document.getElementById('tg-progress-fill');
    const text = document.getElementById('tg-progress-text');
    if (fill) fill.style.width = `${Math.round((done / required.length) * 100)}%`;
    if (text) text.textContent = `${done}/${required.length} qadam`;
}

/** Uchala qadam ham DOM'ga yozilgandan keyin — birinchi tugallanmaganini ochadi,
    qolganini yopadi, shunda oyna "keyingi nima qilish kerak"ni o'zi ko'rsatadi. */
function focusFirstIncompleteTgStep() {
    const ids = ['tg-step-1', 'tg-step-2', 'tg-step-3'];
    // Ixtiyoriy qadam o'zini "qilinmagan ish" qilib ko'rsatmasin: ochiladigani
    // faqat majburiylar orasidan tanlanadi, hammasi tugagan bo'lsa — hech biri.
    const firstOpen = ['tg-step-1', 'tg-step-3']
        .find((id) => !document.getElementById(id).classList.contains('is-done'));
    ids.forEach((id) => { document.getElementById(id).open = (id === firstOpen); });
}

async function openTelegramModal() {
    document.getElementById('telegram-modal').style.display = 'flex';
    await loadIntegrations();
    focusFirstIncompleteTgStep();
}

// ── Bildirishnomalar: qaysi xabar qayerga ──
const CH_ICON = { private: '👤', group: '👥', channel: '📢' };
let NOTIF = { channels: [], events: [] };

async function loadNotifications() {
    const rows = document.getElementById('notif-rows');
    if (!rows) return;
    let d;
    try {
        const resp = await fetch('/api/integrations/notifications');
        if (!resp.ok) throw new Error('yuklanmadi');
        d = await resp.json();
    } catch (e) {
        rows.innerHTML = '<tr><td colspan="2" class="table-empty">Yuklab bo\'lmadi.</td></tr>';
        return;
    }
    NOTIF = d;

    const hasChannels = d.channels.length > 0;
    document.getElementById('notif-empty').style.display = hasChannels ? 'none' : '';
    document.getElementById('notif-table-wrap').style.display = hasChannels ? '' : 'none';
    document.getElementById('notif-save-btn').style.display = hasChannels ? '' : 'none';
    document.getElementById('notif-code-btn').textContent =
        hasChannels ? '+ Yana manzil ulash' : '+ Manzil ulash';

    // Paired destinations, each removable
    document.getElementById('notif-channels').innerHTML = !hasChannels ? '' : `
        <div class="notif-chan-head">Ulangan manzillar</div>
        ${d.channels.map((c) => `
            <div class="notif-chan">
                <span>${CH_ICON[c.kind] || '•'}</span>
                <div class="notif-chan-txt">
                    <b>${escapeHtml(c.title || c.kind_label)}</b>
                    <span>${escapeHtml(c.kind_label)} · <code>${escapeHtml(c.chat_id)}</code></span>
                </div>
                <button class="btn-mini danger" data-unpair="${escapeHtml(c.chat_id)}"
                        data-title="${escapeHtml(c.title || c.kind_label)}">Uzish</button>
            </div>`).join('')}`;

    // One row per message type; a type with nothing ticked is switched off
    rows.innerHTML = d.events.map((ev) => `
        <tr>
            <td>
                <b>${escapeHtml(ev.title)}</b>
                <span class="cell-sub">${escapeHtml(ev.hint)}</span>
            </td>
            <td>
                <div class="notif-picks">
                    ${d.channels.map((c) => {
                        // A channel has nobody to press a confirm button, so the
                        // two button-carrying events cannot be sent there.
                        const blocked = ev.needs_group && c.kind === 'channel';
                        return `<label class="notif-pick${blocked ? ' is-blocked' : ''}"
                                       title="${blocked ? 'Kanalda tugmani bosadigan odam yo\'q' : ''}">
                            <input type="checkbox" data-ev="${escapeHtml(ev.key)}"
                                   value="${escapeHtml(c.chat_id)}"
                                   ${ev.targets.includes(c.chat_id) ? 'checked' : ''}
                                   ${blocked ? 'disabled' : ''}>
                            <span>${CH_ICON[c.kind] || '•'} ${escapeHtml(c.title || c.kind_label)}</span>
                        </label>`;
                    }).join('')}
                </div>
                ${ev.targets.length ? '' : '<span class="notif-off">o\'chirilgan</span>'}
            </td>
        </tr>`).join('');

    document.getElementById('notif-channels').querySelectorAll('[data-unpair]').forEach((b) =>
        b.addEventListener('click', () => unpairChannel(b.dataset.unpair, b.dataset.title)));

    setTgStepState('tg-step-3', hasChannels,
        hasChannels ? `${d.channels.length} ta ulangan` : 'Ulanmagan');

    // Integratsiyalar bo'limidagi ko'rsatkich — oynani ochmasdan holat ko'rinsin.
    const cardStatus = document.getElementById('notif-card-status');
    if (cardStatus) {
        cardStatus.textContent = hasChannels
            ? `${d.channels.length} ta manzil ulangan`
            : "Qaysi xabar qayerga borishini o'zingiz tanlaysiz";
    }
}

async function saveNotifyRoutes() {
    const routes = {};
    NOTIF.events.forEach((ev) => { routes[ev.key] = []; });
    document.querySelectorAll('#notif-rows input[type=checkbox]:checked').forEach((cb) => {
        routes[cb.dataset.ev].push(cb.value);
    });
    try {
        const r = await fetch('/api/integrations/notifications', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ routes }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || 'Saqlanmadi');
        toast('Bildirishnomalar saqlandi');
        loadNotifications();
    } catch (e) { toast(e.message, true); }
}

async function getNotifyCode() {
    try {
        const r = await fetch('/api/integrations/notifications/code', { method: 'POST' });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || 'Xatolik');
        document.getElementById('notif-code').textContent = d.pairing_code;
        document.getElementById('notif-cmd').textContent = `/ulash ${d.pairing_code}`;
        document.getElementById('notif-bot-name').textContent = '@' + (d.bot_username || 'bot');
        document.getElementById('notif-pair-box').style.display = '';
    } catch (e) { toast(e.message, true); }
}

async function unpairChannel(chatId, title) {
    if (!confirm(`"${title}" uzilsinmi? Unga hech qanday xabar bormay qo'yadi.`)) return;
    try {
        const r = await fetch(`/api/integrations/notifications/channels/${encodeURIComponent(chatId)}`,
                              { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json()).detail || 'Uzilmadi');
        toast('Manzil uzildi');
        loadNotifications();
    } catch (e) { toast(e.message, true); }
}

function closeTelegramModal() {
    document.getElementById('telegram-modal').style.display = 'none';
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

// ════════════════════════════════════════════════════════
// YON PANEL — tarif, balans, yangilanish sanasi
// ════════════════════════════════════════════════════════
const UZ_MONTHS = ['yan', 'fev', 'mar', 'apr', 'may', 'iyn',
                   'iyl', 'avg', 'sen', 'okt', 'noy', 'dek'];

/** "2026-09-11" -> "11-sen". Short enough for the sidebar's width. */
function fmtDateShort(iso) {
    if (!iso) return '—';
    const [y, m, d] = iso.split('-').map(Number);
    if (!y || !m || !d) return iso;
    return `${d}-${UZ_MONTHS[m - 1]}`;
}

/**
 * The three things an owner checks without opening a screen: which tariff,
 * how much is on the account, and the date it renews. The model name used to
 * sit here — that is the platform's business, not the shop's.
 */
async function loadSidebarPlan() {
    const box = document.getElementById('side-plan');
    if (!box) return;
    try {
        const resp = await fetch('/api/admin/billing');
        if (!resp.ok) throw new Error('billing');
        const d = await resp.json();

        const days = d.days_left === null || d.days_left === undefined
            ? null : Math.max(0, Math.round(d.days_left));

        // Say what happens next, not just what is true today.
        let when, tone = '';
        if (d.status === 'free') {
            when = 'Muddatsiz';
        } else if (d.status === 'frozen') {
            when = `To'xtatilgan · ${days} kun saqlanmoqda`;
            tone = ' is-warn';
        } else if (d.status === 'grace') {
            when = `Muddat tugadi · bot ${d.grace_days} kun ishlaydi`;
            tone = ' is-warn';
        } else if (d.status === 'expired') {
            when = 'Muddat tugadi — bot to\'xtadi';
            tone = ' is-danger';
        } else {
            // Trial and paid alike: the date is what matters, and whether the
            // balance will actually cover the renewal when it arrives.
            const verb = d.can_auto_renew ? 'Yangilanadi' : 'Tugaydi';
            when = `${verb}: ${fmtDateShort(d.expires_at)} · ${days} kun`;
            if (days !== null && days <= 3) tone = ' is-warn';
        }

        box.innerHTML = `
            <div class="side-plan-row">
                <span>${escapeHtml(d.plan_title || d.plan)}${d.status === 'trial' ? ' · sinov' : ''}</span>
                <b>${fmtNum(d.balance)} <small>so'm</small></b>
            </div>
            <div class="side-plan-when${tone}">${escapeHtml(when)}</div>`;
    } catch (e) {
        box.innerHTML = '<div class="side-plan-when">Tarif ma\'lumoti yuklanmadi</div>';
    }
}

/**
 * Sozlamalar bo'limi yuklovchisi.
 *
 * Telegram bloki Integratsiyalardan shu yerga ko'chirilgan, shuning uchun
 * uning holatini ham shu yerda yuklaymiz - aks holda token maydoni bo'sh
 * qolar va "Ulanmagan" deb ko'rsatilaverardi.
 */
async function loadSettingsTab() {
    loadAccountSettings();
    loadIntegrations();
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
            <span class="bill-label">Joriy obuna</span>
            <div class="bill-sub-row">
                <span class="bill-sub-plan">${escapeHtml(d.plan_title)}</span>
                <span class="bill-sub-state bill-${d.status}">${SUB_STATE[d.status] || d.status}</span>
            </div>
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

        const limit = (v, unit) => (v === null ? 'Cheksiz ' + unit : fmtNum(v) + ' ' + unit);
        document.getElementById('bill-plans').innerHTML = d.plans.map((p) => `
            <div class="bill-plan ${p.current ? 'is-current' : ''}">
                ${p.current ? '<span class="bill-plan-ribbon">Joriy tarif</span>' : ''}
                <h4>${escapeHtml(p.title)}</h4>
                <div class="bill-plan-price">
                    ${fmtNum(p.price_uzs)} <small>so'm / ${p.duration_days} kun</small>
                </div>
                <ul class="bill-plan-list">
                    <li><span class="ico ico-circle-check"></span>${limit(p.max_products, 'mahsulot')}</li>
                    <li><span class="ico ico-circle-check"></span>${limit(p.max_ai_messages_monthly, 'AI xabar / oy')}</li>
                    <li><span class="ico ico-circle-check"></span>${limit(p.max_operators, 'operator')}</li>
                </ul>
                ${p.price_uzs > 0
                    ? `<button class="${p.current ? 'bill-plan-btn is-current' : 'bill-plan-btn'}" data-plan="${escapeHtml(p.name)}">
                        ${p.current ? 'Muddatni uzaytirish' : 'Shu tarifni olish'}</button>`
                    : '<span class="bill-plan-free">Boshlang\'ich tarif</span>'}
            </div>`).join('');

        document.getElementById('bill-plans').querySelectorAll('[data-plan]').forEach((b) =>
            b.addEventListener('click', () => buyPlan(b.dataset.plan, d.balance)));

        const tb = document.getElementById('bill-history');
        tb.innerHTML = d.history.length ? d.history.map((h) => {
            const [icon, label] = BILL_STATE[h.status] || ['', h.status];
            const positive = h.amount >= 0;
            return `<tr>
                <td style="padding:14px 20px; color:var(--text-muted); font-size:13.5px;">${escapeHtml(h.created_at || '')}</td>
                <td style="padding:14px 20px; font-size:14px;">${escapeHtml(BILL_KIND[h.kind] || h.kind)}</td>
                <td style="padding:14px 20px; color:var(--text-muted); font-size:13.5px;">${escapeHtml(h.note || '—')}</td>
                <td style="padding:14px 20px; text-align:right; font-family:var(--font-mono); font-weight:600; color:${positive ? 'var(--primary-text)' : 'var(--text-main)'};">
                    ${positive ? '+' : ''}${fmtNum(h.amount)} <span style="font-size:11px; color:var(--text-muted); font-weight:400;">so'm</span>
                </td>
                <td style="padding:14px 20px; font-size:13.5px; color:var(--text-muted);">${icon} ${label}</td>
            </tr>`;
        }).join('')
          : '<tr><td colspan="5" style="text-align:center;color:var(--text-dim);padding:34px;">Hali to\'lov yo\'q.</td></tr>';
    } catch (e) {
        console.error('Hisobni yuklashda xatolik:', e);
    }
}

document.getElementById('bill-topup-btn')?.addEventListener('click', () => {
    document.getElementById('topup-amount').value = '';
    document.getElementById('topup-note').value = '';
    document.getElementById('topup-modal').style.display = 'flex';
});

function closeTopupModal() {
    document.getElementById('topup-modal').style.display = 'none';
}

async function submitTopup() {
    const amount = Number(document.getElementById('topup-amount').value);
    if (!amount || amount <= 0) return toast('Summa noto\'g\'ri.', true);
    const note = document.getElementById('topup-note').value.trim();
    try {
        const r = await fetch('/api/admin/billing/topup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount, note }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || 'Xatolik');
        closeTopupModal();
        toast(d.message);
        loadBilling();
        loadSidebarPlan();
    } catch (e) { toast(e.message, true); }
}

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
        loadSidebarPlan();
    } catch (e) { alert(e.message); }
}
