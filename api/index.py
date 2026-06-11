from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3
import json
import hashlib
import hmac
import os
import random
from datetime import date

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Корневой маршрут
@app.get("/")
def home():
    return {"status": "ok", "message": "JustGift API is running"}

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8667961704:AAGLpbPSMvcqXDD1sgmRTG2_FtwfHxpZJWI")
ADMIN_IDS = [8526401545]
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "justgift_internal_secret")
DB_PATH = "/tmp/justgift.db"

CASES = {
    "bronze": {
        "name": "Бронзовый кейс", "price": 50, "color": "#CD7F32",
        "items": [
            {"name": "10 звёзд", "stars": 10, "chance": 50, "rarity": "common"},
            {"name": "25 звёзд", "stars": 25, "chance": 30, "rarity": "uncommon"},
            {"name": "50 звёзд", "stars": 50, "chance": 15, "rarity": "rare"},
            {"name": "150 звёзд", "stars": 150, "chance": 4, "rarity": "epic"},
            {"name": "500 звёзд", "stars": 500, "chance": 1, "rarity": "legendary"},
        ]
    },
    "silver": {
        "name": "Серебряный кейс", "price": 150, "color": "#C0C0C0",
        "items": [
            {"name": "50 звёзд", "stars": 50, "chance": 45, "rarity": "common"},
            {"name": "100 звёзд", "stars": 100, "chance": 30, "rarity": "uncommon"},
            {"name": "250 звёзд", "stars": 250, "chance": 15, "rarity": "rare"},
            {"name": "500 звёзд", "stars": 500, "chance": 8, "rarity": "epic"},
            {"name": "2000 звёзд", "stars": 2000, "chance": 2, "rarity": "legendary"},
        ]
    },
    "gold": {
        "name": "Золотой кейс", "price": 500, "color": "#FFD700",
        "items": [
            {"name": "200 звёзд", "stars": 200, "chance": 40, "rarity": "common"},
            {"name": "400 звёзд", "stars": 400, "chance": 30, "rarity": "uncommon"},
            {"name": "800 звёзд", "stars": 800, "chance": 18, "rarity": "rare"},
            {"name": "2000 звёзд", "stars": 2000, "chance": 10, "rarity": "epic"},
            {"name": "10000 звёзд", "stars": 10000, "chance": 2, "rarity": "legendary"},
        ]
    },
    "daily": {
        "name": "Ежедневный кейс", "price": 0, "color": "#C8FF00",
        "items": [
            {"name": "5 звёзд", "stars": 5, "chance": 50, "rarity": "common"},
            {"name": "15 звёзд", "stars": 15, "chance": 30, "rarity": "uncommon"},
            {"name": "30 звёзд", "stars": 30, "chance": 15, "rarity": "rare"},
            {"name": "100 звёзд", "stars": 100, "chance": 4, "rarity": "epic"},
            {"name": "500 звёзд", "stars": 500, "chance": 1, "rarity": "legendary"},
        ]
    }
}

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY,
        username TEXT, first_name TEXT, last_name TEXT, photo_url TEXT,
        balance INTEGER DEFAULT 0, total_won INTEGER DEFAULT 0,
        cases_opened INTEGER DEFAULT 0, last_daily TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER, type TEXT, amount INTEGER, status TEXT DEFAULT "pending",
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS case_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER, case_type TEXT, item_name TEXT,
        stars_won INTEGER, rarity TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

# --- АВТО-АВТОРИЗАЦИЯ АДМИНА (ДЛЯ ТЕСТОВ) ---
def get_current_user(x_init_data: str = Header(None)):
    return {"id": 8526401545, "first_name": "Админ", "username": "admin"}
# -------------------------------------------

def get_or_create_user(tg_user: dict):
    conn = get_db()
    c = conn.cursor()
    tg_id = tg_user["id"]
    user = c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
    if not user:
        c.execute("INSERT INTO users (tg_id,username,first_name,last_name) VALUES (?,?,?,?)",
                  (tg_id, tg_user.get("username"), tg_user.get("first_name"), tg_user.get("last_name")))
        conn.commit()
        user = c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
    result = dict(user)
    conn.close()
    return result

@app.get("/api/me")
def get_me(tg_user=Depends(get_current_user)): return get_or_create_user(tg_user)

