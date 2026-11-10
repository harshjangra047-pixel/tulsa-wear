/**
 * ATELIER LOOK BUILDER & ACCORDION GALLERY
 * Interactive Studio Look Switcher + Accordion Slat Interactions
 */

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', () => {
        // --- 1. LOOK BUILDER ---
        const thumbs = document.querySelectorAll('.look-thumb');
        const mainImg = document.getElementById('lookStageImg');
        const lookTag = document.getElementById('lookTag');
        const lookName = document.getElementById('lookName');
        const lookPrice = document.getElementById('lookPrice');
        const lookDesc = document.getElementById('lookDesc');
        const lookAddBtn = document.getElementById('lookAddBtn');
        const swatches = document.querySelectorAll('.swatch');
        const sizePills = document.querySelectorAll('.size-pill');

        if (thumbs.length > 0 && mainImg) {
            thumbs.forEach(thumb => {
                thumb.addEventListener('click', () => {
                    thumbs.forEach(t => t.classList.remove('active'));
                    thumb.classList.add('active');

                    // Read dataset
                    const title = thumb.dataset.title;
                    const price = thumb.dataset.price;
                    const desc = thumb.dataset.desc;
                    const tag = thumb.dataset.tag;
                    const imgSrc = thumb.dataset.img;
                    const productId = thumb.dataset.id;

                    // Smooth transition
                    mainImg.style.opacity = '0';
                    mainImg.style.transform = 'scale(0.96)';

                    setTimeout(() => {
                        mainImg.src = imgSrc;
                        if (lookName) lookName.textContent = title;
                        if (lookPrice) lookPrice.textContent = '₹' + Number(price).toLocaleString('en-IN');
                        if (lookDesc) lookDesc.textContent = desc;
                        if (lookTag) lookTag.textContent = tag;
                        if (lookAddBtn && productId) {
                            lookAddBtn.dataset.productId = productId;
                        }

                        mainImg.style.opacity = '1';
                        mainImg.style.transform = 'scale(1)';
                    }, 250);
                });
            });
        }

        // Swatch selection
        if (swatches.length > 0) {
            swatches.forEach(swatch => {
                swatch.addEventListener('click', () => {
                    swatches.forEach(s => s.classList.remove('active'));
                    swatch.classList.add('active');
                });
            });
        }

        // Size pill selection
        if (sizePills.length > 0) {
            sizePills.forEach(pill => {
                pill.addEventListener('click', () => {
                    sizePills.forEach(p => p.classList.remove('active'));
                    pill.classList.add('active');
                });
            });
        }

        // Add to Bag handler for Look Builder
        if (lookAddBtn) {
            lookAddBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                const productId = lookAddBtn.dataset.productId;
                if (!productId) return;

                const originalText = lookAddBtn.innerHTML;
                lookAddBtn.innerHTML = '<span>ADDING...</span> ✦';

                try {
                    const formData = new FormData();
                    formData.append('product_id', productId);
                    formData.append('quantity', '1');

                    const response = await fetch('/cart/add', {
                        method: 'POST',
                        body: formData
                    });

                    if (response.ok) {
                        lookAddBtn.innerHTML = '<span>ADDED TO BAG</span> ✓';
                        // Update cart counters in navbar
                        const bagLinks = document.querySelectorAll('.bag-link');
                        bagLinks.forEach(b => {
                            const match = b.textContent.match(/\d+/);
                            const current = match ? parseInt(match[0]) : 0;
                            b.textContent = `Bag (${current + 1})`;
                        });
                        setTimeout(() => {
                            lookAddBtn.innerHTML = originalText;
                        }, 2000);
                    } else {
                        window.location.href = `/product/${productId}`;
                    }
                } catch (err) {
                    window.location.href = `/product/${productId}`;
                }
            });
        }

        // --- 2. ACCORDION GALLERY SLATS ---
        const slats = document.querySelectorAll('.slat-item');
        if (slats.length > 0) {
            slats.forEach(slat => {
                slat.addEventListener('mouseenter', () => {
                    slats.forEach(s => s.classList.remove('active'));
                    slat.classList.add('active');
                });
                slat.addEventListener('click', () => {
                    slats.forEach(s => s.classList.remove('active'));
                    slat.classList.add('active');
                });
            });
        }
    });
})();
