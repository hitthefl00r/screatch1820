import json
import os
import logging
import re
import math
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    ConversationHandler,
    filters,
    JobQueue
)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(
    ADD_LOCATION, ADD_NAME, ADD_QUANTITY, ADD_CATEGORY,
    EDIT_LOCATION, EDIT_NAME, EDIT_QUANTITY, EDIT_CATEGORY,
    REMOVE_LOCATION, REMOVE_ITEM,
    SEARCH_ITEM,
    COUNTING_LOCATION, COUNTING_ITEM, COUNTING_CONFIRM,
    RECEIVE_GOODS,
    FILL_FRIDGE_ITEM, FILL_FRIDGE_QUANTITY
) = range(17)


# Класс для управления инвентарем
class InventoryManager:
    def __init__(self, filename='inventory.json'):
        self.filename = filename
        self.data = self.load_data()

    def load_data(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Ошибка загрузки данных: {e}")
                return self.create_default_data()
        return self.create_default_data()

    def create_default_data(self):
        return {
            'refrigerator_1': {},
            'refrigerator_2': {},
            'refrigerator_3': {},
            'cupboard': {}
        }

    def save_data(self):
        try:
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения данных: {e}")
            return False

    def add_item(self, location, name, quantity, category=None):
        if location not in self.data:
            return False
        if name in self.data[location]:
            return False

        self.data[location][name] = {
            'quantity': quantity,
            'category': category
        }
        return self.save_data()

    def edit_item(self, location, name, new_quantity=None, new_category=None):
        if location not in self.data or name not in self.data[location]:
            return False

        if new_quantity is not None:
            self.data[location][name]['quantity'] = new_quantity
        if new_category is not None:
            self.data[location][name]['category'] = new_category

        return self.save_data()

    def remove_item(self, location, name):
        if location not in self.data or name not in self.data[location]:
            return False

        del self.data[location][name]
        return self.save_data()

    def get_inventory(self, location=None):
        if location:
            return self.data.get(location, {})
        return self.data

    def search_item(self, name):
        results = {}
        for location, items in self.data.items():
            if name in items:
                results[location] = items[name]
        return results if results else None

    def export_to_txt(self, filename=None):
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"inventory_export_{timestamp}.txt"

        try:
            total_items = 0
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=== ИНВЕНТАРИЗАЦИЯ ===\n")
                f.write(f"Дата экспорта: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                for location, items in self.data.items():
                    f.write(f"{location.upper()}:\n")
                    if not items:
                        f.write("  Пусто\n")
                    else:
                        for item, details in items.items():
                            f.write(f"  - {item}: {details['quantity']} шт.")
                            if details['category']:
                                f.write(f" (категория: {details['category']})")
                            f.write("\n")
                            total_items += details['quantity']
                    f.write("\n")

                f.write(f"\nИТОГО: {total_items} единиц товара\n")

            return filename
        except Exception as e:
            logger.error(f"Ошибка экспорта: {e}")
            return None

    def get_items_with_location(self):
        """Возвращает словарь товаров с их основными локациями"""
        items = {}
        for location, loc_items in self.data.items():
            for item in loc_items.keys():
                if item not in items:
                    items[item] = location
        return items

    def get_cupboard_items(self):
        """Возвращает товары в шкафу с их количеством"""
        return self.data.get('cupboard', {})

    def move_from_cupboard(self, item_name, quantity):
        """Перемещает товар из шкафа в его основную локацию"""
        if 'cupboard' not in self.data or item_name not in self.data['cupboard']:
            return False, "Товар не найден в шкафу"

        if self.data['cupboard'][item_name]['quantity'] < quantity:
            return False, "Недостаточно товара в шкафу"

        # Определяем целевую локацию
        target_location = None
        for loc in ['refrigerator_1', 'refrigerator_2', 'refrigerator_3']:
            if item_name in self.data[loc]:
                target_location = loc
                break

        # Если не нашли в холодильниках, используем первый холодильник
        if not target_location:
            target_location = 'refrigerator_1'

        # Уменьшаем количество в шкафу
        self.data['cupboard'][item_name]['quantity'] -= quantity

        # Удаляем запись если количество стало 0
        if self.data['cupboard'][item_name]['quantity'] == 0:
            del self.data['cupboard'][item_name]

        # Добавляем в целевую локацию
        if item_name in self.data[target_location]:
            self.data[target_location][item_name]['quantity'] += quantity
        else:
            # Сохраняем категорию если была
            category = self.data['cupboard'].get(item_name, {}).get('category')
            self.data[target_location][item_name] = {
                'quantity': quantity,
                'category': category
            }

        if self.save_data():
            return True, target_location
        return False, "Ошибка сохранения данных"

    def add_to_cupboard(self, goods_list):
        """Добавляет список товаров в шкаф"""
        if 'cupboard' not in self.data:
            self.data['cupboard'] = {}

        for item_name, quantity in goods_list:
            if item_name in self.data['cupboard']:
                self.data['cupboard'][item_name]['quantity'] += quantity
            else:
                self.data['cupboard'][item_name] = {
                    'quantity': quantity,
                    'category': None
                }
        return self.save_data()

    def calculate_expression(self, expression):
        """Вычисляет математическое выражение"""
        try:
            # Заменяем x на * для умножения
            expression = expression.replace('x', '*').replace('х', '*')
            # Удаляем все символы кроме цифр, операторов и пробелов
            expression = re.sub(r'[^\d\*\+\-\s/]', '', expression)
            return int(eval(expression))
        except:
            return None

    def check_stock_levels(self, threshold=10):
        """Проверяет остатки и возвращает товары, которые нужно заказать"""
        to_order = {}

        # Собираем все товары, которые есть в холодильниках
        fridge_items = set()
        for loc in ['refrigerator_1', 'refrigerator_2', 'refrigerator_3']:
            for item in self.data.get(loc, {}).keys():
                fridge_items.add(item)

        # Проверяем остатки в шкафу для товаров из холодильников
        for item in fridge_items:
            cupboard_qty = self.data.get('cupboard', {}).get(item, {}).get('quantity', 0)
            if cupboard_qty < threshold:
                # Рассчитываем рекомендуемое количество для заказа
                # Суммируем количество во всех холодильниках
                total_in_fridges = 0
                for loc in ['refrigerator_1', 'refrigerator_2', 'refrigerator_3']:
                    total_in_fridges += self.data.get(loc, {}).get(item, {}).get('quantity', 0)

                # Рекомендуем заказать 50% от общего количества в холодильниках, но не менее 10
                recommended = max(10, math.ceil(total_in_fridges * 0.5))
                to_order[item] = {
                    'current': cupboard_qty,
                    'recommended': recommended
                }

        return to_order


# Инициализация менеджера
inventory_manager = InventoryManager()


# Функции для создания клавиатур
def get_locations_keyboard():
    return ReplyKeyboardMarkup([
        ['Холодильник 1', 'Холодильник 2'],
        ['Холодильник 3', 'Шкаф'],
        ['/cancel']
    ], resize_keyboard=True)


def get_main_keyboard():
    return ReplyKeyboardMarkup([
        ['Добавить товар', 'Редактировать товар'],
        ['Удалить товар', 'Просмотреть инвентарь'],
        ['Поиск товара', 'Экспорт в TXT'],
        ['Прием товара', 'Заполнить холодильник'],
        ['Подсчет товара', 'Проверить остатки'],
        ['/help']
    ], resize_keyboard=True)


def get_yes_no_keyboard():
    return ReplyKeyboardMarkup([
        ['Да', 'Нет'],
        ['/cancel']
    ], resize_keyboard=True)


# Команды бота
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "🛒 Добро пожаловать в систему учета товаров!\n"
        "Используйте кнопки ниже для управления инвентарем.",
        reply_markup=get_main_keyboard()
    )


async def help_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "📌 Доступные команды:\n"
        "/start - начать работу\n"
        "/help - справка\n"
        "/cancel - отменить текущее действие\n\n"
        "Основные функции:\n"
        "• Добавить товар - добавить новую позицию\n"
        "• Редактировать товар - изменить количество или категорию\n"
        "• Удалить товар - удалить позицию\n"
        "• Просмотреть инвентарь - показать все товары\n"
        "• Поиск товара - найти товар по названию\n"
        "• Экспорт в TXT - выгрузить отчет\n"
        "• Прием товара - добавить товары в шкаф\n"
        "• Заполнить холодильник - переместить товары из шкафа\n"
        "• Подсчет товара - провести инвентаризацию\n"
        "• Проверить остатки - найти товары для дозаказа",
        reply_markup=get_main_keyboard()
    )


