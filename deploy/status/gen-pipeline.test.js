// node --test deploy/status/gen-pipeline.test.js
"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

const { render, publicModel, readPlatformState, readStagingState, esc } = require("./gen-pipeline.js");

const sample = JSON.parse(fs.readFileSync(path.join(__dirname, "sample-model.json"), "utf8"));

function odooButtons(html) {
  const odoo = html.slice(html.indexOf('class="tool tool-odoo"'));
  const next = html.slice(html.indexOf('class="tool tool-next"'), html.indexOf('class="tool tool-odoo"'));
  return { odoo, next };
}

test("both tools and all three stages are on the page, in both languages", () => {
  for (const [lang, names] of [["fr", ["Développement", "Staging", "Production"]], ["en", ["Development", "Staging", "Production"]]]) {
    const html = render(sample, lang);
    assert.ok(html.includes("Next.js"));
    assert.ok(html.includes("Odoo"));
    for (const name of names) assert.equal(html.split(`<h3>${name}</h3>`).length - 1, 2, name);
  }
});

test("each stage shows branch, commit, author and time", () => {
  const html = render(sample, "en");
  for (const needle of ["<code>dev</code>", "<code>staging</code>", "<code>main</code>", "9f8e7d6", "Sample Author", "2026-12-15"]) {
    assert.ok(html.includes(needle), needle);
  }
});

test("how far ahead each stage is, and whether the running release matches", () => {
  const html = render(sample, "en");
  assert.ok(html.includes("2 commits ahead of Staging"));
  assert.ok(html.includes("12 commits ahead of Production"));
  assert.ok(html.includes("Matches GitHub"));
  assert.ok(html.includes("Differs from GitHub"));
});

test("the buttons are on the Odoo column only, and are plain links", () => {
  for (const lang of ["fr", "en"]) {
    const { odoo, next } = odooButtons(render(sample, lang));
    assert.equal((odoo.match(/class="button[ "]/g) || []).length, 2);
    assert.equal((next.match(/class="button[ "]/g) || []).length, 0);
    assert.ok(odoo.includes('href="https://platform.auditisa.com/odoo/pipeline"'));
    assert.ok(!/<form|<script|onclick|fetch\(|XMLHttpRequest/i.test(odoo + next));
  }
});

test("the page has no script and says how far behind it can be", () => {
  const html = render(sample, "fr");
  assert.ok(!html.includes("<script"));
  assert.ok(html.includes("au plus une minute"));
  assert.ok(render(sample, "en").includes("at most one minute"));
  assert.ok(html.includes('http-equiv="refresh"'));
});

test("what comes from outside is escaped", () => {
  const hostile = JSON.parse(JSON.stringify(sample));
  hostile.tools[0].stages[0].head.author = '<img src=x onerror="alert(1)">';
  const html = render(hostile, "en");
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img"));
  assert.equal(esc("a&b"), "a&amp;b");
});

test("the platform's document: a firm's name or an unknown key does not come through", () => {
  const read = readPlatformState(JSON.stringify({
    firms_total: 3, firms_on_target: 2, target_release: "abcdef1234567", rollout_state: "running",
    last_promotion_at: "2026-12-01T10:00:00Z", firm_name: "Cabinet Agro", reason: "Personne X",
    last_rebuild_state: "Cabinet Agro SA", staging_release: "<script>", firms: ["Cabinet Agro"],
  }));
  assert.equal(read.firms_total, 3);
  assert.equal(read.last_rebuild_state, null);
  assert.equal(read.staging_release, null);
  assert.ok(!JSON.stringify(read).includes("Agro"));
  assert.equal(readPlatformState("not json"), null);
  assert.equal(readPlatformState("null"), null);
  assert.equal(readPlatformState(JSON.stringify({ firms_total: "many" })).firms_total, null);
});

test("staging's document: only a commit, yes-or-no answers and dates", () => {
  const read = readStagingState(JSON.stringify({ release: "dc8db392", at: "2026-11-07T04:00:00Z", mail_off: true, band_on: "yes", other: "x" }));
  assert.deepEqual(read, { release: "dc8db392", at: "2026-11-07T04:00:00Z", mail_off: true, band_on: false, rebuilt_at: null });
});

test("a firm server count of zero says so, and offers no comparison", () => {
  const model = JSON.parse(JSON.stringify(sample));
  const production = model.tools[1].stages[2];
  production.firms_total = 0;
  production.running = null;
  const html = render(model, "en");
  assert.ok(html.includes("No firm server yet"));
});

test("a missing deploy key is said plainly and the page still renders", () => {
  const model = JSON.parse(JSON.stringify(sample));
  model.tools[1].no_access = true;
  model.tools[1].github_ok = false;
  for (const stage of model.tools[1].stages) stage.head = null;
  const html = render(model, "en");
  assert.ok(html.includes("GitHub access is not set up"));
  assert.ok(html.includes("No data"));
});

test("an old reading is marked", () => {
  const model = JSON.parse(JSON.stringify(sample));
  model.tools[0].stale = true;
  model.tools[0].read_at = "2026-12-15T09:10:00.000Z";
  assert.ok(render(model, "en").includes("did not answer: last read at 09:10:00"));
});

test("nothing that looks like a secret, a path or a commit message is published", () => {
  for (const html of [render(sample, "fr"), render(sample, "en"), JSON.stringify(publicModel(sample))]) {
    for (const word of ["password", "token", "secret", "/opt/", "/root/", "BEGIN ", "ssh-", "db_", "git@"]) {
      assert.ok(!html.toLowerCase().includes(word.toLowerCase()), word);
    }
  }
});
