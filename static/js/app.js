// Sotuvchi AI - Dashboard, Categories & Product Engine Logic

let revenueChartInstance = null;
let currentProducts = [];
let currentCategories = [];
let selectedCategoryFilter = null;
let modalImages = []; 
let activeImageIndex = 0;

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    loadDashboardStats();
    loadCategories();
    loadProducts();
    loadOrders();
    loadSettings();
});

// Navigation Tabs
function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const tabViews = document.querySelectorAll('.tab-view');
    const headerTitle = document.getElementById('page-title');
    const headerSubtitle = document.getElementById('page-subtitle');
    const headerActionGroup = document.getElementById('header-action-group');

    const titles = {
        'tab-overview': { title: 'Boshqaruv Paneli', sub: "Haftalik sotuv ko'rsatkichlari va tushum dinamikasi", btn: false },
        'tab-products': { title: 'Mahsulot Kategoriyalari', sub: "Kategoriyalar va ombordagi mahsulotlar ro'yxati", btn: true },
        'tab-orders': { title: 'Buyurtmalar', sub: "Mijozlar tomonidan berilgan barcha buyurtmalar", btn: false },
        'tab-settings': { title: 'AI Sozlamalari', sub: "AI sotuvchining xarakteri va provider sozlamalari", btn: false }
    };

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.getAttribute('data-tab');

            navItems.forEach(i => i.classList.remove('active'));
            tabViews.forEach(v => v.classList.remove('active'));

            item.classList.add('active');
            document.getElementById(targetTab).classList.add('active');

            if (titles[targetTab]) {
                document.querySelector('.top-header').style.display = 'flex';
                headerTitle.textContent = titles[targetTab].title;
                headerSubtitle.textContent = titles[targetTab].sub;
                headerActionGroup.style.display = titles[targetTab].btn ? 'flex' : 'none';
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

// Load Dashboard Stats & Render Chart
async function loadDashboardStats() {
    try {
        const resp = await fetch('/api/admin/stats');
        const data = await resp.json();

        document.getElementById('stat-revenue').textContent = data.total_revenue.toLocaleString() + ' UZS';
        document.getElementById('stat-orders').textContent = data.total_orders;
        document.getElementById('stat-leads').textContent = data.active_leads;
        document.getElementById('stat-conversion').textContent = data.conversion_rate + '%';

        renderRecentOrders(data.recent_orders);
        renderRevenueChart(data.weekly_labels, data.weekly_sales);
    } catch (e) {
        console.error('Stats yuklashda xatolik:', e);
    }
}

function renderRevenueChart(labels, values) {
    if (typeof Chart === 'undefined') {
        console.warn('Chart.js CDN hali yuklanmagan yoki bloklangan.');
        return;
    }
    const canvas = document.getElementById('revenueChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, 200);
    gradient.addColorStop(0, 'rgba(0, 184, 124, 0.35)');
    gradient.addColorStop(1, 'rgba(0, 184, 124, 0.01)');

    if (revenueChartInstance) {
        revenueChartInstance.destroy();
    }

    revenueChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: "Kunlik Tushum (UZS)",
                data: values,
                borderColor: '#00b87c',
                borderWidth: 3,
                pointBackgroundColor: '#00b87c',
                pointBorderColor: '#ffffff',
                pointBorderWidth: 2,
                pointRadius: 5,
                pointHoverRadius: 7,
                fill: true,
                backgroundColor: gradient,
                tension: 0.35
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#0f172a',
                    titleColor: '#ffffff',
                    bodyColor: '#00b87c',
                    padding: 12,
                    displayColors: false,
                    callbacks: {
                        label: function(context) {
                            return `${context.parsed.y.toLocaleString()} UZS`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#64748b', font: { family: 'Plus Jakarta Sans', size: 12, weight: '600' } }
                },
                y: {
                    grid: { color: '#e2e8f0' },
                    ticks: {
                        color: '#64748b',
                        font: { family: 'Plus Jakarta Sans', size: 11 },
                        callback: function(val) {
                            if (val >= 1000000) return (val / 1000000) + ' mln';
                            if (val >= 1000) return (val / 1000) + ' ming';
                            return val;
                        }
                    }
                }
            }
        }
    });
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

// Load Settings
async function loadSettings() {
    try {
        const resp = await fetch('/api/admin/settings');
        const data = await resp.json();

        document.getElementById('setting-provider').value = data.ai_provider;
        document.getElementById('setting-prompt').value = data.system_prompt;
        document.getElementById('ai-provider-badge').textContent = 'Model: ' + data.ai_provider.toUpperCase();
    } catch (e) {
        console.error('Sozlamalarni yuklashda xatolik:', e);
    }
}

async function saveSettings() {
    const provider = document.getElementById('setting-provider').value;
    const prompt = document.getElementById('setting-prompt').value;

    try {
        await fetch('/api/admin/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ai_provider: provider,
                system_prompt: prompt,
                model_name: 'gemini-2.5-flash'
            })
        });

        alert('Sozlamalar saqlandi!');
        loadSettings();
    } catch (e) {
        console.error('Saqlashda xatolik:', e);
    }
}
