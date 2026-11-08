/**
 * TULSA BY ANJALI — GRAND CYLINDRICAL 3D RUNWAY & SPECIFICATION DRAWER
 * Inspired by Reference Video 1:
 * - Cylindrical 3D rotating stage with real Tulsa products
 * - Mouse drag, touch swipe, and step pagination (< 01 / 16 >)
 * - Depth-of-field focus on active product
 * - Sliding luxury specification panel with product name, price, description,
 *   size selection, 'View Product', and 'Add to Bag' connected to existing routes.
 */

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', () => {
        const track = document.getElementById('stageTrack3D') || document.getElementById('curvedTrack');
        const prevBtn = document.getElementById('stagePrev') || document.getElementById('carouselPrev');
        const nextBtn = document.getElementById('stageNext') || document.getElementById('carouselNext');
        const counterEl = document.getElementById('stageCounter');
        const filterChips = document.querySelectorAll('.stage-filter-chip');

        // Spec Drawer Elements
        const specImg = document.getElementById('specPreviewImg');
        const specTitle = document.getElementById('specTitle');
        const specPrice = document.getElementById('specPrice');
        const specCategory = document.getElementById('specCategory');
        const specFabric = document.getElementById('specFabric');
        const specColor = document.getElementById('specColor');
        const specStock = document.getElementById('specStock');
        const specDesc = document.getElementById('specDesc');
        const specViewBtn = document.getElementById('specViewBtn');
        const specBuyBtn = document.getElementById('specBuyBtn');
        const specBagBtn = document.getElementById('specBagBtn');
        const specSizeBtns = document.querySelectorAll('.spec-size-btn');

        if (!track) return;

        let items = Array.from(track.querySelectorAll('.stage-card-3d, .curved-item'));
        if (items.length === 0) return;

        const isMobile = () => window.innerWidth <= 768;
        let currentIndex = 0;
        let isDragging = false;
        let startX = 0;
        let startY = 0;
        let currentTranslate = 0;
        let prevTranslate = 0;
        const itemStride = 352; // 320 card width + 32 gap
        let selectedSize = 'M';

        // Size selector interaction
        specSizeBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                specSizeBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                selectedSize = btn.dataset.size || btn.textContent.trim();
            });
        });

        function updateCounter(index) {
            if (counterEl) {
                const total = items.length;
                const currentStr = String(index + 1).padStart(2, '0');
                const totalStr = String(total).padStart(2, '0');
                counterEl.textContent = `< ${currentStr} / ${totalStr} >`;
            }
        }

        function updateSpecDrawer(item) {
            if (!item) return;
            const id = item.dataset.id;
            const name = item.dataset.name || item.querySelector('.stage-card-name, .curved-title')?.textContent?.trim();
            const price = item.dataset.price || item.querySelector('.stage-card-price, .curved-price')?.textContent?.trim();
            const category = item.dataset.category || item.querySelector('.stage-card-cat, .curved-category')?.textContent?.trim();
            const fabric = item.dataset.fabric || 'Pure Natural Fibers';
            const color = item.dataset.color || 'Artisanal Dye';
            const stock = item.dataset.stock || '10';
            const desc = item.dataset.desc || 'Handcrafted slow luxury shaped from fine natural fibers with artisanal needlework.';
            const imgSrc = item.dataset.img || item.querySelector('img')?.src;

            if (specTitle && name) specTitle.textContent = name;
            if (specPrice && price) specPrice.textContent = price.startsWith('₹') ? price : `₹${Number(price).toLocaleString('en-IN')}`;
            if (specCategory && category) specCategory.textContent = category;
            if (specFabric) specFabric.textContent = fabric;
            if (specColor) specColor.textContent = color;
            if (specStock) specStock.textContent = Number(stock) > 0 ? `In Stock (${stock} available)` : 'Made to Order';
            if (specDesc) specDesc.textContent = desc;

            if (specImg && imgSrc) {
                if (window.gsap) {
                    window.gsap.to(specImg, {
                        opacity: 0,
                        scale: 0.96,
                        duration: 0.15,
                        onComplete: () => {
                            specImg.src = imgSrc;
                            window.gsap.to(specImg, { opacity: 1, scale: 1, duration: 0.25 });
                        }
                    });
                } else {
                    specImg.style.opacity = '0';
                    setTimeout(() => {
                        specImg.src = imgSrc;
                        specImg.style.opacity = '1';
                    }, 150);
                }
            }

            if (specViewBtn && id) {
                specViewBtn.href = `/product/${id}`;
            }

            if (specBuyBtn && id) {
                specBuyBtn.href = `/buy-now/${id}`;
            }

            if (specBagBtn && id) {
                specBagBtn.dataset.productId = id;
            }
        }

        function update3DPositions() {
            if (isMobile()) {
                track.style.transform = 'none';
                items.forEach(item => {
                    item.style.transform = 'none';
                    item.style.opacity = '1';
                });
                return;
            }

            const halfVp = (track.parentElement.offsetWidth || 1200) / 2;

            items.forEach((item, index) => {
                const cardCenterOffset = (index * itemStride) + currentTranslate;
                const distFromCenter = cardCenterOffset / halfVp;
                const clampedDist = Math.max(-1.8, Math.min(1.8, distFromCenter));
                const rotateY = clampedDist * -22;
                const translateZ = -Math.abs(clampedDist) * 85;
                const scale = Math.max(0.85, 1 - Math.abs(clampedDist) * 0.09);
                const opacity = Math.max(0.38, 1 - Math.abs(clampedDist) * 0.32);

                item.style.transform = `rotateY(${rotateY.toFixed(2)}deg) translateZ(${translateZ.toFixed(1)}px) scale(${scale.toFixed(3)})`;
                item.style.opacity = opacity.toFixed(2);

                if (Math.abs(clampedDist) < 0.35) {
                    item.classList.add('active-focus');
                } else {
                    item.classList.remove('active-focus');
                }
            });
        }

        function setIndex(index, animate = true) {
            currentIndex = Math.max(0, Math.min(items.length - 1, index));
            currentTranslate = -currentIndex * itemStride;
            prevTranslate = currentTranslate;

            if (window.gsap && animate && !isMobile()) {
                window.gsap.to(track, {
                    x: currentTranslate,
                    duration: 0.6,
                    ease: 'power2.out',
                    onUpdate: update3DPositions
                });
            } else {
                track.style.transition = animate ? 'transform 0.55s cubic-bezier(0.16, 1, 0.3, 1)' : 'none';
                track.style.transform = `translateX(${currentTranslate}px)`;
                update3DPositions();
            }

            updateCounter(currentIndex);
            updateSpecDrawer(items[currentIndex]);
        }

        // Card Click Selection
        items.forEach((item, idx) => {
            item.addEventListener('click', (e) => {
                if (e.target.closest('.stage-hanger-trigger') || e.target.closest('.btn-reel-quickbag')) {
                    return;
                }
                setIndex(idx, true);
            });
        });

        // Navigation Arrows
        if (nextBtn) {
            nextBtn.addEventListener('click', (e) => {
                e.preventDefault();
                const next = (currentIndex < items.length - 1) ? currentIndex + 1 : 0;
                setIndex(next, true);
            });
        }

        if (prevBtn) {
            prevBtn.addEventListener('click', (e) => {
                e.preventDefault();
                const prev = (currentIndex > 0) ? currentIndex - 1 : items.length - 1;
                setIndex(prev, true);
            });
        }

        // Category Filter Chips
        filterChips.forEach(chip => {
            chip.addEventListener('click', () => {
                filterChips.forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                const cat = chip.dataset.category;

                if (!cat || cat === 'all') {
                    setIndex(0, true);
                    return;
                }

                const targetIdx = items.findIndex(item => {
                    const itemCat = item.dataset.category || '';
                    return itemCat.toLowerCase().includes(cat.toLowerCase());
                });

                if (targetIdx !== -1) {
                    setIndex(targetIdx, true);
                }
            });
        });

        // Mouse Drag Support on Desktop
        track.addEventListener('mousedown', (e) => {
            if (isMobile() || e.button !== 0) return;
            isDragging = true;
            startX = e.clientX;
            track.style.transition = 'none';
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDragging || isMobile()) return;
            const diff = e.clientX - startX;
            currentTranslate = prevTranslate + diff;
            track.style.transform = `translateX(${currentTranslate}px)`;
            update3DPositions();
        });

        window.addEventListener('mouseup', () => {
            if (!isDragging) return;
            isDragging = false;
            if (isMobile()) return;

            const movedBy = currentTranslate - prevTranslate;
            if (movedBy < -60 && currentIndex < items.length - 1) {
                currentIndex++;
            } else if (movedBy > 60 && currentIndex > 0) {
                currentIndex--;
            }
            setIndex(currentIndex, true);
        });

        // Mobile Touch Gesture Swipe Support
        track.addEventListener('touchstart', (e) => {
            if (e.touches.length !== 1) return;
            isDragging = true;
            startX = e.touches[0].clientX;
            startY = e.touches[0].clientY;
        }, { passive: true });

        track.addEventListener('touchend', (e) => {
            if (!isDragging) return;
            isDragging = false;
            const touch = e.changedTouches[0];
            if (!touch) return;
            const diffX = touch.clientX - startX;
            const diffY = touch.clientY - startY;

            // Only act if horizontal gesture is greater than vertical scroll
            if (Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > 40) {
                if (diffX < 0 && currentIndex < items.length - 1) {
                    setIndex(currentIndex + 1, true);
                } else if (diffX > 0 && currentIndex > 0) {
                    setIndex(currentIndex - 1, true);
                }
            }
        }, { passive: true });

        // Resize handler
        window.addEventListener('resize', () => {
            if (isMobile()) {
                track.style.transform = 'none';
                items.forEach(item => {
                    item.style.transform = 'none';
                    item.style.opacity = '1';
                });
            } else {
                setIndex(currentIndex, false);
            }
        }, { passive: true });

        // Add to Bag handler from Spec Drawer
        if (specBagBtn) {
            specBagBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                const pId = specBagBtn.dataset.productId;
                if (!pId) return;

                const origText = specBagBtn.innerHTML;
                specBagBtn.textContent = 'Adding...';
                try {
                    const resp = await fetch(`/add-to-bag/${pId}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: new URLSearchParams({ size: selectedSize, quantity: 1 })
                    });
                    if (resp.ok) {
                        specBagBtn.textContent = '✓ Added to Bag';
                        setTimeout(() => { specBagBtn.innerHTML = origText; }, 2000);
                        const badge = document.querySelector('.bag-badge-pill, .badge-count');
                        if (badge) {
                            const cur = parseInt(badge.textContent) || 0;
                            badge.textContent = cur + 1;
                        }
                    } else {
                        window.location.href = `/product/${pId}`;
                    }
                } catch {
                    window.location.href = `/product/${pId}`;
                }
            });
        }

        // Initial launch
        setIndex(0, false);
    });
})();
