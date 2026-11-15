from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import math
import sqlite3
import jwt
import hashlib

app = FastAPI(title="Reshis Avia API - Secure")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- БАЗА ДАННЫХ И АВТОРИЗАЦИЯ ---
SECRET_KEY = "reshis_avia_super_secret"

# Создаем базу данных SQLite для пользователей
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
conn.commit()

# Функция для шифрования пароля
def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()

class UserAuth(BaseModel):
    username: str
    password: str

@app.post("/register")
def register(user: UserAuth):
    cursor.execute("SELECT * FROM users WHERE username=?", (user.username,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="Пользователь уже существует")
    
    cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (user.username, hash_password(user.password)))
    conn.commit()
    return {"message": "Успешная регистрация! Теперь войдите."}

@app.post("/login")
def login(user: UserAuth):
    cursor.execute("SELECT * FROM users WHERE username=? AND password=?", (user.username, hash_password(user.password)))
    if not cursor.fetchone():
        raise HTTPException(status_code=400, detail="Неверный логин или пароль")
    
    # Генерируем JWT токен
    token = jwt.encode({"sub": user.username}, SECRET_KEY, algorithm="HS256")
    return {"access_token": token}

# Проверка токена
def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Необходима авторизация (Токен не найден)")
    token = authorization.split(" ")[1]
    try:
        jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except:
        raise HTTPException(status_code=401, detail="Неверный или просроченный токен")

# --- БИЗНЕС ЛОГИКА (ТЕПЕРЬ ЗАЩИЩЕНА ТОКЕНОМ) ---
try:
    routes_df = pd.read_csv("routes.csv")
    forecast_df = pd.read_csv("my_forecast.csv")
except FileNotFoundError:
    print("ВНИМАНИЕ: CSV файлы не найдены!")

class PredictionRequest(BaseModel):
    route: str
    date: str
    price: float

# Добавили проверку токена в dependencies
@app.post("/predict", dependencies=[Depends(verify_token)])
def predict_sales(req: PredictionRequest):
    route_info = routes_df[routes_df['route'] == req.route]
    if route_info.empty:
        raise HTTPException(status_code=404, detail="Маршрут не найден")
    
    base_price = route_info.iloc[0]['base_price']
    price_sensitivity = route_info.iloc[0]['price_sensitivity']
    
    forecast_info = forecast_df[(forecast_df['route'] == req.route) & (forecast_df['date'] == req.date)]
    if forecast_info.empty:
        raise HTTPException(status_code=404, detail="Прогноз на эту дату не найден")
    
    seats = int(forecast_info.iloc[0]['seats'])
    quantiles = ["0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9"]
    quantiles_data = {}
    
    for q in quantiles:
        base_demand = forecast_info.iloc[0][f"{q}_base_demand"]
        desired = base_demand - price_sensitivity * (req.price - base_price)
        buyers = min(seats, max(0, desired))
        quantiles_data[q] = {
            "desired": max(0, math.floor(desired)),
            "buyers": math.floor(buyers)
        }
        
    return {
        "route": req.route,
        "date": req.date,
        "price": req.price,
        "seats": seats,
        "median_desired": quantiles_data["0.5"]["desired"],
        "median_buyers": quantiles_data["0.5"]["buyers"],
        "quantiles_data": quantiles_data
    }