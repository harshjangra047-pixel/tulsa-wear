/* =====================================================
   ATELIER — Cinematic Interaction System
   =====================================================
   Scroll reveals, sticky nav, parallax, product rails
===================================================== */

document.addEventListener("DOMContentLoaded", () => {


    /* =========================================
       STICKY NAVBAR — transparent → solid
    ========================================== */

    const navbar = document.querySelector(".navbar");

    if (navbar) {
        const onScroll = () => {
            if (window.scrollY > 60) {
                navbar.classList.add("scrolled");
            } else {
                navbar.classList.remove("scrolled");
            }
        };
        window.addEventListener("scroll", onScroll, { passive: true });
        onScroll();
    }


    /* =========================================
       MOBILE MENU
    ========================================== */

    const menuButton = document.getElementById("menuButton");
    const navLinks = document.getElementById("navLinks");

    if (menuButton && navLinks) {
        menuButton.addEventListener("click", () => {
            const isOpen = navLinks.classList.toggle("mobile-open");
            menuButton.setAttribute("aria-expanded", isOpen);
            menuButton.innerHTML = isOpen ? "✕" : "☰";
        });

        navLinks.querySelectorAll("a").forEach((item) => {
            item.addEventListener("click", () => {
                navLinks.classList.remove("mobile-open");
                menuButton.setAttribute("aria-expanded", "false");
                menuButton.innerHTML = "☰";
            });
        });
    }


    /* =========================================
       HERO — Cinematic entrance
    ========================================== */

    const hero = document.querySelector(".hero");
    if (hero) {
        // Trigger slow zoom after load
        requestAnimationFrame(() => {
            hero.classList.add("loaded");
        });
    }


    /* =========================================
       SCROLL REVEAL — IntersectionObserver
    ========================================== */

    const revealElements = document.querySelectorAll(".reveal, .reveal-scale");

    if (revealElements.length > 0 && "IntersectionObserver" in window) {
        const revealObserver = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add("visible");
                        revealObserver.unobserve(entry.target);
                    }
                });
            },
            {
                threshold: 0.12,
                rootMargin: "0px 0px -40px 0px"
            }
        );

        revealElements.forEach((el) => revealObserver.observe(el));
    } else {
        // Fallback — show everything
        revealElements.forEach((el) => el.classList.add("visible"));
    }


    /* =========================================
       FAQ ACCORDION
    ========================================== */

    const faqItems = document.querySelectorAll(".faq-item");

    faqItems.forEach((item) => {
        item.addEventListener("click", () => {
            const answer = item.nextElementSibling;
            const isOpen = answer.classList.toggle("open");
            item.classList.toggle("active", isOpen);

            // Close others
            faqItems.forEach((other) => {
                if (other !== item) {
                    other.classList.remove("active");
                    other.nextElementSibling.classList.remove("open");
                }
            });
        });
    });


    /* =========================================
       NEWSLETTER
    ========================================== */

    const newsletter = document.querySelector(".newsletter-form");

    if (newsletter) {
        newsletter.addEventListener("submit", (e) => {
            e.preventDefault();
            const input = newsletter.querySelector("input[type='email']");
            const btn = newsletter.querySelector("button");

            if (input && input.value.trim()) {
                btn.textContent = "Subscribed ✓";
                btn.style.opacity = "0.6";
                input.value = "";
                setTimeout(() => {
                    btn.textContent = "Subscribe →";
                    btn.style.opacity = "1";
                }, 3000);
            }
        });
    }


    /* =========================================
       RATING STARS (feedback form)
    ========================================== */

    const ratingButtons = document.querySelectorAll(".rating button");
    const ratingInput = document.getElementById("ratingValue");

    ratingButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            const value = parseInt(btn.getAttribute("data-rating"));
            if (ratingInput) ratingInput.value = value;

            ratingButtons.forEach((b, i) => {
                b.classList.toggle("active", i < value);
            });
        });
    });


    /* =========================================
       FEEDBACK FORM SUBMISSION
    ========================================== */

    const feedbackForm = document.getElementById("feedbackForm");

    if (feedbackForm) {
        feedbackForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const success = document.getElementById("feedbackSuccess");
            const name = document.getElementById("feedbackName")?.value?.trim();
            const email = document.getElementById("feedbackEmail")?.value?.trim();
            const rating = document.getElementById("ratingValue")?.value;
            const message = document.getElementById("feedbackMessage")?.value?.trim();

            if (!name || !message || !rating || rating === "0") {
                if (success) {
                    success.textContent = "Please fill in your name, rating, and message.";
                    success.style.color = "#c62828";
                }
                return;
            }

            try {
                const res = await fetch("/api/feedback", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name, email, rating: parseInt(rating), message })
                });
                const data = await res.json();
                if (success) {
                    success.textContent = data.message || "Thank you for your feedback.";
                    success.style.color = "#2e7d32";
                }
                feedbackForm.reset();
                ratingButtons.forEach((b) => b.classList.remove("active"));
            } catch (err) {
                if (success) {
                    success.textContent = "Something went wrong. Please try again.";
                    success.style.color = "#c62828";
                }
            }
        });
    }


    /* =========================================
       AI STYLE STUDIO
    ========================================== */

    const aiForm = document.getElementById("aiStylistForm");
    const aiInput = document.getElementById("aiStylistInput");
    const aiLoading = document.getElementById("aiLoading");
    const aiResultContainer = document.getElementById("aiResultContainer");
    const aiResponseMessage = document.getElementById("aiResponseMessage");
    const aiProductsGrid = document.getElementById("aiProductsGrid");

    // Quick prompt chips
    const aiChips = document.querySelectorAll(".ai-chip");
    aiChips.forEach((chip) => {
        chip.addEventListener("click", () => {
            if (aiInput) {
                aiInput.value = chip.textContent.trim();
                aiInput.focus();
            }
        });
    });

    if (aiForm) {
        aiForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const query = aiInput?.value?.trim();
            if (!query) return;

            if (aiLoading) aiLoading.style.display = "block";
            if (aiResultContainer) aiResultContainer.style.display = "none";

            try {
                const res = await fetch("/api/ai-stylist", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ query })
                });
                const data = await res.json();

                if (aiLoading) aiLoading.style.display = "none";

                if (data.message && aiResponseMessage) {
                    aiResponseMessage.textContent = data.message;
                }

                if (aiProductsGrid && data.products) {
                    aiProductsGrid.innerHTML = data.products.map((p) => `
                        <a href="/product/${p.id}" style="display:block; text-decoration:none; color:inherit;">
                            <div style="height:280px; overflow:hidden; background:var(--bg-cream); margin-bottom:12px;">
                                ${p.image ? `<img src="/static/images/${p.image}" alt="${p.name}" style="width:100%; height:100%; object-fit:cover;">` : ""}
                            </div>
                            <small class="product-category">${p.category || ""}</small>
                            <h3 style="font-size:18px; margin-bottom:4px;">${p.name}</h3>
                            <p class="product-price">₹${Number(p.price).toLocaleString("en-IN")}</p>
                        </a>
                    `).join("");
                }

                if (aiResultContainer) aiResultContainer.style.display = "block";
            } catch (err) {
                if (aiLoading) aiLoading.style.display = "none";
                if (aiResponseMessage) {
                    aiResponseMessage.textContent = "The stylist is currently unavailable. Please try again.";
                }
                if (aiResultContainer) aiResultContainer.style.display = "block";
            }
        });
    }

    // AI Visual Search — Photo Upload
    const aiPhotoInput = document.getElementById("aiPhotoInput");
    const aiVisualScanBox = document.getElementById("aiVisualScanBox");
    const aiVisualScanPreview = document.getElementById("aiVisualScanPreview");

    if (aiPhotoInput) {
        aiPhotoInput.addEventListener("change", async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            // Show preview
            if (aiVisualScanPreview) {
                aiVisualScanPreview.src = URL.createObjectURL(file);
            }
            if (aiVisualScanBox) aiVisualScanBox.style.display = "block";

            // Upload to AI visual search
            const formData = new FormData();
            formData.append("image", file);

            try {
                const res = await fetch("/api/ai-visual-search", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();
                const msgEl = document.getElementById("aiVisualMessage");
                if (msgEl && data.message) {
                    msgEl.textContent = data.message;
                }
            } catch (err) {
                // Handled silently
            }
        });
    }

    // Bespoke from scan button
    const btnBespokeFromScan = document.getElementById("btnBespokeFromScan");
    if (btnBespokeFromScan) {
        btnBespokeFromScan.addEventListener("click", () => {
            const modal = document.getElementById("customModal");
            if (modal) {
                modal.style.display = "flex";
                document.body.style.overflow = "hidden";

                // Pre-fill with uploaded image if available
                if (aiVisualScanPreview?.src) {
                    const preloaded = document.getElementById("coPreloadedImage");
                    if (preloaded) preloaded.value = aiVisualScanPreview.src;
                    const previewBox = document.getElementById("coImagePreviewBox");
                    const previewThumb = document.getElementById("coImagePreviewThumb");
                    if (previewBox && previewThumb) {
                        previewThumb.src = aiVisualScanPreview.src;
                        previewBox.style.display = "flex";
                    }
                }
            }
        });
    }


    /* =========================================
       CUSTOM ORDER FORM (AJAX)
    ========================================== */

    const customForm = document.getElementById("customOrderForm");
    if (customForm) {
        customForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const submitBtn = document.getElementById("coSubmitBtn");
            const responseEl = document.getElementById("coResponse");

            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = "Submitting...";
            }

            try {
                const formData = new FormData(customForm);
                const res = await fetch(customForm.action, {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();
                if (responseEl) {
                    responseEl.textContent = data.message || "Your bespoke inquiry has been received.";
                    responseEl.style.color = data.success ? "#2e7d32" : "#c62828";
                }
                if (data.success) customForm.reset();
            } catch (err) {
                if (responseEl) {
                    responseEl.textContent = "Something went wrong. Please try again.";
                    responseEl.style.color = "#c62828";
                }
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = "Submit Bespoke Inquiry →";
                }
            }
        });
    }

    // Custom order reference image preview
    const coRefImage = document.getElementById("coReferenceImage");
    if (coRefImage) {
        coRefImage.addEventListener("change", (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const previewBox = document.getElementById("coImagePreviewBox");
            const previewThumb = document.getElementById("coImagePreviewThumb");
            if (previewBox && previewThumb) {
                previewThumb.src = URL.createObjectURL(file);
                previewBox.style.display = "flex";
            }
        });
    }


    /* =========================================
       PRODUCT DETAIL — AI Q&A
    ========================================== */

    const aiProductForm = document.getElementById("aiProductQAForm");
    if (aiProductForm) {
        aiProductForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const input = document.getElementById("aiProductQuestion");
            const result = document.getElementById("aiProductAnswer");
            const productId = aiProductForm.dataset.productId;

            if (!input?.value?.trim() || !productId) return;

            if (result) result.textContent = "Thinking...";

            try {
                const res = await fetch(`/api/ai-product-qa/${productId}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ question: input.value.trim() })
                });
                const data = await res.json();
                if (result) result.textContent = data.answer || "I couldn't find an answer right now.";
            } catch {
                if (result) result.textContent = "The AI assistant is currently unavailable.";
            }
        });
    }

});