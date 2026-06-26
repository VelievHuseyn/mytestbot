import asyncio
import sqlite3
import random
import re
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

API_TOKEN = '8931566799:AAGUj3UIPJvurFx71Bfb_KOhaeZR5xyEghc'

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class QuizStates(StatesGroup):
    waiting_for_range = State()
    choosing_count = State()
    answering = State()

def get_questions_from_range(start_id, end_id, count):
    conn = sqlite3.connect('quiz.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, question_text, options, correct_option 
        FROM questions 
        WHERE id >= ? AND id <= ? 
        ORDER BY RANDOM() 
        LIMIT ?
    """, (start_id, end_id, count))
    rows = cursor.fetchall()
    conn.close()
    
    questions = []
    for row in rows:
        questions.append({
            'id': row[0],
            'text': row[1],
            'options': row[2].split('||'),
            'correct': row[3]
        })
    return questions

def build_quiz_keyboard(total, current_idx, user_answers):
    builder = InlineKeyboardBuilder()
    row_buttons = []
    for i in range(total):
        status_icon = "✅" if i in user_answers and user_answers[i]['is_correct'] else "❌" if i in user_answers else "🔹"
        if i == current_idx: status_icon = "📍"
        row_buttons.append(types.InlineKeyboardButton(text=f"{status_icon} {i+1}", callback_data=f"go_to_{i}"))
    
    for j in range(0, len(row_buttons), 5):
        builder.row(*row_buttons[j:j+5])
    
    nav_buttons = []
    if current_idx > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"go_to_{current_idx-1}"))
    if current_idx < total - 1:
        nav_buttons.append(types.InlineKeyboardButton(text="Вперед ➡️", callback_data=f"go_to_{current_idx+1}"))
    else:
        nav_buttons.append(types.InlineKeyboardButton(text="🏁 Завершить", callback_data="finish_quiz"))
        
    builder.row(*nav_buttons)
    return builder.as_markup()

def build_options_keyboard(options, current_idx):
    builder = InlineKeyboardBuilder()
    for idx, option in enumerate(options):
        short_text = option if len(option) < 34 else option[:31] + "..."
        builder.row(types.InlineKeyboardButton(text=short_text, callback_data=f"answer_{current_idx}_{idx}"))
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*), MIN(id), MAX(id) FROM questions")
    total_in_db, min_id, max_id = c.fetchone()
    conn.close()

    text = f"👋 Привет!\n📊 Всего в базе доступно **{total_in_db}** вопросов.\n\n✏️ Введи диапазон (например: `1-50`) или напиши `все`:"
    await message.answer(text, parse_mode="Markdown")
    await state.set_state(QuizStates.waiting_for_range)

@dp.message(QuizStates.waiting_for_range)
async def process_range(message: types.Message, state: FSMContext):
    user_text = message.text.strip().lower()
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    c.execute("SELECT MIN(id), MAX(id) FROM questions")
    min_id, max_id = c.fetchone()
    conn.close()
    
    if user_text == 'все':
        start_id, end_id = min_id, max_id
    else:
        match = re.match(r'^(\d+)\s*-\s*(\d+)$', user_text)
        if not match:
            await message.answer("⚠️ Напиши диапазон цифрами через дефис, например: `1-50`:")
            return
        start_id, end_id = int(match.group(1)), int(match.group(2))
        if start_id > end_id: start_id, end_id = end_id, start_id
        if start_id < min_id or end_id > max_id:
            await message.answer(f"⚠️ Вопросы должны быть от {min_id} до {max_id}:")
            return

    available_count = end_id - start_id + 1
    await state.update_data(start_id=start_id, end_id=end_id, available_count=available_count)
    
    builder = InlineKeyboardBuilder()
    for c in [5, 10, 20, 50]:
        if c <= available_count:
            builder.add(types.InlineKeyboardButton(text=str(c), callback_data=f"count_{c}"))
    if available_count not in [5, 10, 20, 50]:
        builder.add(types.InlineKeyboardButton(text=f"Все ({available_count})", callback_data=f"count_{available_count}"))
    builder.adjust(4)
    
    await message.answer(f"🎯 Диапазон: {start_id}—{end_id}. Сколько вопросов взять?", reply_markup=builder.as_markup())
    await state.set_state(QuizStates.choosing_count)

@dp.callback_query(QuizStates.choosing_count, F.data.startswith("count_"))
async def count_chosen(callback: types.CallbackQuery, state: FSMContext):
    count = int(callback.data.split("_")[1])
    data = await state.get_data()
    questions = get_questions_from_range(data['start_id'], data['end_id'], count)
    await state.update_data(questions=questions, current_idx=0, user_answers={}, total=len(questions))
    await callback.answer()
    await show_question(callback.message, state, current_idx=0)

async def show_question(message: types.Message, state: FSMContext, current_idx: int):
    data = await state.get_data()
    questions, user_answers, total = data['questions'], data['user_answers'], data['total']
    q = questions[current_idx]
    
    text = f"📍 *Оригинальный №: {q['id']}*\n📝 *Вопрос {current_idx + 1} из {total}:*\n\n{q['text']}\n\n*Варианты:*\n"
    for i, opt in enumerate(q['options']): text += f"{i+1}) {opt}\n"
        
    if current_idx in user_answers:
        ans = user_answers[current_idx]
        text += f"\n-------------------------\nВы выбрали вариант №{ans['user_chosen_idx'] + 1}\n"
        text += "🔴 *Результат:* Правильно! ✅" if ans['is_correct'] else f"🔴 *Результат:* Неправильно! ❌\nПравильный: *{q['options'][q['correct']]}*"
        await message.edit_text(text, parse_mode="Markdown", reply_markup=build_quiz_keyboard(total, current_idx, user_answers))
    else:
        await state.set_state(QuizStates.answering)
        await message.edit_text(text, parse_mode="Markdown", reply_markup=build_options_keyboard(q['options'], current_idx))

@dp.callback_query(QuizStates.answering, F.data.startswith("answer_"))
async def handle_answer(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    _, q_idx, opt_idx = callback.data.split("_")
    q_idx, opt_idx = int(q_idx), int(opt_idx)
    questions, user_answers = data['questions'], data['user_answers']
    
    q = questions[q_idx]
    user_answers[q_idx] = {'user_chosen_idx': opt_idx, 'user_chosen_text': q['options'][opt_idx], 'is_correct': (opt_idx == q['correct'])}
    await state.update_data(user_answers=user_answers)
    await callback.answer("Принято!")
    await show_question(callback.message, state, current_idx=q_idx)

@dp.callback_query(F.data.startswith("go_to_"))
async def go_to_question(callback: types.CallbackQuery, state: FSMContext):
    target_idx = int(callback.data.split("_")[2])
    await state.update_data(current_idx=target_idx)
    await callback.answer()
    await show_question(callback.message, state, current_idx=target_idx)

@dp.callback_query(F.data == "finish_quiz")
async def finish_quiz(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    questions, user_answers, total = data['questions'], data['user_answers'], data['total']
    correct_count = sum(1 for ans in user_answers.values() if ans['is_correct'])
    
    result_text = f"🏁 *Тест завершен!*\n\n✅ Правильно: {correct_count} из {total}\n"
    errors_text = ""
    for i, q in enumerate(questions):
        if i not in user_answers: errors_text += f"\n• Пропущен вопрос {i+1} (В базе №{q['id']})"
        elif not user_answers[i]['is_correct']:
            errors_text += f"\n❌ *Ошибка в №{i+1}:* {q['text']}\n↳ Правильный: *{q['options'][q['correct']]}*\n"
            
    await callback.message.edit_text(result_text + errors_text, parse_mode="Markdown")
    await state.clear()
    await callback.answer()

# --- ФИШКА ДЛЯ СЕРВЕРА ---
async def handle_web(request):
    return web.Response(text="Bot is running!")

async def main():
    # Запускаем фоновое прослушивание сети для сервера
    app = web.Application()
    app.router.add_get("/", handle_web)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    asyncio.create_task(site.start())
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())