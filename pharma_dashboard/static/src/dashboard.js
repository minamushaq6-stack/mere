import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export class PharmaDashboard extends Component {
    static template = "pharma_dashboard.Main";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.tabs = [
            { id: "overview", label: "نظرة عامة", icon: "fa-tachometer" },
            { id: "cash", label: "الصناديق", icon: "fa-money" },
            { id: "debts", label: "الذمم", icon: "fa-handshake-o" },
            { id: "sales", label: "المبيعات والمنتجات", icon: "fa-line-chart" },
            { id: "returns", label: "الرواجع", icon: "fa-undo" },
            { id: "stock", label: "المخزون والصلاحية", icon: "fa-cubes" },
            { id: "partners", label: "الأرباح والشركاء", icon: "fa-users" },
        ];
        this.periods = [
            { id: "today", label: "اليوم" },
            { id: "month", label: "هذا الشهر" },
            { id: "lastmonth", label: "الشهر الماضي" },
            { id: "quarter", label: "هذا الربع" },
            { id: "year", label: "هذه السنة" },
            { id: "custom", label: "مخصص" },
        ];
        this.state = useState({ loading: true, tab: "overview", period: "month", from: "", to: "", data: null, modal: null });
        onWillStart(() => this.setPeriod("month"));
    }

    async setPeriod(p) {
        const t = new Date();
        const y = t.getFullYear(), m = t.getMonth();
        this.state.period = p;
        if (p === "today") { this.state.from = this.state.to = iso(t); }
        else if (p === "month") { this.state.from = iso(new Date(y, m, 1)); this.state.to = iso(t); }
        else if (p === "lastmonth") { this.state.from = iso(new Date(y, m - 1, 1)); this.state.to = iso(new Date(y, m, 0)); }
        else if (p === "quarter") { this.state.from = iso(new Date(y, Math.floor(m / 3) * 3, 1)); this.state.to = iso(t); }
        else if (p === "year") { this.state.from = iso(new Date(y, 0, 1)); this.state.to = iso(t); }
        if (p !== "custom") { await this.load(); }
    }

    async onDate(ev, key) {
        this.state[key] = ev.target.value;
        this.state.period = "custom";
        if (this.state.from && this.state.to) { await this.load(); }
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call("pharma.dashboard", "get_data", [this.state.from, this.state.to]);
        this.state.loading = false;
    }

    get kpis() {
        const d = this.state.data;
        if (!d) { return []; }
        return [
            { label: "رصيد الصناديق والبنوك", value: d.cash_total, icon: "fa-money", tone: "teal", tab: "cash" },
            { label: "ديون العملاء (لنا)", value: d.receivable.total, sub: `متأخر: ${this.fmt(d.receivable.overdue)}`, icon: "fa-arrow-circle-down", tone: "green", tab: "debts" },
            { label: "ديون الموردين (علينا)", value: d.payable.total, sub: `متأخر: ${this.fmt(d.payable.overdue)}`, icon: "fa-arrow-circle-up", tone: "red", tab: "debts" },
            { label: "قيمة المخزون", value: d.inventory.total, sub: `${this.fmt(d.inventory.items)} صنف`, icon: "fa-cubes", tone: "blue", tab: "stock" },
            { label: "المبيعات", value: d.sales_total, sub: `${this.fmt(d.sales_count)} فاتورة/طلب`, icon: "fa-shopping-cart", tone: "purple", tab: "sales" },
            { label: "المشتريات", value: d.purch_total, icon: "fa-truck", tone: "orange", tab: "sales" },
            { label: "رواجع المبيعات", value: d.returns.sales.total, sub: `${d.returns.rate.toFixed(1)}% من المبيعات`, icon: "fa-undo", tone: "red", tab: "returns" },
            { label: "مجمل الربح", value: d.pl.gross, icon: "fa-bar-chart", tone: "teal", tab: "partners" },
            { label: "صافي الربح", value: d.pl.net, icon: "fa-trophy", tone: d.pl.net >= 0 ? "green" : "red", tab: "partners" },
        ];
    }

    fmt(n) { return (n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 }); }
    max(items, key) { return Math.max(1, ...(items || []).map((i) => Math.abs(i[key] || 0))); }
    pct(v, mx) { return v ? Math.max(3, Math.round((Math.abs(v) / mx) * 100)) : 0; }
    trendMax() { return Math.max(1, ...this.state.data.trend.flatMap((t) => [t.sales, t.purchases])); }
    async openBox(b) {
        const rows = await this.orm.call("pharma.dashboard", "get_box_moves", [b.id, this.state.from, this.state.to]);
        this.state.modal = { kind: "box", title: b.name, box: b, rows };
    }
    async openItems(id, name, kind) {
        if (!id || !kind) { return; }
        const rows = await this.orm.call("pharma.dashboard", "get_partner_items", [id, kind]);
        this.state.modal = { kind: "items", title: name, rows, partnerId: id };
    }
    openPartnerForm(id) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "res.partner", res_id: id, views: [[false, "form"]] });
    }
    closeModal() { this.state.modal = null; }
}

registry.category("actions").add("pharma_dashboard.main", PharmaDashboard);
