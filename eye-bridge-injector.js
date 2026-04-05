// EYE Bridge Injector - Add to website <head>
// For Hostinger VPS Hosting integration
(function() {
  if (window.__EYE_BRIDGE_INJECTED) return;
  window.__EYE_BRIDGE_INJECTED = true;

  // Expose EYE-compatible API
  window.__EYE = {
    // Execute arbitrary JS (called by EYE bridge)
    exec: function(code) {
      try {
        return eval(code);
      } catch (e) {
        console.error('[EYE] Execution error:', e);
        return { error: e.message };
      }
    },

    // Get page state for AI context
    getState: function() {
      return {
        url: window.location.href,
        title: document.title,
        pricingTables: [...document.querySelectorAll('.h-pricing-table')].map(p => ({
          name: p.querySelector('.h-pricing-table__name')?.textContent?.trim(),
          price: p.querySelector('.h-pricing-table__price')?.textContent?.trim(),
          features: [...p.querySelectorAll('li')].map(f => f.textContent.trim())
        })),
        buttons: [...document.querySelectorAll('button, a.button, .header__button')].map(b => ({
          text: b.textContent.trim(),
          id: b.id,
          class: b.className,
          visible: b.offsetParent !== null
        })),
        links: [...document.querySelectorAll('a[href]')].slice(0, 50).map(a => ({
          text: a.textContent.trim(),
          href: a.href
        })),
        carouselItems: [...document.querySelectorAll('.h-carousel__item')].map(i => ({
          active: i.classList.contains('h-carousel__item--active'),
          content: i.textContent.trim().slice(0, 100)
        })),
        faqs: [...document.querySelectorAll('[data-testid="faq-item"], .h-accordion')].map(f => ({
          expanded: f.open || f.classList.contains('h-accordion--expanded'),
          question: f.querySelector('h3, button, summary')?.textContent?.trim()
        }))
      };
    },

    // Register callbacks for EYE actions
    onAction: function(actionName, callback) {
      window.__EYE_ACTIONS = window.__EYE_ACTIONS || {};
      window.__EYE_ACTIONS[actionName] = callback;
    }
  };

  console.log('[EYE] Bridge injected and ready');
})();
