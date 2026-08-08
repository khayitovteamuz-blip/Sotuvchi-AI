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
    if (!navReady) { initNavigation(); navReady = true; }
    loadInbox();          // Inbox is the default screen
    loadCategories();     // needed by the product modal's category select
    loadProducts();
    loadSettings();
    startInboxPolling();
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
    'tab-products':     { title: 'Katalog', sub: 'Kategoriyalar va ombordagi mahsulotlar', btn: true, load: loadCategories },
    'tab-orders':       { title: 'Buyurtmalar', sub: 'Barcha buyurtmalar va status workflow', btn: false, load: loadOrders },
    'tab-customers':    { title: 'Mijozlar', sub: 'Mijoz profillari, LTV va xarid tarixi', btn: false, load: loadCustomers },
    'tab-integrations': { title: 'Integratsiyalar', sub: 'Telegram, Instagram, to\'lov va CRM', btn: false, load: loadIntegrations },
    'tab-analytics':    { title: 'Analitika', sub: 'Javob vaqti, eskalatsiya va konversiya', btn: false, load: loadAnalytics },
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
                if (typeof meta.load === 'function') meta.load();
            }

            if (targetTab === 'tab-products') {
                showCategoriesView();
            }
        });
    });
}

function switchToTab(targetTab) {
    const navItem = document.querySelector(`.nav-item[data-tab="${targetTab}"]`);
    if (navItem) {
        navItem.click();
    }
}

// Load Categories
async function loadCategories() {
    try {
        const resp = await fetch('/api/admin/categories');
        currentCategories = await resp.json();

        renderCategoriesGrid();
        populateCategoryDropdown();
    } catch (e) {
        console.error('Kategoriyalarni yuklashda xatolik:', e);
    }
}

function getCategorySvgIcon(iconEmoji, catName) {
    const nameLower = (catName || '').toLowerCase();
    if (nameLower.includes('smart') || nameLower.includes('telefon')) {
        return `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect><line x1="12" y1="18" x2="12.01" y2="18"></line></svg>`;
    }
    if (nameLower.includes('noutbuk') || nameLower.includes('kompyuter')) {
        return `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="2" y1="20" x2="22" y2="20"></line></svg>`;
    }
    if (nameLower.includes('akses') || nameLower.includes('quloq')) {
        return `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18v-6a9 9 0 0 1 18 0v6"></path><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"></path></svg>`;
    }
    if (nameLower.includes('soat') || nameLower.includes('watch')) {
        return `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="7"></circle><polyline points="12 9 12 12 13.5 13.5"></polyline><path d="M16.51 17.35l-.85 3.83a2 2 0 0 1-1.96 1.57h-3.4a2 2 0 0 1-1.96-1.57l-.85-3.83M16.51 6.65l-.85-3.83A2 2 0 0 0 12.8 1.25h-3.4a2 2 0 0 0-1.96 1.57l-.85 3.83"></path></svg>`;
    }
    if (nameLower.includes('televizor') || nameLower.includes('texnika')) {
        return `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="15" rx="2" ry="2"></rect><polyline points="17 2 12 7 7 2"></polyline></svg>`;
    }
    return `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>`;
}

function getCategoryColorTheme(catName, index) {
    const themes = [
        { bg: 'rgba(2, 132, 199, 0.1)', border: 'rgba(2, 132, 199, 0.25)', color: '#0284c7' },  // Blue
        { bg: 'rgba(217, 119, 6, 0.1)', border: 'rgba(217, 119, 6, 0.25)', color: '#d97706' },   // Amber
        { bg: 'rgba(126, 34, 206, 0.1)', border: 'rgba(126, 34, 206, 0.25)', color: '#7e22ce' }, // Purple
        { bg: 'rgba(5, 150, 105, 0.1)', border: 'rgba(5, 150, 105, 0.25)', color: '#059669' },   // Emerald Green
        { bg: 'rgba(225, 29, 72, 0.1)', border: 'rgba(225, 29, 72, 0.25)', color: '#e11d48' }    // Rose / Red
    ];
    
    const nameLower = (catName || '').toLowerCase();
    if (nameLower.includes('smart') || nameLower.includes('telefon')) return themes[0];
    if (nameLower.includes('noutbuk') || nameLower.includes('kompyuter')) return themes[3];
    if (nameLower.includes('akses') || nameLower.includes('quloq')) return themes[1];
    if (nameLower.includes('soat') || nameLower.includes('watch')) return themes[2];
    
    return themes[index % themes.length];
}