async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "❌ Действие отменено.",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END


# Обработчики для добавления товара
async def add_item_start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "Выберите место хранения:",
        reply_markup=get_locations_keyboard()
    )
    return ADD_LOCATION


async def add_item_location(update: Update, context: CallbackContext) -> int:
    location_map = {
        'Холодильник 1': 'refrigerator_1',
        'Холодильник 2': 'refrigerator_2',
        'Холодильник 3': 'refrigerator_3',
        'Шкаф': 'cupboard'
    }

    user_input = update.message.text
    if user_input not in location_map:
        await update.message.reply_text("Пожалуйста, выберите место из предложенных вариантов.")
        return ADD_LOCATION

    context.user_data['location'] = location_map[user_input]
    await update.message.reply_text(
        "Введите название товара:",
        reply_markup=ReplyKeyboardRemove()
    )
    return ADD_NAME


async def add_item_name(update: Update, context: CallbackContext) -> int:
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Введите количество:")
    return ADD_QUANTITY


async def add_item_quantity(update: Update, context: CallbackContext) -> int:
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            raise ValueError
        context.user_data['quantity'] = quantity
        await update.message.reply_text("Введите категорию (или отправьте '-' чтобы пропустить):")
        return ADD_CATEGORY
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите целое положительное число.")
        return ADD_QUANTITY


