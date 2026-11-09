/**
 * ATELIER 3D WORLD — Three.js Cinematic Background & Camera Rig
 * Tulsa Wears High-End Fashion Experience
 */

(function () {
    'use strict';

    // Check prefers-reduced-motion
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Canvas container setup
    let canvasContainer, renderer, scene, camera;
    let fabricMesh, particlesMesh;
    let width = window.innerWidth;
    let height = window.innerHeight;
    let mouse = { x: 0, y: 0, targetX: 0, targetY: 0 };
    let scrollProgress = 0;
    let clock = new THREE.Clock();

    function initThreeWorld() {
        if (window.innerWidth < 768) {
            return;
        }
        canvasContainer = document.getElementById('three-canvas-container');
        if (!canvasContainer) {
            canvasContainer = document.createElement('div');
            canvasContainer.id = 'three-canvas-container';
            canvasContainer.style.position = 'fixed';
            canvasContainer.style.top = '0';
            canvasContainer.style.left = '0';
            canvasContainer.style.width = '100vw';
            canvasContainer.style.height = '100vh';
            canvasContainer.style.pointerEvents = 'none';
            canvasContainer.style.zIndex = '0';
            canvasContainer.style.overflow = 'hidden';
            document.body.prepend(canvasContainer);
        }

        // Scene
        scene = new THREE.Scene();
        scene.fog = new THREE.FogExp2(0x181615, 0.015);

        // Camera
        camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
        camera.position.set(0, 0, 18);

        // Renderer
        renderer = new THREE.WebGLRenderer({ alpha: true, antialias: window.innerWidth >= 768, powerPreference: 'high-performance' });
        renderer.setSize(width, height);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, window.innerWidth < 768 ? 1.0 : 1.5));
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.1;
        canvasContainer.appendChild(renderer.domElement);

        // IntersectionObserver to pause rendering when off-screen
        let isHeroInView = true;
        if ('IntersectionObserver' in window) {
            const heroObserver = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    isHeroInView = entry.isIntersecting;
                });
            }, { threshold: 0.05 });
            heroObserver.observe(canvasContainer);
        }

        // Lighting
        const ambientLight = new THREE.AmbientLight(0xf5f0e8, 0.7);
        scene.add(ambientLight);

        const keyLight = new THREE.DirectionalLight(0xfff3e0, 1.4);
        keyLight.position.set(5, 8, 10);
        scene.add(keyLight);

        const rimLight = new THREE.DirectionalLight(0xc9a96e, 1.2);
        rimLight.position.set(-8, -4, -5);
        scene.add(rimLight);

        const wineLight = new THREE.PointLight(0x681f2e, 2.5, 30);
        wineLight.position.set(0, -6, 4);
        scene.add(wineLight);

        // Build 3D Objects
        createProceduralFabric();
        createAmbientParticles();

        // Event Listeners
        window.addEventListener('resize', onWindowResize, { passive: true });
        window.addEventListener('mousemove', onMouseMove, { passive: true });
        window.addEventListener('scroll', onScrollUpdate, { passive: true });

        // Start Animation Loop
        animate();
    }

    /**
     * Procedural Silk Fabric Mesh using Sine Waves & Sheen Material
     */
    function createProceduralFabric() {
        const segX = window.innerWidth < 768 ? 30 : 60;
        const segY = window.innerWidth < 768 ? 30 : 60;
        const geometry = new THREE.PlaneGeometry(28, 16, segX, segY);

        // High luxury silk material
        const material = new THREE.MeshPhysicalMaterial({
            color: 0x221815,
            emissive: 0x0a0505,
            roughness: 0.32,
            metalness: 0.15,
            clearcoat: 0.6,
            clearcoatRoughness: 0.25,
            sheen: 1.0,
            sheenColor: new THREE.Color(0xd7c5b1),
            side: THREE.DoubleSide,
            wireframe: false,
            transparent: true,
            opacity: 0.85
        });

        fabricMesh = new THREE.Mesh(geometry, material);
        fabricMesh.position.set(0, 0, -4);
        fabricMesh.rotation.x = -0.35;
        scene.add(fabricMesh);

        // Store original position coordinates for wave deformation
        geometry.userData = {
            posArray: geometry.attributes.position.array.slice()
        };
    }

    /**
     * Ambient Gold & Fiber Particles
     */
    function createAmbientParticles() {
        const count = window.innerWidth < 768 ? 80 : 250;
        const particleGeo = new THREE.BufferGeometry();
        const positions = new Float32Array(count * 3);
        const scales = new Float32Array(count);

        for (let i = 0; i < count; i++) {
            positions[i * 3] = (Math.random() - 0.5) * 35;
            positions[i * 3 + 1] = (Math.random() - 0.5) * 25;
            positions[i * 3 + 2] = (Math.random() - 0.5) * 20;
            scales[i] = Math.random() * 0.8 + 0.2;
        }

        particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        particleGeo.setAttribute('scale', new THREE.BufferAttribute(scales, 1));

        // Canvas circular particle texture
        const pCanvas = document.createElement('canvas');
        pCanvas.width = 32;
        pCanvas.height = 32;
        const ctx = pCanvas.getContext('2d');
        const grad = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
        grad.addColorStop(0, 'rgba(215, 197, 177, 0.9)');
        grad.addColorStop(0.5, 'rgba(201, 169, 110, 0.4)');
        grad.addColorStop(1, 'rgba(24, 22, 21, 0)');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, 32, 32);

        const pTexture = new THREE.CanvasTexture(pCanvas);
        const particleMat = new THREE.PointsMaterial({
            size: 0.35,
            map: pTexture,
            transparent: true,
            opacity: 0.65,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });

        particlesMesh = new THREE.Points(particleGeo, particleMat);
        scene.add(particlesMesh);
    }

    function onMouseMove(e) {
        mouse.targetX = (e.clientX / width - 0.5) * 2;
        mouse.targetY = -(e.clientY / height - 0.5) * 2;
    }

    function onScrollUpdate() {
        const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
        if (maxScroll > 0) {
            scrollProgress = window.scrollY / maxScroll;
        }
    }

    function onWindowResize() {
        width = window.innerWidth;
        height = window.innerHeight;
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height);
    }

    function animate() {
        requestAnimationFrame(animate);

        // Pause WebGL rendering when scrolled away from hero or in background to save GPU & eliminate lag
        if (!isHeroInView || window.scrollY > window.innerHeight * 1.1 || document.hidden || window.innerWidth < 768) {
            return;
        }

        const elapsedTime = clock.getElapsedTime();

        // Smooth mouse damping
        mouse.x += (mouse.targetX - mouse.x) * 0.05;
        mouse.y += (mouse.targetY - mouse.y) * 0.05;

        // Camera subtle sway and scroll tracking
        if (!prefersReducedMotion) {
            camera.position.x = mouse.x * 1.2;
            camera.position.y = mouse.y * 0.8 - scrollProgress * 6;
            camera.lookAt(0, -scrollProgress * 6, 0);

            // Deform Fabric Waves
            if (fabricMesh && fabricMesh.geometry) {
                const pos = fabricMesh.geometry.attributes.position;
                const orig = fabricMesh.geometry.userData.posArray;

                for (let i = 0; i < pos.count; i++) {
                    const u = orig[i * 3];
                    const v = orig[i * 3 + 1];

                    // Combined slow waves for luxurious organic drape
                    const wave1 = Math.sin(u * 0.25 + elapsedTime * 0.8) * 0.8;
                    const wave2 = Math.cos(v * 0.35 + elapsedTime * 0.6) * 0.6;
                    const ripple = Math.sin((u + v) * 0.2 + elapsedTime * 1.1) * 0.3;

                    pos.array[i * 3 + 2] = orig[i * 3 + 2] + wave1 + wave2 + ripple;
                }
                pos.needsUpdate = true;
                fabricMesh.rotation.z = Math.sin(elapsedTime * 0.15) * 0.04;
            }

            // Slowly orbit particles
            if (particlesMesh) {
                particlesMesh.rotation.y = elapsedTime * 0.03;
                particlesMesh.rotation.x = Math.sin(elapsedTime * 0.02) * 0.05;
            }
        }

        renderer.render(scene, camera);
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initThreeWorld);
    } else {
        initThreeWorld();
    }
})();


