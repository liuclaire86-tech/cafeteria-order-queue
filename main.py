"""Cafeteria order queue prototype with a persistent SQLite store."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
import sqlite3
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("CAFETERIA_DB", "cafeteria.db"))


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, ticket INTEGER NOT NULL UNIQUE,
            display_name TEXT NOT NULL, items TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS orders_status_ticket ON orders(status, ticket)")
        db.execute("CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
        db.execute("INSERT OR IGNORE INTO counters(name, value) VALUES ('ticket', 0)")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="School Cafeteria Queue", version="0.1.0", lifespan=lifespan)


class OrderIn(BaseModel):
    # Use a first name or pickup alias on the public TV; avoid student ID numbers.
    display_name: str = Field(min_length=1, max_length=40)
    items: list[str] = Field(min_length=1, max_length=20)
    notes: str = Field(default="", max_length=200)


class StatusIn(BaseModel):
    status: Literal["preparing", "ready", "picked_up"]


def serialize(row: sqlite3.Row) -> dict:
    return {**dict(row), "items": row["items"].split("\n")}


@app.get("/health")
def health():
    return {"status": "healthy", "service": "school-cafeteria-queue"}


@app.post("/api/orders", status_code=201)
def create_order(order: OrderIn):
    now = datetime.now(timezone.utc).isoformat()
    order_id = str(uuid4())
    # Allocate a ticket and insert the order in one transaction, so cashiers
    # working at the same time cannot receive the same ticket number.
    with connect() as db:
        db.execute("UPDATE counters SET value = value + 1 WHERE name = 'ticket'")
        ticket = db.execute("SELECT value FROM counters WHERE name = 'ticket'").fetchone()[0]
        db.execute("INSERT INTO orders(id,ticket,display_name,items,notes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                   (order_id, ticket, order.display_name.strip(), "\n".join(i.strip() for i in order.items), order.notes.strip(), "queued", now, now))
        row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return serialize(row)


@app.get("/api/orders")
def list_orders(view: Literal["all", "kitchen", "ready"] = "all"):
    with connect() as db:
        if view == "kitchen":
            rows = db.execute("SELECT * FROM orders WHERE status IN ('queued','preparing') ORDER BY ticket").fetchall()
        elif view == "ready":
            rows = db.execute("SELECT * FROM orders WHERE status='ready' ORDER BY updated_at DESC LIMIT 20").fetchall()
        else:
            rows = db.execute("SELECT * FROM orders WHERE status!='picked_up' ORDER BY ticket").fetchall()
    return [serialize(row) for row in rows]


@app.patch("/api/orders/{order_id}")
def update_order(order_id: str, body: StatusIn):
    with connect() as db:
        row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Order not found")
        allowed = {"queued": {"preparing"}, "preparing": {"ready"}, "ready": {"picked_up"}, "picked_up": set()}
        if body.status not in allowed[row["status"]]:
            raise HTTPException(409, f"Cannot move order from {row['status']} to {body.status}")
        db.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                   (body.status, datetime.now(timezone.utc).isoformat(), order_id))
        row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return serialize(row)


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cafeteria Queue</title><style>
    *{box-sizing:border-box}body{font:16px system-ui;margin:0;background:#f3f6fb;color:#172033}header{background:#163b5c;color:white;padding:22px 5vw}main{max-width:1100px;margin:24px auto;padding:0 18px}.links{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}.card{display:block;background:white;border-radius:14px;padding:22px;color:#163b5c;text-decoration:none;box-shadow:0 3px 16px #102b4414}.card h2{margin:0 0 8px}.muted{color:#66758b}
    </style></head><body><header><h1>School Cafeteria Queue</h1><div>Orders move from cashier to kitchen to pickup.</div></header><main><h2>Open a station</h2><section class="links"><a class="card" href="/cashier"><h2>Cashier</h2><span class="muted">Enter a name and order items; get a ticket number.</span></a><a class="card" href="/kitchen"><h2>Kitchen</h2><span class="muted">See queued orders and move them through preparation.</span></a><a class="card" href="/pickup"><h2>Pickup TV</h2><span class="muted">Show ready ticket numbers and pickup names.</span></a></section><p class="muted">Prototype: use a first name or pickup alias on the public display. Do not enter student ID numbers.</p></main></body></html>""")


@app.get("/cashier", response_class=HTMLResponse)
def cashier_page():
    return HTMLResponse(PAGE.replace("__TITLE__", "Cashier").replace("__BODY__", CASHIER))