async def add_item_category(update: Update, context: CallbackContext) -> int:
    category = update.message.text if update.message.text != '-' else None
    context.user_data['category'] = category

    location = context.user_data['location']
    name = context.user_data['name']
    quantity = context.user_data['quantity']

    if inventory_manager.add_item(location, name, quantity, category):
        await update.message.reply_text(
            f"✅ Товар '{name}' успешно добавлен в {location}!",
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            f"❌ Ошибка: товар '{name}' уже существует в {location}.",
            reply_markup=get_main_keyboard()
        )

    return ConversationHandler.END


# Обработчики для просмотра инвентаря
async def view_inventory(update: Update, context: CallbackContext) -> None:
    inventory = inventory_manager.get_inventory()
    response = "📋 Текущий инвентарь:\n\n"

    for location, items in inventory.items():
        response += f"📍 {location.capitalize()}:\n"
        if not items:
            response += "  Пусто\n"
        else:
            for item, details in items.items():
                response += f"  - {item}: {details['quantity']} шт."
                if details.get('category'):
                    response += f" (категория: {details['category']})"
                response += "\n"
        response += "\n"

    await update.message.reply_text(response)


# Обработчики для экспорта в TXT
async def export_to_txt(update: Update, context: CallbackContext) -> None:
    filename = inventory_manager.export_to_txt()
    if filename:
        try:
            await update.message.reply_document(
                document=open(filename, 'rb'),
                caption="📤 Экспорт инвентаря завершен."
            )
            os.remove(filename)
        except Exception as e:
            logger.error(f"Ошибка отправки файла: {e}")
            await update.message.reply_text("❌ Ошибка отправки файла экспорта.")
    else:
        await update.message.reply_text("❌ Ошибка при экспорте инвентаря.")


