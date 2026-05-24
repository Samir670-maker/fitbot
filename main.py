import sqlite3
import asyncio
import aiohttp
import json
import math

from datetime import date

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

TOKEN = "8662948232:AAFvZ_IsqedQyM07qPmZxRcgWdXnVoWjabM"
GROQ_API_KEY = "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"

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ─── БАЗА ДАННЫХ ──────────────────────────────────────────────────────────────

db = sqlite3.connect("fitbot.db", check_same_thread=False)
db.row_factory = sqlite3.Row
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id   INTEGER PRIMARY KEY,
    gender    TEXT,
    weight    REAL,
    height    REAL,
    age       INTEGER,
    goal      TEXT,
    activity  TEXT,
    calories  INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS food_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    food       TEXT,
    calories   INTEGER,
    protein    REAL,
    fat        REAL,
    carbs      REAL,
    log_date   TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS water_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    amount_ml  INTEGER,
    log_date   TEXT
)
""")

db.commit()

# ─── FSM СОСТОЯНИЯ ────────────────────────────────────────────────────────────

class CalcStates(StatesGroup):
    waiting_gender   = State()
    waiting_weight   = State()
    waiting_height   = State()
    waiting_age      = State()
    waiting_goal     = State()
    waiting_activity = State()


class FoodStates(StatesGroup):
    waiting_food = State()


class WaterStates(StatesGroup):
    waiting_water = State()


class MealPlanStates(StatesGroup):
    waiting_period = State()


class BodyFatStates(StatesGroup):
    waiting_gender  = State()
    waiting_weight  = State()
    waiting_height  = State()
    waiting_neck    = State()
    waiting_waist   = State()
    waiting_hip     = State()


class ClearStates(StatesGroup):
    waiting_confirm = State()


# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🥗 Рассчитать КБЖУ")],
        [KeyboardButton(text="🍔 Добавить еду"), KeyboardButton(text="💧 Добавить воду")],
        [KeyboardButton(text="📊 Мой профиль"), KeyboardButton(text="🔥 Мой дневник")],
        [KeyboardButton(text="📈 Статистика за 7 дней"), KeyboardButton(text="🗑 Очистить дневник")],
        [KeyboardButton(text="🍽 План питания"), KeyboardButton(text="🏋️ Программа тренировок")],
        [KeyboardButton(text="📐 % жира и FFMI")]
    ],
    resize_keyboard=True
)

gender_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👨 Мужчина")],
        [KeyboardButton(text="👩 Женщина")]
    ],
    resize_keyboard=True
)

goal_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔥 Похудение")],
        [KeyboardButton(text="💪 Набор массы")],
        [KeyboardButton(text="⚖️ Поддержание")]
    ],
    resize_keyboard=True
)

activity_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🪑 Низкая")],
        [KeyboardButton(text="🚶 Средняя")],
        [KeyboardButton(text="🏃 Высокая")]
    ],
    resize_keyboard=True
)

confirm_clear_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Да, очистить")],
        [KeyboardButton(text="❌ Отмена")]
    ],
    resize_keyboard=True
)

# ─── GROQ AI ──────────────────────────────────────────────────────────────────

async def ask_groq_food(food_name: str) -> dict | None:
    prompt = (
        f"Дай КБЖУ на 100г или стандартную порцию для: {food_name}\n"
        "Ответь ТОЛЬКО JSON:\n"
        '{"calories":250,"protein":12.5,"fat":8.3,"carbs":30.1,"serving":"плов"}'
    )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    body = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 150,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                raw = data["choices"][0]["message"]["content"].strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                result = json.loads(raw)
                return {
                    "calories": round(float(result.get("calories", 0))),
                    "protein": round(float(result.get("protein", 0)), 1),
                    "fat": round(float(result.get("fat", 0)), 1),
                    "carbs": round(float(result.get("carbs", 0)), 1),
                    "serving": result.get("serving", food_name)
                }
    except Exception:
        return None


async def ask_groq_meal_plan(user_data: dict, period: str) -> str | None:
    prompt = f"""
