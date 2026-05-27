# SPA Smooth Transition Race Condition

## Problem

When deploying a Single Page Application (SPA) with client-side navigation and CSS transitions, the page switch animation may appear to "not work" even though all code and styles are correct.

## Root Cause

The `replaceWith()` DOM API is synchronous. If you add a CSS class immediately after replacement and remove it in the next `requestAnimationFrame`, the browser may optimize away the transition because the element never actually rendered with the initial state.

### Broken Pattern

```javascript
// nav.js — BROKEN: transition skipped
function setPage(nextDoc, url, shouldPush) {
    var currentMain = document.querySelector(".video-page");
    var nextMain = nextDoc.querySelector(".video-page");
    
    // Synchronous replacement — element appears instantly
    currentMain.replaceWith(nextMain);
    
    // Add entering state (opacity: 0)
    nextMain.classList.add("is-page-entering");
    
    // Browser may batch these into same frame — transition never triggers
    requestAnimationFrame(function () {
        nextMain.classList.remove("is-page-entering");
    });
}
```

### CSS

```css
.video-page {
    opacity: 1;
    transform: translateY(0);
    transition: opacity 0.18s ease, transform 0.18s ease;
}

.video-page.is-page-entering {
    opacity: 0;
    transform: translateY(12px);
}

.video-page.is-page-leaving {
    opacity: 0;
    transform: translateY(12px);
}
```

## Solution

Force a reflow between adding the initial state class and removing it, so the browser records the initial computed style:

### Fixed Pattern

```javascript
// nav.js — FIXED: forces reflow before transition
function setPage(nextDoc, url, shouldPush) {
    var currentMain = document.querySelector(".video-page");
    var nextMain = nextDoc.querySelector(".video-page");
    
    // Step 1: Prepare new element with initial hidden state
    nextMain.classList.add("is-page-entering");
    
    // Step 2: Replace DOM
    currentMain.replaceWith(nextMain);
    
    // Step 3: FORCE REFLOW — browser must compute the initial style
    void nextMain.offsetWidth;
    
    // Step 4: Now remove the class — browser sees a real transition
    requestAnimationFrame(function () {
        nextMain.classList.remove("is-page-entering");
    });
}
```

## Alternative Solutions

### Option A: setTimeout instead of rAF

```javascript
currentMain.replaceWith(nextMain);
nextMain.classList.add("is-page-entering");

// Give browser time to render initial state
setTimeout(function () {
    nextMain.classList.remove("is-page-entering");
}, 20);  // > 16ms (one frame at 60fps)
```

### Option B: CSS-only with @starting-style (Chrome 117+)

```css
.video-page {
    @starting-style {
        opacity: 0;
        transform: translateY(12px);
    }
    transition: opacity 0.18s ease, transform 0.18s ease;
}
```

No JavaScript needed for enter animation.

### Option C: Web Animations API

```javascript
const animation = nextMain.animate(
    [
        { opacity: 0, transform: 'translateY(12px)' },
        { opacity: 1, transform: 'translateY(0)' }
    ],
    { duration: 180, easing: 'ease' }
);
```

## Verification Steps

1. Open DevTools → Elements
2. Click a nav link that triggers SPA navigation
3. Watch the `.video-page` element's classes in real-time
4. Expected: `is-page-entering` appears briefly, then removed
5. If the class flickers too fast to see → reflow is being skipped
6. Check computed styles: `getComputedStyle(el).opacity` should be `0` immediately after adding the class

## Related Issues

- **Leaving animation also affected:** The `is-page-leaving` class is added before `fetch()`, but if `fetch()` resolves too quickly (cached response), the 180ms timeout may not give enough time for the leaving animation to be visible.
- **Style sync delays:** If `syncStyles()` loads new stylesheets, the transition may start before styles are fully parsed.

## References

- [MDN: Element.replaceWith()](https://developer.mozilla.org/en-US/docs/Web/API/Element/replaceWith)
- [MDN: CSS transitions](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_transitions/Using_CSS_transitions)
- [Web.dev: @starting-style](https://web.dev/articles/css-starting-style)