# Обработчики для поиска товара
async def search_item_start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "🔍 Введите название товара для поиска:",
        reply_markup=ReplyKeyboardRemove()
    )
    return SEARCH_ITEM


async def search_item_result(update: Update, context: CallbackContext) -> int:
    name = update.message.text
    results = inventory_manager.search_item(name)

    if not results:
        response = f"❌ Товар '{name}' не найден."
    else:
        response = f"🔍 Результаты поиска для '{name}':\n\n"
        for location, details in results.items():
            response += f"📍 {location.capitalize()}:\n"
            response += f"  - Количество: {details['quantity']} шт."
            if details.get('category'):
                response += f"\n  - Категория: {details['category']}"
            response += "\n\n"

    await update.message.reply_text(
        response,
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END


# Обработчики для удаления товара
async def remove_item_start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "Выберите место хранения:",
        reply_markup=get_locations_keyboard()
    )
    return REMOVE_LOCATION


async def remove_item_location(update: Update, context: CallbackContext) -> int:
    location_map = {
        'Холодильник 1': 'refrigerator_1',
        'Холодильник 2': 'refrigerator_2',
        'Холодильник 3': 'refrigerator_3',
        'Шкаф': 'cupboard'
    }

    user_input = update.message.text
    if user_input not in location_map:
        await update.message.reply_text("Пожалуйста, выберите место из предложенных вариантов.")
        return REMOVE_LOCATION

    location = location_map[user_input]
    inventory = inventory_manager.get_inventory(location)

    if not inventory:
        await update.message.reply_text(
            f"❌ В {location} нет товаров для удаления.",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    context.user_data['location'] = location
    items_list = "\n".join([f"- {item}" for item in inventory.keys()])

    await update.message.reply_text(
        f"Товары в {location}:\n{items_list}\n\nВведите название товара для удаления:",
        reply_markup=ReplyKeyboardRemove()
    )
    return REMOVE_ITEM


async def remove_item_name(update: Update, context: CallbackContext) -> int:
    location = context.user_data['location']
    name = update.message.text
    inventory = inventory_manager.get_inventory(location)

    if name not in inventory:
        await update.message.reply_text(
            f"❌ Ошибка: товар '{name}' не найден в {location}.",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    if inventory_manager.remove_item(location, name):
        await update.message.reply_text(
            f"✅ Товар '{name}' успешно удален из {location}!",
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            f"❌ Ошибка при удалении товара '{name}'.",
            reply_markup=get_main_keyboard()
        )

    return ConversationHandler.END


# Обработчики для редактирования товара
async def edit_item_start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "Выберите место хранения:",
        reply_markup=get_locations_keyboard()
    )
    return EDIT_LOCATION


async def edit_item_location(update: Update, context: CallbackContext) -> int:
    location_map = {
        'Холодильник 1': 'refrigerator_1',
        'Холодильник 2': 'refrigerator_2',
        'Холодильник 3': 'refrigerator_3',
        'Шкаф': 'cupboard'
    }

    user_input = update.message.text
    if user_input not in location_map:
        await update.message.reply_text("Пожалуйста, выберите место из предложенных вариантов.")
        return EDIT_LOCATION

    location = location_map[user_input]
    inventory = inventory_manager.get_inventory(location)

    if not inventory:
        await update.message.reply_text(
            f"❌ В {location} нет товаров для редактирования.",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    context.user_data['location'] = location
    items_list = "\n".join([f"- {item}" for item in inventory.keys()])

    await update.message.reply_text(
        f"Товары в {location}:\n{items_list}\n\nВведите название товара для редактирования:",
        reply_markup=ReplyKeyboardRemove()
    )
    return EDIT_NAME


async def edit_item_name(update: Update, context: CallbackContext) -> int:
    location = context.user_data['location']
    name = update.message.text
    inventory = inventory_manager.get_inventory(location)

    if name not in inventory:
        await update.message.reply_text(
            f"❌ Ошибка: товар '{name}' не найден в {location}.",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    context.user_data['name'] = name
    item_details = inventory[name]

    await update.message.reply_text(
        f"✏️ Редактирование товара '{name}':\n"
        f"Текущее количество: {item_details['quantity']}\n"
        f"Текущая категория: {item_details.get('category', 'не указана')}\n\n"
        "Введите новое количество (или '-' чтобы оставить без изменений):",
        reply_markup=ReplyKeyboardRemove()
    )
    return EDIT_QUANTITY


async def edit_item_quantity(update: Update, context: CallbackContext) -> int:
    if update.message.text != '-':
        try:
            quantity = int(update.message.text)
            if quantity <= 0:
                raise ValueError
            context.user_data['new_quantity'] = quantity
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите целое положительное число или '-'.")
            return EDIT_QUANTITY
    else:
        context.user_data['new_quantity'] = None

    await update.message.reply_text(
        "Введите новую категорию (или '-' чтобы оставить без изменений):"
    )
    return EDIT_CATEGORY


async def edit_item_category(update: Update, context: CallbackContext) -> int:
    new_category = update.message.text if update.message.text != '-' else None
    context.user_data['new_category'] = new_category

    location = context.user_data['location']
    name = context.user_data['name']
    new_quantity = context.user_data.get('new_quantity')

    if inventory_manager.edit_item(location, name, new_quantity, new_category):
        await update.message.reply_text(
            f"✅ Товар '{name}' успешно обновлен!",
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            f"❌ Ошибка при обновлении товара '{name}'.",
            reply_markup=get_main_keyboard()
        )

    return ConversationHandler.END


# Новые функции: Подсчет товара
async def start_counting(update: Update, context: CallbackContext) -> int:
    context.user_data['counting'] = {
        'current_location_index': 0,
        'results': {},
        'locations': ['refrigerator_1', 'refrigerator_2', 'refrigerator_3', 'cupboard']
    }

    # Начинаем с первой локации
    location = context.user_data['counting']['locations'][0]
    items = inventory_manager.get_inventory(location)

    if not items:
        await update.message.reply_text(
            f"📍 В локации {location} нет товаров. Переходим к следующей...",
            reply_markup=ReplyKeyboardRemove()
        )
        return await next_counting_location(update, context)

    context.user_data['counting']['current_items'] = list(items.keys())
    context.user_data['counting']['current_item_index'] = 0
    context.user_data['counting']['current_location'] = location

    item_name = context.user_data['counting']['current_items'][0]
    await update.message.reply_text(
        f"🔢 Начинаем подсчет в {location}:\n"
        f"Товар: {item_name}\n"
        f"Текущее количество: {items[item_name]['quantity']}\n\n"
        "Введите новое количество (можно использовать выражения: 1+1, 4x8+4x7):",
        reply_markup=ReplyKeyboardRemove()
    )
    return COUNTING_ITEM


async def handle_counting_quantity(update: Update, context: CallbackContext) -> int:
    expression = update.message.text
    calculated = inventory_manager.calculate_expression(expression)

    if calculated is None or calculated < 0:
        await update.message.reply_text("❌ Некорректное выражение. Попробуйте еще раз:")
        return COUNTING_ITEM

    location = context.user_data['counting']['current_location']
    item_index = context.user_data['counting']['current_item_index']
    item_name = context.user_data['counting']['current_items'][item_index]

    # Сохраняем результат
    if location not in context.user_data['counting']['results']:
        context.user_data['counting']['results'][location] = {}

    context.user_data['counting']['results'][location][item_name] = calculated

    # Переходим к следующему товару
    context.user_data['counting']['current_item_index'] += 1
    items = context.user_data['counting']['current_items']

    if context.user_data['counting']['current_item_index'] < len(items):
        next_item = items[context.user_data['counting']['current_item_index']]
        current_quantity = inventory_manager.get_inventory(location)[next_item]['quantity']

        await update.message.reply_text(
            f"Товар: {next_item}\n"
            f"Текущее количество: {current_quantity}\n\n"
            "Введите новое количество:",
            reply_markup=ReplyKeyboardRemove()
        )
        return COUNTING_ITEM
    else:
        return await next_counting_location(update, context)


async def next_counting_location(update: Update, context: CallbackContext) -> int:
    counting_data = context.user_data['counting']
    counting_data['current_location_index'] += 1

    if counting_data['current_location_index'] >= len(counting_data['locations']):
        # Подсчет завершен
        return await finish_counting(update, context)

    # Переходим к следующей локации
    location = counting_data['locations'][counting_data['current_location_index']]
    items = inventory_manager.get_inventory(location)

    if not items:
        await update.message.reply_text(
            f"📍 В локации {location} нет товаров. Переходим к следующей...",
            reply_markup=ReplyKeyboardRemove()
        )
        return await next_counting_location(update, context)

    counting_data['current_items'] = list(items.keys())
    counting_data['current_item_index'] = 0
    counting_data['current_location'] = location

    item_name = counting_data['current_items'][0]
    current_quantity = items[item_name]['quantity']

    await update.message.reply_text(
        f"🔢 Продолжаем подсчет в {location}:\n"
        f"Товар: {item_name}\n"
        f"Текущее количество: {current_quantity}\n\n"
        "Введите новое количество:",
        reply_markup=ReplyKeyboardRemove()
    )
    return COUNTING_ITEM


async def finish_counting(update: Update, context: CallbackContext) -> int:
    results = context.user_data['counting']['results']
    report = "📊 Отчет по подсчету:\n\n"
    total_difference = 0

    for location, items in results.items():
        report += f"📍 {location}:\n"
        for item, new_quantity in items.items():
            old_quantity = inventory_manager.get_inventory(location)[item]['quantity']
            difference = new_quantity - old_quantity
            total_difference += difference

            report += f"  - {item}: было {old_quantity}, стало {new_quantity} "
            report += f"({'+' if difference >= 0 else ''}{difference})\n"
        report += "\n"

    report += f"Общее изменение: {total_difference}"

    await update.message.reply_text(
        report + "\n\nПрименить изменения?",
        reply_markup=get_yes_no_keyboard()
    )
    return COUNTING_CONFIRM


async def confirm_counting(update: Update, context: CallbackContext) -> int:
    if update.message.text.lower() == 'да':
        results = context.user_data['counting']['results']

        for location, items in results.items():
            for item, new_quantity in items.items():
                inventory_manager.edit_item(location, item, new_quantity)

        await update.message.reply_text(
            "✅ Изменения применены!",
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Изменения отменены.",
            reply_markup=get_main_keyboard()
        )

    return ConversationHandler.END


# Новые функции: Прием товара
async def start_receive_goods(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "📦 Введите список принятых товаров в формате:\n"
        "Название Количество\n"
        "Например:\n"
        "Крым Энергия 10\n"
        "Red Bull 0.5 5\n"
        "Отправьте сообщение с товарами:",
        reply_markup=ReplyKeyboardRemove()
    )
    return RECEIVE_GOODS


async def handle_receive_goods(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    goods_list = []
    errors = []

    for line in text.split('\n'):
        parts = line.strip().rsplit(' ', 1)
        if len(parts) == 2:
            item_name, quantity_str = parts
            try:
                quantity = int(quantity_str)
                goods_list.append((item_name, quantity))
            except ValueError:
                try:
                    # Пробуем преобразовать в целое число, если есть дробная часть
                    quantity = float(quantity_str)
                    goods_list.append((item_name, int(quantity)))
                except:
                    errors.append(f"❌ Неверный формат количества: {line}")
        else:
            errors.append(f"❌ Неверный формат строки: {line}")

    if not goods_list:
        await update.message.reply_text(
            "❌ Не удалось распознать товары. Попробуйте еще раз:",
            reply_markup=ReplyKeyboardRemove()
        )
        return RECEIVE_GOODS

    # Добавляем товары в шкаф
    if inventory_manager.add_to_cupboard(goods_list):
        report = "✅ Товары добавлены в шкаф:\n"
        for item, quantity in goods_list:
            report += f"  - {item}: +{quantity}\n"

        if errors:
            report += "\nОшибки:\n" + "\n".join(errors)

        await update.message.reply_text(
            report,
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Ошибка при добавлении товаров в шкаф.",
            reply_markup=get_main_keyboard()
        )

    return ConversationHandler.END


# Новые функции: Заполнение холодильника
async def start_fill_fridge(update: Update, context: CallbackContext) -> int:
    cupboard_items = inventory_manager.get_cupboard_items()

    if not cupboard_items:
        await update.message.reply_text(
            "❌ В шкафу нет товаров для перемещения.",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    # Создаем клавиатуру с товарами из шкафа
    keyboard = []
    row = []
    for i, item in enumerate(cupboard_items.keys(), 1):
        row.append(item)
        if i % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append(['/cancel'])

    await update.message.reply_text(
        "📥 Выберите товар для перемещения из шкафа:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return FILL_FRIDGE_ITEM


async def select_fill_item(update: Update, context: CallbackContext) -> int:
    item_name = update.message.text
    cupboard_items = inventory_manager.get_cupboard_items()

    if item_name not in cupboard_items:
        await update.message.reply_text(
            "❌ Товар не найден в шкафу. Выберите другой товар:",
            reply_markup=ReplyKeyboardRemove()
        )
        return FILL_FRIDGE_ITEM

    context.user_data['fill_item'] = item_name
    max_quantity = cupboard_items[item_name]['quantity']

    await update.message.reply_text(
        f"Введите количество товара '{item_name}' для перемещения (доступно: {max_quantity}):",
        reply_markup=ReplyKeyboardRemove()
    )
    return FILL_FRIDGE_QUANTITY


async def handle_fill_quantity(update: Update, context: CallbackContext) -> int:
    try:
        quantity = int(update.message.text)
        item_name = context.user_data['fill_item']
        cupboard_items = inventory_manager.get_cupboard_items()

        if item_name not in cupboard_items:
            await update.message.reply_text(
                "❌ Товар больше не доступен в шкафу.",
                reply_markup=get_main_keyboard()
            )
            return ConversationHandler.END

        max_quantity = cupboard_items[item_name]['quantity']
        if quantity > max_quantity:
            await update.message.reply_text(
                f"❌ Недостаточно товара. Доступно: {max_quantity}",
                reply_markup=ReplyKeyboardRemove()
            )
            return FILL_FRIDGE_QUANTITY

        success, target = inventory_manager.move_from_cupboard(item_name, quantity)

        if success:
            await update.message.reply_text(
                f"✅ Товар '{item_name}' ({quantity} шт.) перемещен в {target}!",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                f"❌ Ошибка: {target}",
                reply_markup=get_main_keyboard()
            )
    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите целое число:",
            reply_markup=ReplyKeyboardRemove()
        )
        return FILL_FRIDGE_QUANTITY

    return ConversationHandler.END


# Новая функция: Проверка остатков
async def check_stock(update: Update, context: CallbackContext) -> None:
    low_stock = inventory_manager.check_stock_levels()

    if not low_stock:
        await update.message.reply_text(
            "✅ Все товары в достаточном количестве!",
            reply_markup=get_main_keyboard()
        )
        return

    # Формируем отчет для администратора
    admin_report = "⚠️ Следующие товары заканчиваются:\n\n"
    for item, data in low_stock.items():
        admin_report += f"- {item}: текущий остаток {data['current']}, рекомендуется заказать {data['recommended']} шт.\n"

    # Формируем сообщение для поставщика
    supplier_msg = "Добрый день, необходимо на Кечкеметскую 190А:\n"
    for item, data in low_stock.items():
        supplier_msg += f"- {item}: {data['recommended']} шт.\n"

    await update.message.reply_text(
        admin_report + "\n" + supplier_msg,
        reply_markup=get_main_keyboard()
    )


# Функция для периодической проверки остатков
async def periodic_stock_check(context: CallbackContext):
    low_stock = inventory_manager.check_stock_levels()

    if not low_stock:
        return

    # Формируем отчет
    report = "🔔 Ежедневная проверка остатков:\n\n"
    report += "⚠️ Следующие товары заканчиваются:\n"
    for item, data in low_stock.items():
        report += f"- {item}: остаток {data['current']} шт. (рекомендуется заказать {data['recommended']} шт.)\n"

    # Отправляем сообщение
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=report
    )


# Функция для установки периодической проверки
async def set_periodic_check(update: Update, context: CallbackContext):
    # Добавляем задачу для ежедневной проверки в 10:00
    context.job_queue.run_daily(
        periodic_stock_check,
        time=datetime.time(hour=10, minute=0),
        days=(0, 1, 2, 3, 4, 5, 6),
        chat_id=update.effective_chat.id
    )
    await update.message.reply_text("✅ Ежедневная проверка остатков установлена на 10:00")


# Основная функция
def main() -> None:
    # Замените YOUR_TOKEN на реальный токен бота
    TOKEN = "8227984784:AAFnCqENEm5M8nfzxsiPw9Xcd7KU2xSKWqQ"
    application = Application.builder().token(TOKEN).build()

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("set_check", set_periodic_check))

    # Обработчики для добавления товара
    add_item_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Добавить товар$'), add_item_start)],
        states={
            ADD_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_location)],
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_name)],
            ADD_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_quantity)],
            ADD_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_category)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Обработчики для поиска товара
    search_item_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Поиск товара$'), search_item_start)],
        states={
            SEARCH_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_item_result)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Обработчики для удаления товара
    remove_item_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Удалить товар$'), remove_item_start)],
        states={
            REMOVE_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_item_location)],
            REMOVE_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_item_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Обработчики для редактирования товара
    edit_item_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Редактировать товар$'), edit_item_start)],
        states={
            EDIT_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_item_location)],
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_item_name)],
            EDIT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_item_quantity)],
            EDIT_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_item_category)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Обработчики для подсчета товара
    counting_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Подсчет товара$'), start_counting)],
        states={
            COUNTING_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_counting_quantity)],
            COUNTING_CONFIRM: [MessageHandler(filters.Regex('^(Да|Нет)$'), confirm_counting)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Обработчики для приема товара
    receive_goods_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Прием товара$'), start_receive_goods)],
        states={
            RECEIVE_GOODS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_receive_goods)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Обработчики для заполнения холодильника
    fill_fridge_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Заполнить холодильник$'), start_fill_fridge)],
        states={
            FILL_FRIDGE_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_fill_item)],
            FILL_FRIDGE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fill_quantity)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Регистрация обработчиков
    application.add_handler(add_item_conv)
    application.add_handler(search_item_conv)
    application.add_handler(remove_item_conv)
    application.add_handler(edit_item_conv)
    application.add_handler(counting_conv)
    application.add_handler(receive_goods_conv)
    application.add_handler(fill_fridge_conv)

    # Обработчики простых действий
    application.add_handler(MessageHandler(filters.Regex('^Просмотреть инвентарь$'), view_inventory))
    application.add_handler(MessageHandler(filters.Regex('^Экспорт в TXT$'), export_to_txt))
    application.add_handler(MessageHandler(filters.Regex('^Проверить остатки$'), check_stock))

    # Запуск бота
    application.run_polling()


if __name__ == '__main__':
    main()