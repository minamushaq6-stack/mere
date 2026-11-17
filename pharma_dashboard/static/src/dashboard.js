import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, onWillUpdateProps, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const THEME_KEY = "pharma_dashboard.theme";
const PALETTE = ["#22d3ee", "#2dd4bf", "#3b82f6", "#818cf8", "#a78bfa", "#fb923c", "#f472b6", "#94a3b8"];
const AGING_TONES = ["green", "teal", "orange", "orange", "red"];
const reduceMotion = () => !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

function loadTheme() {
    try {
        const saved = window.localStorage.getItem(THEME_KEY);
        if (saved === "dark" || saved === "light") { return saved; }
    } catch (e) { /* التخزين غير متاح */ }
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// عدّاد متحرك للأرقام الكبيرة
class CountUp extends Component {
    static template = "pharma_dashboard.CountUp";
    static props = { value: { type: Number, optional: true }, dec: { type: Number, optional: true } };

    setup() {
        this.s = useState({ v: 0 });
        onMounted(() => this.run(this.props.value || 0, 0));
        onWillUpdateProps((np) => {
            if ((np.value || 0) !== (this.props.value || 0)) { this.run(np.value || 0, this.s.v); }
        });
        onWillUnmount(() => cancelAnimationFrame(this.raf));
    }
    run(to, from) {
        cancelAnimationFrame(this.raf);
        if (reduceMotion() || from === to) { this.s.v = to; return; }
        const t0 = performance.now(), dur = 900;
        const step = (t) => {
            const k = Math.min(1, (t - t0) / dur);
            this.s.v = from + (to - from) * (1 - Math.pow(1 - k, 3));
            if (k < 1) { this.raf = requestAnimationFrame(step); }
        };
        this.raf = requestAnimationFrame(step);
    }
    get text() {
        const dec = this.props.dec || 0;
        return (this.s.v || 0).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
    }
}

export class PharmaDashboard extends Component {
    static template = "pharma_dashboard.Main";
    static components = { CountUp };

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
        this.state = useState({
            loading: true, tab: "overview", period: "month", from: "", to: "", data: null, modal: null,
            theme: loadTheme(), trendMode: "monthly", hover: null,
        });
        onWillStart(() => this.setPeriod("month"));
    }

    // ---------- الفترة والتحميل ----------
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
        if (!this.state.data.daily.length) { this.state.trendMode = "monthly"; }
        this.state.hover = null;
        this.state.loading = false;
    }

    // ---------- المظهر ----------
    setTheme(theme) {
        this.state.theme = theme;
        try { window.localStorage.setItem(THEME_KEY, theme); } catch (e) { /* ignore */ }
    }

    // ---------- تنسيق الأرقام ----------
    fmt(n) { return (n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 }); }
    fmtC(n, code) {
        return (n || 0).toLocaleString("en-US", { maximumFractionDigits: code === "USD" ? 2 : 0 });
    }
    compact(n) {
        const a = Math.abs(n || 0);
        const f = (v, s) => v.toFixed(1).replace(/\.0$/, "") + s;
        if (a >= 1e9) { return f(n / 1e9, "B"); }
        if (a >= 1e6) { return f(n / 1e6, "M"); }
        if (a >= 1e3) { return f(n / 1e3, "K"); }
        return String(Math.round(n || 0));
    }
    max(items, key) { return Math.max(1, ...(items || []).map((i) => Math.abs(i[key] || 0))); }
    pct(v, mx) { return v ? Math.max(3, Math.round((Math.abs(v) / mx) * 100)) : 0; }
    color(i) { return PALETTE[Math.min(i, PALETTE.length - 1)]; }
    initials(name) { return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join(""); }

    get cur() { return this.state.data ? this.state.data.currency : ""; }

    // ---------- مؤشرات الصفحة الرئيسية ----------
    get kpis() {
        const d = this.state.data;
        if (!d) { return []; }
        return [
            { label: "ديون العملاء (لنا)", value: d.receivable.total, sub: `متأخر: ${this.fmt(d.receivable.overdue)}`, icon: "fa-arrow-circle-down", tone: "green", tab: "debts" },
            { label: "ديون الموردين (علينا)", value: d.payable.total, sub: `متأخر: ${this.fmt(d.payable.overdue)}`, icon: "fa-arrow-circle-up", tone: "red", tab: "debts" },
            { label: "قيمة المخزون", value: d.inventory.total, sub: `${this.fmt(d.inventory.items)} صنف`, icon: "fa-cubes", tone: "blue", tab: "stock" },
            { label: "المشتريات", value: d.purch_total, icon: "fa-truck", tone: "orange", tab: "sales" },
            { label: "رواجع المبيعات", value: d.returns.sales.total, sub: `${d.returns.rate.toFixed(1)}% من المبيعات`, icon: "fa-undo", tone: "red", tab: "returns" },
            { label: "مجمل الربح", value: d.pl.gross, icon: "fa-bar-chart", tone: "teal", tab: "partners" },
            { label: "صافي الربح", value: d.pl.net, icon: "fa-trophy", tone: d.pl.net >= 0 ? "green" : "red", tab: "partners" },
        ];
    }

    // ---------- تحليل المبيعات ----------
    niceMax(v) {
        if (v <= 0) { return 1; }
        const p = Math.pow(10, Math.floor(Math.log10(v)));
        const n = v / p;
        return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
    }
    get chart() {
        const d = this.state.data;
        if (!d) { return null; }
        const daily = this.state.trendMode === "daily" && d.daily.length > 0;
        const src = daily ? d.daily : d.trend;
        const mx = this.niceMax(Math.max(0, ...src.flatMap((t) => [t.sales, t.purchases])));
        const h = (v) => (v > 0 ? Math.max(2, (v / mx) * 100) : 0);
        const fm = this.state.from.slice(0, 7), tm = this.state.to.slice(0, 7);
        return {
            daily,
            ticks: [1, 0.75, 0.5, 0.25, 0].map((f) => mx * f),
            cols: src.map((t) => ({
                key: t.m, sales: t.sales, purchases: t.purchases, sh: h(t.sales), ph: h(t.purchases),
                label: daily ? t.m.slice(8) : `${t.m.slice(5)}/${t.m.slice(2, 4)}`,
                full: daily ? t.m : t.m,
                on: daily ? true : (t.m >= fm && t.m <= tm),
            })),
        };
    }
    get salesStats() {
        const d = this.state.data;
        const delta = d.sales_prev ? ((d.sales_total - d.sales_prev) / d.sales_prev) * 100 : null;
        return {
            avg: d.sales_count ? d.sales_total / d.sales_count : 0,
            delta,
            up: delta !== null && delta >= 0,
        };
    }
    smoothPath(vals, w, h, pad, lo, hi) {
        const n = vals.length;
        if (!n) { return { line: "", area: "" }; }
        const span = hi - lo || 1;
        // RTL: الأقدم يمين والأحدث يسار، مثل أعمدة الرسم
        const pts = vals.map((v, i) => [n > 1 ? w - (i / (n - 1)) * w : w / 2, h - pad - ((v - lo) / span) * (h - pad * 2)]);
        let line = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
        for (let i = 0; i < n - 1; i++) {
            const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
            const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
            const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
            line += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
        }
        const last = pts[n - 1], first = pts[0];
        return { line, area: `${line} L${last[0].toFixed(1)},${h} L${first[0].toFixed(1)},${h} Z` };
    }
    smooth(vals, w, h, pad = 6) {
        return this.smoothPath(vals, w, h, pad, 0, Math.max(1, ...vals));
    }
    // رسم خطي (سلسلة أو أكثر بمقياس مشترك)
    lineChart(series, labels, base0 = true) {
        const all = series.flat();
        let lo = Math.min(...all), hi = Math.max(...all);
        if (base0) { lo = Math.min(0, lo); }
        else {
            const pv = (hi - lo) * 0.15 || Math.abs(hi) * 0.1 || 1;
            lo -= pv; hi += pv;
        }
        if (hi === lo) { hi = lo + 1; }
        return { lines: series.map((v) => this.smoothPath(v, 300, 100, 8, lo, hi)), labels, hi: this.compact(hi), lo: this.compact(lo) };
    }
    // أعمدة (سلسلة أو سلسلتان). العناصر: { label, <key>: value }
    colChart(items, keys = ["value"], tones = null) {
        const mx = this.niceMax(Math.max(0, ...items.flatMap((it) => keys.map((k) => it[k] || 0))));
        const h = (v) => (v > 0 ? Math.max(3, (v / mx) * 100) : 0);
        return {
            two: keys.length > 1,
            ticks: [1, 0.75, 0.5, 0.25, 0].map((f) => mx * f),
            cols: items.map((it, i) => ({
                label: it.label,
                a: it[keys[0]] || 0, ah: h(it[keys[0]]),
                b: keys[1] ? it[keys[1]] || 0 : 0, bh: keys[1] ? h(it[keys[1]]) : 0,
                tone: tones ? tones[i] || "" : "",
            })),
        };
    }
    // ---------- الدوائر البيانية ----------
    layoutParts(rows, total) {
        let acc = 0;
        rows.forEach((r) => {
            r.share = total ? (r.value / total) * 100 : 0;
            r.dash = Math.max(r.share - (rows.length > 1 ? 0.8 : 0), 0.2);
            r.off = -acc;
            acc += r.share;
        });
        return rows;
    }
    // items مرتبة تنازلياً. grand: إجمالي كلي اختياري (الباقي يصير "أخرى")
    donutParts(items, key = "value", max = 5, grand = null) {
        const list = (items || []).filter((i) => (i[key] || 0) > 0);
        const sum = list.reduce((t, i) => t + i[key], 0);
        const total = grand && grand > sum ? grand : sum;
        if (!total) { return { parts: [], total: 0 }; }
        const rows = list.slice(0, max).map((i, idx) => ({ name: i.name, value: i[key], color: PALETTE[idx] }));
        const rest = total - rows.reduce((t, r) => t + r.value, 0);
        if (rest > total * 0.0005) { rows.push({ name: "أخرى", value: rest, color: PALETTE[7] }); }
        return { parts: this.layoutParts(rows, total), total };
    }
    topOf(c) {
        const p = c.parts[0];
        return p ? { name: p.name, value: p.value, sub: `${p.share.toFixed(1)}%` } : null;
    }
    get spark() {
        return this.smooth(this.state.data.trend.map((t) => t.sales), 300, 80);
    }

    // ---------- بطاقات الدوائر (نظرة عامة) ----------
    get donutCards() {
        const d = this.state.data;
        const cards = [];
        const g = this.donutParts(d.governorates, "value", 5);
        cards.push({
            kind: "gov", title: "المبيعات حسب المحافظة", topTitle: "أعلى محافظة مبيعاً", icon: "fa-map-marker",
            ...g, clickable: g.parts.length > 0, hint: "لا توجد مبيعات في هذه الفترة",
            top: d.top_gov ? { name: d.top_gov.name, value: d.top_gov.value, sub: `${d.top_gov.share.toFixed(1)}%` } : this.topOf(g),
        });
        for (const rk of ["commercial", "scientific"]) {
            const r = d.reps[rk];
            const p = this.donutParts(r.list, "value", 5);
            cards.push({
                kind: rk, icon: rk === "scientific" ? "fa-user-md" : "fa-briefcase",
                title: rk === "scientific" ? "المناديب العلميون" : "المناديب التجاريون",
                topTitle: rk === "scientific" ? "أعلى مندوب علمي مبيعاً" : "أعلى مندوب تجاري مبيعاً",
                ...p, clickable: p.parts.length > 0,
                top: r.top ? { name: r.top.name, value: r.top.value, sub: `${r.top.share.toFixed(1)}%` } : this.topOf(p),
                hint: !r.configured ? "لم يُحدَّد مناديب بعد. أضفهم من: لوحة المعلومات ← المناديب" : "لا توجد مبيعات لهذه المجموعة في الفترة",
            });
        }
        return cards;
    }
    get salesDonuts() {
        const d = this.state.data;
        const mk = (kind, title, icon, topTitle, items, key) => {
            const p = this.donutParts(items, key, 5);
            return { kind, title, icon, topTitle, ...p, clickable: false, top: this.topOf(p), hint: "لا توجد بيانات في هذه الفترة" };
        };
        const g = this.donutCards[0];
        return [
            g,
            mk("cust", "حصة أفضل العملاء", "fa-users", "أفضل عميل", d.top_customers, "value"),
            mk("prod", "المنتجات حسب المبلغ", "fa-medkit", "أعلى منتج بالمبلغ", d.top_by_amount, "amount"),
            mk("sup", "المبيعات حسب المورد", "fa-truck", "أعلى مورد", d.sold_by_supplier, "value"),
        ];
    }
    openDonut(kind) {
        if (kind === "gov") { this.openGovs(); }
        else if (kind === "scientific" || kind === "commercial") { this.openReps(kind); }
    }
    get salesKpis() {
        const d = this.state.data, ss = this.salesStats;
        return [
            { label: "مبيعات الفترة", value: d.sales_total, icon: "fa-line-chart", tone: "teal", sub: ss.delta === null ? "" : `${ss.up ? "▲" : "▼"} ${Math.abs(ss.delta).toFixed(1)}% عن الفترة السابقة` },
            { label: "عدد الفواتير", value: d.sales_count, icon: "fa-file-text-o", tone: "blue", sub: "" },
            { label: "متوسط الفاتورة", value: ss.avg, icon: "fa-calculator", tone: "purple", sub: "" },
            { label: "المشتريات", value: d.purch_total, icon: "fa-truck", tone: "orange", sub: "" },
        ];
    }
    get salesTrend() {
        const t = this.state.data.trend;
        return this.lineChart([t.map((x) => x.sales), t.map((x) => x.purchases)], t.map((x) => `${x.m.slice(5)}/${x.m.slice(2, 4)}`));
    }

    // ---------- النفقات (مربع + تفاصيل) ----------
    get expTile() {
        const e = this.state.data.expenses;
        const p = this.donutParts(e.items, "value", 4);
        return { total: e.total, count: e.items.length, parts: p.parts, top: e.items[0] || null };
    }

    // ---------- المخزون (نظرة عامة) ----------
    get invOverview() {
        const d = this.state.data, inv = d.inventory;
        const comp = this.donutParts(inv.top, "value", 5, inv.total);
        const best = d.top_products[0] || null;
        const bestAmt = d.top_by_amount[0] || null;
        return { comp, best, bestAmt: bestAmt && best && bestAmt.id !== best.id ? bestAmt : null, list: d.top_products.slice(0, 4) };
    }

    // ---------- الصناديق ----------
    walletCharts(w) {
        const boxes = w.boxes.filter((b) => b.balance > 0).map((b) => ({ name: b.name, value: b.balance }));
        const lbl = (s) => `${s.m.slice(5)}/${s.m.slice(2, 4)}`;
        const don = this.donutParts(boxes, "value", 5);
        return {
            donut: don,
            col: this.colChart(w.series.map((s) => ({ label: lbl(s), in: s.in, out: s.out })), ["in", "out"]),
            line: this.lineChart([w.series.map((s) => s.bal)], w.series.map(lbl), false),
            hasFlow: w.series.some((s) => s.in || s.out),
        };
    }
    ioShare(b) {
        const t = (b.in || 0) + (b.out || 0);
        return t ? (b.in / t) * 100 : 0;
    }

    // ---------- الذمم ----------
    get debtView() {
        const d = this.state.data;
        const mk = (src) => ({
            cc: this.colChart(src.aging.map((a) => ({ label: a.name, value: a.value })), ["value"], AGING_TONES),
            over: src.total > 0 ? Math.max(0, Math.min(100, (src.overdue / src.total) * 100)) : 0,
        });
        const rec = d.receivable.total, pay = d.payable.total, mx = Math.max(1, rec, pay);
        return {
            rec: mk(d.receivable), pay: mk(d.payable), net: rec - pay,
            recW: this.pct(Math.max(0, rec), mx), payW: this.pct(Math.max(0, pay), mx),
            kpis: [
                { label: "ديون العملاء (لنا)", value: rec, sub: `متأخر: ${this.fmt(d.receivable.overdue)}`, icon: "fa-arrow-circle-down", tone: "green" },
                { label: "ديون الموردين (علينا)", value: pay, sub: `متأخر: ${this.fmt(d.payable.overdue)}`, icon: "fa-arrow-circle-up", tone: "red" },
                { label: "الصافي (لنا − علينا)", value: rec - pay, sub: rec - pay >= 0 ? "الموقف لصالحنا" : "الموقف علينا", icon: "fa-balance-scale", tone: rec - pay >= 0 ? "teal" : "orange" },
            ],
        };
    }

    // ---------- المخزون (تبويب) ----------
    get stockCards() {
        const inv = this.state.data.inventory;
        const cards = [];
        const comp = this.donutParts(inv.top, "value", 5, inv.total);
        cards.push({ kind: "comp", title: "توزيع قيمة المخزون", icon: "fa-pie-chart", topTitle: "أعلى صنف قيمة", ...comp, clickable: false, top: this.topOf(comp), hint: "لا يوجد مخزون" });
        if (inv.total > 0) {
            const dead = Math.min(inv.dead_value, inv.total);
            const rows = this.layoutParts([
                { name: "نشط (مباع بالفترة)", value: inv.total - dead, color: "#34d399" },
                { name: "راكد (غير مباع)", value: dead, color: "#fb923c" },
            ].filter((r) => r.value > 0), inv.total);
            const pc = (dead / inv.total) * 100;
            cards.push({ kind: "dead", title: "نشاط المخزون", icon: "fa-refresh", topTitle: "نسبة الراكد", parts: rows, total: inv.total,
                cmain: `${pc.toFixed(0)}%`, csub: "راكد", clickable: false, top: { name: `${pc.toFixed(1)}%`, value: dead, sub: "من قيمة المخزون" }, hint: "" });
            if (inv.has_expiry) {
                const bad = Math.min(inv.expired_val, inv.total), near = Math.min(inv.near_val, inv.total - bad);
                const rows2 = this.layoutParts([
                    { name: "منتهي الصلاحية", value: bad, color: "#f87171" },
                    { name: "ينتهي خلال 90 يوم", value: near, color: "#fb923c" },
                    { name: "سليم", value: Math.max(0, inv.total - bad - near), color: "#34d399" },
                ].filter((r) => r.value > 0), inv.total);
                const rp = ((bad + near) / inv.total) * 100;
                cards.push({ kind: "exp", title: "حالة الصلاحية", icon: "fa-hourglass-half", topTitle: "معرّض للانتهاء", parts: rows2, total: inv.total,
                    cmain: `${rp.toFixed(0)}%`, csub: "تحت الخطر", clickable: false, top: { name: `${rp.toFixed(1)}%`, value: bad + near, sub: "منتهي + قريب الانتهاء" }, hint: "" });
            }
        } else {
            cards.push({ kind: "dead", title: "نشاط المخزون", icon: "fa-refresh", topTitle: "", parts: [], total: 0, clickable: false, top: null, hint: "لا يوجد مخزون" });
        }
        return cards;
    }

    // ---------- الأرباح والشركاء ----------
    get plView() {
        const p = this.state.data.pl;
        const items = [
            { label: "الإيرادات", value: Math.abs(p.income) }, { label: "التكلفة", value: Math.abs(p.cogs) },
            { label: "مجمل الربح", value: Math.abs(p.gross) }, { label: "المصاريف", value: Math.abs(p.opex) },
            { label: "صافي الربح", value: Math.abs(p.net) },
        ];
        return this.colChart(items, ["value"], ["green", "orange", "teal", "red", p.net >= 0 ? "green" : "red"]);
    }
    get sharesCard() {
        const sh = this.state.data.shares;
        const p = this.donutParts(sh.map((s) => ({ name: s.name, value: s.percent })), "value", 5);
        return { kind: "shares", title: "توزيع حصص الشركاء", icon: "fa-users", topTitle: "أكبر حصة", ...p, cmain: `${this.fmt(p.total)}%`, csub: "مجموع النسب",
                 clickable: false, top: this.topOf(p), hint: "أضف الشركاء ونسبهم من القائمة" };
    }

    // ---------- النوافذ المنبثقة ----------
    async openBox(b) {
        const rows = await this.orm.call("pharma.dashboard", "get_box_moves", [b.id, this.state.from, this.state.to]);
        this.state.modal = { kind: "box", title: b.name, box: b, rows };
    }
    openReps(kind) {
        const r = this.state.data.reps[kind];
        if (!r.configured || !r.list.length) { return; }
        this.state.modal = {
            kind: "ranking", title: kind === "scientific" ? "ترتيب المناديب العلميين" : "ترتيب المناديب التجاريين",
            unit: "rep", rows: r.list, open: 0, max: this.max(r.list, "value"),
        };
    }
    openGovs() {
        const g = this.state.data.governorates;
        if (!g.length) { return; }
        this.state.modal = { kind: "ranking", title: "ترتيب المحافظات حسب المبيعات", unit: "gov", rows: g, open: 0, max: this.max(g, "value") };
    }
    toggleOpen(i) { this.state.modal.open = this.state.modal.open === i ? -1 : i; }
    openExpenses() {
        const e = this.state.data.expenses;
        if (!e.items.length) { return; }
        this.state.modal = { kind: "expenses", title: "فئات النفقات", donut: this.donutParts(e.items, "value", 7) };
    }
    async openExpense(it, back = null) {
        const rows = await this.orm.call("pharma.dashboard", "get_expense_moves", [it.id, this.state.from, this.state.to]);
        this.state.modal = { kind: "expense", title: it.name, item: it, rows, back };
    }
    goBack() {
        const b = this.state.modal && this.state.modal.back;
        if (b) { this.state.modal = b; }
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
