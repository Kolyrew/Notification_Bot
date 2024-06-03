import os
from datetime import date, datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.types import CallbackQuery, ContentTypes
from aiogram.utils import executor
import logging
import asyncio
from models import Notification, NotificationForm, ChooseForm
from aiogram_calendar import simple_cal_callback, SimpleCalendar
from aiogram_timepicker.panel import FullTimePicker, full_timep_callback

API_TOKEN = 'Here was my token'
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=storage)
Notification.create_table()


async def check_notification_time():
    to_notify = Notification.select().where((Notification.date == date.today()) &
                                            (Notification.time < datetime.now().strftime("%H:%M:%S")) &
                                            (Notification.is_finished == False) &
                                            (Notification.is_send == False))
    for task in to_notify:
        msg = f'Hi, you asked - I remember\n\n' \
              f'id: {task.notification_id}\n' \
              f'Task: {task.task}\n' \
              f'{"Description: " + str(task.description) if task.description else ""}\n' \
              f'Date of remind: {task.date}\n' \
              f'Regular or not: {"Yeap" if task.is_periodic == True else "Nope"}\n\n'

        if task.is_periodic and not task.is_edited:
            Notification.create(user_id=task.user_id, task=task.task, description=task.description,
                                date=task.date + timedelta(days=task.interval), time=task.time,
                                is_periodic=task.is_periodic, is_finished=False)

        task.is_send = True
        task.save()
        await bot.send_message(task.user_id, msg)

        if task.attachments:
            directory = f"attachments/{task.notification_id}"
            for filename in os.scandir(directory):
                if filename.is_file():
                    with open(filename.path, "rb") as f:
                        await bot.send_document(task.user_id, f)


async def scheduler():
    while True:
        await check_notification_time()
        await asyncio.sleep(60)  # Check every minute



async def on_startup(_):
    asyncio.create_task(scheduler())


@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    kb = types.InlineKeyboardMarkup(resize_keyboard=True)
    kb.add(types.InlineKeyboardButton(text="Add remind", callback_data="add_notification"))
    kb.add(types.InlineKeyboardButton(text="Current tasks", callback_data="check_tasks"))
    kb.add(types.InlineKeyboardButton(text="Done deals",
                                      callback_data="finished_tasks"))
    await message.answer("Welcome! I'm your personal reminder bot.\n"
                        "Here are some useful commands for you: "
                         "/start — start using bot / go to main menu\n"
                         "/help — open help", reply_markup=kb)


@dp.callback_query_handler(text="finished_tasks")
async def finished_tasks(callback: types.CallbackQuery):
    tasks = Notification.select().where((Notification.user_id == callback.message.chat.id) & (Notification.is_finished == True))
    kb = types.InlineKeyboardMarkup(resize_keyboard=True)
    if len(tasks) == 0:
        msg = "Clear -_-"
    else:
        msg = "Here what you done \n\n"
        for task in tasks:
            msg += f'id: {task.notification_id}\n' \
                   f'Task: {task.task}\n' \
                   f'{"Description: " + str(task.description) if task.description else ""}\n' \
                   f'Date of remind: {task.date}\n' \
                   f'Is it regular: {"Yeap" if task.is_periodic == True else "Nope"}\n\n'
        kb.add(types.InlineKeyboardButton(text="Make deal current", callback_data="return_notification"))
    await callback.message.answer(msg, reply_markup=kb)


@dp.callback_query_handler(text="return_notification")
async def return_notification(callback: types.CallbackQuery):
    await ChooseForm.id.set()
    await callback.message.answer("Enter id of the task that you want bring back to current.")


@dp.callback_query_handler(text="add_notification")
async def add_notification(callback: types.CallbackQuery):
    await NotificationForm.task.set()
    await callback.message.answer("What should I remind you about?")


@dp.message_handler(state=NotificationForm.task)
async def add_description(message: types.Message, state: FSMContext):
    await state.update_data(task=message.text)
    await NotificationForm.description.set()
    await message.reply("Enter description or /skip")


@dp.message_handler(state=NotificationForm.description)
async def add_date(message: types.Message, state: FSMContext):
    if message.text != '/skip':
        await state.update_data(description=message.text)
    await NotificationForm.date.set()
    await message.reply("Enter the date", reply_markup=await SimpleCalendar().start_calendar())


@dp.callback_query_handler(simple_cal_callback.filter(), state=NotificationForm.date)
async def add_time(callback_query: CallbackQuery, callback_data: dict, state: FSMContext):
    selected, date = await SimpleCalendar().process_selection(callback_query, callback_data)
    if selected:
        await callback_query.message.answer(f'You chose {date.strftime("%d/%m/%Y")}', reply_markup=None)
        await state.update_data(date=date)
        await state.set_state(NotificationForm.time)
        await callback_query.message.answer("Enter the date ", reply_markup=await FullTimePicker().start_picker())


