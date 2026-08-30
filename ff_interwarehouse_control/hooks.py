# -*- coding: utf-8 -*-
"""Installation hooks for ff_interwarehouse_control."""


def post_init_hook(env):
    """Discover existing warehouses on install and create every missing
    inter-warehouse lane (and the per-lane transit locations) idempotently.

    ``env`` receives a single argument in Odoo 18 (see
    ``odoo/modules/loading.py``).
    """
    env['ff.interwarehouse.lane']._ff_setup_all()
    warehouses = env['stock.warehouse'].search([('active', '=', True)])
    for warehouse in warehouses:
        warehouse._ff_setup_interwarehouse_ops()
