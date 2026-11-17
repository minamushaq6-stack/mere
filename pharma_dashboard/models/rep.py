from odoo import fields, models


class PharmaDashboardRep(models.Model):
    _name = "pharma.dashboard.rep"
    _description = "مندوب مبيعات (علمي / تجاري)"

    user_id = fields.Many2one("res.users", string="المندوب", required=True)
    rep_type = fields.Selection(
        [("scientific", "مندوب علمي"), ("commercial", "مندوب تجاري")],
        string="النوع", required=True, default="scientific")
    company_id = fields.Many2one("res.company", string="الشركة", required=True,
                                 default=lambda s: s.env.company)