@app.post("/api/me/photo")
def update_photo(data: dict, tg_user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("UPDATE users SET photo_url=? WHERE tg_id=?", (data.get("photo_url"), tg_user["id"]))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/cases")
def get_cases(): return CASES

@app.post("/api/cases/{case_type}/open")
def open_case(case_type: str, tg_user=Depends(get_current_user)):
    if case_type not in CASES: raise HTTPException(status_code=404, detail="Case not found")
    case = CASES[case_type]
    user = get_or_create_user(tg_user)
    tg_id = tg_user["id"]
    if case_type == "daily":
        today = date.today().isoformat()
        if user.get("last_daily") == today: raise HTTPException(status_code=400, detail="Ежедневный кейс уже получен сегодня")
    else:
        if user["balance"] < case["price"]: raise HTTPException(status_code=400, detail="Недостаточно звёзд")
    
    items = case["items"]
    total = sum(i["chance"] for i in items)
    roll = random.uniform(0, total)
    cumulative = 0
    won_item = items[-1]
    for item in items:
        cumulative += item["chance"]
        if roll <= cumulative:
            won_item = item
            break

    conn = get_db()
    c = conn.cursor()
    if case_type == "daily":
        c.execute("UPDATE users SET last_daily=?,balance=balance+?,total_won=total_won+?,cases_opened=cases_opened+1 WHERE tg_id=?",
                  (date.today().isoformat(), won_item["stars"], won_item["stars"], tg_id))
    else:
        c.execute("UPDATE users SET balance=balance-?+?,total_won=total_won+?,cases_opened=cases_opened+1 WHERE tg_id=?",
                  (case["price"], won_item["stars"], won_item["stars"], tg_id))
    c.execute("INSERT INTO case_history (tg_id,case_type,item_name,stars_won,rarity) VALUES (?,?,?,?,?)",
              (tg_id, case_type, won_item["name"], won_item["stars"], won_item["rarity"]))
    conn.commit()
    user_upd = dict(c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone())
    conn.close()
    spin_seq = [random.choice(items) for _ in range(29)] + [won_item]
    return {"won": won_item, "new_balance": user_upd["balance"], "spin_items": spin_seq}

@app.post("/api/deposit/request")
def request_deposit(data: dict, tg_user=Depends(get_current_user)):
    amount = int(data.get("amount", 0))
    if amount < 1: raise HTTPException(status_code=400, detail="Минимум 1 звезда")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO transactions (tg_id,type,amount) VALUES (?,?,?)", (tg_user["id"], "deposit", amount))
    tx_id = c.lastrowid
    conn.commit()
    conn.close()
    bot_username = os.environ.get("BOT_USERNAME", "justgift_support_bot")
    return {"tx_id": tx_id, "bot_url": f"https://t.me/{bot_username}?start=pay_{tx_id}_{amount}", "amount": amount}

@app.post("/api/deposit/confirm")
def confirm_deposit(data: dict):
    if data.get("secret") != INTERNAL_SECRET: raise HTTPException(status_code=403)
    conn = get_db()
    conn.execute("UPDATE transactions SET status='completed' WHERE id=? AND tg_id=?", (data["tx_id"], data["tg_id"]))
    conn.execute("UPDATE users SET balance=balance+? WHERE tg_id=?", (data["amount"], data["tg_id"]))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/withdraw/request")
def request_withdraw(data: dict, tg_user=Depends(get_current_user)):
    amount = int(data.get("amount", 0))
    user = get_or_create_user(tg_user)
    if amount < 50: raise HTTPException(status_code=400, detail="Минимальный вывод — 50 звёзд")
    if user["balance"] < amount: raise HTTPException(status_code=400, detail="Недостаточно звёзд")
    conn = get_db()
    c = conn.cursor()
    conn.execute("UPDATE users SET balance=balance-? WHERE tg_id=?", (amount, tg_user["id"]))
    c.execute("INSERT INTO transactions (tg_id,type,amount) VALUES (?,?,?)", (tg_user["id"], "withdraw", amount))
    tx_id = c.lastrowid
    conn.commit()
    conn.close()
    bot_username = os.environ.get("BOT_USERNAME", "justgift_support_bot")
    return {"tx_id": tx_id, "bot_url": f"https://t.me/{bot_username}?start=withdraw_{tx_id}_{amount}", "amount": amount}

@app.get("/api/history")
def get_history(tg_user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM case_history WHERE tg_id=? ORDER BY created_at DESC LIMIT 20", (tg_user["id"],)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/admin/give-stars")
def admin_give_stars(data: dict, tg_user=Depends(get_current_user)):
    if tg_user["id"] not in ADMIN_IDS: raise HTTPException(status_code=403)
    conn = get_db()
    conn.execute("UPDATE users SET balance=balance+? WHERE tg_id=?", (int(data["amount"]), data["tg_id"]))
    conn.execute("INSERT INTO transactions (tg_id,type,amount,status) VALUES (?,?,?,?)", (data["tg_id"], "admin_gift", data["amount"], "completed"))
    conn.commit()
    conn.close()
    return {"ok": True, "message": f"Выдано {data['amount']} звёзд пользователю {data['tg_id']}"}

@app.get("/api/admin/users")
def admin_get_users(tg_user=Depends(get_current_user)):
    if tg_user["id"] not in ADMIN_IDS: raise HTTPException(status_code=403)
    conn = get_db()
    users = conn.execute("SELECT * FROM users ORDER BY balance DESC LIMIT 100").fetchall()
    conn.close()
    return [dict(u) for u in users]
