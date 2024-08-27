from telebot import TeleBot, apihelper
import json
from telebot.types import *
import requests
from database import User
from keys import ADMIN, BOT_TOKEN, HOST


apihelper.ENABLE_MIDDLEWARE = True
bot = TeleBot(BOT_TOKEN)


def get_db():
    return json.loads(open('data.json', 'rb').read())

def save_db(data):
    with open('data.json', 'wb') as f:
        f.write(json.dumps(data).encode())


def make_request(method, path, token, market, body=None, params=None):
    url = f'http://{HOST}/{market}/{path}'
    resp = requests.request(method, url, json=body, params=params, headers={'Authorization': 'Bearer '+token})
    if resp.status_code // 100 == 2:
        return resp.json()
    else:
        return resp.text


def check_sender(bot, message, *args):
    data = get_db()
    if str(message.from_user.id) in data['blocks']:
        return False
    else:
        return True

bot.add_middleware_handler(check_sender, ['message'])


def list_stores(data):
    markup = InlineKeyboardMarkup()
    for prefix, tag in data['stores'].items():
        markup.add(InlineKeyboardButton(text=tag, callback_data=f"get_store:browse:{prefix}"))
    return markup

@bot.message_handler(commands=['start'])
def start(message: Message):
    chat_id = str(message.chat.id)
    data = get_db()
    user_token = data['users'].get(chat_id)

    if user_token:
        markup = list_stores(data)
        bot.send_message(chat_id, 'Выберите магазин:', reply_markup=markup)

    else:
        bot.send_message(chat_id, 'Привет! Это бот для управления парсерами.\n'
                         'Если у вас уже есть доступ, отправьте ваш токен.\n'
                         'Или введи своё имя и отдел для получения доступа:')
        bot.register_next_step_handler(message, process_get_access_step)


def process_get_access_step(message: Message):
    chat_id = message.chat.id

    data = get_db()
    if message.text.strip() in data['users'].values():
        data['users'][str(chat_id)] = message.text.strip()
        save_db(data)
        bot.send_message(chat_id, 'Токен активирован. Введите /start для начала обзора.')
        return

    markup = InlineKeyboardMarkup()
    for variant in ['allow', 'deny', 'block']:
        markup.add(InlineKeyboardButton(text=variant.capitalize(), callback_data=f"access:{variant}:{chat_id}"))

    bot.send_message(ADMIN, f'Request for access: [{message.from_user.username}] > {message.text}', reply_markup=markup)
    bot.send_message(chat_id=chat_id, text='Запрос отправлен, ждите подтверждение...')


def process_add_link_step(message, market):
    chat_id = str(message.chat.id)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text='Завершить!', callback_data=f"get_store:browse:{market}"))
    data = get_db()
    token = data['users'][chat_id]
    resp = make_request('POST', 'parsing-items', token, market, {'link': message.text})
    if isinstance(resp, str):
        bot.send_message(chat_id, resp, reply_markup=markup)
    else:
        bot.send_message(chat_id, 'Ссылка добавлена! Можете продолжать добавить...', reply_markup=markup)
        bot.register_next_step_handler(message, process_add_link_step, market)

