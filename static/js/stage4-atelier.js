/**
 * TULSA BY ANJALI — STAGE 4 LUXURY SILK ATELIER & 3D WEAVING STUDIO
 * Inspired by Reference Video 4
 * Features:
 * 1. Pick Your Silk: Arched 3D Collection Cards with provenance drawer
 * 2. The Rack: Hanging Atelier Garment Rail with gold hanger & live sizing
 * 3. Cinematic Reel Lookbook: Story progression, sound toggle & quick add
 * 4. Three Silks, One Weave: 3D Three.js helix silk braid with interactive color swatches
 */

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', () => {

        // =============================================================
        // 1. PICK YOUR SILK — ARCHED 3D CARDS & PROVENANCE DRAWER
        // =============================================================
        const silkCards = document.querySelectorAll('.arched-silk-card');
        const silkPrevBtn = document.getElementById('silkCardPrev');
        const silkNextBtn = document.getElementById('silkCardNext');
        const silkTrack = document.getElementById('silkCardsTrack');
        const silkDetailName = document.getElementById('activeSilkName');
        const silkDetailWeave = document.getElementById('activeSilkWeave');
        const silkDetailDesc = document.getElementById('activeSilkDesc');
        const silkDetailCta = document.getElementById('activeSilkCta');

        const SILK_PROVENANCE = {
            '1': {
                name: 'Monsoon Azure Kanjeevaram',
                weave: 'Pure Mulberry Silk • 4-Ply High-Density Zari Warp',
                desc: 'Deep oceanic blue dyed with mineral pigments, woven with 24-carat silver-dipped electroplated zari borders inspired by royal palace courtyards.',
                link: '/shop?category=Wedding%20Wear'
            },
            '2': {
                name: 'Surya Ochre Chanderi Silk',
                weave: 'Featherweight Tissue Chanderi • Handloom Gota Border',
                desc: 'Woven along ancient Malwa looms using sheer silk warp and fine zari weft. Delivers an ethereal golden radiance under natural sunlight.',
                link: '/shop?category=Party%20Wear'
            },
            '3': {
                name: 'Rani Magenta Zardozi Silk',
                weave: 'Heavy Matka Silk • Antique Gold Hand-Needlework',
                desc: 'Vibrant regal fuchsia enriched with floral gul-e-daudi bootas, slow-stitched by third-generation craftsmen in Hansi.',
                link: '/shop?category=Salwar%20Kameez'
            },
            '4': {
                name: 'Palace Crimson Banarasi Brocade',
                weave: 'Kadhwa Brocade • Rich Crimson Satin Ground',
                desc: 'Traditional motifs drawn from Mughal miniature art, woven over sixteen weeks with continuous gold filament threads.',
                link: '/shop?category=Party%20Wear'
            },
            '5': {
                name: 'Bengal Garden Tussar Silk',
                weave: 'Wild Forest Tussar • Pure Handloom Texture',
                desc: 'Rich textured natural ivory raw silk with fine slubs, breathable for ceremonial celebrations in all Indian seasons.',
                link: '/shop?category=Plazo%20/%20Kurta'
            },
            '6': {
                name: 'Marigold Organza Brocade',
                weave: 'Crisp Glass Organza • Handwoven Floral Jaal',
                desc: 'Translucent sheer luster with delicate floral jaal work. Floats effortlessly while retaining architectural drape.',
                link: '/shop?category=Salwar%20Kameez'
            },
            '7': {
                name: 'Emerald Velvet Regalia',
                weave: 'Micro-Velvet & Mulberry Silk Blend',
                desc: 'Deep royal forest emerald, plush and light-reflective, embellished with heritage katori and dabka work.',
                link: '/shop?category=Wedding%20Wear'
            },
            '8': {
                name: 'Mughal Lilac Imperial Anarkali',
                weave: 'Ancestral Loom Silk • Artisanal Lilac Dye',
                desc: 'Signature royal silhouette featuring ancestral zari hemwork and breathable handwoven base fibers.',
                link: '/shop?category=Wedding%20Wear'
            }
        };

        function selectSilkCard(card) {
            if (!card) return;
            silkCards.forEach(c => c.classList.remove('active-silk'));
            card.classList.add('active-silk');

            const sid = card.dataset.silkId || '1';
            const data = SILK_PROVENANCE[sid];
            if (data) {
                if (silkDetailName) silkDetailName.textContent = data.name;
                if (silkDetailWeave) silkDetailWeave.textContent = data.weave;
                if (silkDetailDesc) silkDetailDesc.textContent = data.desc;
                if (silkDetailCta) silkDetailCta.href = data.link;
            }
        }

        silkCards.forEach(card => {
            card.addEventListener('click', () => selectSilkCard(card));
        });

        if (silkTrack) {
            if (silkPrevBtn) {
                silkPrevBtn.addEventListener('click', () => {
                    silkTrack.scrollBy({ left: -320, behavior: 'smooth' });
                });
            }
            if (silkNextBtn) {
                silkNextBtn.addEventListener('click', () => {
                    silkTrack.scrollBy({ left: 320, behavior: 'smooth' });
                });
            }
        }

        // =============================================================
        // 2. THE RACK — HANGING ATELIER COLLECTION RAIL (Video 4)
        // =============================================================
        const rackItems = document.querySelectorAll('.rack-garment-item');
        const rackPrevBtn = document.getElementById('rackPrev');
        const rackNextBtn = document.getElementById('rackNext');
        const rackTrack = document.getElementById('rackGarmentsTrack');
        const rackFeaturedImg = document.getElementById('rackFeaturedImg');
        const rackFeaturedTitle = document.getElementById('rackFeaturedTitle');
        const rackFeaturedPrice = document.getElementById('rackFeaturedPrice');
        const rackFeaturedFabric = document.getElementById('rackFeaturedFabric');
        const rackFeaturedViewBtn = document.getElementById('rackFeaturedViewBtn');
        const rackFeaturedBagBtn = document.getElementById('rackFeaturedBagBtn');
        const rackSizePills = document.querySelectorAll('.rack-size-btn');

        let selectedRackSize = 'M';

        rackSizePills.forEach(pill => {
            pill.addEventListener('click', () => {
                rackSizePills.forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                selectedRackSize = pill.dataset.size || pill.textContent.trim();
            });
        });

        function selectRackItem(item) {
            if (!item) return;
            rackItems.forEach(i => i.classList.remove('active-hanger'));
            item.classList.add('active-hanger');

            const pId = item.dataset.id;
            const pName = item.dataset.name;
            const pPrice = item.dataset.price;
            const pFabric = item.dataset.fabric;
            const pImg = item.dataset.img;

            if (rackFeaturedImg && pImg) rackFeaturedImg.src = pImg;
            if (rackFeaturedTitle && pName) rackFeaturedTitle.textContent = pName;
            if (rackFeaturedPrice && pPrice) {
                const num = Number(pPrice);
                rackFeaturedPrice.textContent = `₹${num.toLocaleString('en-IN')}`;
            }
            if (rackFeaturedFabric && pFabric) rackFeaturedFabric.textContent = `✦ Fabric: ${pFabric}`;
            if (rackFeaturedViewBtn && pId) rackFeaturedViewBtn.href = `/product/${pId}`;
            if (rackFeaturedBagBtn && pId) rackFeaturedBagBtn.dataset.productId = pId;
        }

        rackItems.forEach(item => {
            item.addEventListener('click', () => selectRackItem(item));
        });

        if (rackTrack) {
            if (rackPrevBtn) {
                rackPrevBtn.addEventListener('click', () => {
                    rackTrack.scrollBy({ left: -260, behavior: 'smooth' });
                });
            }
            if (rackNextBtn) {
                rackNextBtn.addEventListener('click', () => {
                    rackTrack.scrollBy({ left: 260, behavior: 'smooth' });
                });
            }
        }

        if (rackFeaturedBagBtn) {
            rackFeaturedBagBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                const pId = rackFeaturedBagBtn.dataset.productId;
                if (!pId) return;

                rackFeaturedBagBtn.textContent = 'Adding...';
                try {
                    const resp = await fetch(`/add-to-bag/${pId}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: new URLSearchParams({ size: selectedRackSize, quantity: 1 })
                    });
                    if (resp.ok) {
                        rackFeaturedBagBtn.textContent = '✓ Added to Bag!';
                        const badge = document.querySelector('.bag-badge-pill, .badge-count');
                        if (badge) {
                            const cur = parseInt(badge.textContent) || 0;
                            badge.textContent = cur + 1;
                        }
                        setTimeout(() => { rackFeaturedBagBtn.textContent = '👜 Add to Bag'; }, 2000);
                    } else {
                        window.location.href = `/product/${pId}`;
                    }
                } catch {
                    window.location.href = `/product/${pId}`;
                }
            });
        }

        // =============================================================
        // 3. CINEMATIC REEL LOOKBOOK ("Feel the Drape")
        // =============================================================
        const reelStoryCards = document.querySelectorAll('.cinematic-reel-card');
        const reelFeaturedMedia = document.getElementById('reelFeaturedMedia');
        const reelFeaturedHeading = document.getElementById('reelFeaturedHeading');
        const reelFeaturedSub = document.getElementById('reelFeaturedSub');
        const reelFeaturedShopBtn = document.getElementById('reelFeaturedShopBtn');
        const reelSoundBtn = document.getElementById('reelSoundBtn');
        const reelQuickAddBtn = document.getElementById('reelQuickAddBtn');

        let isSoundOn = false;
        if (reelSoundBtn) {
            reelSoundBtn.addEventListener('click', () => {
                isSoundOn = !isSoundOn;
                reelSoundBtn.innerHTML = isSoundOn ? '🔊 Sound: On' : '🔇 Ambient: Mute';
                reelSoundBtn.classList.toggle('active', isSoundOn);
            });
        }

        function activateReelStory(card) {
            if (!card) return;
            reelStoryCards.forEach(c => {
                c.classList.remove('active-reel');
                const prog = c.querySelector('.reel-progress-fill');
                if (prog) prog.style.width = '0%';
            });

            card.classList.add('active-reel');
            const activeProg = card.querySelector('.reel-progress-fill');
            if (activeProg) activeProg.style.width = '100%';

            const imgSrc = card.dataset.img;
            const title = card.dataset.title;
            const sub = card.dataset.sub;
            const pId = card.dataset.productId;
            const pLink = card.dataset.link;

            if (reelFeaturedMedia && imgSrc) reelFeaturedMedia.src = imgSrc;
            if (reelFeaturedHeading && title) reelFeaturedHeading.textContent = title;
            if (reelFeaturedSub && sub) reelFeaturedSub.textContent = sub;
            if (reelFeaturedShopBtn) reelFeaturedShopBtn.href = pLink || (pId ? `/product/${pId}` : '/shop');
            if (reelQuickAddBtn && pId) reelQuickAddBtn.dataset.productId = pId;
        }

        reelStoryCards.forEach(card => {
            card.addEventListener('click', () => activateReelStory(card));
        });

        if (reelQuickAddBtn) {
            reelQuickAddBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                const pId = reelQuickAddBtn.dataset.productId;
                if (!pId) return;

                reelQuickAddBtn.textContent = 'Adding...';
                try {
                    const resp = await fetch(`/add-to-bag/${pId}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: new URLSearchParams({ size: 'M', quantity: 1 })
                    });
                    if (resp.ok) {
                        reelQuickAddBtn.textContent = '✓ Added!';
                        const badge = document.querySelector('.bag-badge-pill, .badge-count');
                        if (badge) {
                            const cur = parseInt(badge.textContent) || 0;
                            badge.textContent = cur + 1;
                        }
                        setTimeout(() => { reelQuickAddBtn.textContent = '⚡ One-Tap Add to Bag'; }, 2000);
                    } else {
                        window.location.href = `/product/${pId}`;
                    }
                } catch {
                    window.location.href = `/product/${pId}`;
                }
            });
        }

        // =============================================================
        // 4. THREE SILKS, ONE WEAVE — 3D THREE.JS WEAVING STUDIO
        // =============================================================
        const weaveCanvas = document.getElementById('weaveCanvas');
        if (weaveCanvas) {
            initWeaveStudio(weaveCanvas);
        }

        function initWeaveStudio(canvas) {
            const container = canvas.parentElement;
            const width = container.clientWidth || 900;
            const height = 480;

            const COLOR_HEX_MAP = {
                '0x0C4533': '#0C4533',
                '0xC9A96E': '#C9A96E',
                '0xC71585': '#C71585',
                '0xD9822B': '#D9822B',
                '0x20639B': '#20639B',
                '0xF5EBE1': '#F5EBE1'
            };

            const COLOR_NAMES = {
                '0x0C4533': 'Royal Emerald',
                '0xC9A96E': 'Antique Gold',
                '0xC71585': 'Rani Magenta',
                '0xD9822B': 'Surya Ochre',
                '0x20639B': 'Monsoon Azure',
                '0xF5EBE1': 'Raw Silk Ivory'
            };

            const weaveState = {
                isPlaying: true,
                speedMultiplier: 1.0,
                activeStrandIndex: 1,
                strandSelections: {
                    1: { hex: '0x0C4533', name: 'Royal Emerald', css: '#0C4533' },
                    2: { hex: '0xC9A96E', name: 'Antique Gold', css: '#C9A96E' },
                    3: { hex: '0xC71585', name: 'Rani Magenta', css: '#C71585' }
                }
            };

            const strandPills = document.querySelectorAll('.weave-strand-tab');
            const colorSwatches = document.querySelectorAll('.weave-color-swatch');
            const liveColorReport = document.getElementById('weaveCombinationReport');
            const btnPlayPause = document.getElementById('btnWeavePlayPause');
            const speedPills = document.querySelectorAll('.weave-speed-btn');
            const btnReset = document.getElementById('btnWeaveReset');

            function updateReport() {
                if (liveColorReport) {
                    liveColorReport.innerHTML = `<strong>Selected Weave:</strong> Warp: <span class="strand-val">${weaveState.strandSelections[1].name}</span> • Weft: <span class="strand-val">${weaveState.strandSelections[2].name}</span> • Filament: <span class="strand-val">${weaveState.strandSelections[3].name}</span>`;
                }
            }

            // Check WebGL availability
            let webglSupported = false;
            try {
                const testCanvas = document.createElement('canvas');
                webglSupported = !!(window.WebGLRenderingContext && (testCanvas.getContext('webgl') || testCanvas.getContext('experimental-webgl')));
            } catch {
                webglSupported = false;
            }

            if (webglSupported && typeof THREE !== 'undefined') {
                try {
                    initThreeJSStudio(canvas, width, height, weaveState);
                } catch (err) {
                    console.warn('WebGL initialization failed, falling back to 2D atelier canvas:', err);
                    init2DStudio(canvas, width, height, weaveState);
                }
            } else {
                init2DStudio(canvas, width, height, weaveState);
            }

            // Wire UI Controls
            strandPills.forEach(pill => {
                pill.addEventListener('click', () => {
                    strandPills.forEach(p => p.classList.remove('active'));
                    pill.classList.add('active');
                    weaveState.activeStrandIndex = parseInt(pill.dataset.strand, 10) || 1;
                });
            });

            colorSwatches.forEach(swatch => {
                swatch.addEventListener('click', () => {
                    const hexStr = swatch.dataset.colorHex;
                    const colorName = swatch.dataset.colorName || COLOR_NAMES[hexStr] || 'Artisanal Dye';
                    const cssColor = COLOR_HEX_MAP[hexStr] || hexStr;

                    weaveState.strandSelections[weaveState.activeStrandIndex] = {
                        hex: hexStr,
                        name: colorName,
                        css: cssColor
                    };

                    if (weaveState.onColorChange) {
                        weaveState.onColorChange(weaveState.activeStrandIndex, parseInt(hexStr, 16), cssColor);
                    }

                    colorSwatches.forEach(s => s.classList.remove('selected'));
                    swatch.classList.add('selected');

                    updateReport();
                });
            });

            if (btnPlayPause) {
                btnPlayPause.addEventListener('click', () => {
                    weaveState.isPlaying = !weaveState.isPlaying;
                    btnPlayPause.textContent = weaveState.isPlaying ? '⏸ Pause Weave' : '▶ Resume Weave';
                    btnPlayPause.classList.toggle('is-paused', !weaveState.isPlaying);
                });
            }

            speedPills.forEach(btn => {
                btn.addEventListener('click', () => {
                    speedPills.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    weaveState.speedMultiplier = parseFloat(btn.dataset.speed) || 1.0;
                });
            });

            if (btnReset) {
                btnReset.addEventListener('click', () => {
                    weaveState.strandSelections[1] = { hex: '0x0C4533', name: 'Royal Emerald', css: '#0C4533' };
                    weaveState.strandSelections[2] = { hex: '0xC9A96E', name: 'Antique Gold', css: '#C9A96E' };
                    weaveState.strandSelections[3] = { hex: '0xC71585', name: 'Rani Magenta', css: '#C71585' };
                    weaveState.speedMultiplier = 1.0;
                    weaveState.isPlaying = true;
                    if (btnPlayPause) btnPlayPause.textContent = '⏸ Pause Weave';
                    speedPills.forEach(b => b.classList.toggle('active', b.dataset.speed === '1.0'));
                    if (weaveState.onColorChange) {
                        weaveState.onColorChange(1, 0x0C4533, '#0C4533');
                        weaveState.onColorChange(2, 0xC9A96E, '#C9A96E');
                        weaveState.onColorChange(3, 0xC71585, '#C71585');
                    }
                    updateReport();
                });
            }

            updateReport();
        }

        // --- Three.js WebGL Engine ---
        function initThreeJSStudio(canvas, width, height, state) {
            const scene = new THREE.Scene();
            scene.fog = new THREE.FogExp2(0x061510, 0.04);

            const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
            camera.position.set(0, 0, 14);

            const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
            renderer.setSize(width, height);
            renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

            const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
            scene.add(ambientLight);

            const goldDirLight = new THREE.DirectionalLight(0xE6CA85, 1.4);
            goldDirLight.position.set(5, 10, 7);
            scene.add(goldDirLight);

            const emeraldFill = new THREE.PointLight(0x0C4533, 1.8, 20);
            emeraldFill.position.set(-8, -4, 4);
            scene.add(emeraldFill);

            const NUM_POINTS = 160;
            const LENGTH = 18;
            const TURNS = 3.5;

            const materials = {
                1: new THREE.MeshStandardMaterial({ color: 0x0C4533, metalness: 0.35, roughness: 0.25, side: THREE.DoubleSide }),
                2: new THREE.MeshStandardMaterial({ color: 0xC9A96E, metalness: 0.75, roughness: 0.2, side: THREE.DoubleSide }),
                3: new THREE.MeshStandardMaterial({ color: 0xC71585, metalness: 0.45, roughness: 0.3, side: THREE.DoubleSide })
            };

            function createRibbonGeometry(phaseOffset, radius = 1.3) {
                const points = [];
                for (let i = 0; i < NUM_POINTS; i++) {
                    const u = i / (NUM_POINTS - 1);
                    const x = (u - 0.5) * LENGTH;
                    const angle = u * Math.PI * 2 * TURNS + phaseOffset;
                    const y = Math.sin(angle) * radius;
                    const z = Math.cos(angle) * (radius * 0.75);
                    points.push(new THREE.Vector3(x, y, z));
                }
                const curve = new THREE.CatmullRomCurve3(points);
                return new THREE.TubeGeometry(curve, 120, 0.28, 12, false);
            }

            const meshes = {
                1: new THREE.Mesh(createRibbonGeometry(0), materials[1]),
                2: new THREE.Mesh(createRibbonGeometry((Math.PI * 2) / 3), materials[2]),
                3: new THREE.Mesh(createRibbonGeometry((Math.PI * 4) / 3), materials[3])
            };

            const weaveGroup = new THREE.Group();
            weaveGroup.add(meshes[1]);
            weaveGroup.add(meshes[2]);
            weaveGroup.add(meshes[3]);
            scene.add(weaveGroup);

            state.onColorChange = (idx, colorNum) => {
                if (materials[idx]) {
                    materials[idx].color.setHex(colorNum);
                }
            };

            let clock = new THREE.Clock();
            function animate() {
                requestAnimationFrame(animate);
                if (state.isPlaying) {
                    const delta = clock.getDelta();
                    const rotSpeed = 0.55 * state.speedMultiplier;
                    weaveGroup.rotation.x += delta * rotSpeed;
                    weaveGroup.rotation.y = Math.sin(clock.getElapsedTime() * 0.4) * 0.15;
                }
                renderer.render(scene, camera);
            }
            animate();

            window.addEventListener('resize', () => {
                const w = canvas.parentElement.clientWidth || 900;
                camera.aspect = w / height;
                camera.updateProjectionMatrix();
                renderer.setSize(w, height);
            });
        }

        // --- 2D Procedural Atelier Fallback ---
        function init2DStudio(canvas, width, height, state) {
            const ctx = canvas.getContext('2d');
            if (!ctx) return;

            canvas.width = width;
            canvas.height = height;

            let time = 0;
            function render2D() {
                requestAnimationFrame(render2D);
                if (state.isPlaying) {
                    time += 0.025 * state.speedMultiplier;
                }

                ctx.clearRect(0, 0, width, height);

                // Subtle ambient gradient background
                const gradBg = ctx.createRadialGradient(width / 2, height / 2, 50, width / 2, height / 2, width / 2);
                gradBg.addColorStop(0, 'rgba(14, 48, 36, 0.5)');
                gradBg.addColorStop(1, 'rgba(6, 20, 15, 0.95)');
                ctx.fillStyle = gradBg;
                ctx.fillRect(0, 0, width, height);

                // Draw 3 flowing intertwined silk strands
                const strands = [
                    { css: state.strandSelections[1].css, phase: 0, lineWidth: 16, radius: 65 },
                    { css: state.strandSelections[2].css, phase: (Math.PI * 2) / 3, lineWidth: 20, radius: 75 },
                    { css: state.strandSelections[3].css, phase: (Math.PI * 4) / 3, lineWidth: 14, radius: 60 }
                ];

                strands.forEach((s) => {
                    ctx.beginPath();
                    ctx.lineWidth = s.lineWidth;
                    ctx.strokeStyle = s.css;
                    ctx.shadowColor = s.css;
                    ctx.shadowBlur = 16;
                    ctx.lineCap = 'round';
                    ctx.lineJoin = 'round';

                    for (let x = 0; x <= width; x += 4) {
                        const u = x / width;
                        const angle = u * Math.PI * 2 * 3.5 + s.phase + time;
                        const y = height / 2 + Math.sin(angle) * s.radius;
                        if (x === 0) ctx.moveTo(x, y);
                        else ctx.lineTo(x, y);
                    }
                    ctx.stroke();
                });

                ctx.shadowBlur = 0;
            }
            render2D();

            window.addEventListener('resize', () => {
                const w = canvas.parentElement.clientWidth || 900;
                canvas.width = w;
                canvas.height = height;
            });
        }
    });
})();