@app.get("/kitchen", response_class=HTMLResponse)
def kitchen_page():
    return HTMLResponse(PAGE.replace("__TITLE__", "Kitchen Queue").replace("__BODY__", KITCHEN))


@app.get("/pickup", response_class=HTMLResponse)
def pickup_page():
    return HTMLResponse(PAGE.replace("__TITLE__", "Pickup Screen").replace("__BODY__", PICKUP))


PAGE = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title><style>
*{box-sizing:border-box}body{font:16px system-ui;margin:0;background:#f3f6fb;color:#172033}header{background:#163b5c;color:white;padding:18px 5vw}main{max-width:1000px;margin:24px auto;padding:0 18px}.panel,.order{background:white;border-radius:14px;padding:20px;margin:14px 0;box-shadow:0 3px 16px #102b4414}input,textarea,button{font:inherit;padding:11px;border:1px solid #bac6d5;border-radius:8px}input,textarea{width:100%;margin:6px 0 14px}button{background:#136b54;color:white;border:0;cursor:pointer;font-weight:700;margin:4px}.secondary{background:#315b7d}.danger{background:#66758b}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.ticket{font-size:1.3rem;font-weight:800;color:#087252}.items{margin:8px 0}.status{font-weight:700;text-transform:uppercase;color:#315b7d}.empty{color:#66758b}.large{font-size:clamp(2rem,5vw,4rem)}.ready{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #d8e0e9;padding:12px}.name{font-size:clamp(1.5rem,3vw,2.5rem);font-weight:800}.notice{padding:10px;background:#e2f3ea;border-radius:8px}
</style></head><body><header><a href="/" style="color:white">← Home</a><h1>__TITLE__</h1></header><main>__BODY__</main></body></html>"""

CASHIER = """<section class="panel"><form id="form"><label>Pickup name (first name or alias)<input name="display_name" required maxlength="40" placeholder="e.g. Alex"></label><label>Food items (one item per line)<textarea name="items" required rows="4" placeholder="Chicken sandwich&#10;Apple"></textarea></label><label>Kitchen note (optional)<input name="notes" maxlength="200" placeholder="No cheese"></label><button>Submit order</button></form><div id="result"></div></section><script>
document.querySelector('#form').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target);const r=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_name:f.get('display_name'),items:f.get('items').split('\\n').map(x=>x.trim()).filter(Boolean),notes:f.get('notes')})});const d=await r.json();if(!r.ok){alert(d.detail||'Could not create order');return}document.querySelector('#result').innerHTML=`<p class="notice">Order entered: <b>Ticket #${d.ticket}</b> for ${safe(d.display_name)} — ${safe(d.status)}</p>`;e.target.reset()};function safe(s){const x=document.createElement('span');x.textContent=s;return x.innerHTML}
</script>"""

KITCHEN = """<p class="muted">This board refreshes every 3 seconds. Mark an order preparing, then ready when it is complete.</p><div id="orders"></div><script>
async function refresh(){const rows=await(await fetch('/api/orders?view=kitchen')).json();const root=document.querySelector('#orders');root.innerHTML=rows.length?rows.map(o=>`<article class="order"><div class="row"><span class="ticket">#${o.ticket}</span><b>${safe(o.display_name)}</b><span class="status">${o.status}</span></div><div class="items">${o.items.map(i=>`• ${safe(i)}`).join('<br>')}</div>${o.notes?`<p><b>Note:</b> ${safe(o.notes)}</p>`:''}<button onclick="move('${o.id}','${o.status==='queued'?'preparing':'ready}')">${o.status==='queued'?'Start preparing':'Mark ready'}</button></article>`).join(''):'<p class="empty">No orders waiting in the kitchen.</p>'}async function move(id,status){const r=await fetch('/api/orders/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});if(!r.ok)alert((await r.json()).detail);refresh()}function safe(s){const x=document.createElement('span');x.textContent=s;return x.innerHTML}refresh();setInterval(refresh,3000)
</script>"""

PICKUP = """<p class="muted">Ready orders refresh automatically. Call the ticket number and pickup name.</p><div class="panel"><div id="orders"></div></div><script>
async function refresh(){const rows=await(await fetch('/api/orders?view=ready')).json();document.querySelector('#orders').innerHTML=rows.length?rows.map(o=>`<div class="ready"><span class="ticket large">#${o.ticket}</span><span class="name">${safe(o.display_name)}</span></div>`).join(''):'<p class="empty large">Preparing your orders…</p>'}function safe(s){const x=document.createElement('span');x.textContent=s;return x.innerHTML}refresh();setInterval(refresh,3000)
</script>"""
