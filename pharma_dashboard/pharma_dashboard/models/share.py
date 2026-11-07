from odoo import fields, models


class PharmaDashboardShare(models.Model):
    _name = "pharma.dashboard.share"
    _description = "حصة شريك"

    partner_id = fields.Many2one("res.partner", string="الشريك", required=True)
    percent = fields.Float("النسبة %", required=True)
    company_id = fields.Many2one("res.company", string="الشركة", required=True,
                                 default=lambda s: s.env.company)
