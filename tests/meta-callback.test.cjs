const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const docs = path.join(__dirname, "..", "docs");
const html = fs.readFileSync(path.join(docs, "meta", "index.html"), "utf8");

function fallback(search, hash) {
  const elements = {
    "open-app": { href: html.match(/id="open-app" href="([^"]+)"/)[1] },
    instructions: { textContent: "" },
  };
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1);
  vm.runInNewContext(scripts[0][1], {
    window: { location: { search, hash } },
    document: { getElementById: (id) => elements[id] },
  });
  return elements;
}

test("association matches the signed app and covers the Meta return route", () => {
  const association = JSON.parse(
    fs.readFileSync(path.join(docs, ".well-known", "apple-app-site-association"), "utf8"),
  );
  assert.deepEqual(association.applinks.details[0].appIDs, [
    "K63HT2V83M.com.pocketaimechanic.gaugeking",
  ]);
  assert.equal(association.applinks.details[0].components[0]["/"], "/meta*");
  assert.ok(fs.existsSync(path.join(docs, ".nojekyll")));
});

test("fallback preserves encoded, repeated, and fragment callback parameters", () => {
  const search = "?token=a%2Fb%2Bc&state=one+two&state=three";
  const hash = "#response=x%3Dy";
  const elements = fallback(search, hash);
  assert.equal(elements["open-app"].href, `gaugeking://meta${search}${hash}`);
  assert.match(elements.instructions.textContent, /registration response/);
});

test("fragment-only callback is preserved", () => {
  assert.equal(fallback("", "#token=a%2Fb")["open-app"].href, "gaugeking://meta#token=a%2Fb");
});

test("missing payload opens the dashboard, not a fabricated registration", () => {
  assert.equal(fallback("", "")["open-app"].href, "gaugeking://dashboard");
  assert.match(html, /returning to the app alone does not complete registration/i);
  assert.match(html, /<noscript>/);
  assert.match(html, /name="referrer" content="no-referrer"/);
  assert.doesNotMatch(html, /<script[^>]+src=/);
});
