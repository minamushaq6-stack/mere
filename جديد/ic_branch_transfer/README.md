# Branch Stock Transfer (Odoo 19)

Transfer stock from the main company to a separate branch company (same database)
WITHOUT sales / purchase orders.

## Setup
1. Enable Multi-Companies. Products must be shared (empty Company field) or exist for both companies.
2. Install the module. Open each company (Settings > Companies):
   tab "Branch Transfers": choose users to be notified + optional "Require approval".
3. Inventory > Operations > Branch Transfers > New.

## Flow
Confirm (or Approve) -> Delivery (main) + Receipt (branch) are created, linked via the
Inter-company transit location.
Validate Delivery -> goods in transit, branch is notified (activity + message).
Validate Receipt -> main company is notified, transfer = Received.

The user creating a transfer must be allowed in BOTH companies (to pick the branch).