/**
 * =====================================================
 * THREE SILKS, ONE WEAVE — INTERACTIVE SILK WEAVING STUDIO
 * Inspired by Reference Video 4 (Three dynamic interwoven silk ribbons twisting in real-time,
 * dynamic spool selection, metallic luster, and live bespoke pricing).
 * =====================================================
 */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', () => {
        const canvas = document.getElementById('weaveCanvas');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        let width, height;
        function resizeCanvas() {
            const rect = canvas.getBoundingClientRect();
            width = canvas.width = rect.width * (window.devicePixelRatio || 1);
            height = canvas.height = rect.height * (window.devicePixelRatio || 1);
        }
        resizeCanvas();
        window.addEventListener('resize', resizeCanvas, { passive: true });

        // Silk Spool Colors
        let warpColor = '#1A3D68'; // Kanjeevaram Indigo
        let weftColor = '#C2185B'; // Rani Pink
        let zariColor = '#DFC187'; // Antique Gold Zari

        let warpName = 'Kanjeevaram Indigo';
        let weftName = 'Rani Silk';
        let zariName = 'Antique Gold Zari';
        let basePrice = 6800;

        const spoolCircles = document.querySelectorAll('.spool-swatch-circle');
        const weaveTitle = document.getElementById('weaveTitle');
        const weavePrice = document.getElementById('weavePrice');
        const btnCommissionWeave = document.getElementById('btnCommissionWeave');

        function updateWeaveSummary() {
            if (weaveTitle) {
                weaveTitle.innerHTML = `Bespoke <em>${warpName}</em> &amp; <em>${weftName}</em> with ${zariName}`;
            }
            if (weavePrice) {
                weavePrice.textContent = `₹${basePrice.toLocaleString('en-IN')}`;
            }
            if (btnCommissionWeave) {
                btnCommissionWeave.dataset.warp = warpName;
                btnCommissionWeave.dataset.weft = weftName;
                btnCommissionWeave.dataset.zari = zariName;
                btnCommissionWeave.dataset.price = basePrice;
            }
        }

        spoolCircles.forEach(circle => {
            circle.addEventListener('click', () => {
                const type = circle.dataset.spoolType; // warp, weft, zari
                const parent = circle.closest('.spool-options-grid');
                if (parent) {
                    parent.querySelectorAll('.spool-swatch-circle').forEach(c => c.classList.remove('active'));
                }
                circle.classList.add('active');

                const color = circle.dataset.color;
                const name = circle.dataset.name;
                const priceAdd = Number(circle.dataset.priceAdd || 0);

                if (type === 'warp') {
                    warpColor = color;
                    warpName = name;
                } else if (type === 'weft') {
                    weftColor = color;
                    weftName = name;
                } else if (type === 'zari') {
                    zariColor = color;
                    zariName = name;
                }

                // Dynamic price recalculation
                basePrice = 6200 + (type === 'zari' && name.includes('Silver') ? 950 : 600) + priceAdd;
                updateWeaveSummary();
            });
        });

        // Commission Button click opens custom order modal with prefilled data
        if (btnCommissionWeave) {
            btnCommissionWeave.addEventListener('click', (e) => {
                e.preventDefault();
                const customModal = document.getElementById('customOrderModal') || document.querySelector('.bespoke-modal');
                if (customModal) {
                    customModal.style.display = 'block';
                    const fabricInput = document.getElementById('coFabric') || document.querySelector('[name="fabric_preference"]');
                    const notesInput = document.getElementById('coNotes') || document.querySelector('[name="notes"]');
                    if (fabricInput) {
                        fabricInput.value = `${warpName} blended with ${weftName} & ${zariName}`;
                    }
                    if (notesInput) {
                        notesInput.value = `Three Silks One Weave Bespoke Commission (${warpName} + ${weftName} + ${zariName}). Estimated ₹${basePrice}.`;
                    }
                    customModal.scrollIntoView({ behavior: 'smooth' });
                } else {
                    window.location.href = '#contact';
                }
            });
        }

        // Animation Loop for 3D Twisting Braided Silk Ribbons
        let time = 0;
        function renderWeave() {
            requestAnimationFrame(renderWeave);

            // Optimization: skip rendering when canvas is off-screen
            const rect = canvas.getBoundingClientRect();
            if (rect.bottom < 0 || rect.top > window.innerHeight) {
                return;
            }

            ctx.clearRect(0, 0, width, height);

            const dpr = window.devicePixelRatio || 1;
            const centerY = height / 2;
            const points = 120;
            const waveLength = width * 0.45;
            const amplitude = height * 0.28;
            const ribbonWidth = 28 * dpr;

            time += 0.025;

            // Helper to draw a single sinusoidal undulating silk ribbon strand
            function drawSilkRibbon(colorHex, phaseOffset, thicknessMod, isMetallic) {
                ctx.save();

                // Compute points for top and bottom edge of ribbon
                const topEdge = [];
                const bottomEdge = [];

                for (let i = 0; i <= points; i++) {
                    const x = (i / points) * width;
                    const angle = (x / waveLength) * Math.PI * 2 + time + phaseOffset;
                    const y = centerY + Math.sin(angle) * amplitude;
                    const cosA = Math.cos(angle);
                    const effectiveThickness = ribbonWidth * thicknessMod * (0.6 + 0.4 * Math.abs(cosA));

                    topEdge.push({ x, y: y - effectiveThickness / 2 });
                    bottomEdge.push({ x, y: y + effectiveThickness / 2 });
                }

                // Create gradient along ribbon
                const grad = ctx.createLinearGradient(0, centerY - amplitude, 0, centerY + amplitude);
                grad.addColorStop(0, colorHex);
                grad.addColorStop(0.5, isMetallic ? '#FFF4D6' : colorHex);
                grad.addColorStop(1, colorHex);

                ctx.beginPath();
                ctx.moveTo(topEdge[0].x, topEdge[0].y);
                for (let i = 1; i <= points; i++) {
                    ctx.lineTo(topEdge[i].x, topEdge[i].y);
                }
                for (let i = points; i >= 0; i--) {
                    ctx.lineTo(bottomEdge[i].x, bottomEdge[i].y);
                }
                ctx.closePath();

                ctx.fillStyle = grad;
                ctx.shadowColor = colorHex;
                ctx.shadowBlur = isMetallic ? 20 * dpr : 10 * dpr;
                ctx.globalAlpha = 0.92;
                ctx.fill();

                // Center highlight spine line
                ctx.beginPath();
                ctx.moveTo(topEdge[0].x, (topEdge[0].y + bottomEdge[0].y) / 2);
                for (let i = 1; i <= points; i++) {
                    ctx.lineTo(topEdge[i].x, (topEdge[i].y + bottomEdge[i].y) / 2);
                }
                ctx.strokeStyle = isMetallic ? 'rgba(255, 255, 255, 0.7)' : 'rgba(255, 255, 255, 0.35)';
                ctx.lineWidth = 2 * dpr;
                ctx.stroke();

                ctx.restore();
            }

            // Draw three interbraiding silk ribbons with 120-deg (2*PI/3) phase shift
            drawSilkRibbon(warpColor, 0, 1.0, false);
            drawSilkRibbon(weftColor, (Math.PI * 2) / 3, 0.95, false);
            drawSilkRibbon(zariColor, (Math.PI * 4) / 3, 0.85, true);
        }

        renderWeave();
        updateWeaveSummary();
    });
})();