@dp.callback_query_handler(full_timep_callback.filter(), state=NotificationForm.time)
async def is_periodic(callback_query: CallbackQuery, callback_data: dict, state: FSMContext):
    r = await FullTimePicker().process_selection(callback_query, callback_data)
    if r.selected:
        await callback_query.message.answer(
            f'You chose {r.time.strftime("%H:%M:%S")}', reply_markup=None)
        await state.update_data(time=r.time)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        kb.add("Yeap", "Nope")
        await state.set_state(NotificationForm.is_periodic)
        await callback_query.message.answer("Should it be a periodic reminder?", reply_markup=kb)


@dp.message_handler(state=NotificationForm.is_periodic)
async def add_attachments(message: types.Message, state: FSMContext):
    if message.text == 'Yeap':
        await state.update_data(is_periodic=True)
        await state.set_state(NotificationForm.interval)
        await message.reply("How often should I repeat the reminder? Enter the number of days.")
    else:
        await state.update_data(is_periodic=False)
        await state.set_state(NotificationForm.attachments)
        kb = types.InlineKeyboardMarkup(resize_keyboard=True)
        kb.add(types.InlineKeyboardButton(text="Yeap", callback_data="attach"))
        kb.add(types.InlineKeyboardButton(text="Nope", callback_data="no_attach"))
        await message.reply("Add attachments?", reply_markup=kb)


@dp.message_handler(state=NotificationForm.interval)
async def add_interval(message: types.Message, state: FSMContext):
    await state.update_data(interval=int(message.text))
    await state.set_state(NotificationForm.attachments)
    kb = types.InlineKeyboardMarkup(resize_keyboard=True)
    kb.add(types.InlineKeyboardButton(text="Yeap", callback_data="attach"))
    kb.add(types.InlineKeyboardButton(text="Nope", callback_data="no_attach"))
    await message.reply("Add attachments?", reply_markup=kb)


