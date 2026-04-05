---
name: eye-integrate
description: Analyze a website and auto-generate EYE Assistant function registry + inject bridge
type: skill
---

# EYE Integration Skill

When the user invokes `/eye-integrate`, follow these steps:

## Step 1: Get the website source

Ask the user for:
- **Website URL** (e.g., `https://example.com`) OR **local path** to HTML files
- If local, the path to the website folder

## Step 2: Analyze the website structure

Examine the website for:
- **Interactive elements**: Buttons, forms, links, inputs, dropdowns
- **Navigation patterns**: Menu items, breadcrumbs, tabs
- **Common actions**: Search, login, settings, dark mode toggle, cart operations
- **Page structure**: Main sections, content areas, sidebars
- **Dynamic elements**: Modals, accordions, notifications

## Step 3: Generate the EYE function registry

Create a `~/.aria-assistant/registries/{site-name}.json` file with this structure:

```json
{
  "site": "https://example.com",
  "name": "Example Site",
  "functions": [
    {
      "name": "toggle_dark_mode",
      "description": "Toggle dark/light theme",
      "params": {},
      "action_type": "js",
      "action": "document.documentElement.classList.toggle('dark')"
    },
    {
      "name": "navigate_to_page",
      "description": "Navigate to a specific page",
      "params": {
        "page": "string - page name (e.g., 'home', 'about', 'contact', 'pricing', 'docs')"
      },
      "action_type": "navigate",
      "action": "/pages/{page}"
    },
    {
      "name": "search_site",
      "description": "Search the website content",
      "params": {
        "query": "string - search query"
      },
      "action_type": "js",
      "action": "document.querySelector('#search-input').value = '{query}'; document.querySelector('#search-form').submit();"
    },
    {
      "name": "fill_form",
      "description": "Fill out a form with provided data",
      "params": {
        "fields": "object - key-value pairs of field names and values"
      },
      "action_type": "js",
      "action": "Object.entries({fields}).forEach(([k,v]) => { const el = document.querySelector(`[name=${k}]`) || document.querySelector(`#${k}`); if(el) el.value = v; });"
    },
    {
      "name": "click_element",
      "description": "Click an element by selector or text",
      "params": {
        "selector": "string - CSS selector or button text"
      },
      "action_type": "js",
      "action": "(document.querySelector('{selector}') || [...document.querySelectorAll('button')].find(b=>b.textContent.toLowerCase().includes('{selector}')))?.click();"
    },
    {
      "name": "scroll_to_section",
      "description": "Scroll to a specific section",
      "params": {
        "section": "string - section id or name"
      },
      "action_type": "js",
      "action": "document.querySelector('#{section}')?.scrollIntoView({behavior:'smooth'});"
    }
  ]
}
```

## Step 4: Create the bridge injector script

Generate a `eye-bridge-injector.js` file that can be added to the website:

```javascript
// EYE Bridge Injector - Add to website <head>
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
        forms: [...document.forms].map(f => ({
          name: f.name,
          id: f.id,
          fields: [...f.elements].map(el => ({
            name: el.name,
            type: el.type,
            value: el.value
          }))
        })),
        buttons: [...document.querySelectorAll('button, [role="button"]')].map(b => ({
          text: b.textContent.trim(),
          id: b.id,
          class: b.className
        })),
        links: [...document.querySelectorAll('a[href]')].slice(0, 50).map(a => ({
          text: a.textContent.trim(),
          href: a.href
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
```

## Step 5: Provide integration instructions

Tell the user how to:

1. **Load the registry** in EYE Control Panel → Functions tab → Load Registry
2. **Add the bridge injector** to their website (before `</head>` or via extension)
3. **Test the integration** using voice commands like:
   - "Toggle dark mode"
   - "Go to pricing page"
   - "Search for [query]"
   - "Click the submit button"

## Output format

Present the results as:
1. **Generated registry file path**
2. **Registry preview** (show the JSON)
3. **Bridge injector code** (ready to copy)
4. **Quick-start commands** for testing

---

**Example invocation:**
```
/eye-integrate https://novasuite.com
/eye-integrate D:/websites/myapp
```
