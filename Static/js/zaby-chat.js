/**
 * Zaby Chat Widget — client-side logic
 * Communicates with Flask proxy endpoints:
 *   POST /api/zaby/token   → get disposable runtime token
 *   POST /api/zaby/run     → start an agent run
 *   GET  /api/zaby/stream/<run_id> → SSE stream of agent response
 */
(function () {
    'use strict';

    // ── State ──
    let runtimeToken = null;
    let isOpen = false;
    let isStreaming = false;
    let currentEventSource = null;

    // ── DOM refs (set on init) ──
    let fab, panel, messagesEl, inputEl, sendBtn;

    // ── Init ──
    document.addEventListener('DOMContentLoaded', function () {
        fab = document.getElementById('zaby-fab');
        panel = document.getElementById('zaby-chat-panel');
        messagesEl = document.getElementById('zaby-chat-messages');
        inputEl = document.getElementById('zaby-chat-input');
        sendBtn = document.getElementById('zaby-chat-send');

        if (!fab || !panel) return;

        fab.addEventListener('click', togglePanel);
        sendBtn.addEventListener('click', handleSend);

        // Close button in header
        var closeBtn = document.getElementById('zaby-close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', function () {
                if (isOpen) togglePanel();
            });
        }

        // Textarea auto-resize + send button active state
        inputEl.addEventListener('input', function () {
            autoResizeTextarea();
            updateSendButtonState();
        });

        inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
            }
        });

        // Add listeners for quick action cards
        var quickCards = document.querySelectorAll('.zaby-quick-card');
        quickCards.forEach(function (card) {
            card.addEventListener('click', function () {
                var query = this.getAttribute('data-query');
                if (query) {
                    inputEl.value = query;
                    autoResizeTextarea();
                    handleSend();
                }
            });
        });
    });

    function autoResizeTextarea() {
        if (!inputEl) return;
        inputEl.style.height = '40px'; // Reset
        var newHeight = Math.min(inputEl.scrollHeight, 120);
        inputEl.style.height = newHeight + 'px';
    }

    function updateSendButtonState() {
        if (!sendBtn || !inputEl) return;
        var hasText = inputEl.value.trim().length > 0;
        if (hasText && !isStreaming) {
            sendBtn.classList.add('active');
            sendBtn.disabled = false;
        } else {
            sendBtn.classList.remove('active');
            sendBtn.disabled = true;
        }
    }

    // ── Toggle chat panel ──
    function togglePanel() {
        isOpen = !isOpen;
        panel.classList.toggle('visible', isOpen);
        fab.classList.toggle('open', isOpen);
        
        // Trigger bump animation
        fab.classList.remove('bump');
        void fab.offsetWidth; // Force reflow
        fab.classList.add('bump');
        
        if (isOpen) {
            inputEl.focus();
        }
    }

    // ── Send message ──
    async function handleSend() {
        const text = inputEl.value.trim();
        if (!text || isStreaming) return;

        appendMessage(text, 'user');
        inputEl.value = '';
        autoResizeTextarea();
        updateSendButtonState();

        try {
            // 1. Always acquire a fresh runtime token to prevent expiration or limit errors
            await acquireToken();

            // 2. Start a run
            isStreaming = true;
            setSendEnabled(false);
            showTyping();

            const runResp = await fetch('/api/zaby/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text, token: runtimeToken })
            });

            if (!runResp.ok) {
                const err = await runResp.json().catch(() => ({}));
                throw new Error(err.error || 'Failed to start agent run');
            }

            const runData = await runResp.json();
            const runId = runData.run_id;

            // 3. Stream the response
            streamResponse(runId);

        } catch (err) {
            hideTyping();
            appendError(err.message || 'Something went wrong');
            isStreaming = false;
            setSendEnabled(true);
        }
    }

    // ── Acquire runtime token ──
    async function acquireToken() {
        const resp = await fetch('/api/zaby/token', { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || 'Failed to get chat token');
        }
        const data = await resp.json();
        runtimeToken = data.token;
    }

    // ── Stream SSE response ──
    function streamResponse(runId) {
        const agentMsgEl = createAgentBubble();
        let fullText = '';

        const url = '/api/zaby/stream/' + encodeURIComponent(runId) + '?token=' + encodeURIComponent(runtimeToken || '');
        const es = new EventSource(url);
        currentEventSource = es;

        es.onmessage = function (e) {
            hideTyping();
            try {
                const data = JSON.parse(e.data);
                if (data.text) {
                    fullText += data.text;
                    agentMsgEl.textContent = fullText;
                    scrollToBottom();
                } else if (data.content) {
                    fullText += data.content;
                    agentMsgEl.textContent = fullText;
                    scrollToBottom();
                } else if (data.message) {
                    fullText += data.message;
                    agentMsgEl.textContent = fullText;
                    scrollToBottom();
                }
            } catch (_) {
                // Plain text event
                fullText += e.data;
                agentMsgEl.textContent = fullText;
                scrollToBottom();
            }
        };

        es.addEventListener('done', function () {
            cleanup();
        });

        es.addEventListener('error', function (e) {
            // EventSource fires 'error' when connection closes (normal end)
            if (es.readyState === EventSource.CLOSED) {
                cleanup();
            } else {
                hideTyping();
                if (!fullText) {
                    appendError('Connection to assistant lost');
                }
                cleanup();
            }
        });

        function cleanup() {
            es.close();
            currentEventSource = null;
            isStreaming = false;
            setSendEnabled(true);
            if (!fullText) {
                agentMsgEl.textContent = 'No response received.';
            } else {
                renderRichContent(agentMsgEl, fullText);
            }
            scrollToBottom();
        }
    }

    // ── Rich Component Renderers & Parsers ──
    function renderRichContent(agentMsgEl, fullText) {
        agentMsgEl.innerHTML = '';

        const productRegex = /<zaby-product\s+([^>]+)\s*\/?>/gi;
        const cartRegex = /<zaby-cart\s*\/?>/gi;
        const checkoutRegex = /<zaby-checkout(?:\s+([^>]+))?\s*\/?>/gi;
        const successRegex = /<zaby-success\s+([^>]+)\s*\/?>/gi;
        const compareRegex = /<zaby-compare\s+([^>]+)\s*\/?>/gi;
        const customizationRegex = /<zaby-customization\s+([^>]+)\s*\/?>/gi;
        const actionRegex = /<zaby-action\s+([^>]+)\s*\/?>/gi;

        let cleanText = fullText
            .replace(productRegex, '')
            .replace(cartRegex, '')
            .replace(checkoutRegex, '')
            .replace(successRegex, '')
            .replace(compareRegex, '')
            .replace(customizationRegex, '')
            .replace(actionRegex, '')
            .trim();

        const textNode = document.createElement('div');
        textNode.className = 'zaby-text-content';
        
        // Simple Markdown/Formatting parser
        let formattedText = cleanText
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/\n/g, '<br>');
        textNode.innerHTML = formattedText;
        agentMsgEl.appendChild(textNode);

        // 1. Render Products
        let productMatch;
        productRegex.lastIndex = 0;
        let renderedProducts = false;
        while ((productMatch = productRegex.exec(fullText)) !== null) {
            const attrs = parseAttributes(productMatch[1]);
            renderProductWidget(agentMsgEl, attrs);
            renderedProducts = true;
        }

        // If no XML widgets were rendered at all, auto-detect mentioned products in the text
        if (!renderedProducts && !/<zaby-/i.test(fullText)) {
            const allProducts = [
                "Chicken Pickle", "Fish Pickle", "Gongura Mutton", "Mutton Pickle", "Gongura Prawns",
                "Chicken Pickle (Gongura)", "Spicy Crab Pickle", "Tangy Prawn Pickle", "Boneless Keema Pickle", "Andhra Duck Pickle",
                "Traditional Mango Pickle", "Zesty Lemon Pickle", "Tomato Pickle", "Kakarakaya Pickle", "Chintakaya Pickle",
                "Spicy Pandu Mirchi", "Garlic Pickle", "Avakaya Ginger Pickle", "Amla Pickle", "Green Chili Pickle",
                "Banana Chips", "Crispy Aam-Papad", "Crispy Chekka Pakodi", "Boondhi Acchu", "Ragi Laddu",
                "Dry Fruit Laddu", "Spicy Murukku", "Sweet Jaggery Gavvalu", "Sesame Chikki", "Crispy Kumpolu"
            ];
            allProducts.forEach(name => {
                const escaped = name.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
                const regex = new RegExp('\\b' + escaped + '\\b', 'i');
                if (regex.test(fullText)) {
                    renderProductWidget(agentMsgEl, { id: name, name: name });
                }
            });
        }

        // 2. Render Cart
        if (cartRegex.test(fullText)) {
            renderCartWidget(agentMsgEl);
        }

        // 3. Render Checkout Form
        checkoutRegex.lastIndex = 0;
        const checkoutMatch = checkoutRegex.exec(fullText);
        if (checkoutMatch) {
            const attrs = parseAttributes(checkoutMatch[1] || '');
            renderCheckoutWidget(agentMsgEl, attrs);
        }

        // 4. Render Success Card
        successRegex.lastIndex = 0;
        const successMatch = successRegex.exec(fullText);
        if (successMatch) {
            const attrs = parseAttributes(successMatch[1]);
            renderSuccessWidget(agentMsgEl, attrs);
        }

        // 5. Render Comparison Grid
        compareRegex.lastIndex = 0;
        let compareMatch;
        while ((compareMatch = compareRegex.exec(fullText)) !== null) {
            const attrs = parseAttributes(compareMatch[1]);
            renderCompareWidget(agentMsgEl, attrs);
        }

        // 6. Render Customization Panel
        customizationRegex.lastIndex = 0;
        let customizationMatch;
        while ((customizationMatch = customizationRegex.exec(fullText)) !== null) {
            const attrs = parseAttributes(customizationMatch[1]);
            renderCustomizationWidget(agentMsgEl, attrs);
        }

        // 7. Execute Agent Actions
        actionRegex.lastIndex = 0;
        let actionMatch;
        while ((actionMatch = actionRegex.exec(fullText)) !== null) {
            const attrs = parseAttributes(actionMatch[1]);
            executeActionWidget(agentMsgEl, attrs);
        }
    }

    function parseAttributes(attrString) {
        const attrs = {};
        const regex = /(\w+)="([^"]*)"|(\w+)='([^']*)'/g;
        let match;
        while ((match = regex.exec(attrString)) !== null) {
            const key = match[1] || match[3];
            const val = match[2] || match[4];
            attrs[key] = val;
        }
        return attrs;
    }

    function renderProductWidget(container, attrs) {
        const card = document.createElement('div');
        card.className = 'zaby-widget-product';
        container.appendChild(card);

        const id = attrs.id || attrs.product_id;
        
        let weights = {};
        try {
            weights = JSON.parse(attrs.weights || '{}');
        } catch (_) {}

        if (!attrs.name || attrs.name === 'Product' || !attrs.image || Object.keys(weights).length === 0) {
            fetch('/api/product/' + encodeURIComponent(id))
                .then(res => res.json())
                .then(data => {
                    if (data.error) {
                        card.textContent = 'Product not found.';
                        return;
                    }
                    buildProductCard(card, data.id, data.name, data.image, data.weights);
                })
                .catch(() => {
                    card.textContent = 'Error loading product details.';
                });
        } else {
            buildProductCard(card, id, attrs.name, attrs.image, weights);
        }
    }

    function buildProductCard(card, id, name, image, weights) {
        const img = document.createElement('img');
        img.src = image;
        img.alt = name;
        img.className = 'widget-product-img';
        card.appendChild(img);

        const title = document.createElement('div');
        title.className = 'widget-product-title';
        title.textContent = name;
        card.appendChild(title);

        const select = document.createElement('select');
        select.className = 'widget-product-select';
        select.id = 'widget-weight-' + id;
        for (const [wt, price] of Object.entries(weights)) {
            const opt = document.createElement('option');
            opt.value = price;
            opt.textContent = wt + 'g - ₹' + price;
            select.appendChild(opt);
        }
        card.appendChild(select);

        const btnRow = document.createElement('div');
        btnRow.className = 'widget-product-buttons';

        const addBtn = document.createElement('button');
        addBtn.className = 'btn-widget btn-add-cart';
        addBtn.textContent = 'Add to Cart';
        addBtn.onclick = function () {
            const price = select.value;
            const weight = select.options[select.selectedIndex].text.split('g')[0];
            let cart = JSON.parse(localStorage.getItem('cart') || '[]');
            cart.push({ name: name, price: price, weight: weight });
            localStorage.setItem('cart', JSON.stringify(cart));
            if (typeof updateCartCount === 'function') {
                updateCartCount();
            }
            addBtn.textContent = 'Added! ✓';
            addBtn.classList.add('added');
            setTimeout(function () {
                addBtn.textContent = 'Add to Cart';
                addBtn.classList.remove('added');
            }, 1500);
        };
        btnRow.appendChild(addBtn);

        const buyBtn = document.createElement('button');
        buyBtn.className = 'btn-widget btn-buy-now';
        buyBtn.textContent = 'Buy Now';
        buyBtn.onclick = function () {
            const price = select.value;
            const weight = select.options[select.selectedIndex].text.split('g')[0];
            let cart = [{ name: name, price: price, weight: weight }];
            localStorage.setItem('cart', JSON.stringify(cart));
            if (typeof updateCartCount === 'function') {
                updateCartCount();
            }
            inputEl.value = 'proceed to checkout';
            handleSend();
        };
        btnRow.appendChild(buyBtn);

        card.appendChild(btnRow);
        scrollToBottom();
    }

    function renderCompareWidget(container, attrs) {
        const card = document.createElement('div');
        card.className = 'zaby-widget-compare';
        container.appendChild(card);

        const id1 = attrs.product_id_1 || attrs.id1;
        const id2 = attrs.product_id_2 || attrs.id2;

        if (id1 && id2) {
            Promise.all([
                fetch('/api/product/' + id1).then(r => r.json()),
                fetch('/api/product/' + id2).then(r => r.json())
            ])
            .then(([item1, item2]) => {
                if (item1.error || item2.error) {
                    card.textContent = 'One or both products not found for comparison.';
                    return;
                }
                buildCompareCard(card, [item1, item2]);
            })
            .catch(() => {
                card.textContent = 'Error loading comparison details.';
            });
        } else {
            let items = [];
            try {
                items = JSON.parse(attrs.items || '[]');
            } catch (_) {
                try {
                    items = JSON.parse(attrs.items.replace(/'/g, '"'));
                } catch (__) {}
            }
            if (items && items.length > 0) {
                buildCompareCard(card, items);
            } else {
                card.textContent = 'No items specified for comparison.';
            }
        }
    }

    function buildCompareCard(card, items) {
        const title = document.createElement('div');
        title.className = 'widget-compare-title';
        title.textContent = '⚖️ Product Comparison';
        card.appendChild(title);

        const grid = document.createElement('div');
        grid.className = 'widget-compare-grid';

        items.forEach(function (item) {
            const col = document.createElement('div');
            col.className = 'widget-compare-col';

            let energyHtml = '';
            if (item.calories || item.protein || item.carbs || item.fat) {
                energyHtml = `
                    <div class="compare-spec nutrition-spec">🔥 <strong>Cal:</strong> ${item.calories || 'N/A'}</div>
                    <div class="compare-spec nutrition-spec">💪 <strong>Prot:</strong> ${item.protein || 'N/A'}</div>
                    <div class="compare-spec nutrition-spec">🌾 <strong>Carb:</strong> ${item.carbs || 'N/A'}</div>
                    <div class="compare-spec nutrition-spec">🥑 <strong>Fat:</strong> ${item.fat || 'N/A'}</div>
                `;
            }

            const sweetKeywords = ['laddu', 'papad', 'acchu', 'gavvalu', 'chikki'];
            const isSweet = sweetKeywords.some(kw => item.name.toLowerCase().includes(kw));

            let spiceOrSweetnessHtml = '';
            if (isSweet) {
                const sweetnessValue = item.sweetness || item.spice || 'Medium';
                spiceOrSweetnessHtml = `<div class="compare-spec"><strong>Sweetness:</strong> ${sweetnessValue}</div>`;
            } else {
                const spiceValue = item.spice || item.sweetness || 'Medium';
                spiceOrSweetnessHtml = `<div class="compare-spec"><strong>Spice:</strong> ${spiceValue}</div>`;
            }

            col.innerHTML = `
                <img class="compare-img" src="${item.image || '/static/images/default.jpg'}" alt="${item.name}">
                <div class="compare-name">${item.name}</div>
                ${spiceOrSweetnessHtml}
                <div class="compare-spec"><strong>Pairs:</strong> ${item.pairing || 'Meals'}</div>
                ${energyHtml}
                <div class="compare-price">₹${item.price || '200'}</div>
            `;

            const addBtn = document.createElement('button');
            addBtn.className = 'btn-widget btn-compare-add';
            addBtn.textContent = 'Add to Cart';
            addBtn.onclick = function () {
                let cart = JSON.parse(localStorage.getItem('cart') || '[]');
                cart.push({ name: item.name, price: item.price || 200, weight: '250' });
                localStorage.setItem('cart', JSON.stringify(cart));
                if (typeof updateCartCount === 'function') {
                    updateCartCount();
                }
                addBtn.textContent = 'Added ✓';
                addBtn.disabled = true;
            };
            col.appendChild(addBtn);
            grid.appendChild(col);
        });

        card.appendChild(grid);
        scrollToBottom();
    }

    function renderCustomizationWidget(container, attrs) {
        const card = document.createElement('div');
        card.className = 'zaby-widget-customization';
        container.appendChild(card);

        const id = attrs.id || attrs.product_id;

        if (!attrs.name || attrs.name === 'Product') {
            fetch('/api/product/' + id)
                .then(res => res.json())
                .then(data => {
                    if (data.error) {
                        card.textContent = 'Product not found.';
                        return;
                    }
                    buildCustomizationCard(card, data.id, data.name, data.image, data.price);
                })
                .catch(() => {
                    card.textContent = 'Error loading customizer.';
                });
        } else {
            buildCustomizationCard(card, id, attrs.name, attrs.image, attrs.price || '200');
        }
    }

    function buildCustomizationCard(card, id, name, image, price) {
        const basePrice = parseInt(price || '200');

        const sweetKeywords = ['laddu', 'papad', 'acchu', 'gavvalu', 'chikki'];
        const isSweet = sweetKeywords.some(kw => name.toLowerCase().includes(kw));

        let labelText = '🌶️ Custom Spice Level:';
        let sliderLabels = ['Mild', 'Medium', 'Spicy', 'Andhra'];
        let checkboxHtml = `
            <label class="customizer-checkbox-label">
                <input type="checkbox" id="extra-garlic-${id}">
                <span>Add Extra Garlic (+₹20)</span>
            </label>
            <label class="customizer-checkbox-label">
                <input type="checkbox" id="less-salt-${id}">
                <span>Low Salt (Free)</span>
            </label>
        `;

        if (isSweet) {
            labelText = '🍯 Custom Sweetness:';
            sliderLabels = ['Low Sugar', 'Medium', 'Sweet', 'Extra Sweet'];
            checkboxHtml = `
                <label class="customizer-checkbox-label">
                    <input type="checkbox" id="extra-ghee-${id}">
                    <span>Add Extra Ghee (+₹20)</span>
                </label>
                <label class="customizer-checkbox-label">
                    <input type="checkbox" id="less-sugar-${id}">
                    <span>Low Sugar (Free)</span>
                </label>
            `;
        }

        card.innerHTML = `
            <div class="customizer-header">
                <img src="${image}" alt="${name}" class="customizer-img">
                <div class="customizer-meta">
                    <div class="customizer-title">Custom Jar: ${name}</div>
                    <div class="customizer-price">Price: <strong id="custom-price-val-${id}">₹${basePrice}</strong></div>
                </div>
            </div>
            <div class="customizer-section">
                <label class="customizer-label">${labelText}</label>
                <input type="range" min="0" max="3" value="1" class="customizer-slider" id="spice-slider-${id}">
                <div class="customizer-slider-labels">
                    <span>${sliderLabels[0]}</span>
                    <span>${sliderLabels[1]}</span>
                    <span>${sliderLabels[2]}</span>
                    <span>${sliderLabels[3]}</span>
                </div>
            </div>
            <div class="customizer-section">
                <label class="customizer-label">✨ Custom Options:</label>
                <div class="customizer-options">
                    ${checkboxHtml}
                </div>
            </div>
        `;

        const slider = card.querySelector(`#spice-slider-${id}`);
        const primaryCheck = card.querySelector(isSweet ? `#extra-ghee-${id}` : `#extra-garlic-${id}`);
        const secondaryCheck = card.querySelector(isSweet ? `#less-sugar-${id}` : `#less-salt-${id}`);
        const priceText = card.querySelector(`#custom-price-val-${id}`);
        
        const levelNames = isSweet 
            ? ['Low Sugar', 'Medium Sweetness', 'Traditional Sweetness', 'Extra Sweet']
            : ['Mild', 'Medium', 'Spicy', 'Andhra Style'];

        function calculatePrice() {
            let price = basePrice;
            if (primaryCheck && primaryCheck.checked) price += 20;
            priceText.textContent = '₹' + price;
            return price;
        }

        if (primaryCheck) primaryCheck.onchange = calculatePrice;

        const addBtn = document.createElement('button');
        addBtn.className = 'btn-widget btn-customizer-add';
        addBtn.textContent = 'Add Custom jar';
        addBtn.onclick = function () {
            const finalPrice = calculatePrice();
            const level = levelNames[slider.value];
            let suffix = ` (${level}`;
            if (primaryCheck && primaryCheck.checked) suffix += isSweet ? ', Extra Ghee' : ', Extra Garlic';
            if (secondaryCheck && secondaryCheck.checked) suffix += isSweet ? ', Low Sugar' : ', Low Salt';
            suffix += ')';

            let cart = JSON.parse(localStorage.getItem('cart') || '[]');
            cart.push({ name: name + suffix, price: finalPrice, weight: '250' });
            localStorage.setItem('cart', JSON.stringify(cart));
            if (typeof updateCartCount === 'function') {
                updateCartCount();
            }
            addBtn.textContent = 'Custom Jar Added! ✓';
            addBtn.disabled = true;
        };

        card.appendChild(addBtn);
    }

    function executeActionWidget(container, attrs) {
        const type = attrs.type;
        const toast = document.createElement('div');
        toast.className = 'zaby-action-toast';

        if (type === 'remove-item') {
            const item = attrs.item || '';
            let cart = JSON.parse(localStorage.getItem('cart') || '[]');
            const index = cart.findIndex(i => i.name.toLowerCase().includes(item.toLowerCase()));
            if (index !== -1) {
                cart.splice(index, 1);
                localStorage.setItem('cart', JSON.stringify(cart));
                if (typeof updateCartCount === 'function') {
                    updateCartCount();
                }
                toast.textContent = `Removed "${item}" from cart ✓`;
            } else {
                toast.textContent = `Could not find "${item}" in cart`;
            }
        } else if (type === 'clear-cart') {
            localStorage.setItem('cart', '[]');
            if (typeof updateCartCount === 'function') {
                updateCartCount();
            }
            toast.textContent = `Cart emptied ✓`;
        } else if (type === 'apply-coupon') {
            const code = attrs.code || 'BOGO10';
            const discount = parseFloat(attrs.discount || 20);
            localStorage.setItem('coupon', JSON.stringify({ code: code, discount: discount }));
            toast.textContent = `Applied coupon ${code} (-₹${discount})! ✓`;
        }

        container.appendChild(toast);
    }

    function renderCartWidget(container) {
        const card = document.createElement('div');
        card.className = 'zaby-widget-cart';

        const cart = JSON.parse(localStorage.getItem('cart') || '[]');
        if (cart.length === 0) {
            card.innerHTML = '<div class="widget-cart-empty">Your cart is empty.</div>';
            container.appendChild(card);
            return;
        }

        const title = document.createElement('div');
        title.className = 'widget-cart-title';
        title.textContent = '🛍 Your Shopping Cart';
        card.appendChild(title);

        const listContainer = document.createElement('div');
        listContainer.className = 'widget-cart-items';

        let total = 0;
        cart.forEach(function (item, index) {
            const priceNum = parseFloat(item.price) || 0;
            total += priceNum;

            const row = document.createElement('div');
            row.className = 'widget-cart-row';

            const details = document.createElement('div');
            details.className = 'widget-cart-item-details';
            details.innerHTML = '<strong>' + item.name + '</strong> <span class="widget-item-meta">(' + item.weight + 'g)</span>';
            row.appendChild(details);

            const priceTag = document.createElement('div');
            priceTag.className = 'widget-cart-item-price';
            priceTag.textContent = '₹' + item.price;
            row.appendChild(priceTag);

            const removeBtn = document.createElement('button');
            removeBtn.className = 'widget-cart-remove';
            removeBtn.innerHTML = '✕';
            removeBtn.onclick = function () {
                cart.splice(index, 1);
                localStorage.setItem('cart', JSON.stringify(cart));
                if (typeof updateCartCount === 'function') {
                    updateCartCount();
                }
                renderCartWidget(container);
                card.remove();
            };
            row.appendChild(removeBtn);

            listContainer.appendChild(row);
        });
        card.appendChild(listContainer);

        const totalRow = document.createElement('div');
        totalRow.className = 'widget-cart-total';
        totalRow.innerHTML = '<span>Total:</span><strong>₹' + total + '</strong>';
        card.appendChild(totalRow);

        const checkBtn = document.createElement('button');
        checkBtn.className = 'btn-widget btn-cart-checkout';
        checkBtn.textContent = 'Proceed to Checkout';
        checkBtn.onclick = function () {
            inputEl.value = 'proceed to checkout';
            handleSend();
        };
        card.appendChild(checkBtn);

        container.appendChild(card);
    }

    function renderCheckoutWidget(container, attrs) {
        const card = document.createElement('div');
        card.className = 'zaby-widget-checkout';

        const cart = JSON.parse(localStorage.getItem('cart') || '[]');
        let total = 0;
        cart.forEach(function (item) {
            total += (parseFloat(item.price) || 0);
        });

        if (cart.length === 0) {
            card.innerHTML = '<div class="widget-cart-empty">Your cart is empty. Cannot checkout.</div>';
            container.appendChild(card);
            return;
        }

        const title = document.createElement('div');
        title.className = 'widget-checkout-title';
        title.textContent = '📝 Shipping & Checkout';
        card.appendChild(title);

        // Fetch user profile info for autofill
        fetch('/api/profile')
            .then(res => res.json())
            .then(profile => {
                if (profile.name || profile.phone || profile.address) {
                    const nameInput = card.querySelector('#chk-name');
                    const phoneInput = card.querySelector('#chk-phone');
                    const addressInput = card.querySelector('#chk-address');
                    if (nameInput && profile.name) nameInput.value = profile.name;
                    if (phoneInput && profile.phone) phoneInput.value = profile.phone;
                    if (addressInput && profile.address) addressInput.value = profile.address;

                    const badge = document.createElement('div');
                    badge.className = 'profile-autofill-badge';
                    badge.textContent = 'Saved profile pre-filled ✓';
                    card.insertBefore(badge, title.nextSibling);
                }
            })
            .catch(err => console.log('Profile prefetch failed:', err));

        // Deduct coupon discount if any
        let coupon = null;
        try {
            coupon = JSON.parse(localStorage.getItem('coupon') || 'null');
        } catch (_) {}
        let summaryHtml = '<span>Amount Due:</span><strong>₹' + total + '</strong>';
        if (coupon) {
            const discount = coupon.discount || 0;
            total = Math.max(0, total - discount);
            summaryHtml = '<span>Amount Due:</span><strong>₹' + total + '</strong><span class="checkout-discount-text"> (Coupon ' + coupon.code + ' applied: -₹' + discount + ')</span>';
        }

        const form = document.createElement('div');
        form.className = 'widget-checkout-form';
        form.innerHTML = 
            '<div class="form-group">' +
                '<label>Name</label>' +
                '<input type="text" id="chk-name" placeholder="John Doe" required />' +
            '</div>' +
            '<div class="form-group">' +
                '<label>Phone Number</label>' +
                '<input type="tel" id="chk-phone" placeholder="9876543210" required />' +
            '</div>' +
            '<div class="form-group">' +
                '<label>Delivery Address</label>' +
                '<textarea id="chk-address" placeholder="123 Main St, Hyderabad" rows="2" required></textarea>' +
            '</div>' +
            '<div class="widget-checkout-summary">' +
                summaryHtml +
            '</div>';
        card.appendChild(form);

        const errorEl = document.createElement('div');
        errorEl.className = 'widget-checkout-error';
        errorEl.style.display = 'none';
        card.appendChild(errorEl);

        const orderBtn = document.createElement('button');
        orderBtn.className = 'btn-widget btn-place-order';
        orderBtn.textContent = 'Confirm & Place Order';

        orderBtn.onclick = async function () {
            const name = document.getElementById('chk-name').value.trim();
            const phone = document.getElementById('chk-phone').value.trim();
            const address = document.getElementById('chk-address').value.trim();

            if (!name || !phone || !address) {
                errorEl.textContent = 'Please fill out all fields.';
                errorEl.style.display = 'block';
                return;
            }

            errorEl.style.display = 'none';
            orderBtn.disabled = true;
            orderBtn.textContent = 'Placing Order...';

            try {
                const resp = await fetch('/api/checkout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name,
                        phone: phone,
                        address: address,
                        cart_data: cart,
                        total_amount: total
                    })
                });

                if (!resp.ok) {
                    const err = await resp.json().catch(function () { return {}; });
                    throw new Error(err.error || 'Checkout failed');
                }

                const result = await resp.json();

                localStorage.setItem('cart', '[]');
                localStorage.removeItem('coupon');
                if (typeof updateCartCount === 'function') {
                    updateCartCount();
                }

                card.remove();
                renderSuccessWidget(container, {
                    orderId: result.order_id,
                    name: name,
                    total: total
                });

                inputEl.value = 'order placed successfully: ID ' + result.order_id + ' total ₹' + total;
                handleSend();

            } catch (e) {
                orderBtn.disabled = false;
                orderBtn.textContent = 'Confirm & Place Order';
                errorEl.textContent = e.message;
                errorEl.style.display = 'block';
            }
        };
        card.appendChild(orderBtn);

        container.appendChild(card);
    }

    function renderSuccessWidget(container, attrs) {
        const card = document.createElement('div');
        card.className = 'zaby-widget-success';
        card.innerHTML = 
            '<div class="success-icon">✓</div>' +
            '<div class="success-title">Order Placed Successfully!</div>' +
            '<div class="success-details">' +
                '<div><strong>Order ID:</strong> <span class="success-val">' + attrs.orderId + '</span></div>' +
                '<div><strong>Recipient:</strong> <span class="success-val">' + attrs.name + '</span></div>' +
                '<div><strong>Total:</strong> <span class="success-val">₹' + attrs.total + '</span></div>' +
            '</div>' +
            '<p class="success-meta">Thank you for shopping with Taste the Best! Your order will be dispatched shortly.</p>';
        container.appendChild(card);
    }


    // ── DOM helpers ──
    function appendMessage(text, role) {
        const div = document.createElement('div');
        div.className = 'zaby-msg ' + role;
        div.textContent = text;
        messagesEl.appendChild(div);
        scrollToBottom();
        // Remove welcome message & quick actions if present
        const welcome = messagesEl.querySelector('.zaby-welcome');
        if (welcome) welcome.remove();
        const quickActions = messagesEl.querySelector('.zaby-quick-actions');
        if (quickActions) quickActions.remove();
    }

    function createAgentBubble() {
        const row = document.createElement('div');
        row.className = 'zaby-agent-row';

        const avatar = document.createElement('div');
        avatar.className = 'zaby-agent-mini-avatar';
        row.appendChild(avatar);

        const contentDiv = document.createElement('div');
        contentDiv.className = 'zaby-agent-content';

        const msgDiv = document.createElement('div');
        msgDiv.className = 'zaby-msg agent';
        msgDiv.textContent = '';
        contentDiv.appendChild(msgDiv);

        const timeDiv = document.createElement('div');
        timeDiv.className = 'zaby-msg-timestamp';
        const now = new Date();
        let hours = now.getHours();
        let minutes = now.getMinutes();
        const ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12;
        hours = hours ? hours : 12;
        minutes = minutes < 10 ? '0' + minutes : minutes;
        timeDiv.textContent = `${hours}:${minutes} ${ampm}`;
        contentDiv.appendChild(timeDiv);

        row.appendChild(contentDiv);
        messagesEl.appendChild(row);

        scrollToBottom();
        return msgDiv;
    }

    function appendError(msg) {
        const div = document.createElement('div');
        div.className = 'zaby-error';
        div.textContent = '⚠ ' + msg;
        messagesEl.appendChild(div);
        scrollToBottom();
    }

    function showTyping() {
        if (document.getElementById('zaby-typing')) return;
        const div = document.createElement('div');
        div.className = 'zaby-typing';
        div.id = 'zaby-typing';
        div.innerHTML = '<span class="wave-particle wave-1"></span><span class="wave-particle wave-2"></span><span class="wave-particle wave-3"></span>';
        messagesEl.appendChild(div);
        scrollToBottom();
    }

    function hideTyping() {
        const el = document.getElementById('zaby-typing');
        if (el) el.remove();
    }

    function setSendEnabled(enabled) {
        sendBtn.disabled = !enabled;
        if (enabled && inputEl.value.trim().length > 0) {
            sendBtn.classList.add('active');
        } else {
            sendBtn.classList.remove('active');
        }
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }
})();
