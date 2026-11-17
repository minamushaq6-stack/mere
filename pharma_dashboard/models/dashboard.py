from collections import defaultdict
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


def _n(v):
    return f"{(v or 0):,.0f}"


class PharmaDashboard(models.AbstractModel):
    _name = "pharma.dashboard"
    _description = "Pharma Dashboard Data"

    @api.model
    def get_data(self, date_from, date_to):
        if not self.env.user.has_group("pharma_dashboard.group_dashboard_viewer"):
            raise AccessError(_("ليس لديك صلاحية عرض لوحة المعلومات."))
        E = self.sudo().env
        cids = E.companies.ids
        cid = ("company_id", "in", cids)
        today = fields.Date.context_today(self)
        dt_from, dt_to = f"{date_from} 00:00:00", f"{date_to} 23:59:59"
        unknown = _("غير محدد")
        d_from, d_to = fields.Date.to_date(date_from), fields.Date.to_date(date_to)

        def months_ending(ref, n):
            y, m, out = ref.year, ref.month, []
            for _i in range(n):
                out.append(f"{y}-{m:02d}")
                m -= 1
                if m == 0:
                    m, y = 12, y - 1
            return out[::-1]
        months = months_ending(today, 12)
        cash_months = months_ending(d_to, 6)
        cash_start = f"{cash_months[0]}-01"

        AML = E["account.move.line"]
        posted = [("parent_state", "=", "posted"), cid]

        # ---------- الصناديق والبنوك (مجمّعة حسب العملة: دولار / دينار) ----------
        # الرصيد = الرصيد الكلي لحساب الصندوق في دفتر الأستاذ العام (كل القيود المرحّلة على الحساب
        # من أي يومية وأي تاريخ، شاملاً الأرصدة الافتتاحية). الفترة تخص الداخل/الخارج فقط.
        Currency = E["res.currency"].with_context(active_test=False)
        ccy_names = {"USD": "الدولار الأمريكي", "IQD": "الدينار العراقي"}
        wallets = {}

        def wallet(cur):
            if cur.name not in wallets:
                wallets[cur.name] = {
                    "code": cur.name, "symbol": cur.symbol or cur.name,
                    "name": ccy_names.get(cur.name) or cur.currency_unit_label or cur.name,
                    "total": 0.0, "in": 0.0, "out": 0.0, "boxes": [],
                    "_pre": 0.0, "_ser": {},
                }
            return wallets[cur.name]

        # الدولار والدينار يظهران دائماً حتى لو ما بيهم صناديق
        for cur in Currency.search([("name", "in", ("USD", "IQD"))]):
            wallet(cur)

        def _sum(dom, fld):
            return AML._read_group(dom, [], [f"{fld}:sum"])[0][0] or 0

        def _flows(dom, foreign):
            if foreign:
                i = _sum(dom + [("amount_currency", ">", 0)], "amount_currency")
                o = -_sum(dom + [("amount_currency", "<", 0)], "amount_currency")
            else:
                i, o = AML._read_group(dom, [], ["debit:sum", "credit:sum"])[0]
                i, o = i or 0, o or 0
            return i, o

        journals = E["account.journal"].search([("type", "in", ("cash", "bank")), cid])
        pay_map = defaultdict(float)
        for j, pt, ptn, amt in E["account.payment"]._read_group(
                [("journal_id", "in", journals.ids), ("move_id.state", "=", "posted"),
                 ("date", ">=", date_from), ("date", "<=", date_to)],
                ["journal_id", "payment_type", "partner_type"], ["amount:sum"]):
            pay_map[(j.id, pt, ptn)] += amt
        seen_acc = set()
        for j in journals:
            acc = j.default_account_id
            if not acc or acc.id in seen_acc:   # حساب مشترك بين يوميتين: لا نعدّه مرتين
                continue
            seen_acc.add(acc.id)
            cur = j.currency_id or j.company_id.currency_id
            foreign = cur != j.company_id.currency_id
            fld = "amount_currency" if foreign else "balance"
            ldom = posted + [("account_id", "=", acc.id)]
            if foreign:
                ldom.append(("currency_id", "=", cur.id))
            bal = _sum(ldom, fld)  # الرصيد الكلي: كل القيود المرحّلة بما فيها الرصيد الافتتاحي
            opening = _sum(ldom + [("date", "<", date_from)], fld)
            inn, out = _flows(ldom + [("date", ">=", date_from), ("date", "<=", date_to)], foreign)
            box = {
                "id": j.id, "name": j.name, "type": j.type, "balance": bal, "opening": opening,
                "in": inn, "out": out, "currency": cur.name, "account": acc.display_name,
                "cust_refund": pay_map[(j.id, "outbound", "customer")],
                "supp_refund": pay_map[(j.id, "inbound", "supplier")],
            }
            w = wallet(cur)
            w["boxes"].append(box)
            w["total"] += bal
            w["in"] += inn
            w["out"] += out

            # حركة آخر 6 أشهر (داخل / خارج) + الرصيد التراكمي للرسوم البيانية
            w["_pre"] += _sum(ldom + [("date", "<", cash_start)], fld)
            mdom = ldom + [("date", ">=", cash_start), ("date", "<=", date_to)]
            ser = w["_ser"]
            if foreign:
                for d, v in AML._read_group(mdom + [("amount_currency", ">", 0)], ["date:month"], ["amount_currency:sum"]):
                    if d:
                        ser.setdefault(d.strftime("%Y-%m"), [0.0, 0.0])[0] += v
                for d, v in AML._read_group(mdom + [("amount_currency", "<", 0)], ["date:month"], ["amount_currency:sum"]):
                    if d:
                        ser.setdefault(d.strftime("%Y-%m"), [0.0, 0.0])[1] += -v
            else:
                for d, dr, cr in AML._read_group(mdom, ["date:month"], ["debit:sum", "credit:sum"]):
                    if d:
                        row = ser.setdefault(d.strftime("%Y-%m"), [0.0, 0.0])
                        row[0] += dr or 0
                        row[1] += cr or 0
        _order = {"USD": 0, "IQD": 1}
        wallet_list = sorted(wallets.values(), key=lambda w: (_order.get(w["code"], 9), w["code"]))
        for w in wallet_list:
            w["boxes"].sort(key=lambda b: -b["balance"])
            run, series = w.pop("_pre"), []
            raw = w.pop("_ser")
            for mth in cash_months:
                i, o = raw.get(mth, (0.0, 0.0))
                run += i - o
                series.append({"m": mth, "in": i, "out": o, "bal": run})
            w["series"] = series

        # ---------- المرتجعات (الرواجع) ----------
        # من الإشعارات الدائنة المرحّلة، بعملة الشركة (balance) وليس بعملة المستند.
        def returns(mtype, sign):
            dom = [("move_id.move_type", "=", mtype), ("parent_state", "=", "posted"),
                   ("display_type", "=", "product"), cid, ("date", ">=", date_from), ("date", "<=", date_to)]
            direction = "desc" if sign > 0 else "asc"
            tot, cnt = AML._read_group(dom, [], ["balance:sum", "__count"])[0]
            prod = AML._read_group(dom, ["product_id"], ["quantity:sum", "balance:sum"],
                                   order="balance:sum " + direction, limit=10)
            part = AML._read_group(dom, ["partner_id"], ["balance:sum", "__count"],
                                   order="balance:sum " + direction, limit=10)
            return {
                "total": sign * (tot or 0), "lines": cnt,
                "products": [{"name": p.display_name, "value": sign * a, "qty": q, "sub": f"الكمية: {_n(q)}"}
                             for p, q, a in prod if p],
                "partners": [{"id": p.id, "name": p.display_name, "value": sign * a, "sub": f"{c} بند"}
                             for p, a, c in part if p],
            }
        ret_sales, ret_purch = returns("out_refund", 1), returns("in_refund", -1)

        # ---------- الذمم (عملاء / موردين) ----------
        # الأرصدة = المبالغ المتبقية غير المسوّاة على حسابات المدينين/الدائنين (نفس تقرير أعمار الذمم).
        # الإشارة محفوظة: رصيد عميل دائن (دفعة مقدّمة) لا يُعدّ ديناً، وتاريخ الاستحقاق الفارغ يُستبدل بتاريخ القيد.
        def due(op, d):
            return ["|", "&", ("date_maturity", "!=", False), ("date_maturity", op, d),
                    "&", ("date_maturity", "=", False), ("date", op, d)]

        def term_accounts(mtypes, atype):
            """الحسابات التي تستخدمها فواتير العملاء/الموردين فعلياً (مثل Accounts Receivable 121000)،
            حتى لا تدخل حسابات أخرى من نفس النوع (تخليص كمركي، مقبوض مقدماً...)."""
            rows = AML._read_group(
                posted + [("display_type", "=", "payment_term"), ("move_id.move_type", "in", mtypes)],
                ["account_id"], ["__count"])
            return E["account.account"].browse([a.id for a, _c in rows if a and a.account_type == atype])

        def open_items(atype, sign, mtypes):
            accs = term_accounts(mtypes, atype)
            acc_dom = [("account_id", "in", accs.ids)] if accs else [("account_id.account_type", "=", atype)]
            dom = posted + acc_dom + [("reconciled", "=", False)]
            rsum = lambda extra: sign * (AML._read_group(dom + extra, [], ["amount_residual:sum"])[0][0] or 0)
            top = AML._read_group(
                dom, ["partner_id"], ["amount_residual:sum"],
                order="amount_residual:sum " + ("desc" if sign > 0 else "asc"), limit=40)
            d30, d60, d90 = (today - timedelta(days=n) for n in (30, 60, 90))
            aging = [
                {"name": "غير مستحق", "value": rsum(due(">=", today))},
                {"name": "1-30 يوم", "value": rsum(due("<", today) + due(">=", d30))},
                {"name": "31-60 يوم", "value": rsum(due("<", d30) + due(">=", d60))},
                {"name": "61-90 يوم", "value": rsum(due("<", d60) + due(">=", d90))},
                {"name": "أكثر من 90", "value": rsum(due("<", d90))},
            ]
            return {
                "total": rsum([]), "overdue": rsum(due("<", today)),
                "top": [{"id": p.id, "name": p.display_name, "value": sign * v}
                        for p, v in top if p and sign * v > 0.0001][:10],
                "aging": aging, "accounts": accs.mapped("display_name"),
            }
        receivable = open_items("asset_receivable", 1, ("out_invoice", "out_refund"))
        payable = open_items("liability_payable", -1, ("in_invoice", "in_refund"))

        # ---------- الأرباح ----------
        def bal(types):
            return AML._read_group(
                posted + [("date", ">=", date_from), ("date", "<=", date_to),
                          ("account_id.account_type", "in", types)], [], ["balance:sum"])[0][0] or 0
        income = -bal(["income", "income_other"])
        cogs = bal(["expense_direct_cost"])
        opex = bal(["expense", "expense_depreciation"])
        gross = income - cogs
        net = gross - opex

        # ---------- المبيعات والمشتريات ----------
        # من الفواتير المرحّلة بالدفتر (بدون الضريبة) بعد خصم الإشعارات الدائنة، بعملة الشركة.
        def inv_dom(types, a_, b_):
            return posted + [("move_id.move_type", "in", types), ("display_type", "=", "product"),
                             ("date", ">=", a_), ("date", "<=", b_)]
        SALE_T, PURCH_T = ("out_invoice", "out_refund"), ("in_invoice", "in_refund")
        sale_dom = inv_dom(SALE_T, date_from, date_to)
        purch_dom = inv_dom(PURCH_T, date_from, date_to)
        sales_total = -(AML._read_group(sale_dom, [], ["balance:sum"])[0][0] or 0)
        purch_total = AML._read_group(purch_dom, [], ["balance:sum"])[0][0] or 0
        sales_count = E["account.move"].search_count([
            ("move_type", "=", "out_invoice"), ("state", "=", "posted"), cid,
            ("date", ">=", date_from), ("date", "<=", date_to)])

        # المنتجات: الكمية والمبلغ بعد خصم المرتجعات
        pagg = defaultdict(lambda: [0.0, 0.0])
        for mt, sg in (("out_invoice", 1), ("out_refund", -1)):
            for p, q, bl in AML._read_group(sale_dom + [("move_id.move_type", "=", mt)],
                                            ["product_id"], ["quantity:sum", "balance:sum"]):
                if p:
                    pagg[p][0] += sg * q
                    pagg[p][1] += -bl
        prods = [{"id": p.id, "name": p.display_name, "qty": q, "amount": a_, "sub": f"المبلغ: {_n(a_)}"}
                 for p, (q, a_) in pagg.items() if q > 0]
        prods.sort(key=lambda x: -x["qty"])
        sold_ids = {p["id"] for p in prods}
        top_products = prods[:10]
        bottom_products = sorted(prods, key=lambda x: x["qty"])[:10]
        top_by_amount = sorted(prods, key=lambda x: -x["amount"])[:10]

        # أكثر مورد نبيع من منتجاته
        sup_sales = defaultdict(float)
        amt_by_id = {x["id"]: x["amount"] for x in prods}
        for p in E["product.product"].browse(list(sold_ids)):
            sup = p.product_tmpl_id.seller_ids[:1].partner_id
            sup_sales[sup.display_name if sup else unknown] += amt_by_id.get(p.id, 0)
        sold_by_supplier = [{"name": k, "value": v} for k, v in sorted(sup_sales.items(), key=lambda x: -x[1])[:10]]

        # العملاء / المحافظات / المناديب: صافي كل فاتورة (الفاتورة - إشعاراتها) حسب العميل والمندوب
        cust = defaultdict(lambda: [0.0, 0])
        rep_agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
        for m, bl in AML._read_group(sale_dom, ["move_id"], ["balance:sum"]):
            if not m:
                continue
            val, n_inv = -bl, (1 if m.move_type == "out_invoice" else 0)
            pt = m.commercial_partner_id
            cust[pt][0] += val
            cust[pt][1] += n_inv
            ra = rep_agg[m.invoice_user_id.id][pt]
            ra[0] += val
            ra[1] += n_inv
        top_customers = [{"id": p.id, "name": p.display_name, "value": v[0]}
                         for p, v in sorted(cust.items(), key=lambda x: -x[1][0])[:10] if p and v[0] > 0]
        gov = defaultdict(lambda: {"value": 0.0, "orders": 0, "customers": []})
        for p, (v, c) in cust.items():
            if not p:
                continue
            g = gov[p.state_id.name or unknown]
            g["value"] += v
            g["orders"] += c
            g["customers"].append({"id": p.id, "name": p.display_name, "value": v, "count": c})
        gov_total = sum(g["value"] for g in gov.values())
        governorates = []
        for k, g in sorted(gov.items(), key=lambda x: -x[1]["value"]):
            g["customers"].sort(key=lambda x: -x["value"])
            governorates.append({
                "name": k, "value": g["value"], "orders": g["orders"], "known": k != unknown,
                "n_customers": len(g["customers"]), "sub": f"{len(g['customers'])} عميل",
                "share": (g["value"] / gov_total * 100) if gov_total else 0,
                "customers": g["customers"][:5],
            })
        top_gov = next((g for g in governorates if g["known"] and g["value"] > 0), None)

        # ---------- أعلى مندوب (علمي / تجاري) = مسؤول المبيعات في الفاتورة ----------
        rep_cfg = E["pharma.dashboard.rep"].search([cid])
        reps = {}
        for rtype in ("scientific", "commercial"):
            users = rep_cfg.filtered(lambda r, t=rtype: r.rep_type == t).mapped("user_id")
            items = []
            for u in users:
                custs = [{"name": pt.display_name, "value": v, "count": c}
                         for pt, (v, c) in rep_agg.get(u.id, {}).items() if pt]
                custs.sort(key=lambda x: -x["value"])
                val = sum(x["value"] for x in custs)
                cnt = sum(x["count"] for x in custs)
                items.append({"id": u.id, "name": u.display_name, "value": val, "count": cnt,
                              "avg": (val / cnt) if cnt else 0, "customers": custs[:5]})
            items.sort(key=lambda x: -x["value"])
            tot = sum(i["value"] for i in items)
            for i in items:
                i["share"] = (i["value"] / tot * 100) if tot else 0
            reps[rtype] = {"configured": bool(users), "total": tot, "list": items,
                           "top": items[0] if items and items[0]["value"] > 0 else None}

        # ---------- أكثر الموردين شراءً منهم (فواتير مشتريات صافية) ----------
        prow = AML._read_group(purch_dom, ["partner_id"], ["balance:sum"], order="balance:sum desc", limit=10)
        top_suppliers = [{"id": p.id, "name": p.display_name, "value": v} for p, v in prow if p and v > 0]

        # ---------- اتجاه 12 شهر ----------
        def monthly(types, sign):
            out = {}
            for d, v in AML._read_group(inv_dom(types, f"{months[0]}-01", today), ["date:month"], ["balance:sum"]):
                if d:
                    out[d.strftime("%Y-%m")] = sign * v
            return out
        sm, pm = monthly(SALE_T, -1), monthly(PURCH_T, 1)
        trend = [{"m": k, "sales": sm.get(k, 0), "purchases": pm.get(k, 0)} for k in months]

        # ---------- النفقات: من موديل النفقات (hr.expense) فقط، حسب فئة النفقة ----------
        exp_items, exp_total = [], 0.0
        if "hr.expense" in E:
            X = E["hr.expense"]
            amt_f = "total_amount" if "total_amount" in X._fields else "total_amount_currency"
            xdom = [("state", "not in", ("draft", "refused")), cid,
                    ("date", ">=", date_from), ("date", "<=", date_to)]
            exp_items = [{"id": pr.id, "name": pr.display_name, "value": v, "count": c, "sub": f"{c} نفقة"}
                         for pr, v, c in X._read_group(xdom, ["product_id"], [f"{amt_f}:sum", "__count"])
                         if pr and v > 0.0001]
            exp_items.sort(key=lambda x: -x["value"])
            exp_total = sum(i["value"] for i in exp_items)
        for i in exp_items:
            i["share"] = (i["value"] / exp_total * 100) if exp_total else 0

        # ---------- مقارنة الفترة السابقة + المبيعات اليومية ----------
        span = (d_to - d_from).days + 1
        prev_to = d_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=span - 1)
        sales_prev = -(AML._read_group(inv_dom(SALE_T, prev_from, prev_to), [], ["balance:sum"])[0][0] or 0)
        daily = []
        if 0 < span <= 92:
            def per_day(dom, sign):
                out = {}
                for d, v in AML._read_group(dom, ["date:day"], ["balance:sum"]):
                    if d:
                        out[d.strftime("%Y-%m-%d")] = sign * v
                return out
            sd, pd_ = per_day(sale_dom, -1), per_day(purch_dom, 1)
            for i in range(span):
                k = str(d_from + timedelta(days=i))
                daily.append({"m": k, "sales": sd.get(k, 0), "purchases": pd_.get(k, 0)})

        # ---------- المخزون ----------
        Q = E["stock.quant"]
        qdom = [("location_id.usage", "=", "internal"), cid]
        stock_rows = Q._read_group(qdom, ["product_id"], ["quantity:sum"])
        inv_items, inv_total, inv_qty, negative = [], 0.0, 0.0, 0
        for p, q in stock_rows:
            if not p:
                continue
            if q < 0:
                negative += 1
                continue
            val = q * p.standard_price
            inv_total += val
            inv_qty += q
            inv_items.append({"id": p.id, "name": p.display_name, "value": val, "qty": q,
                              "sub": f"الكمية: {_n(q)}"})
        top_stock = sorted(inv_items, key=lambda x: -x["value"])[:10]
        dead = sorted([i for i in inv_items if i["id"] not in sold_ids and i["value"] > 0],
                      key=lambda x: -x["value"])
        dead_value = sum(i["value"] for i in dead)
        dead_stock = dead[:10]

        expiry, expired_val, near_val = [], 0.0, 0.0
        if "expiration_date" in E["stock.lot"]._fields:
            lim = today + timedelta(days=90)
            quants = Q.search(qdom + [("quantity", ">", 0), ("lot_id", "!=", False),
                                      ("lot_id.expiration_date", "<=", f"{lim} 23:59:59")], limit=1000)
            for qt in quants:
                exp = qt.lot_id.expiration_date
                if not exp:
                    continue
                days = (exp.date() - today).days
                val = qt.quantity * qt.product_id.standard_price
                if days < 0:
                    expired_val += val
                else:
                    near_val += val
                expiry.append({"name": qt.product_id.display_name, "lot": qt.lot_id.name,
                               "qty": qt.quantity, "date": str(exp.date()), "days": days})
            expiry.sort(key=lambda x: x["days"])
            expiry = expiry[:25]

        # قيمة المخزون كما في دفتر الأستاذ: رصيد حسابات تقييم المخزون لفئات المنتجات
        book_value = None
        try:
            fld = "property_stock_valuation_account_id"
            cats = E["product.category"]
            if fld in cats._fields:
                acc_ids = set()
                for co in E.companies:
                    acc_ids |= set(cats.with_company(co).search([]).mapped(fld).ids)
                if acc_ids:
                    book_value = AML._read_group(
                        posted + [("account_id", "in", list(acc_ids))],
                        [], ["balance:sum"])[0][0] or 0
        except Exception:
            book_value = None

        # ---------- حصص الشركاء ----------
        shares = [{"name": s.partner_id.display_name, "percent": s.percent, "amount": net * s.percent / 100.0}
                  for s in E["pharma.dashboard.share"].search([cid])]

        return {
            "currency": E.company.currency_id.symbol or "",
            "company": ", ".join(E.companies.mapped("name")),
            "wallets": wallet_list, "as_of": date_to,
            "returns": {"sales": ret_sales, "purchase": ret_purch,
                        "rate": (ret_sales["total"] / (sales_total + ret_sales["total"]) * 100)
                    if (sales_total + ret_sales["total"]) else 0},
            "receivable": receivable, "payable": payable,
            "pl": {"income": income, "cogs": cogs, "gross": gross, "opex": opex, "net": net},
            "sales_total": sales_total, "sales_count": sales_count, "purch_total": purch_total,
            "sales_prev": sales_prev, "daily": daily,
            "reps": reps, "top_gov": top_gov,
            "expenses": {"total": exp_total, "items": exp_items},
            "top_products": top_products, "bottom_products": bottom_products,
            "top_by_amount": top_by_amount, "sold_by_supplier": sold_by_supplier,
            "top_customers": top_customers, "governorates": governorates,
            "top_suppliers": top_suppliers, "trend": trend,
            "inventory": {"total": book_value if book_value is not None else inv_total,
                          "from_book": book_value is not None, "estimated": inv_total, "qty": inv_qty, "items": len(inv_items), "negative": negative,
                          "top": top_stock, "dead": dead_stock, "dead_value": dead_value,
                          "expiry": expiry, "expired_val": expired_val, "near_val": near_val,
                          "has_expiry": "expiration_date" in E["stock.lot"]._fields},
            "shares": shares,
        }

    def _check(self):
        if not self.env.user.has_group("pharma_dashboard.group_dashboard_viewer"):
            raise AccessError(_("ليس لديك صلاحية عرض لوحة المعلومات."))
        return self.sudo().env

    @api.model
    def get_box_moves(self, journal_id, date_from, date_to):
        """حركات حساب الصندوق/البنك في دفتر الأستاذ خلال الفترة (آخر 60 حركة، من أي يومية)."""
        E = self._check()
        j = E["account.journal"].browse(journal_id)
        if j.company_id.id not in E.companies.ids or not j.default_account_id:
            return []
        cur = j.currency_id or j.company_id.currency_id
        foreign = cur != j.company_id.currency_id
        dom = [("account_id", "=", j.default_account_id.id), ("parent_state", "=", "posted"),
               ("company_id", "in", E.companies.ids),
               ("date", ">=", date_from), ("date", "<=", date_to)]
        if foreign:
            dom.append(("currency_id", "=", cur.id))
        lines = E["account.move.line"].search(dom, order="date desc, id desc", limit=60)
        out = []
        for l in lines:
            pay = l.move_id.origin_payment_id
            tag = ""
            if pay and pay.partner_type == "customer" and pay.payment_type == "outbound":
                tag = "رجيع زبون"
            elif pay and pay.partner_type == "supplier" and pay.payment_type == "inbound":
                tag = "رجيع مورد"
            if foreign:
                inn, outv = max(l.amount_currency, 0), max(-l.amount_currency, 0)
            else:
                inn, outv = l.debit, l.credit
            out.append({"date": str(l.date), "ref": l.move_id.name or "",
                        "journal": l.journal_id.name or "",
                        "partner": l.partner_id.display_name or l.name or "",
                        "in": inn, "out": outv, "tag": tag})
        return out

    @api.model
    def get_expense_moves(self, product_id, date_from, date_to):
        """آخر 60 نفقة من موديل النفقات لفئة معيّنة خلال الفترة."""
        E = self._check()
        if "hr.expense" not in E:
            return []
        X = E["hr.expense"]
        amt_f = "total_amount" if "total_amount" in X._fields else "total_amount_currency"
        rows = X.search([("product_id", "=", product_id), ("state", "not in", ("draft", "refused")),
                         ("company_id", "in", E.companies.ids),
                         ("date", ">=", date_from), ("date", "<=", date_to)],
                        order="date desc, id desc", limit=60)
        return [{"date": str(x.date), "ref": x.name or "", "label": x.name or "",
                 "partner": x.employee_id.display_name or "", "amount": x[amt_f]} for x in rows]

    @api.model
    def get_partner_items(self, partner_id, kind):
        """الفواتير/القيود المفتوحة لعميل أو مورد."""
        E = self._check()
        today = fields.Date.context_today(self)
        atype = "asset_receivable" if kind == "customer" else "liability_payable"
        sign = 1 if kind == "customer" else -1
        mt = ("out_invoice", "out_refund") if kind == "customer" else ("in_invoice", "in_refund")
        rows = E["account.move.line"]._read_group(
            [("parent_state", "=", "posted"), ("display_type", "=", "payment_term"),
             ("move_id.move_type", "in", mt), ("company_id", "in", E.companies.ids)], ["account_id"], ["__count"])
        acc_ids = [a.id for a, _c in rows if a and a.account_type == atype]
        lines = E["account.move.line"].search([
            ("partner_id", "=", partner_id),
            ("account_id", "in", acc_ids) if acc_ids else ("account_id.account_type", "=", atype),
            ("reconciled", "=", False), ("parent_state", "=", "posted"),
            ("company_id", "in", E.companies.ids)], order="date_maturity, date")
        return [{"name": l.move_id.name or "", "date": str(l.date),
                 "due": str(l.date_maturity or l.date), "amount": sign * l.amount_residual,
                 "late": (l.date_maturity or l.date) < today and sign * l.amount_residual > 0} for l in lines]
