/* GameZone — небольшие UI-улучшения.
   Бизнес-логика (корзина, цены, заказы) выполняется на сервере Django. */

(function () {
  'use strict';

  // --- Мобильное меню ---
  var navToggle = document.getElementById('nav-toggle');
  var mainNav = document.getElementById('main-nav');
  var navBackdrop = document.getElementById('nav-backdrop');

  function closeNav() {
    if (!mainNav) return;
    mainNav.classList.remove('is-open');
    if (navBackdrop) navBackdrop.hidden = true;
    if (navToggle) navToggle.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  }

  function openNav() {
    if (!mainNav) return;
    mainNav.classList.add('is-open');
    if (navBackdrop) navBackdrop.hidden = false;
    if (navToggle) navToggle.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
  }

  if (navToggle && mainNav) {
    navToggle.addEventListener('click', function () {
      if (mainNav.classList.contains('is-open')) {
        closeNav();
      } else {
        openNav();
      }
    });
    if (navBackdrop) navBackdrop.addEventListener('click', closeNav);
    mainNav.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', closeNav);
    });
    window.addEventListener('resize', function () {
      if (window.innerWidth > 960) closeNav();
    });
  }

  // --- Панель поиска в шапке ---
  var searchToggle = document.getElementById('search-toggle');
  var searchPanel = document.getElementById('search-panel');

  if (searchToggle && searchPanel) {
    searchToggle.addEventListener('click', function () {
      var willShow = searchPanel.hidden;
      searchPanel.hidden = !willShow;
      searchToggle.setAttribute('aria-expanded', String(willShow));
      if (willShow) {
        var input = searchPanel.querySelector('input[name="q"]');
        if (input) input.focus();
      }
    });
  }

  // --- Выбор количества на странице товара ---
  document.querySelectorAll('.qty-picker[data-max]').forEach(function (picker) {
    var input = picker.querySelector('.qty-input');
    if (!input) return;
    var max = parseInt(picker.getAttribute('data-max'), 10) || 1;

    picker.querySelectorAll('.qty-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var step = parseInt(btn.getAttribute('data-qty'), 10) || 0;
        var value = parseInt(input.value, 10) || 1;
        value = Math.min(Math.max(value + step, 1), max);
        input.value = value;
      });
    });

    input.addEventListener('change', function () {
      var value = parseInt(input.value, 10);
      if (isNaN(value) || value < 1) value = 1;
      if (value > max) value = max;
      input.value = value;
    });
  });

  // --- Переключение миниатюр изображений товара ---
  var galleryMain = document.getElementById('gallery-main');
  if (galleryMain) {
    document.querySelectorAll('.gallery-thumb').forEach(function (thumb) {
      thumb.addEventListener('click', function () {
        var full = thumb.getAttribute('data-full');
        if (!full) return;
        galleryMain.src = full;
        document.querySelectorAll('.gallery-thumb').forEach(function (t) {
          t.classList.remove('gallery-thumb--active');
        });
        thumb.classList.add('gallery-thumb--active');
      });
    });
  }

  // --- Подтверждение удаления / очистки ---
  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (!window.confirm(form.getAttribute('data-confirm') || 'Вы уверены?')) {
        event.preventDefault();
      }
    });
  });
})();