Составь {period} план питания на русском языке.
Данные пользователя:
Пол: {user_data.get('gender')}
Вес: {user_data.get('weight')} кг
Рост: {user_data.get('height')} см
Возраст: {user_data.get('age')}
Цель: {user_data.get('goal')}
Активность: {user_data.get('activity')}
Калории: {user_data.get('calories')} ккал

Сделай:
- Завтрак
- Обед
- Ужин
- Перекусы
- КБЖУ
- Полезные советы
Пиши красиво с эмодзи.
"""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 1500
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=40)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
    except Exception:
        return None


async def ask_groq_workout(user_data: dict) -> str | None:
    prompt = f"""
Создай программу тренировок на русском языке.
Данные пользователя:
Пол: {user_data.get('gender')}
Вес: {user_data.get('weight')}
Рост: {user_data.get('height')}
Возраст: {user_data.get('age')}
Цель: {user_data.get('goal')}
Активность: {user_data.get('activity')}

Сделай:
- План на неделю
- Упражнения
- Подходы
- Повторения
- Кардио
- Разминку
- Советы
Пиши красиво с эмодзи.
"""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 1500
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=40)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
    except Exception:
        return None

# ─── ХЕЛПЕРЫ ──────────────────────────────────────────────────────────────────

def today() -> str:
    return date.today().isoformat()


def calc_calories(gender: str, weight: float, height: float,
                  age: int, goal: str, activity: str):
    if "Мужчина" in gender:
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    if "Низкая" in activity:
        bmr *= 1.2
    elif "Средняя" in activity:
        bmr *= 1.55
    elif "Высокая" in activity:
        bmr *= 1.9

    if "Похудение" in goal:
        bmr -= 300
    elif "Набор" in goal:
        bmr += 300

    calories = int(bmr)
    protein = int(weight * 2)
    fat = int(weight * 1)
    carbs = int((calories - (protein * 4 + fat * 9)) / 4)

    return calories, protein, fat, carbs


def calc_body_fat(gender: str, weight: float, height: float,
                  neck: float, waist: float, hip: float = 0.0) -> float:
    if "Мужчина" in gender:
        bf = (495 / (1.0324 - 0.19077 * math.log10(waist - neck) + 0.15456 * math.log10(height)) - 450)
    else:
        bf = (495 / (1.29579 - 0.35004 * math.log10(waist + hip - neck) + 0.22100 * math.log10(height)) - 450)
    return round(bf, 1)


def calc_ffmi(weight: float, body_fat_pct: float, height_cm: float) -> float:
    fat_mass    = weight * (body_fat_pct / 100)
    lean_mass   = weight - fat_mass
    height_m    = height_cm / 100
    ffmi = (lean_mass / (height_m ** 2)) + 6.1 * (1.8 - height_m)
    return round(ffmi, 1)


def body_fat_category(gender: str, bf: float) -> str:
    if "Мужчина" in gender:
        if bf < 6: return "⚠️ Дефицит жира (< 6%)"
        elif bf < 14: return "🏆 Атлетический"
        elif bf < 18: return "✅ Фитнес"
        elif bf < 25: return "👍 Норма"
        else: return "⚠️ Выше нормы"
    else:
        if bf < 14: return "⚠️ Дефицит жира (< 14%)"
        elif bf < 21: return "🏆 Атлетический"
        elif bf < 25: return "✅ Фитнес"
        elif bf < 32: return "👍 Норма"
        else: return "⚠️ Выше нормы"


def ffmi_category(ffmi: float) -> str:
    if ffmi < 18: return "📉 Ниже среднего"
    elif ffmi < 20: return "📊 Среднее"
    elif ffmi < 22: return "💪 Выше среднего"
    elif ffmi < 24: return "🏋️ Атлетический"
    elif ffmi < 26: return "🔥 Элитный"
    else: return "🚀 Экстремальный (≥ 26)"

# ─── СТАРТ ────────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "💪 Добро пожаловать в FitBot!\n\nВыберите действие:",
        reply_markup=main_menu
    )

# ─── РАСЧЁТ КБЖУ ─────────────────────────────────────────────────────────────

@dp.message(F.text == "🥗 Рассчитать КБЖУ")
async def calc_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(CalcStates.waiting_gender)
    await message.answer("👤 Укажите ваш пол:", reply_markup=gender_keyboard)


@dp.message(CalcStates.waiting_gender)
async def calc_gender(message: Message, state: FSMContext):
    if message.text not in ("👨 Мужчина", "👩 Женщина"):
        await message.answer("❌ Выберите кнопку ниже.")
        return
    await state.update_data(gender=message.text)
    await state.set_state(CalcStates.waiting_weight)
    await message.answer("⚖️ Введите ваш вес (кг):", reply_markup=ReplyKeyboardRemove())


@dp.message(CalcStates.waiting_weight)
async def calc_weight(message: Message, state: FSMContext):
    try:
        w = float(message.text.replace(",", "."))
        if not (20 < w < 300): raise ValueError
        await state.update_data(weight=w)
        await state.set_state(CalcStates.waiting_height)
        await message.answer("📏 Введите ваш рост (см):")
    except ValueError:
        await message.answer("❌ Введите корректный вес.")


@dp.message(CalcStates.waiting_height)
async def calc_height(message: Message, state: FSMContext):
    try:
        h = float(message.text.replace(",", "."))
        if not (100 < h < 250): raise ValueError
        await state.update_data(height=h)
        await state.set_state(CalcStates.waiting_age)
        await message.answer("🎂 Введите возраст:")
    except ValueError:
        await message.answer("❌ Введите корректный рост.")


@dp.message(CalcStates.waiting_age)
async def calc_age(message: Message, state: FSMContext):
    try:
        a = int(message.text)
        if not (5 < a < 120): raise ValueError
        await state.update_data(age=a)
        await state.set_state(CalcStates.waiting_goal)
        await message.answer("🎯 Выберите цель:", reply_markup=goal_keyboard)
    except ValueError:
        await message.answer("❌ Введите корректный возраст.")


@dp.message(CalcStates.waiting_goal)
async def calc_goal(message: Message, state: FSMContext):
    await state.update_data(goal=message.text)
    await state.set_state(CalcStates.waiting_activity)
    await message.answer("⚡ Выберите активность:", reply_markup=activity_keyboard)


@dp.message(CalcStates.waiting_activity)
async def calc_activity(message: Message, state: FSMContext):
    await state.update_data(activity=message.text)
    data = await state.get_data()
    await state.clear()

    calories, protein, fat, carbs = calc_calories(
        data["gender"], data["weight"], data["height"], data["age"], data["goal"], data["activity"]
    )

    cursor.execute("""
    INSERT OR REPLACE INTO users (user_id, gender, weight, height, age, goal, activity, calories)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (message.from_user.id, data["gender"], data["weight"], data["height"], data["age"], data["goal"], data["activity"], calories))
    db.commit()

    water_ml = int(data["weight"] * 30)

    await message.answer(
        f"📊 Ваш результат:\n\n"
        f"🔥 Калории: {calories} ккал\n"
        f"🥩 Белки: {protein} г\n"
        f"🧈 Жиры: {fat} г\n"
        f"🍞 Углеводы: {carbs} г\n"
        f"💧 Рекомендуемая вода: {water_ml} мл",
        reply_markup=main_menu
    )

