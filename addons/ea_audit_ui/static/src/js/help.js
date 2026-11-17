import { Component, markup, onWillStart, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { debounce } from "@web/core/utils/timing";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { shellSession } from "./context_service";

/** The user manual ships with the add-on: static pages in English and French, one index. */
const MANUAL = "/ea_audit_ui/static/manual";

/** fr_FR (and any French) reads the French pages; every other language the English ones. */
export function manualLanguage() {
    const lang = shellSession?.language || user.lang || "en_US";
    return lang.startsWith("fr") ? "fr" : "en";
}

/**
 * The names under which the help pages know the screen on display, most precise first:
 * a client action's tag, a tool board's view, a dataset's kind, the model and view type,
 * the action's XML id, then the model alone. Each page lists the names it explains.
 */
export function helpKeys(controller) {
    const action = controller?.action || {};
    const props = controller?.props || {};
    const context = action.context || {};
    const keys = [];
    if (action.tag) {
        keys.push(`tag:${action.tag}`);
    }
    if (context.ea_help_view && props.resModel === "ea.audit.engagement") {
        keys.push(`view:${context.ea_help_view}`);
    }
    if (context.ea_dataset_kind) {
        keys.push(`dataset:${context.ea_dataset_kind}`);
    }
    if (props.resModel && props.type) {
        keys.push(`model:${props.resModel}:${props.type}`);
    }
    if (action.xml_id) {
        keys.push(action.xml_id);
    }
    if (props.resModel) {
        keys.push(`model:${props.resModel}`);
    }
    return keys;
}

/** The first page that explains one of the keys, in the keys' order. */
export function pageForKeys(index, keys) {
    for (const key of keys || []) {
        const page = index.pages.find((p) => p.screens.includes(key));
        if (page) {
            return page.id;
        }
    }
    return null;
}

/** Lower case, without accents: "écart" is found by "ecart". */
function fold(text) {
    return (text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** Pages whose title or words hold every word typed, title matches first, with a line of context. */
export function searchPages(index, words, lang, query) {
    const terms = fold(query).split(/\s+/).filter((t) => t.length > 1);
    if (!terms.length) {
        return [];
    }
    const results = [];
    for (const page of index.pages) {
        const title = fold(page.title[lang]);
        const raw = words[page.id] || "";
        const body = fold(raw);
        if (!terms.every((t) => title.includes(t) || body.includes(t))) {
            continue;
        }
        const at = body.indexOf(terms[0]);
        const start = Math.max(0, at - 50);
        const snippet = at < 0 ? "" : `${start ? "…" : ""}${raw.slice(start, at + 90)}…`;
        const score = terms.filter((t) => title.includes(t)).length;
        results.push({ id: page.id, title: page.title[lang], snippet, score });
    }
    return results.sort((a, b) => b.score - a.score);
}

export class EaHelp extends Component {
    static template = "ea_audit_ui.Help";
    static props = { ...standardActionServiceProps };
    static path = "ea-help";
    static displayName = _t("User manual");

    setup() {
        this.lang = manualLanguage();
        this.state = useState({
            index: null,
            failed: false,
            page: null,
            html: null,
            // the page of the screen the manual was opened from
            screenPage: null,
            query: "",
            results: null,
            contentsOpen: false,
        });
        this.words = null;
        this.root = useRef("root");
        this.askedForScreen = Boolean(this.props.action.params?.keys?.length);
        this.runSearch = debounce(this.runSearch.bind(this), 200);
        const params = this.props.action.params || {};
        onWillStart(async () => {
            try {
                const response = await browser.fetch(`${MANUAL}/index.json`, { cache: "no-cache" });
                if (!response.ok) {
                    throw new Error(response.statusText);
                }
                this.state.index = await response.json();
            } catch {
                this.state.failed = true;
                return;
            }
            this.state.screenPage = pageForKeys(this.state.index, params.keys);
            const first = params.page || this.state.screenPage;
            if (first && this.findPage(first)) {
                await this.loadPage(first);
            }
        });
    }

    findPage(id) {
        return this.state.index?.pages.find((p) => p.id === id);
    }

    get parts() {
        const index = this.state.index;
        if (!index) {
            return [];
        }
        return index.parts.map((part) => ({
            key: part.key,
            title: part[this.lang],
            pages: index.pages.filter((p) => p.part === part.key).map((p) => ({ id: p.id, title: p.title[this.lang] })),
        }));
    }

    get partTitle() {
        const page = this.findPage(this.state.page);
        const part = page && this.state.index.parts.find((p) => p.key === page.part);
        return part ? part[this.lang] : "";
    }

    get neighbours() {
        const pages = this.state.index?.pages || [];
        const at = pages.findIndex((p) => p.id === this.state.page);
        const link = (p) => p && { id: p.id, title: p.title[this.lang] };
        return { previous: at > 0 ? link(pages[at - 1]) : null, next: at >= 0 ? link(pages[at + 1]) : null };
    }

    get onScreenPage() {
        return Boolean(this.state.screenPage) && this.state.page === this.state.screenPage;
    }

    /** Opened from a screen the manual has no page for: the contents say so. */
    get noScreenPage() {
        return this.askedForScreen && !this.state.screenPage;
    }

    async loadPage(id) {
        const build = this.state.index.build;
        try {
            const response = await browser.fetch(`${MANUAL}/${this.lang}/${id}.html?v=${build}`);
            if (!response.ok) {
                throw new Error(response.statusText);
            }
            // Pages are files of this add-on, written by the firm's supplier, never user input.
            this.state.html = markup(await response.text());
            this.state.page = id;
            this.state.failed = false;
        } catch {
            this.state.html = null;
            this.state.page = null;
            this.state.failed = true;
        }
        this.state.contentsOpen = false;
        if (this.state.page) {
            // a reload comes back to the same page
            this.props.updateActionState({ page: this.state.page });
        }
        if (this.root.el) {
            this.root.el.scrollTop = 0;
        }
    }

    openPage(id) {
        if (this.findPage(id)) {
            return this.loadPage(id);
        }
    }

    showContents() {
        this.state.page = null;
        this.state.html = null;
        this.state.contentsOpen = false;
    }

    toggleContents() {
        this.state.contentsOpen = !this.state.contentsOpen;
    }

    /** A link to another page of the manual opens it here; other links keep their meaning. */
    onArticleClick(ev) {
        const link = ev.target.closest?.("a[href^='#']");
        if (!link) {
            return;
        }
        ev.preventDefault();
        this.openPage(link.getAttribute("href").slice(1));
    }

    onSearchInput(ev) {
        this.state.query = ev.target.value;
        this.runSearch();
    }

    async runSearch() {
        const query = this.state.query.trim();
        if (query.length < 2) {
            this.state.results = null;
            return;
        }
        if (!this.words) {
            try {
                const build = this.state.index.build;
                const response = await browser.fetch(`${MANUAL}/search-${this.lang}.json?v=${build}`);
                this.words = await response.json();
            } catch {
                this.words = {};
            }
        }
        this.state.results = searchPages(this.state.index, this.words, this.lang, query);
    }

    pickResult(result) {
        this.state.query = "";
        this.state.results = null;
        return this.openPage(result.id);
    }
}

registry.category("actions").add("ea_audit_ui.help", EaHelp);