function getCategoryRealImage(cat) {
    if (cat && cat.image_url && cat.image_url.trim().length > 0) {
        return cat.image_url;
    }
    
    const nameLower = ((cat && cat.name) || '').toLowerCase();
    if (nameLower.includes('smart') || nameLower.includes('telefon')) {
        return 'https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=300&auto=format&fit=crop&q=80';
    }
    if (nameLower.includes('noutbuk') || nameLower.includes('kompyuter')) {
        return 'https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=300&auto=format&fit=crop&q=80';
    }
    if (nameLower.includes('akses') || nameLower.includes('quloq')) {
        return 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=300&auto=format&fit=crop&q=80';
    }
    if (nameLower.includes('soat') || nameLower.includes('watch')) {
        return 'https://images.unsplash.com/photo-1508685096489-7aacd43bd3b1?w=300&auto=format&fit=crop&q=80';
    }
    if (nameLower.includes('televizor') || nameLower.includes('texnika')) {
        return 'https://images.unsplash.com/photo-1593359677879-a4bb92f829d1?w=300&auto=format&fit=crop&q=80';
    }
    return 'https://images.unsplash.com/photo-1526738549149-8e07eca6c147?w=300&auto=format&fit=crop&q=80';
}

function renderCategoriesGrid() {
    const grid = document.getElementById('categories-cards-grid');
    if (!grid) return;

    grid.innerHTML = '';
    const badge = document.getElementById('categories-count-text');
    if (badge) {
        badge.textContent = `${currentCategories.length} ta kategoriya`;
    }

    currentCategories.forEach((cat, idx) => {
        const pCount = cat.product_count || 0;
        const card = document.createElement('div');
        card.className = 'category-card';
        
        card.onclick = (e) => {
            if (e.target.closest('.btn-delete-cat-icon') || e.target.closest('.btn-edit-cat-icon')) return;
            openCategoryProducts(cat.name);
        };

        const theme = getCategoryColorTheme(cat.name, idx);
        const realImgUrl = getCategoryRealImage(cat);
        const avatarHtml = `<img src="${realImgUrl}" alt="${cat.name}" style="width: 100%; height: 100%; object-fit: cover; border-radius: 10px;">`;

        card.innerHTML = `
            <div class="category-card-header">
                <div class="category-icon-wrapper" style="background: ${theme.bg}; border: 1px solid ${theme.border}; color: ${theme.color}; overflow: hidden; padding: 0;">
                    ${avatarHtml}
                </div>
                <div class="category-card-header-right">
                    <span class="category-count-pill" style="background: ${theme.bg}; border: 1px solid ${theme.border}; color: ${theme.color};">
                        ${pCount} ta mahsulot
                    </span>
                    <button class="btn-edit-cat-icon" onclick="openEditCategoryModal('${cat.id}', event)" title="Tahrirlash">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 20h9"></path>
                            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                        </svg>
                    </button>
                    <button class="btn-delete-cat-icon" onclick="deleteCategory('${cat.id}', '${cat.name}', event)" title="O'chirish">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            </div>
            
            <div class="category-card-body">
                <h4 class="category-card-title">${cat.name}</h4>
            </div>

            <div class="category-card-footer" style="color: ${theme.color};">
                <span>Mahsulotlarni ko'rish</span>
                <span class="arrow">→</span>
            </div>
        `;
        grid.appendChild(card);
    });
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
        if (mode === 'edit') {
            await fetch(`/api/admin/categories/${catId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } else {
            await fetch('/api/admin/categories', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }
        closeCategoryModal();
        loadCategories();
    } catch (e) {
        console.error('Kategoriyani saqlashda xatolik:', e);
        alert('Kategoriyani saqlashda xatolik yuz berdi!');
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

function showCategoriesView() {
    selectedCategoryFilter = null;
    document.querySelector('.top-header').style.display = 'flex';
    document.getElementById('header-action-group').style.display = 'flex';
    document.getElementById('categories-view').style.display = 'block';
    document.getElementById('category-products-view').style.display = 'none';
    loadCategories();
}

function openCategoryProducts(categoryName) {
    selectedCategoryFilter = categoryName;
    document.querySelector('.top-header').style.display = 'none';
    document.getElementById('header-action-group').style.display = 'none';
    document.getElementById('categories-view').style.display = 'none';
    document.getElementById('category-products-view').style.display = 'block';
    document.getElementById('current-category-title').textContent = categoryName;
    
    // Update button text to reflect current category
    const addBtn = document.getElementById('btn-add-product-in-category');
    if (addBtn) {
        addBtn.innerHTML = `<span>+</span> Mahsulot Qo'shish`;
    }

    renderFilteredProducts();
}

// Add Product specifically inside current open category
function openAddProductModalForCurrentCategory() {
    openAddProductModal();
    if (selectedCategoryFilter) {
        const catSelect = document.getElementById('prod-category');
        if (catSelect) {
            catSelect.value = selectedCategoryFilter;
        }
    }
}

// Add / Delete Category Modal Handlers
function openAddCategoryModal() {
    document.getElementById('cat-name').value = '';
    document.getElementById('category-modal').style.display = 'flex';
}

function closeCategoryModal() {
    document.getElementById('category-modal').style.display = 'none';
}

async function saveCategoryForm() {
    const name = document.getElementById('cat-name').value.trim();
    const icon = document.getElementById('cat-icon').value;

    if (!name) {
        alert('Iltimos, kategoriya nomini kiriting!');
        return;
    }

    const newCat = {
        id: 'cat-' + Date.now(),
        name: name,
        icon: icon,
        product_count: 0
    };

    try {
        await fetch('/api/admin/categories', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newCat)
        });

        closeCategoryModal();
        loadCategories();
    } catch (e) {
        console.error('Kategoriyani saqlashda xatolik:', e);
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
function kpiCard(icon, color, label, value, hint) {
    return `<div class="kpi-card">
        <div class="kpi-icon" style="background:${color}1a; color:${color};">${icon}</div>
        <div class="kpi-body">
            <span class="kpi-label">${label}</span>
            <h3 class="kpi-value">${value}</h3>
            ${hint ? `<span class="kpi-hint">${hint}</span>` : ''}
        </div>
    </div>`;
}

async function loadDashboardStats() {
    try {
        const [statsResp, anResp] = await Promise.all([
            fetch('/api/admin/stats'),
            fetch('/api/admin/analytics')
        ]);
        const data = await statsResp.json();
        const an = await anResp.json();

        document.getElementById('dashboard-kpis').innerHTML =
            kpiCard('💰', '#00b87c', 'Jami tushum', data.total_revenue.toLocaleString() + ' UZS', null) +
            kpiCard('🧾', '#06b6d4', 'Buyurtmalar', data.total_orders, null) +
            kpiCard('💬', '#f59e0b', 'Suhbatlar', an.total_conversations, an.total_messages + ' xabar') +
            kpiCard('📈', '#a855f7', 'Konversiya', an.conversion_rate + '%', 'suhbat → buyurtma') +
            kpiCard('⚡️', '#0ea5e9', "O'rtacha javob", an.avg_latency_ms + ' ms', null) +
            kpiCard('🙋', '#e11d48', 'Eskalatsiya', an.escalation_rate + '%', 'operatorga uzatildi');

        renderRecentOrders(data.recent_orders);
    } catch (e) {
        console.error('Stats yuklashda xatolik:', e);
    }
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
        tr.innerHTML = `
            <td><code>${o.id}</code></td>
            <td><strong>${o.customer_name}</strong></td>
            <td>${o.customer_phone}</td>
            <td>${o.total_amount.toLocaleString()} UZS</td>
            <td><span class="badge badge-${o.status.toLowerCase().replace("'", "")}">${o.status}</span></td>
            <td>${o.created_at}</td>
        `;
        tbody.appendChild(tr);
    });
}

