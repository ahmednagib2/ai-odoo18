/** @odoo-module **/
import { Component, useState, useRef, useEffect, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { deserializeDate, deserializeDateTime } from "@web/core/l10n/dates";
import { renderMarkdown } from "./markdown";
import { aiFormRegistry } from "./form_registry";

const MAX_FILES = 4;
const MAX_BYTES = 8 * 1024 * 1024;
const INLINE_TYPES = [
    "image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf",
];
const TEXT_EXT = [];
const ACCEPT = "image/png,image/jpeg,image/webp,image/gif,application/pdf";
const SUGGESTIONS = [
    "إيه مبيعات النهاردة؟",
    "وريني الفواتير المتأخرة",
    "افتحلي المخزون",
    "لخّص لي السجل المفتوح",
];

const extOf = (name) => (name && name.includes(".") ? name.split(".").pop().toLowerCase() : "");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export class AiChat extends Component {
    static template = "ai_assistant.Chat";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.menu = useService("menu");
        this.listRef = useRef("list");
        this.fileRef = useRef("file");
        this.timers = [];
        this.recognition = null;
        this.lastRequest = null;
        this.watching = false;
        this.suggestions = SUGGESTIONS;
        this.accept = ACCEPT;
        this.state = useState({
            allowed: false,
            open: false,
            maximized: false,
            loading: false,
            loaded: false,
            listening: false,
            status: "",
            hello: "",
            input: "",
            providerId: parseInt(localStorage.getItem("ai_assistant.provider")) || false,
            providers: [],
            messages: [],
            attachments: [],
        });
        useEffect(
            () => {
                this.scrollDown();
            },
            () => [this.state.messages.length, this.state.open, this.state.loading]
        );
        // The AI button is shown only to users who have access (group-based, decided by the server).
        onMounted(async () => {
            try {
                const me = await rpc("/ai_assistant/me", {});
                this.state.allowed = !!(me && me.allowed);
                this.state.hello = (me && me.name) || "";
            } catch {
                this.state.allowed = false;
            }
        });
        onWillUnmount(() => {
            this.watching = false;
            this.timers.forEach((t) => clearInterval(t));
            if (this.recognition) {
                this.recognition.stop();
            }
        });
    }

    scrollDown() {
        const el = this.listRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    md(text) {
        return renderMarkdown(text);
    }

    isImage(a) {
        return a.mimetype.startsWith("image/");
    }

    src(a) {
        return "data:" + a.mimetype + ";base64," + a.data;
    }

    friendly(raw) {
        const text = String(raw || "");
        if (/Failed to fetch|NetworkError|ConnectionLost|Load failed/i.test(text)) {
            return "تعذّر الاتصال بالخادم. تأكد من الإنترنت ثم أعد المحاولة.";
        }
        if (/timeout|timed out|504|502|Odoo Server Error/i.test(text)) {
            return "الطلب أخذ وقتاً أطول من المتوقع. أعد المحاولة أو اكتبه بشكل أبسط.";
        }
        return text;
    }

    getContext() {
        try {
            const c = this.action.currentController;
            const p = (c && c.props) || {};
            return {
                model: p.resModel || null,
                res_id: p.resId || null,
                name: (c && c.displayName) || null,
                view_type: (c && c.view && c.view.type) || p.type || null,
            };
        } catch {
            return {};
        }
    }

    // Polls the server for what the assistant is doing right now ("opening...", "searching...").
    startWatch() {
        this.state.status = "";
        if (this.watching) {
            return;
        }
        this.watching = true;
        const loop = async () => {
            while (this.watching) {
                try {
                    const r = await rpc("/ai_assistant/status", {});
                    if (this.watching) {
                        this.state.status = (r && r.status) || "";
                    }
                } catch {
                    /* ignore */
                }
                await sleep(800);
            }
        };
        loop();
    }

    stopWatch() {
        this.watching = false;
        this.state.status = "";
    }

    async loadProviders() {
        this.state.providers = await rpc("/ai_assistant/providers", {});
        const ids = this.state.providers.map((p) => p.id);
        if (!ids.includes(this.state.providerId)) {
            this.state.providerId = ids[0] || false;
        }
    }

    async toggle() {
        this.state.open = !this.state.open;
        if (!this.state.open) {
            return;
        }
        try {
            await this.loadProviders();
            if (!this.state.loaded) {
                this.state.messages = await rpc("/ai_assistant/history", {});
                this.state.loaded = true;
            }
        } catch (e) {
            this.push("error", this.friendly(e.message || e));
        }
    }

    toggleMax() {
        this.state.maximized = !this.state.maximized;
    }

    onProviderChange(ev) {
        this.state.providerId = parseInt(ev.target.value) || false;
        localStorage.setItem("ai_assistant.provider", this.state.providerId);
    }

    push(role, content, extra = {}) {
        this.state.messages.push({ role, content, ...extra });
    }

    async copy(m) {
        try {
            await navigator.clipboard.writeText(m.content || "");
        } catch {
            /* ignore */
        }
    }

    // Reveals the answer quickly (short typing effect, about half a second at most).
    typeOut(text) {
        text = String(text || "");
        this.state.messages.push({ role: "assistant", content: "" });
        const msg = this.state.messages[this.state.messages.length - 1];
        const step = Math.max(3, Math.ceil(text.length / 35));
        let i = 0;
        return new Promise((resolve) => {
            const timer = setInterval(() => {
                i += step;
                msg.content = text.slice(0, i);
                this.scrollDown();
                if (i >= text.length) {
                    clearInterval(timer);
                    resolve();
                }
            }, 15);
            this.timers.push(timer);
        });
    }

    async newChat() {
        try {
            await rpc("/ai_assistant/new", {});
        } finally {
            this.state.messages = [];
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    useSuggestion(text) {
        this.state.input = text;
        this.send();
    }

    // Removes the failed exchange from the screen and sends the same request again.
    retry(m) {
        if (!this.lastRequest || this.state.loading) {
            return;
        }
        const idx = this.state.messages.indexOf(m);
        if (idx >= 0) {
            this.state.messages.splice(idx, 1);
            const prev = this.state.messages[idx - 1];
            if (prev && prev.role === "user") {
                this.state.messages.splice(idx - 1, 1);
            }
        }
        this.state.input = this.lastRequest.text;
        this.state.attachments = this.lastRequest.files.slice();
        this.send();
    }

    // ---------- attachments: picker, drag & drop, paste ----------
    pickFile() {
        if (this.fileRef.el) {
            this.fileRef.el.click();
        }
    }

    supported(f) {
        return INLINE_TYPES.includes(f.type) || TEXT_EXT.includes(extOf(f.name)) || f.type.startsWith("text/");
    }

    async addFiles(list) {
        for (const f of Array.from(list)) {
            if (this.state.attachments.length >= MAX_FILES) {
                this.push("error", "الحد الأقصى " + MAX_FILES + " ملفات لكل رسالة.");
                break;
            }
            if (!this.supported(f)) {
                this.push("error", "نوع الملف غير مدعوم: " + f.name);
                continue;
            }
            if (f.size > MAX_BYTES) {
                this.push("error", "الملف كبير (الحد الأقصى 8 ميجا): " + f.name);
                continue;
            }
            const data = await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(String(reader.result).split(",")[1]);
                reader.onerror = reject;
                reader.readAsDataURL(f);
            });
            this.state.attachments.push({
                name: f.name || "pasted.png",
                mimetype: f.type || "application/octet-stream",
                data,
            });
        }
    }

    async onFiles(ev) {
        const files = [...ev.target.files];
        ev.target.value = "";
        await this.addFiles(files);
    }

    onDragOver() {}

    async onDrop(ev) {
        if (ev.dataTransfer && ev.dataTransfer.files.length) {
            await this.addFiles(ev.dataTransfer.files);
        }
    }

    async onPaste(ev) {
        const files = ev.clipboardData && ev.clipboardData.files;
        if (files && files.length) {
            ev.preventDefault();
            await this.addFiles(files);
        }
    }

    removeFile(index) {
        this.state.attachments.splice(index, 1);
    }

    // ---------- voice dictation (browser speech recognition) ----------
    toggleMic() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
            this.push("error", "الإملاء الصوتي غير مدعوم في هذا المتصفح (استخدم Chrome أو Edge).");
            return;
        }
        if (this.recognition) {
            this.recognition.stop();
            return;
        }
        const rec = new SR();
        const htmlLang = document.documentElement.getAttribute("lang") || "";
        rec.lang = htmlLang.toLowerCase().startsWith("en") ? "en-US" : "ar-SA";
        rec.interimResults = true;
        rec.continuous = true;
        const base = this.state.input ? this.state.input + " " : "";
        rec.onresult = (e) => {
            const text = Array.from(e.results)
                .map((r) => r[0].transcript)
                .join(" ");
            this.state.input = base + text;
        };
        rec.onerror = () => {};
        rec.onend = () => {
            this.recognition = null;
            this.state.listening = false;
        };
        this.recognition = rec;
        this.state.listening = true;
        rec.start();
    }

    // ---------- actions from the assistant ----------
    async navigate(nav) {
        try {
            if (nav.kind === "menu") {
                await this.menu.selectMenu(nav.menu_id);
            } else {
                await this.action.doAction(nav.action);
            }
        } catch (e) {
            this.push("error", this.friendly((e && e.message) || e));
        }
    }

    async applyFill(fill) {
        const ctrl = aiFormRegistry.current;
        const root = ctrl && ctrl.model && ctrl.model.root;
        if (!root || root.resModel !== fill.model) {
            this.push("error", "النموذج لم يعد مفتوحاً.");
            return;
        }
        const changes = {};
        for (const [name, spec] of Object.entries(fill.values)) {
            if (!(name in root.fields)) {
                continue;
            }
            let value = spec.value;
            if (spec.type === "date") {
                value = deserializeDate(value);
            } else if (spec.type === "datetime") {
                value = deserializeDateTime(value);
            } else if (spec.type === "many2one") {
                value = { id: spec.value, display_name: spec.display };
            }
            changes[name] = value;
        }
        try {
            await root.update(changes);
        } catch (e) {
            this.push("error", this.friendly((e && e.message) || e));
        }
    }

    async handle(res) {
        if (res.type === "confirm") {
            this.push("assistant", "مقترح: " + res.summary, {
                pendingId: res.pending_id,
                details: res.details,
                status: "pending",
            });
        } else if (res.type === "error") {
            this.push("error", this.friendly(res.message), { retry: true });
        } else {
            await this.typeOut(res.message);
            if (res.type === "navigate") {
                await this.navigate(res.navigate);
            } else if (res.type === "fill") {
                await this.applyFill(res.fill);
            }
        }
    }

    async send() {
        const text = this.state.input.trim();
        if ((!text && !this.state.attachments.length) || this.state.loading) {
            return;
        }
        if (this.recognition) {
            this.recognition.stop();
        }
        if (!this.state.providerId) {
            try {
                await this.loadProviders();
            } catch {
                /* ignore */
            }
        }
        if (!this.state.providerId) {
            this.push("error", "لا يوجد مزود ذكاء اصطناعي مفعّل. اذهب إلى الإعدادات > AI Assistant > Providers وأضف مفتاح API ثم فعّل المزود.");
            return;
        }
        const files = this.state.attachments.slice();
        this.lastRequest = { text, files };
        this.state.input = "";
        this.state.attachments = [];
        this.push("user", text + files.map((f) => "\n[file: " + f.name + "]").join(""));
        this.state.loading = true;
        this.startWatch();
        try {
            const res = await rpc("/ai_assistant/chat", {
                provider_id: this.state.providerId,
                text,
                context: this.getContext(),
                attachments: files,
            });
            this.stopWatch();
            this.state.loading = false;
            await this.handle(res);
        } catch (e) {
            this.push("error", this.friendly((e.data && e.data.message) || e.message || e), { retry: true });
        } finally {
            this.stopWatch();
            this.state.loading = false;
        }
    }

    async decide(msg, approve) {
        msg.status = "busy";
        this.state.loading = true;
        this.startWatch();
        try {
            const res = await rpc("/ai_assistant/confirm", { pending_id: msg.pendingId, approve });
            this.stopWatch();
            this.state.loading = false;
            const ok = res.type === "reply" || res.type === "navigate";
            msg.status = ok ? (approve ? "done" : "cancelled") : "failed";
            await this.handle(res);
            if (ok && approve && res.type !== "navigate") {
                try {
                    await this.action.doAction("soft_reload");
                } catch {
                    /* ignore */
                }
            }
        } catch (e) {
            msg.status = "pending";
            this.push("error", this.friendly((e.data && e.data.message) || e.message || e));
        } finally {
            this.stopWatch();
            this.state.loading = false;
        }
    }
}

// Button in the top navbar (systray), placed just left of the Discuss / messaging icon.
registry.category("systray").add("ai_assistant.systray", { Component: AiChat }, { sequence: 26 });
