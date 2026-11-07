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

        AML = E["account.move.line"]
        posted = [("parent_state", "=", "posted"), cid]

        # ---------- الصناديق والبنوك ----------
        journals = E["account.journal"].search([("type", "in", ("cash", "bank")), cid])
        pay_map = defaultdict(float)
        for j, pt, ptn, amt in E["account.payment"]._read_group(
                [("journal_id", "in", journals.ids), ("move_id.state", "=", "posted"),
                 ("date", ">=", date_from), ("date", "<=", date_to)],
                ["journal_id", "payment_type", "partner_type"], ["amount:sum"]):
            pay_map[(j.id, pt, ptn)] += amt
        boxes = []
        for j in journals:
            if not j.default_account_id:
                continue
            ldom = posted + [("account_id", "=", j.default_account_id.id), ("journal_id", "=", j.id)]
            bal = AML._read_group(ldom, [], ["balance:sum"])[0][0] or 0
            opening = AML._read_group(ldom + [("date", "<", date_from)], [], ["balance:sum"])[0][0] or 0
            inn, out = AML._read_group(
                ldom + [("date", ">=", date_from), ("date", "<=", date_to)], [], ["debit:sum", "credit:sum"])[0]
            boxes.append({
                "id": j.id, "name": j.name, "type": j.type, "balance": bal, "opening": opening,
                "in": inn or 0, "out": out or 0,
                "cust_refund": pay_map[(j.id, "outbound", "customer")],
                "supp_refund": pay_map[(j.id, "inbound", "supplier")],
            })
        boxes.sort(key=lambda b: -b["balance"])
        cash = [{"id": b["id"], "name": b["name"], "value": b["balance"]} for b in boxes]
        cash_total = sum(b["balance"] for b in boxes)

        # ---------- المرتجعات (الرواجع) ----------
        def returns(mtype):
            dom = [("move_id.move_type", "=", mtype), ("parent_state", "=", "posted"),
                   ("display_type", "=", "product"), cid, ("date", ">=", date_from), ("date", "<=", date_to)]
            tot, cnt = AML._read_group(dom, [], ["price_subtotal:sum", "__count"])[0]
            prod = AML._read_group(dom, ["product_id"], ["quantity:sum", "price_subtotal:sum"],
                                   order="price_subtotal:sum desc", limit=10)
            part = AML._read_group(dom, ["partner_id"], ["price_subtotal:sum", "__count"],
                                   order="price_subtotal:sum desc", limit=10)
            return {
                "total": tot or 0, "lines": cnt,
                "products": [{"name": p.display_name, "value": a, "qty": q, "sub": f"الكمية: {_n(q)}"}
                             for p, q, a in prod if p],
                "partners": [{"id": p.id, "name": p.display_name, "value": a, "sub": f"{c} بند"}
                             for p, a, c in part if p],
            }
        ret_sales, ret_purch = returns("out_refund"), returns("in_refund")

        # ---------- الذمم (عملاء / موردين) ----------
        def open_items(atype, desc):
            dom = posted + [("account_id.account_type", "=", atype), ("reconciled", "=", False)]
            total = AML._read_group(dom, [], ["amount_residual:sum"])[0][0] or 0
            overdue = AML._read_group(dom + [("date_maturity", "<", today)], [], ["amount_residual:sum"])[0][0] or 0
            top = AML._read_group(
                dom, ["partner_id"], ["amount_residual:sum"],
                order="amount_residual:sum " + ("desc" if desc else "asc"), limit=15)
            buckets = [("غير مستحق", [("date_maturity", ">=", today)]),
                       ("1-30 يوم", [("date_maturity", "<", today), ("date_maturity", ">=", today - timedelta(days=30))]),
                       ("31-60 يوم", [("date_maturity", "<", today - timedelta(days=30)), ("date_maturity", ">=", today - timedelta(days=60))]),
                       ("61-90 يوم", [("date_maturity", "<", today - timedelta(days=60)), ("date_maturity", ">=", today - timedelta(days=90))]),
                       ("أكثر من 90", [("date_maturity", "<", today - timedelta(days=90))])]
            aging = []
            for label, extra in buckets:
                v = AML._read_group(dom + extra, [], ["amount_residual:sum"])[0][0] or 0
                aging.append({"name": label, "value": abs(v)})
            return {
                "total": abs(total), "overdue": abs(overdue),
                "top": [{"id": p.id, "name": p.display_name, "value": abs(v)} for p, v in top if p and abs(v) > 0.0001][:10],
                "aging": aging,
            }
        receivable = open_items("asset_receivable", True)
        payable = open_items("liability_payable", False)

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

        # ---------- المبيعات ----------
        SO, SL = E["sale.order"], E["sale.order.line"]
        sodom = [("state", "=", "sale"), ("date_order", ">=", dt_from), ("date_order", "<=", dt_to), cid]
        sales_total, sales_count = SO._read_group(sodom, [], ["amount_untaxed:sum", "__count"])[0]
        sales_total = sales_total or 0

        sdom = [("state", "=", "sale"), ("display_type", "=", False),
                ("order_id.date_order", ">=", dt_from), ("order_id.date_order", "<=", dt_to), cid]
        prows = SL._read_group(sdom, ["product_id"], ["product_uom_qty:sum", "price_subtotal:sum"])
        prods = [{"id": p.id, "name": p.display_name, "qty": q, "amount": a,
                  "sub": f"المبلغ: {_n(a)}"} for p, q, a in prows if p]
        prods.sort(key=lambda x: -x["qty"])
        sold_ids = {p["id"] for p in prods}
        top_products = prods[:10]
        bottom_products = sorted(prods, key=lambda x: x["qty"])[:10]
        top_by_amount = sorted(prods, key=lambda x: -x["amount"])[:10]

        # أكثر مورد نبيع من منتجاته
        sup_sales = defaultdict(float)
        for p in E["product.product"].browse(list(sold_ids)):
            sup = p.product_tmpl_id.seller_ids[:1].partner_id
            amt = next((x["amount"] for x in prods if x["id"] == p.id), 0)
            sup_sales[sup.display_name if sup else unknown] += amt
        sold_by_supplier = [{"name": k, "value": v} for k, v in sorted(sup_sales.items(), key=lambda x: -x[1])[:10]]

        crow = SO._read_group(sodom, ["partner_id"], ["amount_untaxed:sum"])
        top_customers = [{"id": p.id, "name": p.display_name, "value": v}
                         for p, v in sorted(crow, key=lambda x: -x[1])[:10]]
        gov = defaultdict(lambda: [0.0, 0])
        for p, v in crow:
            k = p.state_id.name or unknown
            gov[k][0] += v
            gov[k][1] += 1
        governorates = [{"name": k, "value": v[0], "sub": f"{v[1]} عميل"}
                        for k, v in sorted(gov.items(), key=lambda x: -x[1][0])]

        # ---------- المشتريات ----------
        PO = E["purchase.order"]
        podom = [("state", "in", ("purchase", "done")), ("date_order", ">=", dt_from), ("date_order", "<=", dt_to), cid]
        purch_total = PO._read_group(podom, [], ["amount_untaxed:sum"])[0][0] or 0
        prow = PO._read_group(podom, ["partner_id"], ["amount_untaxed:sum"], order="amount_untaxed:sum desc", limit=10)
        top_suppliers = [{"id": p.id, "name": p.display_name, "value": v} for p, v in prow]

        # ---------- اتجاه 12 شهر ----------
        first = date(today.year, today.month, 1)
        months = []
        y, m = first.year, first.month
        for _i in range(12):
            months.append(f"{y}-{m:02d}")
            m -= 1
            if m == 0:
                m, y = 12, y - 1
        months.reverse()
        start12 = f"{months[0]}-01 00:00:00"

        def monthly(model, dom):
            out = {}
            for d, v in E[model]._read_group(dom, ["date_order:month"], ["amount_untaxed:sum"]):
                if d:
                    out[d.strftime("%Y-%m")] = v
            return out
        sm = monthly("sale.order", [("state", "=", "sale"), ("date_order", ">=", start12), cid])
        pm = monthly("purchase.order", [("state", "in", ("purchase", "done")), ("date_order", ">=", start12), cid])
        trend = [{"m": k, "sales": sm.get(k, 0), "purchases": pm.get(k, 0)} for k in months]

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

        # ---------- حصص الشركاء ----------
        shares = [{"name": s.partner_id.display_name, "percent": s.percent, "amount": net * s.percent / 100.0}
                  for s in E["pharma.dashboard.share"].search([cid])]

        return {
            "currency": E.company.currency_id.symbol or "",
            "company": ", ".join(E.companies.mapped("name")),
            "cash": cash, "cash_total": cash_total, "boxes": boxes,
            "returns": {"sales": ret_sales, "purchase": ret_purch,
                        "rate": (ret_sales["total"] / sales_total * 100) if sales_total else 0},
            "receivable": receivable, "payable": payable,
            "pl": {"income": income, "cogs": cogs, "gross": gross, "opex": opex, "net": net},
            "sales_total": sales_total, "sales_count": sales_count, "purch_total": purch_total,
            "top_products": top_products, "bottom_products": bottom_products,
            "top_by_amount": top_by_amount, "sold_by_supplier": sold_by_supplier,
            "top_customers": top_customers, "governorates": governorates,
            "top_suppliers": top_suppliers, "trend": trend,
            "inventory": {"total": inv_total, "qty": inv_qty, "items": len(inv_items), "negative": negative,
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
        """حركات صندوق/بنك محدد خلال الفترة (آخر 60 حركة)."""
        E = self._check()
        j = E["account.journal"].browse(journal_id)
        if j.company_id.id not in E.companies.ids or not j.default_account_id:
            return []
        lines = E["account.move.line"].search([
            ("journal_id", "=", j.id), ("account_id", "=", j.default_account_id.id),
            ("parent_state", "=", "posted"), ("date", ">=", date_from), ("date", "<=", date_to)],
            order="date desc, id desc", limit=60)
        out = []
        for l in lines:
            pay = l.move_id.origin_payment_id
            tag = ""
            if pay and pay.partner_type == "customer" and pay.payment_type == "outbound":
                tag = "رجيع زبون"
            elif pay and pay.partner_type == "supplier" and pay.payment_type == "inbound":
                tag = "رجيع مورد"
            out.append({"date": str(l.date), "ref": l.move_id.name or "",
                        "partner": l.partner_id.display_name or l.name or "",
                        "in": l.debit, "out": l.credit, "tag": tag})
        return out

    @api.model
    def get_partner_items(self, partner_id, kind):
        """الفواتير/القيود المفتوحة لعميل أو مورد."""
        E = self._check()
        today = fields.Date.context_today(self)
        atype = "asset_receivable" if kind == "customer" else "liability_payable"
        lines = E["account.move.line"].search([
            ("partner_id", "=", partner_id), ("account_id.account_type", "=", atype),
            ("reconciled", "=", False), ("parent_state", "=", "posted"),
            ("company_id", "in", E.companies.ids)], order="date_maturity, date")
        return [{"name": l.move_id.name or "", "date": str(l.date),
                 "due": str(l.date_maturity or l.date), "amount": abs(l.amount_residual),
                 "late": bool(l.date_maturity and l.date_maturity < today)} for l in lines]
