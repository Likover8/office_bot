from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)
import asyncio
from typing import Dict, Set, List, Optional

API_TOKEN = '8087657192:AAGS85PcbVynIAJN9h12Ic4Pd8YspnWzaxM'
bot = Bot(token=API_TOKEN)
dp  = Dispatcher()

# План кабинета: 3 ряда по 4 места (A–D)
SEAT_ROWS = [
    ["A1","B1","C1","D1"],
    ["A2","B2","C2","D2"],
    ["A3","B3","C3","D3"],
]

# Хранилища по chat_id
reserved_seats:   Dict[int, Dict[str,int]] = {}  # закреплённые места {seat: owner_id}
marketing_seats:  Dict[int, Set[str]]      = {}  # маркетинговые места
occupied:         Dict[int, Dict[str,int]] = {}  # текущие брони {seat: user_id}
user_seat:        Dict[int, Dict[int,str]] = {}  # где сидит каждый пользователь {user_id: seat}
chart_message:    Dict[int, int]           = {}  # ID сообщения-диаграммы

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

    lines: List[str] = ["┌────────── Окно ───────────┐"]
    for row in SEAT_ROWS:
        left  = "".join(f"[<i>{s}</i>{status[s]}]" for s in row[:2])
        right = "".join(f"[<i>{s}</i>{status[s]}]" for s in row[2:])
        lines.append(f"{left}    {right}")
    plants = EMOJI["plant"]*6 + "   " + EMOJI["plant"]*6
    lines.append(plants)
    lines.append("└────────── Проход ─────────┘")

    out: List[str] = ["<pre>"] + lines + ["</pre>\n", "В офисе сейчас:"]
    for uid, seat in list(user_seat[cid].items()):
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

def seat_keyboard(cid: int, uid: Optional[int]) -> InlineKeyboardMarkup:
    init_chat(cid)
    rows: List[List[InlineKeyboardButton]] = []
    for row in SEAT_ROWS:
        btns: List[InlineKeyboardButton] = []
        for s in row:
            if s in marketing_seats[cid] or s in occupied[cid]:
                continue
            btns.append(InlineKeyboardButton(text=s, callback_data=f"book|{s}"))
        if btns:
            rows.append(btns)
    if uid is not None and uid in user_seat[cid]:
        rows.append([InlineKeyboardButton(text="Я ушёл", callback_data="leave")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

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
        reply_markup=seat_keyboard(cid, message.from_user.id)
    )
    chart_message[cid] = msg.message_id

@dp.message(Command(commands=["reserve"]))
async def cmd_reserve(message: types.Message):
    cid = message.chat.id
    init_chat(cid)
    if not message.reply_to_message:
        return await message.reply(
            "Чтобы закрепить место, отправьте `/reserve <место>` в ответ на сообщение.",
            parse_mode="Markdown"
        )
    parts = message.text.split()
    if len(parts) != 2:
        return await message.reply("Неверный формат. `/reserve <место>`", parse_mode="Markdown")
    seat = parts[1].upper()
    if seat not in [s for row in SEAT_ROWS for s in row]:
        return await message.reply(f"Места `{seat}` не существует.", parse_mode="Markdown")
    if seat in marketing_seats[cid]:
        return await message.reply("Нельзя закрепить маркетинговое место.", parse_mode="Markdown")
    if seat in occupied[cid]:
        return await message.reply("Сначала освободите это место.", parse_mode="Markdown")

    owner = message.reply_to_message.from_user
    reserved_seats[cid][seat] = owner.id

    chart = await build_chart_html(cid)
    await bot.edit_message_text(
        chat_id=cid,
        message_id=chart_message[cid],
        text=chart,
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid, message.from_user.id)
    )
    await message.reply(
        f"Место <i>{seat}</i> закреплено за {owner.full_name}.",
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data and c.data.startswith("book|"))
async def book_seat(callback: types.CallbackQuery):
    cid, uid = callback.message.chat.id, callback.from_user.id
    init_chat(cid)
    _, seat = callback.data.split("|")

    if seat in marketing_seats[cid]:
        return await callback.answer("Маркетинговое место недоступно.", show_alert=True)

    owner = reserved_seats[cid].get(seat)
    if owner and owner != uid:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Разрешить", callback_data=f"allow|{seat}|{uid}"),
            InlineKeyboardButton(text="Отказать",  callback_data=f"deny|{seat}|{uid}")
        ]])
        owner_name = (await bot.get_chat_member(cid, owner)).user.full_name
        notif = await bot.send_message(
            chat_id=cid,
            text=(
                f"<a href='tg://user?id={owner}'>{owner_name}</a>, "
                f"место {seat} хочет занять {callback.from_user.full_name}. Разрешить?"
            ),
            parse_mode="HTML",
            reply_markup=kb
        )
        asyncio.create_task(_auto_delete(cid, notif.message_id, 300))
        return await callback.answer()

    if seat in occupied[cid]:
        return await callback.answer("Уже занято.", show_alert=True)

    prev = user_seat[cid].pop(uid, None)
    if prev:
        occupied[cid].pop(prev, None)
    occupied[cid][seat] = uid
    user_seat[cid][uid] = seat

    chart = await build_chart_html(cid)
    await bot.edit_message_text(
        text=chart,
        chat_id=cid,
        message_id=chart_message[cid],
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid, uid)
    )
    await callback.answer("Место забронировано.")

