/**
 * ATELIER CURVED CAROUSEL — High-Performance 3D Cylindrical Carousel
 * Fully optimized for zero-lag mobile scrolling and silky smooth 3D desktop perspective
 */

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', () => {
        const track = document.getElementById('curvedTrack');
        const viewport = document.getElementById('curvedViewport');
        const prevBtn = document.getElementById('carouselPrev');
        const nextBtn = document.getElementById('carouselNext');

        if (!track || !viewport) return;

        const items = Array.from(track.querySelectorAll('.curved-item'));
        if (items.length === 0) return;

        const isMobile = () => window.innerWidth <= 768;

        let currentIndex = 0;
        let isDragging = false;
        let startX = 0;
        let currentTranslate = 0;
        let prevTranslate = 0;
        const itemStride = 352; // 320 card + 32 gap

        /**
         * Pure-Math 3D Cylindrical Arc for Desktop
         * Zero DOM reflows (no getBoundingClientRect inside animation loop)
         */
        function updateDesktopCurvedPositions() {
            if (isMobile()) {
                track.style.transform = 'none';
                items.forEach(item => {
                    item.style.transform = 'none';
                    item.style.opacity = '1';
                });
                return;
            }

            const halfVp = viewport.offsetWidth / 2 || 600;

            items.forEach((item, index) => {
                // Distance from center card in pixels based on current translation
                const cardCenterOffset = (index * itemStride) + currentTranslate;
                const distFromCenter = cardCenterOffset / halfVp;
                const clampedDist = Math.max(-1.6, Math.min(1.6, distFromCenter));
                const rotateY = clampedDist * -24;
                const translateZ = -Math.abs(clampedDist) * 70;
                const scale = Math.max(0.85, 1 - Math.abs(clampedDist) * 0.08);
                const opacity = Math.max(0.35, 1 - Math.abs(clampedDist) * 0.35);

                item.style.transform = `rotateY(${rotateY.toFixed(2)}deg) translateZ(${translateZ.toFixed(1)}px) scale(${scale.toFixed(3)})`;
                item.style.opacity = opacity.toFixed(2);
            });
        }

        function setDesktopIndex(index, animate = true) {
            currentIndex = Math.max(0, Math.min(items.length - 1, index));
            currentTranslate = -currentIndex * itemStride;
            prevTranslate = currentTranslate;

            track.style.transition = animate ? 'transform 0.55s cubic-bezier(0.16, 1, 0.3, 1)' : 'none';
            track.style.transform = `translateX(${currentTranslate}px)`;
            updateDesktopCurvedPositions();
        }

        /**
         * Mobile Smooth Scroll
         */
        function scrollMobileBy(direction) {
            const firstCard = track.querySelector('.curved-item');
            const step = firstCard ? firstCard.offsetWidth + 16 : 280;
            viewport.scrollBy({ left: direction * step, behavior: 'smooth' });
        }

        // Navigation Arrows
        if (nextBtn) {
            nextBtn.addEventListener('click', (e) => {
                e.preventDefault();
                if (isMobile()) {
                    scrollMobileBy(1);
                } else {
                    const next = (currentIndex < items.length - 1) ? currentIndex + 1 : 0;
                    setDesktopIndex(next);
                }
            });
        }

        if (prevBtn) {
            prevBtn.addEventListener('click', (e) => {
                e.preventDefault();
                if (isMobile()) {
                    scrollMobileBy(-1);
                } else {
                    const prev = (currentIndex > 0) ? currentIndex - 1 : items.length - 1;
                    setDesktopIndex(prev);
                }
            });
        }

        // Desktop Mouse Drag Support (Only enabled on screens > 768px)
        track.addEventListener('mousedown', (e) => {
            if (isMobile() || e.button !== 0) return;
            isDragging = true;
            startX = e.clientX;
            track.style.transition = 'none';
            track.classList.add('is-dragging');
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDragging || isMobile()) return;
            const diff = e.clientX - startX;
            currentTranslate = prevTranslate + diff;
            track.style.transform = `translateX(${currentTranslate}px)`;
            updateDesktopCurvedPositions();
        });

        window.addEventListener('mouseup', (e) => {
            if (!isDragging) return;
            isDragging = false;
            track.classList.remove('is-dragging');

            if (isMobile()) return;

            const movedBy = currentTranslate - prevTranslate;
            if (movedBy < -60 && currentIndex < items.length - 1) {
                currentIndex++;
            } else if (movedBy > 60 && currentIndex > 0) {
                currentIndex--;
            }
            setDesktopIndex(currentIndex, true);
        });

        // Resize handler with clean mode switching
        let resizeTimer = null;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                if (isMobile()) {
                    track.style.transform = 'none';
                    track.style.transition = 'none';
                    items.forEach(item => {
                        item.style.transform = 'none';
                        item.style.opacity = '1';
                    });
                } else {
                    setDesktopIndex(currentIndex, false);
                }
            }, 100);
        }, { passive: true });

        // Initial setup
        if (isMobile()) {
            track.style.transform = 'none';
            items.forEach(item => {
                item.style.transform = 'none';
                item.style.opacity = '1';
            });
        } else {
            setDesktopIndex(0, false);
        }
    });
})();