@bot.callback_query_handler(lambda x: True)
def callback_passport(call: CallbackQuery):
    chat_id = str(call.from_user.id)
    method, key, value = call.data.split(":")
    data = get_db()
    token = data['users'][chat_id]
    print(call.data)

    if method == 'access':
        if key == 'allow':
            user = User.create(name=call.message.text.rsplit('> ')[-1])
            bot.send_message(value, 'Вам открыт доступ к данным. \n'
                             f'Вот ваш токен: `{user.token}`\n'
                             '(Никому не передайте!)\n'
                             'Введите /start для начала обзора.')

        elif key == 'deny':
            bot.send_message(value, 'Запрос на доступ отклонен.')

        elif key == 'block':
            bot.send_message(value, 'Запрос на доступ заблокирован!')
            data['blocks'].append(value)
            save_db(data)

        bot.answer_callback_query(call.id, 'Done')
        bot.delete_message(chat_id, call.message.id)

    elif method == 'get_store':
        if key == 'browse':
            markup = InlineKeyboardMarkup()
            resp = make_request('GET', 'parsing-items', token, value)
            print([resp])
            for num, item in enumerate(resp):
                markup.add(
                    InlineKeyboardButton(text=item['link'], callback_data=f"get_store:send:{num}"),
                    InlineKeyboardButton(text='❌', callback_data=f"get_store:delete:{value}_{num}"),
                )
            markup.add(InlineKeyboardButton(text='Добавить', callback_data=f"get_store:add:{value}"))
            markup.add(InlineKeyboardButton('Поиск товара', switch_inline_query_current_chat=f'Поиск на [{value}]: '))
            markup.add(InlineKeyboardButton(text='<= Назад', callback_data=f"get_store:list:{value}"))
            bot.edit_message_text('Список парсируемых страниц:\n(Чтобы увеличить ссылку, нажмите на него)', chat_id, call.message.id, reply_markup=markup)

        elif key == 'list':
            markup = list_stores(data)
            bot.edit_message_text('Выберите магазин:', chat_id, call.message.id, reply_markup=markup)

        elif key == 'send':
            bot.answer_callback_query(call.id, call.message.reply_markup.keyboard[int(value)][0].text, True)

        elif key == 'delete':
            value, num = value.rsplit('_', 1)
            body = {'link': call.message.reply_markup.keyboard[int(num)][0].text}
            resp = make_request('DELETE', 'parsing-items', token, value, body)
            bot.answer_callback_query(call.id, resp['message'])
            if resp['success']:
                call.message.reply_markup.keyboard.pop(int(num))
                for num, keyboard in enumerate(call.message.reply_markup.keyboard):
                    keyboard[0].callback_data = keyboard[0].callback_data.rsplit(':', 1)[0] + f':{num}'
                    keyboard[1].callback_data = keyboard[1].callback_data.rsplit(':', 1)[0] + f':{value}_{num}'
                
                bot.edit_message_reply_markup(chat_id, call.message.id, reply_markup=call.message.reply_markup)

        elif key == 'add':
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text='Завершить!', callback_data=f"get_store:browse:{value}"))
            bot.edit_message_text('Для добавления ссылки введите её адрес:', chat_id, call.message.id, reply_markup=markup)
            bot.register_next_step_handler(call.message, process_add_link_step, value)


    else:
        bot.answer_callback_query(call.id, 'Unknown input.')


@bot.message_handler(func=lambda m: m.reply_markup)
def select(message: Message):
    chat_id = str(message.chat.id)
    btn = message.reply_markup.keyboard[0][0]
    print(message.html_text)
    url = message.html_text.split('href="')[1].split('"')[0]
    print(url)
    action, data, market = btn.callback_data.split(':')

    data = get_db()
    token = data['users'][chat_id]

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text='<= Назад', callback_data=f"get_store:list:{market}"))
    markup.add(InlineKeyboardButton('Поиск товара', switch_inline_query_current_chat=f'Поиск на [{market}]: '))
    
    if action == 'details':
        resp = make_request('GET', 'products/by_url', token, market, params={'product_urls': url})
        if isinstance(resp, list):
            prod = resp[0]
            details = '\n'.join(f" * {key}: <b>{val}</b>" for key, val in prod['details'].items())
            bot.send_message(chat_id, 
                f"Название: <a href=\"{prod['productUrl']}\">{prod['name']}</a>\n"
                f"Цена: <b>{prod['price']}</b>\n"
                f"Бренд: <b>{prod['brandName']}</b>\n"
                f"Описание: <b>{prod.get('description')}</b>\n"
                +details,
                parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup
            )
        else:
            bot.send_message(chat_id, 
                f"Данные для этого товара ещё не распарсены. Пока можете посмотреть их по ссылке товара: {url}",
                reply_markup=markup
            )


@bot.inline_handler(lambda query: query.query.startswith('Поиск '))
def query_search(query: InlineQuery):
    chat_id = str(query.from_user.id)
    qy, text = query.query.split(':', 1)
    if not text: return
    market = qy.split('[')[1].split(']')[0]

    data = get_db()
    token = data['users'][chat_id]

    answer = []
    prod_list = make_request('GET', 'products/search', token, market, params={'query': text.strip()})
    print(len(prod_list))
    for n, prod in enumerate(prod_list):
        prod_card = InlineQueryResultArticle(
            id=n,
            title=f"{prod['name']} - {prod['price']}",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("Подробнее", callback_data=f"details:url:{market}")
            ),
            input_message_content=InputTextMessageContent(
                message_text=f"Название: <a href=\"{prod['productUrl']}\">{prod['name']}</a>\nЦена: <b>{prod['price']}</b>",
                parse_mode="HTML",
                disable_web_page_preview=True))

        answer.append(prod_card)

    if len(answer) == 0:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton('Поиск товара', switch_inline_query_current_chat=qy+':'))
        card = InlineQueryResultArticle(
            id='None',
            title='Not found', reply_markup=markup, description='Sorry, we are unable to find anything(',
            thumbnail_url='https://img.freepik.com/premium-vector/error-404-found-glitch-effect_8024-4.jpg?w=120', thumbnail_width=120, thumbnail_height=120,

            input_message_content=InputTextMessageContent(
                message_text=f"Not found <b>{text}!</b> Try to type something else.",
                parse_mode="HTML",
                disable_web_page_preview=True))

        answer.append(card)
    bot.answer_inline_query(str(query.id), answer, cache_time=2)
    answer.clear()
