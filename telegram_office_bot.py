import os
import asyncio
from typing import Dict, Set, List, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand

API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    raise RuntimeError("API_TOKEN environment variable is not set")

bot = Bot(token=API_TOKEN)
dp  = Dispatcher()

SEAT_ROWS = [
    ["A1","B1","C1","D1"],
    ["A2","B2","C2","D2"],
    ["A3","B3","C3","D3"],
]

reserved_seats:   Dict[int, Dict[str,int]] = {}
marketing_seats:  Dict[int, Set[str]]      = {}
occupied:         Dict[int, Dict[str,int]] = {}
user_seat:        Dict[int, Dict[int,str]] = {}
chart_message:    Dict[int, int]           = {}

EMOJI = {
    "free":      "🌕",
    "occupied":  "🌑",
    "reserved":  "🌓",
    "marketing": "🤍",
    "plant":     "🌿",
}

def init_chat(cid: int):
    reserved_seats.setdefault(cid, {})
    marketing_seats.setdefault(cid, set())
    occupied.setdefault(cid, {})
    user_seat.setdefault(cid, {})

async def build_chart_html(cid: int) -> str:
    init_chat(cid)
    status: Dict[str,str] = {}
    for row in SEAT_ROWS:
        for s in row:
            if s in marketing_seats[cid]:
                status[s] = EMOJI["marketing"]
            elif s in occupied[cid]:
                status[s] = EMOJI["occupied"]
            elif s in reserved_seats[cid]:
                status[s] = EMOJI["reserved"]
            else:
                status[s] = EMOJI["free"]

    lines: List[str] = ["┌───────── Окно ──────────┐"]
    for row in SEAT_ROWS:
        left  = "".join(f"[<i>{s}</i>{status[s]}]" for s in row[:2])
        right = "".join(f"[<i>{s}</i>{status[s]}]" for s in row[2:])
        lines.append(f"{left}    {right}")
    plants = EMOJI["plant"]*6 + "    " + EMOJI["plant"]*6
    lines.append(plants)
    lines.append("└───────── Проход ────────┘")

    out: List[str] = ["<pre>"] + lines + ["</pre>\n", "В офисе сейчас:"]
    for uid, seat in user_seat[cid].items():
        member = await bot.get_chat_member(cid, uid)
        out.append(f"{member.user.full_name} [{seat}]")
    out.append(f"\nВсего людей в офисе: {len(user_seat[cid])}\n")
    out += [
        "🌕 — свободно",
        "🌑 — занято",
        "🌓 — закреплено",
        "🤍 — маркетинг (недоступно)",
    ]
    return "\n".join(out)

def seat_keyboard(cid: int) -> InlineKeyboardMarkup:
    """Кнопки свободных мест + 'Я ушёл', пока в офисе есть хотя бы один."""
    init_chat(cid)
    kb: List[List[InlineKeyboardButton]] = []
    for row in SEAT_ROWS:
        btns: List[InlineKeyboardButton] = []
        for s in row:
            if s in marketing_seats[cid] or s in occupied[cid]:
                continue
            btns.append(InlineKeyboardButton(text=s, callback_data=f"book|{s}"))
        if btns:
            kb.append(btns)
    # показываем «Я ушёл», пока в офисе хоть один человек
    if user_seat[cid]:
        kb.append([InlineKeyboardButton(text="Я ушёл", callback_data="leave")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command(commands=["attendance"]))
async def cmd_attendance(message: types.Message):
    cid = message.chat.id
    init_chat(cid)
    marketing_seats[cid] = {"A2","A3"}
    occupied[cid].clear()
    user_seat[cid].clear()
    reserved_seats[cid].clear()

    chart = await build_chart_html(cid)
    msg   = await bot.send_message(
        chat_id=cid,
        text=chart,
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid)
    )
    chart_message[cid] = msg.message_id

# ... остальные хендлеры "/reserve", book_seat, allow_cb, deny_cb, без изменений ...

@dp.callback_query(lambda c: c.data == "leave")
async def leave_cb(cb: types.CallbackQuery):
    cid, uid = cb.message.chat.id, cb.from_user.id
    init_chat(cid)
    if uid not in user_seat[cid]:
        # если пользователь и так не в офисе
        return await cb.answer("Вы и так не в офисе.", show_alert=True)

    # убираем только этого пользователя
    prev = user_seat[cid].pop(uid)
    occupied[cid].pop(prev, None)

    # перерисовываем схему
    chart = await build_chart_html(cid)
    await bot.edit_message_text(
        text=chart,
        chat_id=cid,
        message_id=chart_message[cid],
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid)
    )
    await cb.answer("Вы вышли из офиса.")

async def on_startup():
    await bot.set_my_commands([
        BotCommand("attendance", "Показать рассадку"),
        BotCommand("reserve",    "Закрепить место"),
    ])

if __name__ == "__main__":
    dp.run_polling(bot, skip_updates=True, on_startup=on_startup)
