import { reactive } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

/** The top bar's facts, absent for someone outside the firm. */
export const shellSession = session.ea_audit_shell || null;

const UI_MODEL = "ea.audit.ui";

/**
 * What the top bar and the screens share: the mission the user is in, the ring
 * that is open, and the ways to move between screens.
 */
const contextService = {
    dependencies: ["orm", "action"],
    // openItem opens the paper: the renderer of ea_audit_papers, inside this top bar.
    start(env, { orm, action }) {
        const state = reactive({
            mission: null,
            openSection: null,
            // what the bar shows on a screen that belongs to one phase: a paper, a group
            pageSection: null,
            screen: "home",
            recent: [],
            unread: 0,
        });
        const call = (method, ...args) => orm.call(UI_MODEL, method, args);
        const clientAction = (tag, name, params) => ({
            type: "ir.actions.client",
            tag,
            name,
            params,
        });
        return {
            state,
            call,
            async refreshShell() {
                const shell = await call("ea_ui_shell");
                state.recent = shell.recent;
                state.unread = shell.unread;
            },
            enterHome() {
                state.mission = null;
                state.openSection = null;
                state.screen = "home";
            },
            enterMission(mission) {
                if (state.mission?.id !== mission.id) {
                    state.openSection = null;
                }
                state.mission = mission;
                state.pageSection = null;
                state.screen = "mission";
            },
            openHome() {
                return action.doAction("ea_audit_ui.action_home", { clearBreadcrumbs: true });
            },
            openMissions() {
                state.mission = null;
                state.openSection = null;
                state.screen = "missions";
                return action.doAction("ea_audit_core.action_engagement", { clearBreadcrumbs: true });
            },
            openDashboard(engagementId, section = null) {
                const current = action.currentController?.action;
                state.openSection = section;
                if (current?.tag === "ea_audit_ui.dashboard" && state.mission?.id === engagementId) {
                    return;
                }
                return action.doAction(
                    clientAction("ea_audit_ui.dashboard", _t("Engagement dashboard"), {
                        resId: engagementId,
                        section,
                    }),
                    { clearBreadcrumbs: true }
                );
            },
            openTasks(engagementId, group) {
                return action.doAction(
                    clientAction("ea_audit_ui.tasks", _t("Task list"), { resId: engagementId, group })
                );
            },
            openAllTasks(engagementId) {
                return action.doAction(clientAction("ea_audit_ui.all_tasks", _t("Tasks"), { resId: engagementId }));
            },
            openItem(itemId) {
                return action.doAction({
                    type: "ir.actions.client",
                    tag: "ea_audit_paper",
                    name: _t("Working paper"),
                    params: { file_item_id: itemId },
                    context: { active_id: itemId },
                });
            },
            /** A method of the engagement that returns the action of a tool. */
            async openTool(engagementId, method) {
                const description = await orm.call("ea.audit.engagement", method, [[engagementId]]);
                return action.doAction(description);
            },
            openItems(itemIds, name) {
                return action.doAction({
                    type: "ir.actions.act_window",
                    name,
                    res_model: "ea.audit.file.item",
                    domain: [["id", "in", itemIds]],
                    views: [
                        [false, "list"],
                        [false, "form"],
                    ],
                });
            },
            openForm(model, resId) {
                return action.doAction({
                    type: "ir.actions.act_window",
                    res_model: model,
                    res_id: resId,
                    views: [[false, "form"]],
                });
            },
            openXmlid(xmlid) {
                return action.doAction(xmlid);
            },
            /** Keeps the top bar right when a form or a list opens by another road. */
            async syncFromController() {
                const controller = action.currentController;
                const current = controller?.action;
                const enter = async (model, id) => {
                    const mission = await call("ea_ui_context", model, id);
                    if (mission) {
                        state.mission = mission;
                        state.pageSection = mission.item_section || null;
                        state.screen = "mission";
                    }
                };
                // a group's page keeps the phase it set; every other screen starts clean
                if (current?.tag !== "ea_audit_ui.tasks") {
                    state.pageSection = null;
                }
                state.onDashboard = current?.tag === "ea_audit_ui.dashboard";
                state.onAllTasks = current?.tag === "ea_audit_ui.all_tasks";
                if (current?.tag === "ea_audit_paper") {
                    const itemId = Number(current.params?.file_item_id || current.context?.active_id);
                    return itemId ? enter("ea.audit.file.item", itemId) : undefined;
                }
                if (current?.type !== "ir.actions.act_window") {
                    return;
                }
                const toolEngagement = current.context?.ea_engagement_id;
                if (toolEngagement) {
                    return enter("ea.audit.engagement", toolEngagement);
                }
                const { resModel, resId, type } = controller.props;
                if (resModel === "ea.audit.engagement" && type !== "form") {
                    state.mission = null;
                    state.screen = "missions";
                } else if (
                    type === "form" &&
                    resId &&
                    ["ea.audit.engagement", "ea.audit.file.item"].includes(resModel)
                ) {
                    const mission = await call("ea_ui_context", resModel, resId);
                    if (mission) {
                        state.mission = mission;
                        state.screen = "mission";
                    }
                }
            },
        };
    },
};

registry.category("services").add("ea_audit_context", contextService);
