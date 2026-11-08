/** @odoo-module **/
import { markup } from "@odoo/owl";

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");
const SEP = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/;

export function renderMarkdown(text) {
    const lines = esc(String(text || "")).split("\n");
    const out = [];
    let inList = false;
    let table = [];
    const flushList = () => {
        if (inList) {
            out.push("</ul>");
            inList = false;
        }
    };
    const flushTable = () => {
        if (!table.length) {
            return;
        }
        const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
        const rows = table.filter((r) => !SEP.test(r.trim())).map(cells);
        out.push('<table class="o_ai_table">');
        rows.forEach((row, i) => {
            const tag = i === 0 ? "th" : "td";
            out.push("<tr>" + row.map((c) => `<${tag}>${c}</${tag}>`).join("") + "</tr>");
        });
        out.push("</table>");
        table = [];
    };
    for (const line of lines) {
        if (line.trim().startsWith("|")) {
            flushList();
            table.push(line);
            continue;
        }
        flushTable();
        const li = line.match(/^\s*[-*]\s+(.*)$/);
        if (li) {
            if (!inList) {
                out.push('<ul dir="auto">');
                inList = true;
            }
            out.push("<li>" + inline(li[1]) + "</li>");
            continue;
        }
        flushList();
        out.push(line.trim() ? '<div dir="auto">' + inline(line) + "</div>" : '<div class="o_ai_sp"></div>');
    }
    flushList();
    flushTable();
    return markup(out.join(""));
}
