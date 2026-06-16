# SPA Smooth Transition Fix

## Problem

When using JavaScript to intercept link clicks and swap page content (SPA-style navigation), CSS transitions fail to animate because the browser optimizes away the state change.

## Root Cause

`replaceWith()` is synchronous. If you add a class AFTER inserting the element, the browser may batch the add+remove operations into a single frame, skipping the transition entirely.

## Broken Pattern

```javascript
currentMain.replaceWith(nextMain);
nextMain.classList.add("is-page-entering");  // ❌ Too late

requestAnimationFrame(function () {
    nextMain.classList.remove("is-page-entering");
});
```

## Fixed Pattern

```javascript
nextMain.classList.add("is-page-entering");  // ✅ Set state BEFORE inserting
currentMain.replaceWith(nextMain);

void nextMain.offsetWidth;  // ✅ Force reflow

requestAnimationFrame(function () {
    nextMain.classList.remove("is-page-entering");  // ✅ Now transition triggers
});
```

## Why This Works

1. **Pre-set initial state** — Element enters DOM already in the "hidden" state
2. **Force reflow** — `offsetWidth` access forces browser to calculate layout, recording the initial state
3. **Trigger transition** — `requestAnimationFrame` ensures the class removal happens in the next paint cycle, creating a visible transition

## CSS Required

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

## Full Working Example (nav.js)

See `templates/nav-spa.js` for a complete, reusable navigation script.
