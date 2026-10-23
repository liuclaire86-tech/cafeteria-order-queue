# School Cafeteria Queue

A first working prototype for moving cafeteria orders from the cashier to the kitchen and then to a pickup display. The cashier enters a pickup name or alias and food items; the kitchen advances orders through preparation; the TV view lists ready ticket numbers and names.

## Run locally

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
fastapi dev app/main.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Choose **Cashier**, **Kitchen**, or **Pickup TV**. Interactive API documentation is at `/docs`. Orders persist in `cafeteria.db`; set `CAFETERIA_DB` to use another local path.

## Order flow

```text
Cashier → queued → Kitchen: preparing → ready → Pickup: picked_up
```

The API rejects invalid state transitions. Each order gets a unique ID and an incrementing ticket. The kitchen and pickup boards refresh every three seconds.

## API

- `POST /api/orders` creates an order (`display_name`, `items`, optional `notes`).
- `GET /api/orders?view=kitchen` lists queued and preparing orders.
- `GET /api/orders?view=ready` lists ready orders.
- `GET /api/orders` lists all orders that have not been picked up.
- `PATCH /api/orders/{id}` moves an order to `preparing`, `ready`, or `picked_up`.
- `GET /health` checks service health.

## Important prototype limits

This is a single-server learning prototype using SQLite. It is not yet suitable for a live school cafeteria or for multiple application instances. A production version should use PostgreSQL for durable shared state, authenticated staff accounts, role-based permissions, audit history, backups, monitoring, HTTPS, and tested recovery procedures. Redis can be added later for queue coordination, but the database should remain the source of truth.

The public pickup screen displays the entered name. To reduce exposure of student information, use a first name or a pickup alias and ticket number; never enter student ID numbers. A real school rollout should follow the school's privacy rules and obtain the relevant approval before displaying student names.

## Next milestones

1. Add tests for order creation and state transitions.
2. Move persistence to PostgreSQL with schema migrations.
3. Add staff authentication and a menu catalog instead of free-text items.
4. Add live screen updates, order cancellation, and pickup confirmation.
5. Add deployment configuration, backups, and operational monitoring.