// Load Products
async function loadProducts() {
    try {
        const resp = await fetch('/api/admin/products');
        currentProducts = await resp.json();

        if (selectedCategoryFilter) {
            renderFilteredProducts();
        }
    } catch (e) {
        console.error('Mahsulotlarni yuklashda xatolik:', e);
    }
}

function renderFilteredProducts() {
    const tbody = document.getElementById('products-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const filtered = selectedCategoryFilter 
        ? currentProducts.filter(p => p.category.toLowerCase() === selectedCategoryFilter.toLowerCase())
        : currentProducts;

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 36px;">Ushbu kategoriyada hali mahsulotlar mavjud emas. Yuqoridagi <strong>"+ ${selectedCategoryFilter} ga Mahsulot Qo'shish"</strong> tugmasini bosing!</td></tr>`;
        return;
    }

    filtered.forEach(p => {
        const imgSrc = (p.image_urls && p.image_urls.length > 0) ? p.image_urls[0] : (p.image_url || '/static/images/logo.svg');
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>
                <img src="${imgSrc}" alt="${p.name}" style="width: 44px; height: 44px; border-radius: 10px; object-fit: cover; border: 1px solid var(--card-border);">
            </td>
            <td><code>${p.id}</code></td>
            <td>
                <strong>${p.name}</strong>
                <p style="font-size: 11px; color: var(--text-muted); max-width: 260px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${p.description || ''}</p>
            </td>
            <td><strong>${p.price.toLocaleString()} ${p.currency}</strong></td>
            <td>${p.stock_quantity} ta</td>
            <td>
                <div style="display: flex; gap: 8px;">
                    <button onclick="openEditProductModal('${p.id}')" style="background: rgba(0, 245, 160, 0.15); border: 1px solid rgba(0, 245, 160, 0.3); color: #00F5A0; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600;">
                        ✏️ Tahrirlash
                    </button>
                    <button onclick="deleteProduct('${p.id}')" style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); color: #f87171; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600;">
                        🗑 O'chirish
                    </button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
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
        if (editMode === 'edit') {
            await fetch(`/api/admin/products/${productId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(productData)
            });
        } else {
            await fetch('/api/admin/products', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(productData)
            });
        }

        closeProductModal();
        await loadProducts();
        await loadCategories();

        if (selectedCategoryFilter) {
            renderFilteredProducts();
        }
    } catch (e) {
        console.error('Mahsulotni saqlashda xatolik:', e);
    }
}

async function deleteProduct(productId) {
    if (!confirm('Ushbu mahsulotni katalogdan o\'chirmoqchimisiz?')) return;
    try {
        await fetch(`/api/admin/products/${productId}`, { method: 'DELETE' });
        await loadProducts();
        await loadCategories();
        if (selectedCategoryFilter) {
            renderFilteredProducts();
        }
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

        // Build row HTML safely (no inline quotes inside template)
        tr.innerHTML = `
            <td><code>${o.id}</code></td>
            <td style="font-size: 12px; color: var(--text-muted);">${o.created_at}</td>
            <td><strong>${o.customer_name}</strong></td>
            <td>${o.customer_phone}</td>
            <td style="max-width: 220px; font-size: 13px;">${itemsStr}</td>
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

        const badge = document.getElementById('ai-provider-badge');
        if (badge) badge.textContent = 'Model: ' + hiddenSettings.model_name;
    } catch (e) {
        console.error('Sozlamalarni yuklashda xatolik:', e);
    }
}

async function saveSettings() {
    const gv = (id) => { const el = document.getElementById(id); return el ? el.value : null; };
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
                greeting_message: gv('ai-greeting')
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
    const badge = document.getElementById('inbox-nav-badge');
    if (!badge) return;
    const waiting = (list || []).filter(c => c.waiting_for_operator).length;
    const unread = (list || []).reduce((n, c) => n + (c.unread_count || 0), 0);
    // Waiting-for-operator wins: it is the number someone must act on
    const count = waiting || unread;
    badge.textContent = count;
    badge.style.display = count > 0 ? 'inline-flex' : 'none';
    badge.classList.toggle('urgent', waiting > 0);
    lastWaitingCount = waiting;
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
        return `<div class="msg msg-${side} sender-${m.sender}">
            <div class="msg-who">${who}${meta}</div>
            <div class="msg-bubble">${escapeHtml(m.text).replace(/\n/g, '<br>')}</div>
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
                updateWaitingBadge(d.waiting);
            } catch (e) { /* offline; try again next tick */ }
        }
    }, 8000);
}

let lastWaitingCount = 0;
function updateWaitingBadge(waiting) {
    const badge = document.getElementById('inbox-nav-badge');
    if (badge && waiting > 0) {
        badge.textContent = waiting;
        badge.style.display = 'inline-flex';
        badge.classList.add('urgent');
    } else if (badge) {
        badge.classList.remove('urgent');
    }
    // Alert once per new escalation, not on every poll
    if (waiting > lastWaitingCount) {
        toast(`🔔 ${waiting} ta mijoz operator kutmoqda`);
    }
    lastWaitingCount = waiting;
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
// MIJOZLAR
// ════════════════════════════════════════════════════════
async function loadCustomers() {
    try {
        const resp = await fetch('/api/admin/customers');
        const list = await resp.json();
        const tbody = document.getElementById('customers-tbody');
        if (!list || list.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">Hali mijozlar yo'q — birinchi buyurtmadan keyin paydo bo'ladi.</td></tr>`;
            return;
        }
        tbody.innerHTML = list.map(c => `
            <tr>
                <td><strong>${escapeHtml(c.customer_name)}</strong></td>
                <td>${escapeHtml(c.customer_phone)}</td>
                <td>${c.order_count}</td>
                <td><strong>${c.ltv.toLocaleString()} UZS</strong></td>
                <td>${c.last_order_at || '—'}</td>
            </tr>`).join('');
    } catch (e) {
        console.error('Mijozlarni yuklashda xatolik:', e);
    }
}

