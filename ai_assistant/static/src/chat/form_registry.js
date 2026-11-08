/** @odoo-module **/
import { onWillUnmount } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

// Keeps a reference to the form currently displayed so the assistant can fill it.
export const aiFormRegistry = { current: null };

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        const ctrl = this;
        aiFormRegistry.current = ctrl;
        onWillUnmount(() => {
            if (aiFormRegistry.current === ctrl) {
                aiFormRegistry.current = null;
            }
        });
    },
});
