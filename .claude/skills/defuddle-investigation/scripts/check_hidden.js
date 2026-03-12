/**
 * Check which elements defuddle's hidden-element detection would miss.
 *
 * Given a raw HTML file and a CSS selector, reports whether those elements:
 * - Have inline display:none/visibility:hidden
 * - Have a "hidden" class pattern
 * - Are detected by getComputedStyle on the original document
 * - Are detected by getComputedStyle on a cloneNode (spoiler: never)
 *
 * Usage:
 *   node check_hidden.js PAGE.html ".hover-info"
 *   node check_hidden.js PAGE.html ".permalink-widget"
 *   node check_hidden.js PAGE.html "[aria-hidden='true']"
 */

const DEFUDDLE_REPO = require('path').join(
  require('os').homedir(), 'repos/github/kepano/defuddle'
);
const { JSDOM } = require(`${DEFUDDLE_REPO}/node_modules/jsdom`);
const fs = require('fs');

const htmlPath = process.argv[2];
const selector = process.argv[3];

if (!htmlPath || !selector) {
  console.log('Usage: node check_hidden.js PAGE.html "CSS_SELECTOR"');
  process.exit(1);
}

const html = fs.readFileSync(htmlPath, 'utf8');
const dom = new JSDOM(html, { url: 'https://example.com' });
const doc = dom.window.document;

const elements = doc.querySelectorAll(selector);
console.log(`\nSelector: ${selector}`);
console.log(`Matched: ${elements.length} elements\n`);

if (elements.length === 0) process.exit(0);

// Check inline styles
let inlineHidden = 0;
let classHidden = 0;
const hiddenStylePattern = /(?:^|;\s*)(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0)(?:\s*;|\s*$)/i;

for (const el of elements) {
  const style = el.getAttribute('style') || '';
  if (style && hiddenStylePattern.test(style)) inlineHidden++;

  const cls = el.getAttribute('class') || '';
  const tokens = cls.split(/\s+/);
  if (tokens.some(t => t === 'hidden' || t.endsWith(':hidden'))) classHidden++;
}

console.log(`Inline style hidden: ${inlineHidden}/${elements.length}`);
console.log(`Class pattern hidden: ${classHidden}/${elements.length}`);

// Check getComputedStyle on original
const first = elements[0];
try {
  const cs = dom.window.getComputedStyle(first);
  console.log(`\nOriginal doc getComputedStyle:`);
  console.log(`  display: ${cs.display}`);
  console.log(`  visibility: ${cs.visibility}`);
  console.log(`  opacity: ${cs.opacity}`);
} catch (e) {
  console.log(`\nOriginal doc getComputedStyle: FAILED (${e.message})`);
}

// Check clone
const clone = doc.cloneNode(true);
console.log(`\nClone defaultView: ${clone.defaultView}`);
const cloneEls = clone.querySelectorAll(selector);
console.log(`Clone matched: ${cloneEls.length} elements`);

if (clone.defaultView) {
  const cs = clone.defaultView.getComputedStyle(cloneEls[0]);
  console.log(`Clone getComputedStyle display: ${cs.display}`);
} else {
  console.log(`Clone getComputedStyle: IMPOSSIBLE (no defaultView)`);
}

// Verdict
console.log(`\n--- VERDICT ---`);
if (inlineHidden === elements.length) {
  console.log(`✓ All elements have inline hidden styles — defuddle catches these.`);
} else if (classHidden === elements.length) {
  console.log(`✓ All elements have 'hidden' class — defuddle catches these.`);
} else {
  const missed = elements.length - inlineHidden - classHidden;
  console.log(`⚠ ${missed}/${elements.length} elements hidden only via CSS stylesheet.`);
  console.log(`  Defuddle will NOT detect these (cloneNode has no defaultView).`);
}

// Show first element context
console.log(`\nFirst element preview:`);
const text = (first.textContent || '').trim().slice(0, 200);
console.log(`  tag: <${first.tagName.toLowerCase()}>`);
console.log(`  class: ${first.getAttribute('class') || '(none)'}`);
console.log(`  text: ${text || '(empty)'}${text.length >= 200 ? '...' : ''}`);