# ─── ПРОФИЛЬ ──────────────────────────────────────────────────────────────────

@dp.message(F.text == "📊 Мой профиль")
async def profile(message: Message, state: FSMContext):
    await state.clear()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()

    if not user:
        await message.answer("❌ Профиль пуст. Сначала рассчитайте КБЖУ.", reply_markup=main_menu)
        return

    await message.answer(
        f"📊 Ваш профиль:\n\n"
        f"👤 Пол: {user['gender']}\n"
        f"⚖️ Вес: {user['weight']} кг\n"
        f"📏 Рост: {user['height']} см\n"
        f"🎂 Возраст: {user['age']}\n"
        f"🎯 Цель: {user['goal']}\n"
        f"⚡ Активность: {user['activity']}\n"
        f"🔥 Целевые калории: {user['calories']} ккал",
        reply_markup=main_menu
    )

# ─── ДОБАВИТЬ ЕДУ ────────────────────────────────────────────────────────────

@dp.message(F.text == "🍔 Добавить еду")
async def add_food_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(FoodStates.waiting_food)
    await message.answer("🍽 Напишите продукт или блюдо (например: '100г плова' или 'банан'):", reply_markup=ReplyKeyboardRemove())


@dp.message(FoodStates.waiting_food)
async def process_food(message: Message, state: FSMContext):
    food_name = message.text.strip()
    await state.clear()

    wait_msg = await message.answer("⏳ Анализирую продукт через ИИ...")
    info = await ask_groq_food(food_name)

    if not info:
        await wait_msg.edit_text("❌ Не удалось распознать КБЖУ продукта. Попробуйте еще раз.", reply_markup=main_menu)
        return

    cursor.execute("""
    INSERT INTO food_log (user_id, food, calories, protein, fat, carbs, log_date)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (message.from_user.id, info["serving"], info["calories"], info["protein"], info["fat"], info["carbs"], today()))
    db.commit()

    await wait_msg.delete()
    await message.answer(
        f"✅ Добавлено в дневник:\n\n"
        f"🍔 {info['serving']}\n"
        f"🔥 {info['calories']} ккал\n"
        f"🥩 Белки: {info['protein']} г\n"
        f"🧈 Жиры: {info['fat']} г\n"
        f"🍞 Углеводы: {info['carbs']} г",
        reply_markup=main_menu
    )

# ─── ДОБАВИТЬ ВОДУ ────────────────────────────────────────────────────────────

@dp.message(F.text == "💧 Добавить воду")
async def add_water_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(WaterStates.waiting_water)
    await message.answer("💧 Введите количество выпитой воды в миллилитрах (например: 250):", reply_markup=ReplyKeyboardRemove())


@dp.message(WaterStates.waiting_water)
async def process_water(message: Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount <= 0 or amount > 5000: raise ValueError

        cursor.execute("""
        INSERT INTO water_log (user_id, amount_ml, log_date)
        VALUES (?, ?, ?)
        """, (message.from_user.id, amount, today()))
        db.commit()

        await state.clear()
        await message.answer(f"✅ Успешно добавлено {amount} мл воды!", reply_markup=main_menu)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число миллилитров (от 1 до 5000).")

# ─── МОЙ ДНЕВНИК ──────────────────────────────────────────────────────────────

@dp.message(F.text == "🔥 Мой дневник")
async def my_diary(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        await message.answer("❌ Сначала рассчитайте КБЖУ в меню.", reply_markup=main_menu)
        return

    cursor.execute("""
    SELECT SUM(calories) as cal, SUM(protein) as prot, SUM(fat) as fat, SUM(carbs) as carb 
    FROM food_log WHERE user_id = ? AND log_date = ?
    """, (user_id, today()))
    food_summary = cursor.fetchone()

    cursor.execute("""
    SELECT SUM(amount_ml) as water FROM water_log WHERE user_id = ? AND log_date = ?
    """, (user_id, today()))
    water_summary = cursor.fetchone()

    weight = user['weight']
    target_cal = user['calories']
    target_prot = int(weight * 2)
    target_fat = int(weight * 1)
    target_carb = int((target_cal - (target_prot * 4 + target_fat * 9)) / 4)
    target_water = int(weight * 30)

    cur_cal = food_summary['cal'] or 0
    cur_prot = round(food_summary['prot'] or 0, 1)
    cur_fat = round(food_summary['fat'] or 0, 1)
    cur_carb = round(food_summary['carb'] or 0, 1)
    cur_water = water_summary['water'] or 0

    left_cal = max(0, target_cal - cur_cal)

    text = (
        f"🔥 Дневник на сегодня ({today()}):\n\n"
        f"🍏 Калории: {cur_cal} / {target_cal} ккал\n"
        f"🥩 Белки: {cur_prot} / {target_prot} г\n"
        f"🧈 Жиры: {cur_fat} / {target_fat} г\n"
        f"🍞 Углеводы: {cur_carb} / {target_carb} г\n"
        f"💧 Вода: {cur_water} / {target_water} мл\n\n"
        f"🏁 Осталось употребить: {left_cal} ккал"
    )
    await message.answer(text, reply_markup=main_menu)

# ─── ОЧИСТИТЬ ДНЕВНИК ──────────────────────────────────────────────────────────

@dp.message(F.text == "🗑 Очистить дневник")
async def clear_diary_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ClearStates.waiting_confirm)
    await message.answer("⚠️ Вы уверены, что хотите полностью очистить свой дневник за СЕГОДНЯ?", reply_markup=confirm_clear_keyboard)


@dp.message(ClearStates.waiting_confirm, F.text == "✅ Да, очистить")
async def clear_diary_confirm(message: Message, state: FSMContext):
    user_id = message.from_user.id
    cursor.execute("DELETE FROM food_log WHERE user_id = ? AND log_date = ?", (user_id, today()))
    cursor.execute("DELETE FROM water_log WHERE user_id = ? AND log_date = ?", (user_id, today()))
    db.commit()
    await state.clear()
    await message.answer("🗑 Ваш дневник за сегодня успешно очищен!", reply_markup=main_menu)


@dp.message(ClearStates.waiting_confirm, F.text == "❌ Отмена")
async def clear_diary_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("↩️ Действие отменено.", reply_markup=main_menu)

# ─── СТАТИСТИКА ЗА 7 ДНЕЙ ─────────────────────────────────────────────────────

@dp.message(F.text == "📈 Статистика за 7 дней")
async def statistics_7_days(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    cursor.execute("""
    SELECT log_date, SUM(calories) as cal, SUM(protein) as prot, SUM(fat) as fat, SUM(carbs) as carb
    FROM food_log WHERE user_id = ? AND log_date >= date('now', '-7 days')
    GROUP BY log_date ORDER BY log_date DESC
    """, (user_id,))
    food_stats = cursor.fetchall()

    cursor.execute("""
    SELECT log_date, SUM(amount_ml) as water
    FROM water_log WHERE user_id = ? AND log_date >= date('now', '-7 days')
    GROUP BY log_date
    """, (user_id,))
    water_stats = {row['log_date']: row['water'] for row in cursor.fetchall()}

    if not food_stats and not water_stats:
        await message.answer("📈 У вас пока нет записей за последние 7 дней.", reply_markup=main_menu)
        return

    all_dates = sorted(list(set([row['log_date'] for row in food_stats] + list(water_stats.keys()))), reverse=True)
    food_dict = {row['log_date']: row for row in food_stats}

    text = "📊 Ваша статистика за неделю:\n\n"
    for d in all_dates:
        f_row = food_dict.get(d)
        w_amount = water_stats.get(d, 0)
        cal = f_row['cal'] if f_row else 0
        p = round(f_row['prot'], 1) if f_row and f_row['prot'] else 0
        f = round(f_row['fat'], 1) if f_row and f_row['fat'] else 0
        c = round(f_row['carb'], 1) if f_row and f_row['carb'] else 0

        text += f"📅 Дата: {d}\n"
        text += f"🔥 Калории: {cal} ккал | 💧 Вода: {w_amount} мл\n"
        text += f"🥩 Б: {p}г | 🧈 Ж: {f}г | 🍞 У: {c}г\n"
        text += "━━━━━━━━━━━━━━━━\n"

    await message.answer(text, reply_markup=main_menu)

# ─── ПЛАН ПИТАНИЯ ────────────────────────────────────────────────────────────

@dp.message(F.text == "🍽 План питания")
async def meal_plan_start(message: Message, state: FSMContext):
    await state.clear()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()

    if not user:
        await message.answer("❌ Сначала рассчитайте КБЖУ.", reply_markup=main_menu)
        return

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 На день")],
            [KeyboardButton(text="🗓 На неделю")],
            [KeyboardButton(text="📆 На месяц")]
        ],
        resize_keyboard=True
    )
    await state.set_state(MealPlanStates.waiting_period)
    await message.answer("🍽 Выберите период:", reply_markup=keyboard)


@dp.message(MealPlanStates.waiting_period)
async def meal_plan_generate(message: Message, state: FSMContext):
    periods = {
        "📅 На день": "план питания на 1 день",
        "🗓 На неделю": "план питания на 7 дней",
        "📆 На месяц": "план питания на 30 дней"
    }

    if message.text not in periods:
        await message.answer("❌ Выберите кнопку.")
        return

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()

    user_data = {
        "gender": user["gender"], "weight": user["weight"], "height": user["height"],
        "age": user["age"], "goal": user["goal"], "activity": user["activity"], "calories": user["calories"]
    }

    wait_msg = await message.answer("🤖 ИИ составляет план питания, это может занять до 30 секунд...")
    result = await ask_groq_meal_plan(user_data, periods[message.text])
    await state.clear()

    if not result:
        await wait_msg.edit_text("❌ Ошибка генерации плана. Попробуйте позже.", reply_markup=main_menu)
        return

    await wait_msg.delete()
    if len(result) > 4000:
        for i in range(0, len(result), 4000):
            await message.answer(result[i:i+4000])
    else:
        await message.answer(result)

    await message.answer("✅ План готов!", reply_markup=main_menu)

# ─── ПРОГРАММА ТРЕНИРОВОК ───────────────────────────────────────────────────

@dp.message(F.text == "🏋️ Программа тренировок")
async def workout_program(message: Message, state: FSMContext):
    await state.clear()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()

    if not user:
        await message.answer("❌ Сначала рассчитайте КБЖУ.", reply_markup=main_menu)
        return

    user_data = {
        "gender": user["gender"], "weight": user["weight"], "height": user["height"],
        "age": user["age"], "goal": user["goal"], "activity": user["activity"]
    }

    wait_msg = await message.answer("🤖 Создаю программу тренировок...")
    result = await ask_groq_workout(user_data)

    if not result:
        await wait_msg.edit_text("❌ Ошибка генерации.", reply_markup=main_menu)
        return

    await wait_msg.delete()
    if len(result) > 4000:
        for i in range(0, len(result), 4000):
            await message.answer(result[i:i+4000])
    else:
        await message.answer(result)

    await message.answer("🔥 Программа готова!", reply_markup=main_menu)

# ─── % ЖИРА И FFMI ───────────────────────────────────────────────────────────

@dp.message(F.text == "📐 % жира и FFMI")
async def body_fat_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BodyFatStates.waiting_gender)
    await message.answer(
        "📐 Расчёт % жира и FFMI\n\nИспользуется формула ВМФ США.\n"
        "Все замеры делаются сантиметровой лентой.\n\n👤 Укажите ваш пол:",
        reply_markup=gender_keyboard
    )


@dp.message(BodyFatStates.waiting_gender)
async def body_fat_gender(message: Message, state: FSMContext):
    if message.text not in ("👨 Мужчина", "👩 Женщина"):
        await message.answer("❌ Выберите кнопку ниже.")
        return
    await state.update_data(gender=message.text)
    await state.set_state(BodyFatStates.waiting_weight)
    await message.answer(
        "⚖️ Введите ваш вес (кг):",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
    )


@dp.message(BodyFatStates.waiting_weight)
async def body_fat_weight(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("↩️ Отменено.", reply_markup=main_menu)
        return
    try:
        w = float(message.text.replace(",", "."))
        if not (20 < w < 300): raise ValueError
        await state.update_data(weight=w)
        await state.set_state(BodyFatStates.waiting_height)
        await message.answer("📏 Введите ваш рост (см):")
    except ValueError:
        await message.answer("❌ Введите корректный вес (например: 75 или 75.5).")


@dp.message(BodyFatStates.waiting_height)
async def body_fat_height(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("↩️ Отменено.", reply_markup=main_menu)
        return
    try:
        h = float(message.text.replace(",", "."))
        if not (100 < h < 250): raise ValueError
        await state.update_data(height=h)
        await state.set_state(BodyFatStates.waiting_neck)
        await message.answer("📐 Введите обхват шеи (см):\n\nℹ️ Измеряйте чуть ниже кадыка, лента горизонтально.")
    except ValueError:
        await message.answer("❌ Введите корректный рост (например: 175 или 175.5).")


@dp.message(BodyFatStates.waiting_neck)
async def body_fat_neck(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("↩️ Отменено.", reply_markup=main_menu)
        return
    try:
        neck = float(message.text.replace(",", "."))
        if not (20 < neck < 60): raise ValueError
        await state.update_data(neck=neck)
        await state.set_state(BodyFatStates.waiting_waist)
        await message.answer("📐 Введите обхват талии (см):\n\nℹ️ Мужчины — на уровне пупка.\nℹ️ Женщины — в самым узком месте.")
    except ValueError:
        await message.answer("❌ Введите корректный обхват шеи (например: 38 или 38.5).")


@dp.message(BodyFatStates.waiting_waist)
async def body_fat_waist(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("↩️ Отменено.", reply_markup=main_menu)
        return
    try:
        waist = float(message.text.replace(",", "."))
        if not (40 < waist < 200): raise ValueError

        data = await state.get_data()
        if "Мужчина" in data["gender"] and waist <= data["neck"]:
            await message.answer("❌ Обхват талии должен быть больше обхвата шеи. Попробуйте еще раз.")
            return

        await state.update_data(waist=waist)
        if "Женщина" in data["gender"]:
            await state.set_state(BodyFatStates.waiting_hip)
            await message.answer("📐 Введите обхват бёдер (см):\n\nℹ️ Измеряйте в самом широком месте.")
        else:
            final_data = await state.get_data()
            await state.clear()
            await _calculate_and_send(message, final_data)
    except ValueError:
        await message.answer("❌ Введите корректный обхват талии (например: 80 или 80.5).")


@dp.message(BodyFatStates.waiting_hip)
async def body_fat_hip(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("↩️ Отменено.", reply_markup=main_menu)
        return
    try:
        hip = float(message.text.replace(",", "."))
        if not (50 < hip < 200): raise ValueError

        final_data = await state.get_data()
        if "Женщина" in final_data["gender"] and (final_data["waist"] + hip <= final_data["neck"]):
            await message.answer("❌ Сумма талии и бедер не может быть меньше обхвата шеи. Начните расчет заново.", reply_markup=main_menu)
            await state.clear()
            return

        await state.update_data(hip=hip)
        final_data = await state.get_data()
        await state.clear()
        await _calculate_and_send(message, final_data)
    except ValueError:
        await message.answer("❌ Введите корректный обхват бёдер (например: 95 или 95.5).")


async def _calculate_and_send(message: Message, data: dict):
    gender = data["gender"]
    weight = data["weight"]
    height = data["height"]
    neck   = data["neck"]
    waist  = data["waist"]
    hip    = data.get("hip", 0.0)

    try:
        bf   = calc_body_fat(gender, weight, height, neck, waist, hip)
        ffmi = calc_ffmi(weight, bf, height)
    except (ValueError, ZeroDivisionError):
        await message.answer("❌ Ошибка в расчетах. Проверьте правильность введенных замеров.", reply_markup=main_menu)
        return

    fat_mass  = round(weight * (bf / 100), 1)
    lean_mass = round(weight - fat_mass, 1)
    bf_cat   = body_fat_category(gender, bf)
    ffmi_cat = ffmi_category(ffmi)

    result_text = (
        f"📐 Результаты анализа состава тела:\n\n"
        f"👤 Пол: {gender}\n"
        f"⚖️ Вес: {weight} кг\n"
        f"📏 Рост: {height} см\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💧 % жира: {bf}%\n"
        f"   Жировая масса: {fat_mass} кг\n"
        f"   Категория: {bf_cat}\n\n"
        f"💪 Сухая масса: {lean_mass} кг\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🏋️ FFMI: {ffmi}\n"
        f"   Категория: {ffmi_cat}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"ℹ️ Натуральный генетический предел FFMI ≈ 25."
    )
    await message.answer(result_text, reply_markup=main_menu)

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────

async def main():
    print("FitBot запущен 🚀")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())