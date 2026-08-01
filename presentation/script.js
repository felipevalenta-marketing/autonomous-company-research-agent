(() => {
  "use strict";

  const slides = Array.from(document.querySelectorAll(".slide"));
  const total = slides.length;
  const dotsContainer = document.getElementById("nav-dots");
  const counterEl = document.getElementById("slide-counter");
  const progressFill = document.getElementById("progress-fill");
  const presentToggle = document.getElementById("present-toggle");

  let activeIndex = 0;

  // Build nav dots
  slides.forEach((slide, i) => {
    const dot = document.createElement("button");
    dot.type = "button";
    dot.setAttribute("role", "tab");
    dot.setAttribute("aria-label", `Go to slide ${i + 1}: ${slide.dataset.title || ""}`);
    dot.addEventListener("click", () => goToSlide(i));
    dotsContainer.appendChild(dot);
  });
  const dots = Array.from(dotsContainer.children);

  function updateActive(index) {
    activeIndex = index;
    dots.forEach((dot, i) => dot.setAttribute("aria-current", String(i === index)));
    counterEl.textContent = `${String(index + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
    progressFill.style.width = `${((index + 1) / total) * 100}%`;
  }

  function goToSlide(index) {
    const clamped = Math.max(0, Math.min(total - 1, index));
    slides[clamped].scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Track which slide is in view
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && entry.intersectionRatio >= 0.5) {
          const index = slides.indexOf(entry.target);
          if (index !== -1) updateActive(index);
        }
      });
    },
    { threshold: [0.5] }
  );
  slides.forEach((slide) => observer.observe(slide));

  // Keyboard navigation
  window.addEventListener("keydown", (event) => {
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
      case " ":
        event.preventDefault();
        goToSlide(activeIndex + 1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        goToSlide(activeIndex - 1);
        break;
      case "Home":
        event.preventDefault();
        goToSlide(0);
        break;
      case "End":
        event.preventDefault();
        goToSlide(total - 1);
        break;
      default:
        break;
    }
  });

  // Presentation mode toggle (hides chrome until hovered)
  presentToggle.addEventListener("click", () => {
    const isPresenting = document.body.classList.toggle("is-presenting");
    presentToggle.setAttribute("aria-pressed", String(isPresenting));
  });

  updateActive(0);

  // ---------------------------------------------------------------
  // Subtle animated network background (decorative, reduced-motion aware)
  // ---------------------------------------------------------------
  const canvas = document.getElementById("bg-canvas");
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (canvas && !prefersReducedMotion) {
    const ctx = canvas.getContext("2d");
    let width, height, nodes;
    const NODE_COUNT = 46;
    const LINK_DISTANCE = 150;

    function resize() {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    }

    function initNodes() {
      nodes = Array.from({ length: NODE_COUNT }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
      }));
    }

    function step() {
      ctx.clearRect(0, 0, width, height);

      nodes.forEach((node) => {
        node.x += node.vx;
        node.y += node.vy;
        if (node.x < 0 || node.x > width) node.vx *= -1;
        if (node.y < 0 || node.y > height) node.vy *= -1;
      });

      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.hypot(dx, dy);
          if (dist < LINK_DISTANCE) {
            ctx.strokeStyle = `rgba(59, 130, 246, ${0.14 * (1 - dist / LINK_DISTANCE)})`;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }

      nodes.forEach((node) => {
        ctx.fillStyle = "rgba(34, 211, 238, 0.55)";
        ctx.beginPath();
        ctx.arc(node.x, node.y, 1.6, 0, Math.PI * 2);
        ctx.fill();
      });

      requestAnimationFrame(step);
    }

    resize();
    initNodes();
    requestAnimationFrame(step);
    window.addEventListener("resize", () => {
      resize();
      initNodes();
    });
  }
})();
