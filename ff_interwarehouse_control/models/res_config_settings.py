# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ff_enable_auto_setup = fields.Boolean(
        string='Enable Automatic Warehouse Setup',
        config_parameter='ff_interwarehouse_control.auto_setup',
        default=True)
    ff_enable_partial_receipt_notifications = fields.Boolean(
        string='Enable Partial Receipt Notifications',
        config_parameter='ff_interwarehouse_control.partial_receipt_notifications',
        default=True)
    ff_require_partial_receipt_reason = fields.Boolean(
        string='Require Partial Receipt Reason',
        config_parameter='ff_interwarehouse_control.require_partial_reason',
        default=False)
    ff_notify_source_responsible = fields.Boolean(
        string='Notify Source Responsible',
        config_parameter='ff_interwarehouse_control.notify_source_responsible',
        default=True)
    ff_auto_create_lanes = fields.Boolean(
        string='Auto-create Lanes for New Warehouses',
        config_parameter='ff_interwarehouse_control.auto_create_lanes',
        default=True)
    ff_notify_destination = fields.Boolean(
        string='Notify Destination Warehouse',
        config_parameter='ff_interwarehouse_control.notify_destination',
        default=True)
