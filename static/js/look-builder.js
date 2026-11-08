/**
 * TULSA BY ANJALI — INTERACTIVE VIRTUAL FITTING ROOM (Stage 3 Enhanced)
 * Fully interactive left-side dress preview with:
 * - Complete outfit visibility using object-fit: contain (no head/hem clipping)
 * - True vertical and trackpad/mouse-wheel scrolling in preview panel
 * - Previous/Next gallery exploration arrows (< and >)
 * - Gallery thumbnail/indicator pills with smooth transitions
 * - Zoom in (+), Zoom out (-), Reset (⟲), and Full/Scroll mode toggle
 * - Mouse drag to pan enlarged view, and touch swiping between authentic gallery photos
 * - Non-interfering wardrobe selection with active WEARING indicator preserved
 */

    const BASE_STATIC = (typeof window !== 'undefined' && window.location.protocol === 'file:') 
        ? '/Users/harsh/Documents/tulsa-preview-safe' 
        : '';

    function normalizeImgUrl(url) {
        if (!url) return '';
        if (BASE_STATIC && url.startsWith('/static/')) {
            return BASE_STATIC + url;
        }
        return url;
    }

    // Authentic Tulsa photoshoot gallery mappings for all 16 catalog silhouettes
    const PRODUCT_GALLERIES = {
        '1': [
            '/static/images/product-1.jpg',
            '/static/images/handcrafted-cotton-stole-detail.jpg'
        ],
        '2': [
            '/static/images/product-2.jpg',
            '/static/images/kurta-palazzo-category.jpg'
        ],
        '3': [
            '/static/images/product-3.jpg',
            '/static/images/salwar-kameez-category.jpg'
        ],
        '4': [
            '/static/images/prod_4_21d6b1.jpg',
            '/static/images/party-wear-category.jpg'
        ],
        '5': [
            '/static/images/prod_5_9cc749.png',
            '/static/images/wedding-regalia-category.jpg'
        ],
        '6': [
            '/static/images/garment-07.jpg',
            '/static/images/garment-08.jpg'
        ],
        '7': [
            '/static/images/garment-01.jpg',
            '/static/images/garment-02.jpg'
        ],
        '8': [
            '/static/images/garment-11.jpg',
            '/static/images/garment-12.jpg'
        ],
        '9': [
            '/static/images/garment-14.jpg',
            '/static/images/garment-13.jpg',
            '/static/images/garment-15.jpg'
        ],
        '10': [
            '/static/images/garment-03.jpg',
            '/static/images/garment-04.jpg'
        ],
        '11': [
            '/static/images/garment-16.jpg',
            '/static/images/garment-17.jpg',
            '/static/images/garment-18.jpg'
        ],
        '12': [
            '/static/images/garment-09.jpg',
            '/static/images/garment-10.jpg'
        ],
        '13': [
            '/static/images/garment-19.jpg',
            '/static/images/garment-20.jpg'
        ],
        '14': [
            '/static/images/garment-21.jpg',
            '/static/images/garment-22.jpg'
        ],
        '15': [
            '/static/images/garment-24.jpg',
            '/static/images/garment-23.jpg',
            '/static/images/garment-25.jpg'
        ],
        '16': [
            '/static/images/garment-27.jpg',
            '/static/images/garment-26.jpg'
        ]
    };

    document.addEventListener('DOMContentLoaded', () => {
        // --- PREVIEW PANEL ELEMENTS ---
        const stageImg = document.getElementById('fittingStageImg');
        const stageViewport = document.getElementById('fittingAvatarViewport');
        const stageCanvas = document.getElementById('fittingAvatarCanvas');
        const stageImgPrev = document.getElementById('stageImgPrev');
        const stageImgNext = document.getElementById('stageImgNext');
        const stageGalleryDots = document.getElementById('stageGalleryDots');

        // Zoom Controls
        const btnZoomIn = document.getElementById('btnZoomIn');
        const btnZoomOut = document.getElementById('btnZoomOut');
        const btnZoomReset = document.getElementById('btnZoomReset');
        const btnFitToggle = document.getElementById('btnFitToggle');

        // Specification & Metadata Elements
        const stageTitle = document.getElementById('fittingStageTitle');
        const stagePrice = document.getElementById('fittingStagePrice');
        const stageCategory = document.getElementById('fittingStageCategory');
        const stageSpecsCategory = document.getElementById('stageSpecsCategory');
        const stageDesc = document.getElementById('fittingStageDesc');
        const stageFabric = document.getElementById('fittingStageFabric');
        const stageColor = document.getElementById('fittingStageColor');
        const stageStock = document.getElementById('fittingStageStock');
        const stageAdvice = document.getElementById('fittingStageAdvice');
        const fittedBuyBtn = document.getElementById('fittedBuyBtn');
        const fittedBagBtn = document.getElementById('fittedBagBtn');
        const fittedViewBtn = document.getElementById('fittedViewBtn');

        // Controls
        const wardrobeCards = document.querySelectorAll('.wardrobe-item-card');
        const filterBtns = document.querySelectorAll('.wardrobe-filter-btn');
        const ambiencePills = document.querySelectorAll('.stage-ambience-pill');
        const anglePills = document.querySelectorAll('.stage-angle-pill');
        const sizePills = document.querySelectorAll('.fitted-size-btn');

        // --- STATE ---
        let currentGarment = null;
        let currentGallery = [];
        let currentImgIdx = 0;
        let selectedSize = 'M';
        let zoomScale = 1.0;
        let panX = 0;
        let panY = 0;
        let isPanning = false;
        let panStartX = 0;
        let panStartY = 0;
        let isScrollMode = false;

        // -------------------------------------------------------------
        // 1. ZOOM & PAN IMPLEMENTATION
        // -------------------------------------------------------------
        function applyImageTransform(animate = true) {
            if (!stageImg) return;
            if (animate) {
                stageImg.style.transition = 'transform 0.25s cubic-bezier(0.16, 1, 0.3, 1)';
            } else {
                stageImg.style.transition = 'none';
            }
            stageImg.style.transform = `scale(${zoomScale}) translate(${panX}px, ${panY}px)`;

            if (zoomScale > 1.0) {
                stageImg.style.cursor = isPanning ? 'grabbing' : 'grab';
                stageImg.classList.add('is-zoomed');
            } else {
                stageImg.style.cursor = 'default';
                stageImg.classList.remove('is-zoomed');
            }
        }

        function setZoom(newScale) {
            zoomScale = Math.min(3.0, Math.max(1.0, parseFloat(newScale.toFixed(2))));
            if (zoomScale <= 1.0) {
                panX = 0;
                panY = 0;
            }
            applyImageTransform(true);
        }

        function resetZoom() {
            zoomScale = 1.0;
            panX = 0;
            panY = 0;
            applyImageTransform(true);
        }

        if (btnZoomIn) {
            btnZoomIn.addEventListener('click', (e) => {
                e.preventDefault();
                setZoom(zoomScale + 0.35);
            });
        }

        if (btnZoomOut) {
            btnZoomOut.addEventListener('click', (e) => {
                e.preventDefault();
                setZoom(zoomScale - 0.35);
            });
        }

        if (btnZoomReset) {
            btnZoomReset.addEventListener('click', (e) => {
                e.preventDefault();
                resetZoom();
            });
        }

        if (btnFitToggle && stageViewport) {
            btnFitToggle.addEventListener('click', (e) => {
                e.preventDefault();
                isScrollMode = !isScrollMode;
                stageViewport.classList.toggle('mode-scroll', isScrollMode);
                btnFitToggle.textContent = isScrollMode ? '↕ Fit' : '⤢ Full';
                resetZoom();
            });
        }

        // Mouse Drag to Pan when Zoomed In
        if (stageCanvas) {
            stageCanvas.addEventListener('mousedown', (e) => {
                if (zoomScale <= 1.0) return;
                isPanning = true;
                panStartX = e.clientX - panX * zoomScale;
                panStartY = e.clientY - panY * zoomScale;
                stageImg.classList.add('is-dragging');
                e.preventDefault();
            });

            window.addEventListener('mousemove', (e) => {
                if (!isPanning) return;
                panX = (e.clientX - panStartX) / zoomScale;
                panY = (e.clientY - panStartY) / zoomScale;
                applyImageTransform(false);
            });

            window.addEventListener('mouseup', () => {
                if (isPanning) {
                    isPanning = false;
                    if (stageImg) stageImg.classList.remove('is-dragging');
                    applyImageTransform(true);
                }
            });

            // Trackpad Pinch / Mouse-Wheel Zoom
            stageCanvas.addEventListener('wheel', (e) => {
                if (e.ctrlKey || e.metaKey) {
                    e.preventDefault();
                    const delta = e.deltaY < 0 ? 0.15 : -0.15;
                    setZoom(zoomScale + delta);
                }
            }, { passive: false });
        }

        // -------------------------------------------------------------
        // 2. GALLERY NAVIGATION (<, >, DOTS, TRANSITIONS)
        // -------------------------------------------------------------
        function renderGalleryView(smooth = false) {
            if (!stageImg || currentGallery.length === 0) return;

            const targetSrcRaw = currentGallery[currentImgIdx] || (currentGarment ? currentGarment.img : '');
            if (!targetSrcRaw) return;
            const targetSrc = normalizeImgUrl(targetSrcRaw);

            if (smooth && stageImg.src && stageImg.getAttribute('src') !== targetSrc) {
                stageImg.style.opacity = '0.35';
                stageImg.src = targetSrc;
                setTimeout(() => {
                    if (stageImg) stageImg.style.opacity = '1';
                }, 70);
            } else {
                stageImg.src = targetSrc;
                stageImg.style.opacity = '1';
                resetZoom();
            }

            // Update Previous / Next Buttons
            if (stageImgPrev && stageImgNext) {
                if (currentGallery.length <= 1) {
                    stageImgPrev.classList.add('disabled');
                    stageImgNext.classList.add('disabled');
                } else {
                    stageImgPrev.classList.remove('disabled');
                    stageImgNext.classList.remove('disabled');
                }
            }

            // Update Indicator Dots / Pills
            if (stageGalleryDots) {
                stageGalleryDots.innerHTML = '';
                if (currentGallery.length > 1) {
                    currentGallery.forEach((src, idx) => {
                        const dot = document.createElement('button');
                        dot.type = 'button';
                        dot.className = `stage-gallery-dot ${idx === currentImgIdx ? 'active' : ''}`;
                        const labelText = idx === 0 ? 'Front' : (idx === 1 ? 'Drape Detail' : `View ${idx + 1}`);
                        dot.innerHTML = `<span class="dot-bullet"></span><span>${labelText}</span>`;
                        dot.addEventListener('click', (e) => {
                            e.preventDefault();
                            if (currentImgIdx !== idx) {
                                currentImgIdx = idx;
                                renderGalleryView(true);
                            }
                        });
                        stageGalleryDots.appendChild(dot);
                    });
                }
            }

            // Sync Drape Angle Pills if present
            anglePills.forEach(p => {
                const angle = p.dataset.angle;
                if ((angle === 'front' && currentImgIdx === 0) || (angle === 'drape' && currentImgIdx > 0)) {
                    p.classList.add('active');
                } else {
                    p.classList.remove('active');
                }
            });
        }

        function navigateGallery(direction) {
            if (currentGallery.length <= 1) return;
            currentImgIdx = (currentImgIdx + direction + currentGallery.length) % currentGallery.length;
            renderGalleryView(true);
        }

        if (stageImgPrev) {
            stageImgPrev.addEventListener('click', (e) => {
                e.preventDefault();
                navigateGallery(-1);
            });
        }

        if (stageImgNext) {
            stageImgNext.addEventListener('click', (e) => {
                e.preventDefault();
                navigateGallery(1);
            });
        }

        // Angle Pills Sync
        anglePills.forEach(pill => {
            pill.addEventListener('click', () => {
                anglePills.forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                const targetAngle = pill.dataset.angle || 'front';
                if (targetAngle === 'front') {
                    currentImgIdx = 0;
                } else if (currentGallery.length > 1) {
                    currentImgIdx = 1;
                }
                renderGalleryView(true);
            });
        });

        // Keyboard Navigation (Left / Right Arrows when over viewport)
        document.addEventListener('keydown', (e) => {
            if (!currentGarment) return;
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            if (e.key === 'ArrowLeft') {
                navigateGallery(-1);
            } else if (e.key === 'ArrowRight') {
                navigateGallery(1);
            }
        });

        // -------------------------------------------------------------
        // 3. TOUCH SWIPE & MOUSE SWIPE (Mobile and Desktop)
        // -------------------------------------------------------------
        if (stageViewport) {
            let touchStartX = 0;
            let touchStartY = 0;
            let touchStartTime = 0;

            stageViewport.addEventListener('touchstart', (e) => {
                if (e.touches.length === 1) {
                    touchStartX = e.touches[0].clientX;
                    touchStartY = e.touches[0].clientY;
                    touchStartTime = Date.now();
                }
            }, { passive: true });

            stageViewport.addEventListener('touchend', (e) => {
                if (zoomScale > 1.0) return; // Allow natural pinch/zoom pan
                if (e.changedTouches.length === 1) {
                    const deltaX = e.changedTouches[0].clientX - touchStartX;
                    const deltaY = e.changedTouches[0].clientY - touchStartY;
                    const elapsed = Date.now() - touchStartTime;

                    // If primarily horizontal and moved > 40px within 500ms
                    if (Math.abs(deltaX) > Math.abs(deltaY) * 1.4 && Math.abs(deltaX) > 40 && elapsed < 600) {
                        if (deltaX < 0) {
                            navigateGallery(1); // Swipe left -> Next image
                        } else {
                            navigateGallery(-1); // Swipe right -> Prev image
                        }
                    }
                }
            }, { passive: true });
        }

        // -------------------------------------------------------------
        // 4. STUDIO LIGHTING AMBIENCE SWITCHER
        // -------------------------------------------------------------
        ambiencePills.forEach(pill => {
            pill.addEventListener('click', () => {
                ambiencePills.forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                const mode = pill.dataset.ambience;

                if (!stageViewport) return;
                stageViewport.classList.remove('ambience-festive', 'ambience-candlelight');

                if (mode === 'festive') {
                    stageViewport.classList.add('ambience-festive');
                } else if (mode === 'candlelight') {
                    stageViewport.classList.add('ambience-candlelight');
                }
            });
        });

        // -------------------------------------------------------------
        // 5. SIZE SELECTOR
        // -------------------------------------------------------------
        sizePills.forEach(btn => {
            btn.addEventListener('click', () => {
                sizePills.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                selectedSize = btn.dataset.size || btn.textContent.trim();
            });
        });

        // -------------------------------------------------------------
        // 6. SINGLE SOURCE OF TRUTH: PRODUCT SELECTION ARCHITECTURE
        // -------------------------------------------------------------
        let selectedProductId = null;

        async function selectProduct(rawId, animate = false) {
            if (!rawId) return;
            const pid = String(rawId);
            selectedProductId = pid;

            // Find the corresponding card
            const targetCard = Array.from(wardrobeCards).find(c => String(c.dataset.id) === pid);
            if (!targetCard) return;

            // Extract authentic product details
            const productData = {
                id: pid,
                name: targetCard.dataset.name || '',
                price: targetCard.dataset.price || '',
                category: targetCard.dataset.category || '',
                fabric: targetCard.dataset.fabric || 'Pure Handloom Silk',
                color: targetCard.dataset.color || 'Artisanal Dye',
                desc: targetCard.dataset.desc || '',
                stock: targetCard.dataset.stock || '',
                img: targetCard.dataset.img || ''
            };

            currentGarment = productData;

            // Load authentic gallery photoshoot images
            if (PRODUCT_GALLERIES[pid] && PRODUCT_GALLERIES[pid].length > 0) {
                currentGallery = [...PRODUCT_GALLERIES[pid]];
            } else if (productData.img) {
                currentGallery = [productData.img];
            } else {
                currentGallery = ['/static/images/bridal-wedding-collection.jpg'];
            }
            currentImgIdx = 0;

            // Render gallery image on left preview immediately
            renderGalleryView(animate);

            // Update Metadata Texts
            if (stageTitle && productData.name) stageTitle.textContent = productData.name;
            if (stageCategory && productData.category) stageCategory.textContent = `${productData.category} • Hansi Atelier`;
            if (stageSpecsCategory && productData.category) stageSpecsCategory.textContent = productData.category;
            if (stagePrice && productData.price) {
                const p = String(productData.price);
                stagePrice.textContent = p.startsWith('₹') ? p : `₹${Number(p).toLocaleString('en-IN')}`;
            }
            if (stageFabric && productData.fabric) stageFabric.textContent = productData.fabric;
            if (stageColor && productData.color) stageColor.textContent = productData.color;
            if (stageStock && productData.stock) {
                stageStock.textContent = Number(productData.stock) > 0 ? `In Stock (${productData.stock} pieces)` : 'Made to Order';
            }
            if (stageDesc && productData.desc) stageDesc.textContent = productData.desc;

            // Update Action Buttons
            if (fittedBuyBtn) fittedBuyBtn.href = `/buy-now/${pid}`;
            if (fittedViewBtn) fittedViewBtn.href = `/product/${pid}`;
            if (fittedBagBtn) fittedBagBtn.dataset.productId = pid;

            // Move WEARING badge exclusively to the newly selected card
            wardrobeCards.forEach(card => {
                if (String(card.dataset.id) === pid) {
                    card.classList.add('active-wear');
                    let wearingTag = card.querySelector('.wearing-pill-indicator');
                    if (!wearingTag) {
                        wearingTag = document.createElement('span');
                        wearingTag.className = 'wearing-pill-indicator';
                        wearingTag.textContent = 'WEARING';
                        card.appendChild(wearingTag);
                    }
                } else {
                    card.classList.remove('active-wear');
                    const wearingTag = card.querySelector('.wearing-pill-indicator');
                    if (wearingTag) wearingTag.remove();
                }
            });

            // Note: Rail position remains completely stationary. Selecting a dress does NOT scroll the rail.

            // Fetch Senior AI Stylist Craftsmanship Guidance
            if (stageAdvice && pid) {
                stageAdvice.innerHTML = '<strong>✦ AI Stylist Drape Guidance</strong><span style="opacity: 0.7;">Curating atelier notes on silhouette, proportion, and jewelry pairing...</span>';
                try {
                    const res = await fetch(`/api/ai-product-qa/${pid}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ question: 'What occasion is this best for?' })
                    });
                    if (res.ok) {
                        const json = await res.json();
                        stageAdvice.innerHTML = `<strong>✦ AI Stylist Drape Guidance</strong>${json.answer || 'Hand-stitched slow luxury tailored to your proportions.'}`;
                    } else {
                        stageAdvice.innerHTML = `<strong>✦ AI Stylist Drape Guidance</strong>${productData.name} is shaped slowly from ${productData.fabric || 'pure natural handloom'} with delicate needlework, suited for ceremonial gatherings and timeless heirloom elegance.`;
                    }
                } catch {
                    stageAdvice.innerHTML = `<strong>✦ AI Stylist Drape Guidance</strong>${productData.name} is shaped slowly from ${productData.fabric || 'pure natural handloom'} with delicate needlework, suited for ceremonial gatherings and timeless heirloom elegance.`;
                }
            }
        }

        // Backward compatibility alias
        window.setFittedGarment = (data, animate) => {
            if (data && data.id) selectProduct(data.id, animate);
        };

        // -------------------------------------------------------------
        // 7. WARDROBE CARD & HANGER BUTTON CLICK HANDLERS
        // -------------------------------------------------------------
        wardrobeCards.forEach(card => {
            let touchMoved = false;
            let touchStartX = 0;
            let touchStartY = 0;

            // Touch events to allow smooth swiping on mobile without false selection
            card.addEventListener('touchstart', (e) => {
                if (e.touches.length === 1) {
                    touchStartX = e.touches[0].clientX;
                    touchStartY = e.touches[0].clientY;
                    touchMoved = false;
                }
            }, { passive: true });

            card.addEventListener('touchmove', (e) => {
                if (e.touches.length === 1) {
                    const dx = Math.abs(e.touches[0].clientX - touchStartX);
                    const dy = Math.abs(e.touches[0].clientY - touchStartY);
                    if (dx > 8 || dy > 8) {
                        touchMoved = true;
                    }
                }
            }, { passive: true });

            // Entire card click
            card.addEventListener('click', (e) => {
                if (touchMoved) {
                    touchMoved = false;
                    return; // Ignore if user was swiping the rail
                }
                e.preventDefault();
                selectProduct(card.dataset.id, true);
            });

            // Dedicated hanger button click
            const hangerBtn = card.querySelector('.hanger-btn-overlay');
            if (hangerBtn) {
                hangerBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    selectProduct(card.dataset.id, true);
                });
            }
        });

        // -------------------------------------------------------------
        // 8. WARDROBE RAIL SCROLL & ARROW CONTROLS
        // -------------------------------------------------------------
        const wardrobeRail = document.getElementById('wardrobeCardsRail');
        const wardrobeRailPrev = document.getElementById('wardrobeRailPrev');
        const wardrobeRailNext = document.getElementById('wardrobeRailNext');

        if (wardrobeRail) {
            if (wardrobeRailPrev) {
                wardrobeRailPrev.addEventListener('click', (e) => {
                    e.preventDefault();
                    wardrobeRail.scrollBy({ left: -320, behavior: 'smooth' });
                });
            }
            if (wardrobeRailNext) {
                wardrobeRailNext.addEventListener('click', (e) => {
                    e.preventDefault();
                    wardrobeRail.scrollBy({ left: 320, behavior: 'smooth' });
                });
            }

            // Mouse wheel over wardrobe rail scrolls horizontally
            wardrobeRail.addEventListener('wheel', (e) => {
                if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && !e.ctrlKey && !e.metaKey) {
                    wardrobeRail.scrollLeft += e.deltaY;
                    e.preventDefault();
                }
            }, { passive: false });
        }

        // -------------------------------------------------------------
        // 9. WARDROBE CATEGORY FILTERS
        // -------------------------------------------------------------
        filterBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                filterBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const cat = btn.dataset.category;

                wardrobeCards.forEach(card => {
                    const cardCat = card.dataset.category || '';
                    if (!cat || cat === 'all' || cardCat.toLowerCase().includes(cat.toLowerCase())) {
                        card.style.display = 'flex';
                    } else {
                        card.style.display = 'none';
                    }
                });
            });
        });

        // -------------------------------------------------------------
        // 10. ADD TO BAG ACTION
        // -------------------------------------------------------------
        if (fittedBagBtn) {
            fittedBagBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                if (!currentGarment || !currentGarment.id) return;

                const origHtml = fittedBagBtn.innerHTML;
                fittedBagBtn.textContent = 'Adding...';

                try {
                    const resp = await fetch(`/add-to-bag/${currentGarment.id}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: new URLSearchParams({ size: selectedSize, quantity: 1 })
                    });
                    if (resp.ok) {
                        fittedBagBtn.textContent = '✓ Added to Bag!';
                        setTimeout(() => { fittedBagBtn.innerHTML = origHtml; }, 2000);
                        const badge = document.querySelector('.bag-badge-pill, .badge-count');
                        if (badge) {
                            const cur = parseInt(badge.textContent) || 0;
                            badge.textContent = cur + 1;
                        }
                    } else {
                        window.location.href = `/product/${currentGarment.id}`;
                    }
                } catch {
                    window.location.href = `/product/${currentGarment.id}`;
                }
            });
        }

        // -------------------------------------------------------------
        // 11. INITIALIZATION: DERIVE ACTIVE STATE FROM FIRST PRODUCT
        // -------------------------------------------------------------
        const firstCard = wardrobeCards[0];
        if (firstCard) {
            selectProduct(firstCard.dataset.id, false);
        }
    });