@dp.callback_query(lambda c: c.data and c.data.startswith("allow|"))
async def allow_callback(callback: types.CallbackQuery):
    cid = callback.message.chat.id
    init_chat(cid)
    _, seat, req = callback.data.split("|")
    owner     = callback.from_user.id
    requester = int(req)

    # Только владелец может
    if reserved_seats[cid].get(seat) != owner:
        return await callback.answer("Только владелец может разрешить.", show_alert=True)

    # Удаляем запрос-уведомление
    await bot.delete_message(chat_id=cid, message_id=callback.message.message_id)

    # Если место всё ещё свободно
    if seat in occupied[cid]:
        return await callback.answer("Уже занято.", show_alert=True)

    prev = user_seat[cid].pop(requester, None)
    if prev:
        occupied[cid].pop(prev, None)
    occupied[cid][seat]       = requester
    user_seat[cid][requester] = seat

    chart = await build_chart_html(cid)
    await bot.edit_message_text(
        text=chart,
        chat_id=cid,
        message_id=chart_message[cid],
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid, requester)
    )

    member = await bot.get_chat_member(cid, requester)
    mention = f"<a href='tg://user?id={requester}'>{member.user.full_name}</a>"
    notif = await bot.send_message(
        chat_id=cid,
        text=f"{mention}, вам разрешили занять место {seat}.",
        parse_mode="HTML"
    )
    asyncio.create_task(_auto_delete(cid, notif.message_id, 300))
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("deny|"))
async def deny_callback(callback: types.CallbackQuery):
    cid = callback.message.chat.id
    init_chat(cid)
    _, seat, req = callback.data.split("|")
    owner = callback.from_user.id
    requester = int(req)

    # Только владелец может
    if reserved_seats[cid].get(seat) != owner:
        return await callback.answer("Только владелец может отказать.", show_alert=True)

    # Удаляем запрос-уведомление
    await bot.delete_message(chat_id=cid, message_id=callback.message.message_id)

    member = await bot.get_chat_member(cid, requester)
    mention = f"<a href='tg://user?id={requester}'>{member.user.full_name}</a>"
    notif = await bot.send_message(
        chat_id=cid,
        text=f"{mention}, к сожалению, владелец отметил место недоступным в данный момент.",
        parse_mode="HTML"
    )
    asyncio.create_task(_auto_delete(cid, notif.message_id, 300))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "leave")
async def leave(callback: types.CallbackQuery):
    cid, uid = callback.message.chat.id, callback.from_user.id
    init_chat(cid)
    prev = user_seat[cid].pop(uid, None)
    if prev:
        occupied[cid].pop(prev, None)

    chart = await build_chart_html(cid)
    await bot.edit_message_text(
        text=chart,
        chat_id=cid,
        message_id=chart_message[cid],
        parse_mode="HTML",
        reply_markup=seat_keyboard(cid, uid)
    )
    await callback.answer("Место освобождено.")

async def _auto_delete(chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except:
        pass

async def on_startup():
    await bot.set_my_commands([
        BotCommand("attendance", "Показать рассадку"),
        BotCommand("reserve",    "Закрепить место (reply only)"),
    ])

if __name__ == "__main__":
    dp.run_polling(bot, skip_updates=True, on_startup=on_startup)