// ════════════════════════════════════════════════════════
// INTEGRATSIYALAR — Telegram
// ════════════════════════════════════════════════════════
async function loadIntegrations() {
    loadOperatorPairing();
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
async function loadAnalytics() {
    try {
        const resp = await fetch('/api/admin/analytics');
        const a = await resp.json();

        document.getElementById('analytics-metrics').innerHTML =
            kpiCard('💬', '#00b87c', 'Suhbatlar', a.total_conversations, a.total_messages + ' xabar') +
            kpiCard('⚡️', '#0ea5e9', "O'rtacha javob vaqti", a.avg_latency_ms + ' ms', null) +
            kpiCard('🙋', '#e11d48', 'Eskalatsiya', a.escalation_rate + '%', 'operatorga uzatildi') +
            kpiCard('📈', '#a855f7', 'Savdo konversiyasi', a.conversion_rate + '%', a.order_count + ' buyurtma') +
            kpiCard('🎫', '#f59e0b', 'Token sarfi', a.total_tokens.toLocaleString(), 'tannarx hisobi uchun') +
            kpiCard('💰', '#06b6d4', 'Tushum', a.revenue.toLocaleString() + ' UZS', null);

        const total = Math.max(a.total_conversations, 1);
        const bar = (label, val, color) => `
            <div class="stat-bar-row">
                <span class="stat-bar-label">${label}</span>
                <div class="stat-bar-track"><div class="stat-bar-fill" style="width:${(val / total * 100).toFixed(1)}%; background:${color};"></div></div>
                <span class="stat-bar-val">${val}</span>
            </div>`;
        document.getElementById('analytics-status-bars').innerHTML =
            bar('🤖 AI', a.by_status.ai, '#00b87c') +
            bar('👨‍💼 Operator', a.by_status.operator, '#f59e0b') +
            bar('✅ Yopilgan', a.by_status.closed, '#64748b');
    } catch (e) {
        console.error('Analitikani yuklashda xatolik:', e);
    }
}

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
