#!/usr/bin/env node
// gen-pipeline.js: the public status page, status.auditisa.com: Development, Staging and Production of
// the Next.js tool and of the Odoo tool, side by side, against GitHub.
//
//   node gen-pipeline.js                    reads the world, writes index.html, en.html, pipeline.json
//   node gen-pipeline.js --model FILE       renders a saved model instead of reading anything (tests, samples)
//   node gen-pipeline.js --dump-model FILE  also writes the model it read
//
// It runs right after the existing generator (gen-status.js), whose page and figures it reads:
//   status.json   what the Next.js servers are running, unchanged
//   index.html    copied aside as details.html, the page as it was
//
// This page is public. So:
//   - it shows commits, author names, dates, health words and counts. No commit message, no address other
//     than the public sites, no path, no name of a firm, and it reads no secret of any kind;
//   - everything from outside goes through a strict pattern or is dropped, and every value is escaped;
//   - its Promote and Rebuild buttons are plain links to the Pipeline screen of the admin Odoo, which answers
//     only the owner's addresses and asks for a login, a typed confirmation and a reason. They act on Odoo
//     only: the Next.js column has no button, because nothing here may reach the live firm's tool.
//
// Reading GitHub: `git ls-remote` each minute. Commit details are fetched only when a branch has moved, into
// a blobless mirror. If GitHub or a site does not answer, the last good reading is shown, marked as old.

"use strict";

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const ENV = process.env;
const WWW = ENV.STATUS_WWW || "/var/www/status.auditisa.com";
const STATE = ENV.STATUS_STATE || "/opt/ea-audit-status/pipeline";
const NEXT_REMOTE = ENV.NEXT_REMOTE || "https://github.com/Nekoutb/ea-audit-tool.git";
const ODOO_REMOTE = ENV.ODOO_REMOTE || "git@github.com:Nekoutb/auditisa-odoo.git";
const ODOO_KEY = ENV.ODOO_DEPLOY_KEY || "/root/.ssh/auditisa_odoo_status_ro";
const STAGING_STATE_URL = ENV.STAGING_STATE_URL || "https://test.auditisa.com/manual/staging-state.json";
const STAGING_HEALTH_URL = ENV.STAGING_HEALTH_URL || "https://test.auditisa.com/web/health";
const PLATFORM_STATE_URL = ENV.PLATFORM_STATE_URL || "";
const PIPELINE_URL = ENV.PIPELINE_URL || "https://platform.auditisa.com/odoo/pipeline";

const SHA = /^[0-9a-f]{7,40}$/;
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
const WORD = /^[a-z_]{1,24}$/;
const REMOTE_TIMEOUT = 25000;

// ------------------------------------------------------------------ reading

function git(args, options = {}) {
  return execFileSync("git", args, {
    encoding: "utf8", timeout: REMOTE_TIMEOUT, stdio: ["ignore", "pipe", "ignore"], ...options,
  }).trim();
}

function sshEnv(remote) {
  if (!remote.startsWith("git@")) return process.env;
  return {
    ...process.env,
    GIT_SSH_COMMAND: `ssh -i ${ODOO_KEY} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15`,
  };
}

function lsRemote(remote) {
  const heads = {};
  const output = git(["ls-remote", "--heads", remote], { env: sshEnv(remote) });
  for (const line of output.split("\n")) {
    const match = /^([0-9a-f]{40})\s+refs\/heads\/([A-Za-z0-9._/-]+)$/.exec(line);
    if (match) heads[match[2]] = match[1];
  }
  return heads;
}

// A blobless mirror: commits and trees only, enough for authors, dates and counts.
function mirror(name, remote, heads) {
  const dir = path.join(STATE, `${name}.git`);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(STATE, { recursive: true });
    git(["clone", "--quiet", "--bare", "--filter=blob:none", remote, dir], { env: sshEnv(remote), timeout: 120000 });
  }
  const missing = Object.values(heads).some((sha) => !hasCommit(dir, sha));
  if (missing) {
    git(["-C", dir, "fetch", "--quiet", "--prune", "--filter=blob:none", remote, "+refs/heads/*:refs/heads/*"], {
      env: sshEnv(remote), timeout: 60000,
    });
  }
  return dir;
}

