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
        'tab-products': { title: 'Mahsulotlar Katalogi', sub: "Kategoriyalar va ombordagi mahsulotlar ro'yxati", btn: true },
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

function renderCategoriesGrid() {
    const grid = document.getElementById('categories-cards-grid');
    if (!grid) return;

    grid.innerHTML = '';
    document.getElementById('categories-count-text').textContent = `${currentCategories.length} ta kategoriya`;

    currentCategories.forEach(cat => {
        const pCount = cat.product_count || 0;
        const card = document.createElement('div');
        card.className = 'category-card';
        
        card.onclick = (e) => {
            if (e.target.closest('.btn-delete-cat-icon')) return;
            openCategoryProducts(cat.name);
        };

        card.innerHTML = `
            <div class="category-card-header">
                <div class="category-icon-wrapper">${cat.icon || '📁'}</div>
                <button class="btn-delete-cat-icon" onclick="deleteCategory('${cat.id}', '${cat.name}', event)" title="Kategoriyani o'chirish">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
            
            <div class="category-card-body">
                <h4 class="category-card-title">${cat.name}</h4>
                <span class="category-count-pill">${pCount} ta mahsulot</span>
            </div>

            <div class="category-card-footer">
                <span>Mahsulotlarni ko'rish</span>
                <span class="arrow">→</span>
            </div>
        `;
        grid.appendChild(card);
    });
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
    const canvas = document.getElementById('revenueChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    const gradient = ctx.createLinearGradient(0, 0, 0, 200);
    gradient.addColorStop(0, 'rgba(0, 245, 160, 0.35)');
    gradient.addColorStop(1, 'rgba(0, 245, 160, 0.0)');

    if (revenueChartInstance) {
        revenueChartInstance.destroy();
    }

    revenueChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Kunlik Tushum (UZS)',
                data: values,
                borderColor: '#00F5A0',
                borderWidth: 3.5,
                backgroundColor: gradient,
                fill: true,
                tension: 0.42,
                pointBackgroundColor: '#00F5A0',
                pointBorderColor: '#070A11',
                pointBorderWidth: 2,
                pointRadius: 5,
                pointHoverRadius: 9,
                pointHoverBackgroundColor: '#FFFFFF',
                pointHoverBorderColor: '#00F5A0',
                pointHoverBorderWidth: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(11, 16, 26, 0.95)',
                    titleColor: '#94a3b8',
                    bodyColor: '#00F5A0',
                    bodyFont: { weight: 'bold', size: 14 },
                    borderColor: 'rgba(0, 245, 160, 0.3)',
                    borderWidth: 1,
                    padding: 12,
                    displayColors: false,
                    callbacks: {
                        label: function(context) {
                            return 'Kunlik Tushum: ' + context.parsed.y.toLocaleString() + ' UZS';
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)', drawBorder: false },
                    ticks: { color: '#64748b', font: { size: 12, weight: '600' } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)', drawBorder: false },
                    ticks: {
                        color: '#64748b',
                        font: { size: 11 },
                        callback: function(value) {
                            if (value >= 1000000) return (value / 1000000) + ' mln';
                            if (value >= 1000) return (value / 1000) + ' ming';
                            return value;
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

// Load Orders
async function loadOrders() {
    try {
        const resp = await fetch('/api/admin/orders');
        const orders = await resp.json();

        const tbody = document.getElementById('orders-tbody');
        tbody.innerHTML = '';

        orders.forEach(o => {
            const itemsStr = o.items.map(i => `${i.product_name} (${i.quantity}x)`).join(', ');
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><code>${o.id}</code></td>
                <td><strong>${o.customer_name}</strong></td>
                <td>${o.customer_phone}</td>
                <td style="max-width: 200px;">${itemsStr}</td>
                <td><strong>${o.total_amount.toLocaleString()} UZS</strong></td>
                <td>
                    <select onchange="updateOrderStatus('${o.id}', this.value)" style="background: rgba(255,255,255,0.05); color: #fff; border: 1px solid var(--card-border); padding: 4px 8px; border-radius: 6px;">
                        <option value="Yangi" ${o.status==='Yangi'?'selected':''}>Yangi</option>
                        <option value="Tasdiqlandi" ${o.status==='Tasdiqlandi'?'selected':''}>Tasdiqlandi</option>
                        <option value="Yo'lda" ${o.status==="Yo'lda"?'selected':''}>Yo'lda</option>
                        <option value="Yetkazildi" ${o.status==='Yetkazildi'?'selected':''}>Yetkazildi</option>
                        <option value="Bekor qilindi" ${o.status==='Bekor qilindi'?'selected':''}>Bekor qilindi</option>
                    </select>
                </td>
                <td>
                    <span style="font-size: 11px; color: var(--text-dim);">${o.created_at}</span>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error('Buyurtmalarni yuklashda xatolik:', e);
    }
}

async function updateOrderStatus(orderId, newStatus) {
    try {
        await fetch(`/api/admin/orders/${orderId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        loadDashboardStats();
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