@dp.callback_query_handler(state=NotificationForm.attachments, text="no_attach")
async def process_no_attachments(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if 'description' not in data:
        data['description'] = None
    if 'interval' not in data:
        data['interval'] = None
    instance = Notification.create(user_id=callback.message.chat.id, task=data['task'], description=data['description'],
                                   date=data['date'], time=data['time'], is_periodic=data['is_periodic'],
                                   interval=data['interval'], is_finished=False)
    await state.finish()
    await callback.message.answer("Reminder set successfully")


@dp.callback_query_handler(state=NotificationForm.attachments, text="attach")
async def process_attachments(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Send the attachment as the following message. You must send one at a time.")


@dp.message_handler(content_types=ContentTypes.ANY, state=NotificationForm.attachments)
async def process_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if message.text == "/done":
        await state.finish()
        await message.answer("Reminder added. To return to the main menu, enter the command /start")
    if 'notification_id' not in data:
        if 'description' not in data:
            data['description'] = None
        if 'interval' not in data:
            data['interval'] = None
        instance = Notification.create(user_id=message.chat.id, task=data['task'], description=data['description'],
                            date=data['date'], time=data['time'], is_periodic=data['is_periodic'],
                            interval=data['interval'], attachments=True, is_finished=False)
        await state.update_data(notification_id=instance.notification_id)
    else:
        instance = Notification.get_by_id(data['notification_id'])
    if (document := message.document) and instance:
        if not os.path.isdir(f"attachments/{instance.notification_id}"):
            os.makedirs(f"attachments/{instance.notification_id}")
        await document.download(destination_file=f'attachments/{instance.notification_id}/{document.file_name}')
        await message.answer("The attachment has been saved. You can send another one. Or set /done")


@dp.callback_query_handler(text="check_tasks")
async def check_tasks(callback: types.CallbackQuery):
    tasks = Notification.select().where((Notification.user_id == callback.message.chat.id) & (Notification.is_finished == False))
    if len(tasks) == 0:
        msg = "You have not ane deals today"
        kb = types.InlineKeyboardMarkup(resize_keyboard=True)
    else:
        msg = "Here is you should do: \n\n"
        kb = types.InlineKeyboardMarkup(resize_keyboard=True)
        kb.add(types.InlineKeyboardButton(text="Select reminder", callback_data="choose_notification"))
        for task in tasks:
            msg += f'id: {task.notification_id}\n' \
                   f'Deal: {task.task}\n' \
                   f'{"Description: " + str(task.description) if task.description else ""}\n' \
                   f'Date: {task.date}\n' \
                   f'Time: {task.time}\n' \
                   f'Is it regular: {"Yeap" if task.is_periodic == True else "Nope"}\n\n'
    await callback.message.answer(msg, reply_markup=kb)


@dp.callback_query_handler(text="choose_notification")
async def choose_notification(callback: types.CallbackQuery):
    await ChooseForm.id.set()
    await callback.message.answer("Enter reminder ID to change: ")


@dp.message_handler(lambda message: message.text.isdigit(), state=ChooseForm.id)
async def process_notification_id(message: types.Message, state: FSMContext):
    try:
        instance = Notification.get_by_id(int(message.text))
        if instance.user_id != message.chat.id:
            await message.reply("Error, there is no such reminder, try again")
        else:
            if instance.is_finished:
                instance.is_finished = False
                instance.save()
                await state.update_data(id=int(message.text))
                await ChooseForm.date.set()
                await message.answer(f"Enter new date: ", reply_markup=await SimpleCalendar().start_calendar())
            else:
                await state.update_data(id=int(message.text))
                kb = types.InlineKeyboardMarkup(resize_keyboard=True)
                kb.add(types.InlineKeyboardButton(text="Delete remind", callback_data="delete_notification"))
                kb.add(types.InlineKeyboardButton(text="Edit reminder", callback_data="edit_notification"))
                kb.add(types.InlineKeyboardButton(text="Mark done", callback_data="finish_notification"))
                await message.answer(f"Selected reminder: {message.text}", reply_markup=kb)
    except:
        await message.reply("Error, there is no such reminder, try again")


@dp.callback_query_handler(text="delete_notification", state=ChooseForm)
async def delete_notification(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    Notification.delete_by_id(data['id'])
    await state.finish()
    await callback.message.answer(f"Remind with id={data['id']} deleted. To return to the main menu, enter the command /start")


@dp.callback_query_handler(text="finish_notification", state=ChooseForm)
async def finish_notification(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    instance = Notification.get_by_id(data['id'])
    instance.is_finished = True
    instance.save()
    await state.finish()
    await callback.message.answer(f"Remind with id={data['id']} marked completed. To return to the main menu, enter the command /start")


@dp.callback_query_handler(text="edit_notification", state=ChooseForm)
async def edit_notification(callback: types.CallbackQuery, state: FSMContext):
    if Notification.get_by_id((await state.get_data())['id']).is_periodic:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
        kb.add("Current", "Entirely")
        await state.set_state(ChooseForm.current)
        await callback.message.answer(f"Are we changing the current deal or are we changing the regular business entirely?", reply_markup=kb)
    else:
        kb = types.InlineKeyboardMarkup(resize_keyboard=True)
        kb.add(types.InlineKeyboardButton(text="Edit date", callback_data="edit_date"))
        kb.add(types.InlineKeyboardButton(text="Edit time", callback_data="edit_time"))
        kb.add(types.InlineKeyboardButton(text="Edit description", callback_data="edit_task"))
        kb.add(types.InlineKeyboardButton(text="Replace files", callback_data="new_files"))
        await callback.message.answer(f"What do you want to edit? ", reply_markup=kb)


@dp.message_handler(state=ChooseForm.current)
async def current_or_not(message: types.Message, state: FSMContext):
    kb = types.InlineKeyboardMarkup(resize_keyboard=True)
    if message.text == 'Entirely':
        await state.update_data(current=False)
    else:
        await state.update_data(current=True)
    kb.add(types.InlineKeyboardButton(text="Edit date", callback_data="edit_date"))
    kb.add(types.InlineKeyboardButton(text="Edit time", callback_data="edit_time"))
    kb.add(types.InlineKeyboardButton(text="Edit description", callback_data="edit_task"))
    kb.add(types.InlineKeyboardButton(text="Replace files", callback_data="new_files"))
    await message.answer(f"What do you want to edit? ", reply_markup=kb)


@dp.callback_query_handler(text="new_files", state=ChooseForm)
async def new_files(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    instance = Notification.get_by_id(data['id'])
    try:
        if data['current']:
            new_instance = Notification.create(user_id=instance.user_id, task=instance.task, description=instance.description,
                            date=instance.date + timedelta(days=instance.interval), time=instance.time,
                            is_periodic=instance.is_periodic, is_finished=False)
            os.rename(f"attachments/{instance.notification_id}", f"attachments/{new_instance.notification_id}")
    except:
        pass
    if not os.path.isdir(f"attachments/{instance.notification_id}"):
        os.makedirs(f"attachments/{instance.notification_id}")
    else:
        for f in os.listdir(f"attachments/{instance.notification_id}"):
            os.remove(os.path.join(f"attachments/{instance.notification_id}", f))
    await ChooseForm.attachments.set()
    await callback.message.answer("Send the attachment as the following message. You must send one at a time.")


@dp.message_handler(content_types=ContentTypes.ANY, state=ChooseForm.attachments)
async def process_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if message.text == "/done":
        await state.finish()
        await message.answer("Files have been changed. To return to the main menu, enter the command /start")
    instance = Notification.get_by_id(data['id'])
    if (document := message.document) and instance:
        if not os.path.isdir(f"attachments/{instance.notification_id}"):
            os.makedirs(f"attachments/{instance.notification_id}")
        await document.download(destination_file=f'attachments/{instance.notification_id}/{document.file_name}')
        await message.answer("The attachment has been saved. You can send another one. Or set /done")



@dp.callback_query_handler(text="edit_task", state=ChooseForm)
async def edit_task_input(callback: types.CallbackQuery, state: FSMContext):
    await ChooseForm.description.set()
    await callback.message.answer(f"Enter new decription: ")


@dp.message_handler(state=ChooseForm.description)
async def edit_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    data = await state.get_data()
    instance = Notification.get_by_id(data['id'])
    try:
        if data['current']:
            Notification.create(user_id=instance.user_id, task=instance.task, description=instance.description,
                            date=instance.date + timedelta(days=instance.interval), time=instance.time,
                            is_periodic=instance.is_periodic, is_finished=False)
    except:
        pass
    instance.description = data['description']
    instance.is_edited = True
    instance.save()
    await state.finish()
    await message.answer(f'Description has been changed. To return to the main menu, enter the command /start', reply_markup=None)



@dp.callback_query_handler(text="edit_date", state=ChooseForm)
async def edit_date_input(callback: types.CallbackQuery, state: FSMContext):
    await ChooseForm.date.set()
    await callback.message.answer(f"Enter new date: ", reply_markup=await SimpleCalendar().start_calendar())


@dp.callback_query_handler(simple_cal_callback.filter(), state=ChooseForm.date)
async def edit_date(callback_query: CallbackQuery, callback_data: dict, state: FSMContext):
    selected, date = await SimpleCalendar().process_selection(callback_query, callback_data)
    if selected:
        await callback_query.message.answer(f'You chose {date.strftime("%d/%m/%Y")}. The date has been changed. To return to the main menu, enter the command /start', reply_markup=None)
        await state.update_data(date=date)
        data = await state.get_data()
        print(data)
        instance = Notification.get_by_id(data['id'])
        try:
            if data['current']:
                Notification.create(user_id=instance.user_id, task=instance.task, description=instance.description,
                                date=instance.date + timedelta(days=instance.interval), time=instance.time,
                                is_periodic=instance.is_periodic, is_finished=False)
        except:
            pass
        instance.date = data['date']
        instance.is_edited = True
        instance.save()
        await state.finish()


@dp.callback_query_handler(text="edit_time", state=ChooseForm)
async def edit_time_input(callback: types.CallbackQuery, state: FSMContext):
    await ChooseForm.time.set()
    await callback.message.answer(f"Enter new time: ", reply_markup=await FullTimePicker().start_picker())


@dp.callback_query_handler(full_timep_callback.filter(), state=ChooseForm.time)
async def edit_time(callback_query: CallbackQuery, callback_data: dict, state: FSMContext):
    r = await FullTimePicker().process_selection(callback_query, callback_data)
    if r.selected:
        await callback_query.message.answer(
            f'You chose {r.time.strftime("%H:%M:%S")}. The time has been changed. To return to the main menu, enter the command /start', reply_markup=None)
        await state.update_data(time=r.time)
        data = await state.get_data()
        print(data)
        instance = Notification.get_by_id(data['id'])
        try:
            if data['current']:
                Notification.create(user_id=instance.user_id, task=instance.task, description=instance.description,
                                date=instance.date + timedelta(days=instance.interval), time=instance.time,
                                is_periodic=instance.is_periodic, is_finished=False)
        except:
            pass
        instance.time = data['time']
        instance.is_edited = True
        instance.save()
        await state.finish()


@dp.message_handler(commands=['help'])
async def help(message: types.Message):
    await message.answer("I can:\n"
                         "I can create a task using the 'Add reminder' button and notify about tasks at the right time\n"
                         "To return to the main menu, enter the command /start")


@dp.message_handler()
async def unknown_message(message: types.Message):
    await message.answer("I dont understand you. Restart by command /start(\n")


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(scheduler())
    executor.start_polling(dp, skip_updates=True)