function hasCommit(dir, sha) {
  try {
    git(["-C", dir, "cat-file", "-e", `${sha}^{commit}`]);
    return true;
  } catch {
    return false;
  }
}

function commit(dir, sha) {
  if (!sha || !SHA.test(sha) || !hasCommit(dir, sha)) return sha && SHA.test(sha) ? { sha, short: sha.slice(0, 7) } : null;
  const [author, at] = git(["-C", dir, "log", "-1", "--format=%an%x00%cI", sha]).split("\0");
  return { sha, short: sha.slice(0, 7), author: author.slice(0, 40), at: new Date(at).toISOString() };
}

function ahead(dir, from, to) {
  // Commits in `to` that `from` lacks.
  if (!from || !to || !hasCommit(dir, from) || !hasCommit(dir, to)) return null;
  return Number(git(["-C", dir, "rev-list", "--count", `${from}..${to}`]));
}

function fetchUrl(url) {
  try {
    return execFileSync("curl", ["-fsS", "--max-time", "15", url], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
  } catch {
    return null;
  }
}

function safeSha(value) {
  return typeof value === "string" && SHA.test(value) ? value : null;
}

function safeInstant(value) {
  return typeof value === "string" && INSTANT.test(value) ? value : null;
}

function safeWord(value) {
  return typeof value === "string" && WORD.test(value) ? value : null;
}

function safeCount(value) {
  return Number.isInteger(value) && value >= 0 && value < 1000000 ? value : null;
}

// Only the listed keys, each through its pattern. A firm's name cannot come through this.
function readPlatformState(text) {
  let raw;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object") return null;
  return {
    firms_total: safeCount(raw.firms_total),
    firms_on_target: safeCount(raw.firms_on_target),
    target_release: safeSha(raw.target_release),
    rollout_state: safeWord(raw.rollout_state),
    rollout_done: safeCount(raw.rollout_done),
    rollout_total: safeCount(raw.rollout_total),
    last_promotion_at: safeInstant(raw.last_promotion_at),
    last_promotion_release: safeSha(raw.last_promotion_release),
    last_rebuild_at: safeInstant(raw.last_rebuild_at),
    last_rebuild_state: safeWord(raw.last_rebuild_state),
    staging_release: safeSha(raw.staging_release),
    staging_health: safeWord(raw.staging_health),
  };
}

function readStagingState(text) {
  let raw;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object") return null;
  return {
    release: safeSha(raw.release),
    at: safeInstant(raw.at),
    mail_off: raw.mail_off === true,
    band_on: raw.band_on === true,
    rebuilt_at: safeInstant(raw.rebuilt_at),
  };
}

function loadCache() {
  try {
    return JSON.parse(fs.readFileSync(path.join(STATE, "last-good.json"), "utf8"));
  } catch {
    return {};
  }
}

function collectNext(statusJson, now, cache) {
  const byKey = {};
  for (const env of (statusJson && statusJson.envs) || []) byKey[env.key] = env;
  const prod = byKey.prod || {};
  const dev = byKey.dev || {};
  const runningProd = safeSha(prod.sha);
  const runningDev = safeSha(dev.sha);
  let heads = null;
  let dir = null;
  let readAt = now;
  try {
    heads = lsRemote(NEXT_REMOTE);
    dir = mirror("next", NEXT_REMOTE, heads);
  } catch {
    const old = cache.next;
    if (old) return { ...old, stale: true };
    heads = null;
  }
  const details = (sha) => (dir ? commit(dir, sha) : (safeSha(sha) ? { sha, short: sha.slice(0, 7) } : null));
  const count = (from, to) => (dir ? ahead(dir, from, to) : null);
  const devHead = heads && heads.dev;
  const mainHead = heads && heads.main;
  const lastDeploy = (env) => {
    const row = (env.log || []).find((entry) => entry && entry.kind === "deploy");
    return row ? { at: safeInstant(row.when), sha: safeSha(row.sha) } : null;
  };
  return {
    key: "next",
    read_at: readAt,
    github_ok: Boolean(heads),
    stages: [
      {
        key: "development", branch: "dev", head: details(devHead), running: null,
        ahead_of_next: count(runningDev, devHead),
      },
      {
        key: "staging", branch: "dev", head: details(devHead), running: details(runningDev), site: "dev.auditisa.com",
        health: dev.healthy === true ? "ok" : (dev.httpCode ? "down" : "unknown"),
        matches: devHead && runningDev ? devHead === runningDev : null,
        last_promotion: lastDeploy(dev), ahead_of_next: count(runningProd, runningDev),
      },
      {
        key: "production", branch: "main", head: details(mainHead), running: details(runningProd), site: "www.auditisa.com",
        health: prod.healthy === true ? "ok" : (prod.httpCode ? "down" : "unknown"),
        matches: mainHead && runningProd ? mainHead === runningProd : null,
        behind_github: count(runningProd, mainHead), last_promotion: lastDeploy(prod),
      },
    ],
  };
}

function collectOdoo(now, cache, stagingText, healthText, platformText) {
  const staging = stagingText ? readStagingState(stagingText) : null;
  const platform = platformText ? readPlatformState(platformText) : null;
  const health = healthText === null ? "down" : "ok";
  if (ODOO_REMOTE.startsWith("git@") && !fs.existsSync(ODOO_KEY)) {
    return { key: "odoo", read_at: now, github_ok: false, no_access: true, staging, health, platform, stages: odooStages(null, null, staging, health, platform) };
  }
  let heads;
  let dir;
  try {
    heads = lsRemote(ODOO_REMOTE);
    dir = mirror("odoo", ODOO_REMOTE, heads);
  } catch {
    if (cache.odoo) return { ...cache.odoo, stale: true };
    return { key: "odoo", read_at: now, github_ok: false, staging, health, platform, stages: odooStages(null, null, staging, health, platform) };
  }
  return { key: "odoo", read_at: now, github_ok: true, staging, health, platform, stages: odooStages(heads, dir, staging, health, platform) };
}

function odooStages(heads, dir, staging, health, platform) {
  const details = (sha) => (dir ? commit(dir, sha) : (safeSha(sha) ? { sha, short: sha.slice(0, 7) } : null));
  const count = (from, to) => (dir ? ahead(dir, from, to) : null);
  const devHead = heads && heads.dev;
  const stagingHead = heads && heads.staging;
  const mainHead = heads && heads.main;
  // Until the `staging` branch exists, staging deploys from `dev`.
  const stagingBranch = stagingHead ? "staging" : "dev";
  const stagingTip = stagingHead || devHead;
  const runningStaging = staging && staging.release;
  const stagingSha = runningStaging || stagingTip;
  const fullRunning = dir && runningStaging && hasCommit(dir, runningStaging)
    ? git(["-C", dir, "rev-parse", `${runningStaging}^{commit}`]) : runningStaging;
  const firms = platform ? platform.firms_total : null;
  const target = platform && platform.target_release;
  return [
    { key: "development", branch: "dev", head: details(devHead), running: null, ahead_of_next: count(fullRunning || stagingTip, devHead) },
    {
      key: "staging", branch: stagingBranch, branch_missing: Boolean(heads) && !stagingHead, head: details(stagingTip),
      running: details(fullRunning), site: "test.auditisa.com", health,
      matches: stagingTip && fullRunning ? stagingTip === fullRunning : null,
      ahead_of_next: count(mainHead, stagingSha && dir && hasCommit(dir, stagingSha) ? stagingSha : stagingTip),
      mail_off: staging ? staging.mail_off : null, band_on: staging ? staging.band_on : null,
      last_rebuild: platform && platform.last_rebuild_at ? { at: platform.last_rebuild_at, state: platform.last_rebuild_state } : (staging && staging.rebuilt_at ? { at: staging.rebuilt_at } : null),
      action: "rebuild",
    },
    {
      key: "production", branch: "main", head: details(mainHead),
      running: target ? details(target) : null,
      firms_total: firms, firms_on_target: platform ? platform.firms_on_target : null,
      rollout: platform && platform.rollout_state ? { state: platform.rollout_state, done: platform.rollout_done, total: platform.rollout_total } : null,
      matches: target && mainHead ? target === mainHead : null,
      last_promotion: platform && platform.last_promotion_at ? { at: platform.last_promotion_at, sha: platform.last_promotion_release } : null,
      action: "promote",
    },
  ];
}

function collect(now) {
  const cache = loadCache();
  let statusJson = null;
  try {
    statusJson = JSON.parse(fs.readFileSync(path.join(WWW, "status.json"), "utf8"));
  } catch {
    statusJson = null;
  }
  const next = collectNext(statusJson, now, cache);
  const odoo = collectOdoo(
    now, cache, fetchUrl(STAGING_STATE_URL), fetchUrl(STAGING_HEALTH_URL),
    PLATFORM_STATE_URL ? fetchUrl(PLATFORM_STATE_URL) : null,
  );
  const model = { schema: 1, generated: now, tools: [next, odoo] };
  try {
    const good = {};
    if (next.github_ok && !next.stale) good.next = next; else if (cache.next) good.next = cache.next;
    if (odoo.github_ok && !odoo.stale) good.odoo = odoo; else if (cache.odoo) good.odoo = cache.odoo;
    fs.mkdirSync(STATE, { recursive: true });
    fs.writeFileSync(path.join(STATE, "last-good.json"), JSON.stringify(good));
  } catch {
    // The page still renders: the cache only helps when GitHub does not answer.
  }
  return model;
}

// ------------------------------------------------------------------ rendering

const TEXT = {
  fr: {
    lang: "fr", other: "English", otherHref: "en.html", title: "État d'AuditISA",
    intro: "Où en est chaque outil, de GitHub à la production.",
    read: (t) => `Lu sur GitHub à ${t} UTC.`,
    delay: "La page a au plus une minute de retard sur GitHub, plus le temps de recharger.",
    stale: (t) => `GitHub n'a pas répondu : dernière lecture à ${t} UTC.`,
    noAccess: "Accès à GitHub pas encore en place pour ce dépôt privé : les branches ne sont pas affichées.",
    tools: { next: "Outil Next.js", odoo: "Outil Odoo" },
    toolNote: {
      next: "L'outil en service. Ses versions se publient comme aujourd'hui : aucun bouton ici.",
      odoo: "L'outil en construction. Une version va aux cabinets par la Pipeline.",
    },
    stages: { development: "Développement", staging: "Staging", production: "Production" },
    branch: "Branche", github: "GitHub", running: "En service", author: "Auteur", when: "Date",
    none: "Aucune donnée", noServer: "Pas de serveur : bases jetables des agents",
    sameStaging: "Pas de serveur de staging à part : dev.auditisa.com tient ce rôle",
    match: "Conforme à GitHub", differ: "Différent de GitHub", unknownMatch: "Comparaison impossible",
    health: { ok: "En ligne", down: "Ne répond pas", unknown: "Inconnu" },
    behind: (n) => `${n} commit${n > 1 ? "s" : ""} sur GitHub pas encore en service`,
    ahead: (n, a, b) => (n === 0 ? `${a} et ${b} sont au même point` : `${n} commit${n > 1 ? "s" : ""} d'avance sur ${b}`),
    unknownAhead: "Avance inconnue",
    lastPromotion: "Dernière publication", lastRebuild: "Dernière reconstruction",
    never: "Jamais", branchMissing: "branche staging pas encore créée : le staging suit dev",
    mail: { on: "Courriel coupé, bandeau affiché", off: "Attention : courriel ou bandeau à vérifier" },
    firms: (n) => `${n} cabinet${n > 1 ? "s" : ""}`, noFirms: "Aucun serveur de cabinet pour l'instant",
    onTarget: (a, b) => `${a} sur ${b} sur cette version`,
    rollout: { running: "Déploiement en cours", stopped: "Déploiement arrêté sur un échec", done: "Déploiement terminé", draft: "Déploiement préparé" },
    promote: "Promouvoir le staging en production", rebuild: "Reconstruire le staging depuis la production",
    buttonsNote: "Ces boutons mènent à l'écran Pipeline de l'Odoo d'administration : adresses du propriétaire, connexion, confirmation tapée et motif. Ils agissent sur Odoo seulement.",
    details: "Détail des déploiements Next.js", ago: agoFr,
  },
  en: {
    lang: "en", other: "Français", otherHref: "index.html", title: "AuditISA status",
    intro: "Where each tool stands, from GitHub to production.",
    read: (t) => `Read from GitHub at ${t} UTC.`,
    delay: "This page is at most one minute behind GitHub, plus the time to reload.",
    stale: (t) => `GitHub did not answer: last read at ${t} UTC.`,
    noAccess: "GitHub access is not set up yet for this private repository: branches are not shown.",
    tools: { next: "Next.js tool", odoo: "Odoo tool" },
    toolNote: {
      next: "The tool in service. Its releases are published as they are today: no button here.",
      odoo: "The tool being built. A release reaches the firms through the Pipeline.",
    },
    stages: { development: "Development", staging: "Staging", production: "Production" },
    branch: "Branch", github: "GitHub", running: "Running", author: "Author", when: "Date",
    none: "No data", noServer: "No server: agents' throwaway databases",
    sameStaging: "No separate staging server: dev.auditisa.com plays that part",
    match: "Matches GitHub", differ: "Differs from GitHub", unknownMatch: "Cannot compare",
    health: { ok: "Up", down: "Not answering", unknown: "Unknown" },
    behind: (n) => `${n} commit${n > 1 ? "s" : ""} on GitHub not yet running`,
    ahead: (n, a, b) => (n === 0 ? `${a} and ${b} are level` : `${n} commit${n > 1 ? "s" : ""} ahead of ${b}`),
    unknownAhead: "Lead unknown",
    lastPromotion: "Last release", lastRebuild: "Last rebuild",
    never: "Never", branchMissing: "staging branch not created yet: staging follows dev",
    mail: { on: "Mail off, band on", off: "Check: mail or band" },
    firms: (n) => `${n} firm${n > 1 ? "s" : ""}`, noFirms: "No firm server yet",
    onTarget: (a, b) => `${a} of ${b} on this release`,
    rollout: { running: "Rollout under way", stopped: "Rollout stopped on a failure", done: "Rollout finished", draft: "Rollout prepared" },
    promote: "Promote staging to production", rebuild: "Rebuild staging from production",
    buttonsNote: "These buttons lead to the Pipeline screen of the admin Odoo: the owner's addresses, sign-in, typed confirmation and a reason. They act on Odoo only.",
    details: "Next.js deployment details", ago: agoEn,
  },
};

function plural(n, word) {
  return `${n} ${word}${n > 1 ? "s" : ""}`;
}

function spans(seconds) {
  if (seconds < 90) return ["s", Math.max(1, Math.round(seconds))];
  if (seconds < 5400) return ["min", Math.round(seconds / 60)];
  if (seconds < 129600) return ["h", Math.round(seconds / 3600)];
  return ["d", Math.round(seconds / 86400)];
}

function agoFr(seconds) {
  const [unit, n] = spans(seconds);
  return `il y a ${{ s: `${n} s`, min: `${n} min`, h: `${n} h`, d: plural(n, "jour") }[unit]}`;
}

function agoEn(seconds) {
  const [unit, n] = spans(seconds);
  return `${{ s: `${n} s`, min: `${n} min`, h: `${n} h`, d: plural(n, "day") }[unit]} ago`;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function clock(iso) {
  return iso ? esc(iso.slice(11, 19)) : "";
}

function dateTime(iso, now, t) {
  if (!iso) return "";
  const seconds = (new Date(now) - new Date(iso)) / 1000;
  return `<time datetime="${esc(iso)}" title="${esc(iso.slice(0, 16).replace("T", " "))} UTC">${esc(iso.slice(0, 10))} · ${esc(t.ago(Math.max(seconds, 1)))}</time>`;
}

function commitRow(label, data, now, t) {
  if (!data) return `<div class="row"><dt>${esc(label)}</dt><dd class="muted">${esc(t.none)}</dd></div>`;
  const who = data.author ? `<span class="who">${esc(data.author)}</span>` : "";
  const when = data.at ? dateTime(data.at, now, t) : "";
  return `<div class="row"><dt>${esc(label)}</dt><dd><code>${esc(data.short)}</code>${who}${when ? `<span class="when">${when}</span>` : ""}</dd></div>`;
}

function chip(kind, text) {
  return `<span class="chip chip-${esc(kind)}">${esc(text)}</span>`;
}

function renderStage(stage, tool, now, t) {
  const rows = [];
  const chips = [];
  rows.push(`<div class="row"><dt>${esc(t.branch)}</dt><dd><code>${esc(stage.branch)}</code>${stage.branch_missing ? `<span class="note-inline">${esc(t.branchMissing)}</span>` : ""}</dd></div>`);
  rows.push(commitRow(t.github, stage.head, now, t));
  if (stage.key === "development") {
    rows.push(`<div class="row"><dt>${esc(t.running)}</dt><dd class="muted">${esc(tool.key === "next" ? t.sameStaging : t.noServer)}</dd></div>`);
  } else if (tool.key === "odoo" && stage.key === "production") {
    const firms = stage.firms_total;
    if (firms === null || firms === undefined || firms === 0) {
      rows.push(`<div class="row"><dt>${esc(t.running)}</dt><dd class="muted">${esc(t.noFirms)}</dd></div>`);
    } else {
      rows.push(commitRow(t.running, stage.running, now, t));
      rows.push(`<div class="row"><dt>${esc(t.firms(firms))}</dt><dd>${esc(t.onTarget(stage.firms_on_target ?? 0, firms))}</dd></div>`);
    }
    if (stage.rollout) chips.push(chip(stage.rollout.state === "stopped" ? "bad" : "info", `${t.rollout[stage.rollout.state] || stage.rollout.state} (${stage.rollout.done}/${stage.rollout.total})`));
  } else {
    rows.push(commitRow(t.running, stage.running, now, t));
  }
  if (stage.site) rows.push(`<div class="row"><dt>Site</dt><dd><a href="https://${esc(stage.site)}">${esc(stage.site)}</a></dd></div>`);
  if (stage.health) chips.push(chip({ ok: "ok", down: "bad", unknown: "muted" }[stage.health] || "muted", t.health[stage.health] || stage.health));
  if (stage.key !== "development" && !(tool.key === "odoo" && stage.key === "production" && !stage.firms_total)) {
    if (stage.matches === true) chips.push(chip("ok", t.match));
    else if (stage.matches === false) chips.push(chip("warn", t.differ));
    else chips.push(chip("muted", t.unknownMatch));
  }
  if (stage.behind_github) chips.push(chip("warn", t.behind(stage.behind_github)));
  if (stage.mail_off !== undefined && stage.mail_off !== null) chips.push(chip(stage.mail_off && stage.band_on ? "ok" : "bad", stage.mail_off && stage.band_on ? t.mail.on : t.mail.off));
  if (stage.key === "production" || stage.key === "staging") {
    if (stage.last_promotion !== undefined) {
      const lp = stage.last_promotion;
      rows.push(`<div class="row"><dt>${esc(t.lastPromotion)}</dt><dd>${lp && lp.at ? `${lp.sha ? `<code>${esc(lp.sha.slice(0, 7))}</code>` : ""}<span class="when">${dateTime(lp.at, now, t)}</span>` : `<span class="muted">${esc(t.never)}</span>`}</dd></div>`);
    }
    if (stage.last_rebuild !== undefined) {
      const lr = stage.last_rebuild;
      rows.push(`<div class="row"><dt>${esc(t.lastRebuild)}</dt><dd>${lr && lr.at ? `<span class="when">${dateTime(lr.at, now, t)}</span>` : `<span class="muted">${esc(t.never)}</span>`}</dd></div>`);
    }
  }
  const action = stage.action
    ? `<a class="button ${stage.action === "promote" ? "button-primary" : ""}" href="${esc(PIPELINE_URL)}" rel="nofollow">${esc(stage.action === "promote" ? t.promote : t.rebuild)}</a>`
    : "";
  return `<article class="stage stage-${esc(stage.key)}">
<header><h3>${esc(t.stages[stage.key])}</h3><div class="chips">${chips.join("")}</div></header>
<dl>${rows.join("")}</dl>${action}
</article>`;
}

function connector(stage, next, t) {
  const n = stage.key === "development" ? stage.ahead_of_next : stage.ahead_of_next;
  const from = t.stages[stage.key];
  const to = t.stages[next.key];
  const label = n === null || n === undefined ? t.unknownAhead : t.ahead(n, from, to);
  return `<div class="link${n ? " link-ahead" : ""}" aria-label="${esc(label)}"><span class="arrow" aria-hidden="true"></span><span class="link-text">${esc(label)}</span></div>`;
}

function renderTool(tool, now, t) {
  const parts = [];
  tool.stages.forEach((stage, index) => {
    parts.push(renderStage(stage, tool, now, t));
    if (index < tool.stages.length - 1) parts.push(connector(stage, tool.stages[index + 1], t));
  });
  const notices = [];
  if (tool.no_access) notices.push(`<p class="notice">${esc(t.noAccess)}</p>`);
  if (tool.stale && tool.read_at) notices.push(`<p class="notice">${esc(t.stale(clock(tool.read_at)))}</p>`);
  const hasButtons = tool.key === "odoo";
  return `<section class="tool tool-${esc(tool.key)}" aria-labelledby="t-${esc(tool.key)}">
<h2 id="t-${esc(tool.key)}">${esc(t.tools[tool.key])}</h2>
<p class="tool-note">${esc(t.toolNote[tool.key])}</p>
${notices.join("")}
${parts.join("\n")}
${hasButtons ? `<p class="buttons-note">${esc(t.buttonsNote)}</p>` : ""}
</section>`;
}

const STYLE = `
:root{color-scheme:light dark;--bg:#f3f5f4;--panel:#fff;--ink:#16211c;--soft:#46534d;--muted:#66736c;--line:#d5dcd7;--accent:#0f6e56;--accent-ink:#fff;--ok:#12703f;--ok-bg:#e3f4ea;--warn:#8a5a00;--warn-bg:#fbf0d9;--bad:#a92d24;--bad-bg:#fbe6e4;--info:#1c5f93;--info-bg:#e2eff8;--chip:#eef2ef}
@media (prefers-color-scheme:dark){:root{--bg:#0f1512;--panel:#17211c;--ink:#e6eeea;--soft:#c0cdc6;--muted:#93a29b;--line:#2c3a33;--accent:#4fc39e;--accent-ink:#06231a;--ok:#6fd8a1;--ok-bg:#12301f;--warn:#e7bf6b;--warn-bg:#33270f;--bad:#f09a92;--bad-bg:#3a1a17;--info:#8cc4ee;--info-bg:#132a3b;--chip:#1e2a24}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 48px}
.top{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px 24px;margin-bottom:6px}
h1{font-size:24px;line-height:1.2;margin:0;letter-spacing:-.01em}
.lang{font-size:14px}
.lede{margin:0 0 4px;color:var(--soft)}
.fresh{margin:0 0 22px;color:var(--muted);font-size:13.5px}
a{color:var(--accent)}
code{font:600 13.5px/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.tools{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:28px}
@media (max-width:900px){.tools{grid-template-columns:minmax(0,1fr)}}
h2{font-size:18px;margin:0 0 2px}
.tool-note{margin:0 0 14px;color:var(--soft);font-size:13.5px;min-height:2.9em}
@media (max-width:900px){.tool-note{min-height:0}}
.notice{margin:0 0 12px;padding:9px 12px;border-radius:8px;background:var(--warn-bg);color:var(--warn);font-size:13.5px}
.stage{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.stage-production{border-top:3px solid var(--accent)}
.stage header{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;justify-content:space-between;margin-bottom:10px}
h3{font-size:15.5px;margin:0}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600;line-height:1.5;background:var(--chip);color:var(--soft)}
.chip-ok{background:var(--ok-bg);color:var(--ok)}
.chip-warn{background:var(--warn-bg);color:var(--warn)}
.chip-bad{background:var(--bad-bg);color:var(--bad)}
.chip-info{background:var(--info-bg);color:var(--info)}
dl{margin:0;display:grid;gap:6px}
.row{display:grid;grid-template-columns:128px minmax(0,1fr);gap:10px;align-items:baseline}
@media (max-width:420px){.row{grid-template-columns:minmax(0,1fr);gap:0}}
dt{color:var(--muted);font-size:13px}
dd{margin:0;font-size:14px;display:flex;flex-wrap:wrap;gap:2px 10px;align-items:baseline;min-width:0;overflow-wrap:anywhere}
.who{font-size:13.5px}
.when,.muted,.note-inline{color:var(--muted);font-size:13px}
.link{display:flex;align-items:center;gap:10px;padding:6px 0 6px 20px;color:var(--muted);font-size:13px}
.arrow{position:relative;flex:none;width:2px;height:24px;background:var(--line)}
.arrow::after{content:"";position:absolute;left:-4px;bottom:-1px;width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:7px solid var(--line)}
.link-ahead{color:var(--warn);font-weight:600}
.link-ahead .arrow{background:var(--warn)}
.link-ahead .arrow::after{border-top-color:var(--warn)}
.button{display:inline-block;margin-top:12px;padding:8px 12px;min-height:38px;border-radius:7px;border:1px solid var(--accent);color:var(--accent);font-weight:600;font-size:13.5px;text-decoration:none}
.button-primary{background:var(--accent);color:var(--accent-ink)}
.button:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.buttons-note{margin:10px 0 0;color:var(--muted);font-size:12.5px}
footer{margin-top:28px;font-size:13.5px;color:var(--muted)}
`;

function render(model, lang) {
  const t = TEXT[lang];
  const now = model.generated;
  return `<!doctype html><html lang="${t.lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta http-equiv="refresh" content="60">
<title>${esc(t.title)}</title><style>${STYLE}</style></head>
<body><main>
<div class="top"><h1>${esc(t.title)}</h1><a class="lang" href="${t.otherHref}" lang="${lang === "fr" ? "en" : "fr"}">${esc(t.other)}</a></div>
<p class="lede">${esc(t.intro)}</p>
<p class="fresh">${esc(t.read(clock(now)))} ${esc(t.delay)}</p>
<div class="tools">
${model.tools.map((tool) => renderTool(tool, now, t)).join("\n")}
</div>
<footer><a href="details.html">${esc(t.details)}</a></footer>
</main></body></html>
`;
}

// Only what the page itself shows, for anyone who prefers the figures.
function publicModel(model) {
  const pick = (stage) => {
    const out = { key: stage.key, branch: stage.branch };
    for (const name of ["head", "running"]) {
      if (stage[name]) out[name] = { sha: stage[name].sha, author: stage[name].author, at: stage[name].at };
    }
    for (const name of ["matches", "health", "ahead_of_next", "behind_github", "firms_total", "firms_on_target", "last_promotion", "last_rebuild", "rollout", "mail_off", "band_on", "site"]) {
      if (stage[name] !== undefined) out[name] = stage[name];
    }
    return out;
  };
  return {
    schema: 1, generated: model.generated,
    tools: model.tools.map((tool) => ({ key: tool.key, github_ok: tool.github_ok, stale: Boolean(tool.stale), stages: tool.stages.map(pick) })),
  };
}

function writeAtomic(file, text) {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, text, { mode: 0o644 });
  fs.renameSync(tmp, file);
}

function main(argv) {
  const modelFlag = argv.indexOf("--model");
  const dumpFlag = argv.indexOf("--dump-model");
  let model;
  if (modelFlag >= 0) {
    model = JSON.parse(fs.readFileSync(argv[modelFlag + 1], "utf8"));
  } else {
    // The page gen-status.js just wrote becomes details.html. If anything below fails, the old page stays as
    // index.html, and it still reads correctly: this script can fail without taking the page down.
    const fresh = path.join(WWW, "index.html");
    const marker = "<!-- ea-pipeline-page -->";
    if (fs.existsSync(fresh) && !fs.readFileSync(fresh, "utf8").includes(marker)) {
      fs.copyFileSync(fresh, path.join(WWW, "details.html"));
    }
    // The last page goes back at once, so a visitor does not see the old one while GitHub is being read.
    const last = path.join(STATE, "last-index.html");
    if (fs.existsSync(last)) writeAtomic(fresh, fs.readFileSync(last, "utf8"));
    model = collect(new Date().toISOString());
  }
  if (dumpFlag >= 0) fs.writeFileSync(argv[dumpFlag + 1], JSON.stringify(model, null, 1));
  const stamp = "<!-- ea-pipeline-page -->\n";
  writeAtomic(path.join(WWW, "index.html"), stamp + render(model, "fr"));
  writeAtomic(path.join(WWW, "en.html"), stamp + render(model, "en"));
  writeAtomic(path.join(WWW, "pipeline.json"), `${JSON.stringify(publicModel(model), null, 1)}\n`);
  if (modelFlag < 0) {
    fs.mkdirSync(STATE, { recursive: true });
    fs.copyFileSync(path.join(WWW, "index.html"), path.join(STATE, "last-index.html"));
  }
}

if (require.main === module) main(process.argv.slice(2));

module.exports = { render, publicModel, readPlatformState, readStagingState, esc, collectOdoo, odooStages, TEXT };
