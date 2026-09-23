import { useEffect, useRef } from "react";

interface DottedGridProps {
  className?: string;
  paused?: boolean;
}

interface TrailPoint {
  x: number;
  y: number;
  createdAt: number;
}

/**
 * A restrained operations-console adaptation of ObsidianUI's MIT-licensed
 * Dotted Grid. It retains the responsive canvas field and cursor trail while
 * removing decorative shape cycling so the visual never implies system data.
 * https://www.obsidianui.dev/docs/dotted-grid
 */
export function DottedGrid({ className = "", paused = false }: DottedGridProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const surface = canvas?.parentElement;
    if (!canvas || !surface) return;
    if (navigator.userAgent.toLowerCase().includes("jsdom")) return;

    const context = canvas.getContext("2d");
    if (!context) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const pointer = { x: -1000, y: -1000, active: false };
    const trail: TrailPoint[] = [];
    let width = 1;
    let height = 1;
    let frame = 0;
    let dotColor = "rgba(148, 163, 184, .2)";
    let signalColor = "56, 189, 248";

    const readColors = () => {
      const styles = getComputedStyle(document.documentElement);
      dotColor = styles.getPropertyValue("--grid-dot").trim() || "rgba(148, 163, 184, .2)";
      signalColor = styles.getPropertyValue("--grid-signal-rgb").trim() || "56, 189, 248";
    };

    const resize = () => {
      const rect = surface.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      readColors();
    };

    const draw = (time: number) => {
      context.clearRect(0, 0, width, height);
      const spacing = width < 520 ? 22 : 26;
      const now = performance.now();
      while (trail.length && now - trail[0].createdAt > 850) trail.shift();

      for (let y = spacing / 2; y < height; y += spacing) {
        for (let x = spacing / 2; x < width; x += spacing) {
          let influence = 0;
          if (!paused && !reducedMotion.matches) {
            if (pointer.active) {
              const distance = Math.hypot(x - pointer.x, y - pointer.y);
              influence = Math.max(influence, 1 - distance / 150);
            }
            for (let index = trail.length - 1; index >= Math.max(0, trail.length - 18); index -= 1) {
              const point = trail[index];
              const age = (now - point.createdAt) / 850;
              const distance = Math.hypot(x - point.x, y - point.y);
              influence = Math.max(influence, Math.max(0, 1 - distance / 80) * (1 - age) * 0.58);
            }
          }

          const wave = paused || reducedMotion.matches ? 0 : (Math.sin(time * 0.0007 + x * 0.012 + y * 0.009) + 1) * 0.08;
          const alpha = Math.min(0.92, Math.max(0, influence) * 0.78 + wave);
          context.beginPath();
          context.fillStyle = alpha > 0.12 ? `rgba(${signalColor}, ${alpha})` : dotColor;
          context.arc(x, y, 1 + Math.max(0, influence) * 1.35, 0, Math.PI * 2);
          context.fill();
        }
      }

      if (!paused && !reducedMotion.matches) frame = requestAnimationFrame(draw);
    };

    const handlePointerMove = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      pointer.x = event.clientX - rect.left;
      pointer.y = event.clientY - rect.top;
      pointer.active = true;
      trail.push({ x: pointer.x, y: pointer.y, createdAt: performance.now() });
      if (trail.length > 30) trail.shift();
    };
    const handlePointerLeave = () => { pointer.active = false; };
    const handleMotionChange = () => {
      cancelAnimationFrame(frame);
      draw(performance.now());
      if (!paused && !reducedMotion.matches) frame = requestAnimationFrame(draw);
    };

    resize();
    draw(performance.now());
    if (!paused && !reducedMotion.matches) frame = requestAnimationFrame(draw);

    const resizeObserver = new ResizeObserver(resize);
    const themeObserver = new MutationObserver(() => { readColors(); });
    resizeObserver.observe(surface);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    reducedMotion.addEventListener("change", handleMotionChange);
    canvas.addEventListener("pointermove", handlePointerMove);
    canvas.addEventListener("pointerleave", handlePointerLeave);

    return () => {
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      themeObserver.disconnect();
      reducedMotion.removeEventListener("change", handleMotionChange);
      canvas.removeEventListener("pointermove", handlePointerMove);
      canvas.removeEventListener("pointerleave", handlePointerLeave);
    };
  }, [paused]);

  return <canvas ref={canvasRef} className={`obsidian-dotted-grid ${className}`.trim()} aria-hidden="true" />;
}
