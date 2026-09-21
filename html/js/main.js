/* Galileo project site — Copyright (C) 2025-2026 Gord Tulloch. GPL-3.0-or-later. */
(function () {
  'use strict';

  var root = document.documentElement;
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function store(key, value) {
    try { value === undefined ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch (e) { /* storage blocked */ }
  }

  /* ---------- Header: solid background once scrolled, mobile menu ---------- */
  var header = document.querySelector('.site-header');
  function onScroll() { header.classList.toggle('scrolled', window.scrollY > 8); }
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  var menuBtn = document.getElementById('menu');
  var links = document.getElementById('nav-links');
  function setMenu(open) {
    links.classList.toggle('open', open);
    menuBtn.setAttribute('aria-expanded', String(open));
    menuBtn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  }
  menuBtn.addEventListener('click', function () { setMenu(!links.classList.contains('open')); });
  links.addEventListener('click', function (e) { if (e.target.closest('a')) setMenu(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setMenu(false); });

  /* ---------- Night-vision (red) theme ---------- */
  var nightBtn = document.getElementById('night');
  var starColor = '232, 237, 247';
  function readStarColor() {
    var v = getComputedStyle(root).getPropertyValue('--star').trim();
    if (v) starColor = v;
  }
  function setNight(on) {
    if (on) root.dataset.theme = 'night'; else delete root.dataset.theme;
    nightBtn.setAttribute('aria-pressed', String(on));
    store('galileo-theme', on ? 'night' : undefined);
    readStarColor();
    if (reduceMotion) drawStars(0);
  }
  nightBtn.setAttribute('aria-pressed', String(root.dataset.theme === 'night'));
  nightBtn.addEventListener('click', function () { setNight(root.dataset.theme !== 'night'); });

  /* ---------- Reveal on scroll ---------- */
  var revealEls = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !reduceMotion) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add('in'); });
  }

  /* ---------- Star field ---------- */
  var canvas = document.getElementById('stars');
  var ctx = canvas.getContext('2d');
  var stars = [];
  var w = 0, h = 0, dpr = 1;
  var rafId = 0;

  function seedStars() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    var count = Math.min(320, Math.round((w * h) / 6500));
    stars = [];
    for (var i = 0; i < count; i++) {
      var depth = Math.random();
      stars.push({
        x: Math.random() * w,
        y: Math.random() * h,
        r: 0.35 + depth * 1.15,
        base: 0.25 + depth * 0.6,
        tw: 0.6 + Math.random() * 1.8,
        ph: Math.random() * Math.PI * 2,
        par: 0.02 + depth * 0.10
      });
    }
  }

  function drawStars(t) {
    ctx.clearRect(0, 0, w, h);
    var sy = window.scrollY;
    for (var i = 0; i < stars.length; i++) {
      var s = stars[i];
      var a = reduceMotion ? s.base : s.base * (0.65 + 0.35 * Math.sin(t / 1000 * s.tw + s.ph));
      var y = (((s.y - sy * s.par) % h) + h) % h;
      ctx.fillStyle = 'rgba(' + starColor + ',' + a.toFixed(3) + ')';
      ctx.beginPath();
      ctx.arc(s.x, y, s.r, 0, 6.2832);
      ctx.fill();
    }
  }

  function loop(t) { drawStars(t); rafId = requestAnimationFrame(loop); }

  function startStars() {
    readStarColor();
    seedStars();
    cancelAnimationFrame(rafId);
    if (reduceMotion) { drawStars(0); return; }
    rafId = requestAnimationFrame(loop);
  }
  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(startStars, 150);
  });
  if (reduceMotion) window.addEventListener('scroll', function () { drawStars(0); }, { passive: true });
  document.addEventListener('visibilitychange', function () {
    if (reduceMotion) return;
    if (document.hidden) cancelAnimationFrame(rafId); else rafId = requestAnimationFrame(loop);
  });
  startStars();

  /* ---------- Gallery filter ---------- */
  var tabs = document.querySelectorAll('.tab');
  var shots = Array.prototype.slice.call(document.querySelectorAll('#gallery .shot'));
  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      var f = tab.dataset.filter;
      tabs.forEach(function (t) { t.setAttribute('aria-selected', String(t === tab)); });
      shots.forEach(function (s) { s.hidden = !(f === 'all' || s.dataset.cat === f); });
    });
  });

  /* ---------- Lightbox ---------- */
  var box = document.getElementById('lightbox');
  var lbImg = document.getElementById('lb-img');
  var lbTitle = document.getElementById('lb-title');
  var lbDesc = document.getElementById('lb-desc');
  var openers = Array.prototype.slice.call(document.querySelectorAll('.shot, .shot-open'));
  var current = -1;
  var supportsDialog = typeof box.showModal === 'function';

  function visibleOpeners() { return openers.filter(function (o) { return !o.hidden && o.offsetParent !== null; }); }

  function show(el) {
    lbImg.src = el.dataset.full;
    lbImg.alt = el.dataset.title + ' — ' + el.dataset.desc;
    lbTitle.textContent = el.dataset.title;
    lbDesc.textContent = el.dataset.desc;
    current = el;
  }
  function step(dir) {
    var list = visibleOpeners();
    if (list.length < 2) return;
    var i = list.indexOf(current);
    show(list[(i + dir + list.length) % list.length]);
  }

  if (supportsDialog) {
    openers.forEach(function (el) {
      el.addEventListener('click', function (e) {
        e.preventDefault();
        show(el);
        box.showModal();
      });
    });
    document.getElementById('lb-close').addEventListener('click', function () { box.close(); });
    document.getElementById('lb-prev').addEventListener('click', function () { step(-1); });
    document.getElementById('lb-next').addEventListener('click', function () { step(1); });
    box.addEventListener('click', function (e) { if (e.target === box) box.close(); });
    box.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowLeft') step(-1);
      if (e.key === 'ArrowRight') step(1);
    });
  }

  /* ---------- Install command tabs + copy ---------- */
  var osTabs = document.querySelectorAll('.term-tabs button');
  var cmds = document.querySelectorAll('.term pre');
  function setOS(os) {
    osTabs.forEach(function (b) { b.setAttribute('aria-selected', String(b.dataset.os === os)); });
    cmds.forEach(function (p) { p.hidden = p.dataset.os !== os; });
  }
  osTabs.forEach(function (b) { b.addEventListener('click', function () { setOS(b.dataset.os); }); });
  if (/Mac|Linux|X11|CrOS/i.test(navigator.userAgent) && !/Windows/i.test(navigator.userAgent)) setOS('nix');

  var copyBtn = document.getElementById('copy');
  copyBtn.addEventListener('click', function () {
    var pre = document.querySelector('.term pre:not([hidden])');
    // Copy only the commands: skip comment lines, strip the "$ " prompts.
    var text = pre.textContent.split('\n')
      .filter(function (l) { return l.trim() && l.charAt(0) !== '#'; })
      .map(function (l) { return l.replace(/^\$\s/, ''); })
      .join('\n');
    var done = function (ok) {
      copyBtn.textContent = ok ? 'Copied!' : 'Press Ctrl+C';
      setTimeout(function () { copyBtn.textContent = 'Copy'; }, 1800);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
    } else {
      var ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { /* ignore */ }
      document.body.removeChild(ta);
      done(ok);
    }
  });
})();
