"""Заполнение базы демонстрационными категориями и товарами.

Команда безопасна при повторном запуске: категории и товары создаются
через get_or_create / update_or_create, пользовательские данные не удаляются.

    python manage.py seed_data
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from decimal import Decimal

from shop.models import Category, Coupon, Product

CATEGORIES = [
    {
        'name': 'Игровые мышки',
        'slug': 'mouse',
        'description': 'Точные сенсоры, эргономичный корпус и настраиваемые кнопки '
                       'для динамичных игр и киберспорта.',
    },
    {
        'name': 'Механические клавиатуры',
        'slug': 'keyboard',
        'description': 'Механические переключатели, RGB-подсветка и надёжная конструкция '
                       'для комфортной игры и работы.',
    },
    {
        'name': 'Игровые наушники',
        'slug': 'headset',
        'description': 'Объёмный звук, чистый микрофон и удобные амбушюры для долгих игровых сессий.',
    },
    {
        'name': 'Геймпады и контроллеры',
        'slug': 'gamepad',
        'description': 'Контроллеры для консолей и ПК с отзывчивыми триггерами и точными стиками.',
    },
    {
        'name': 'Микрофоны',
        'slug': 'microphone',
        'description': 'Микрофоны для стримов, подкастов и голосового общения в играх.',
    },
    {
        'name': 'Коврики для мыши',
        'slug': 'mousepad',
        'description': 'Игровые поверхности разных размеров для точного скольжения мыши.',
    },
    {
        'name': 'Аксессуары для игровых компьютеров',
        'slug': 'accessories',
        'description': 'Веб-камеры, подставки, кабели и полезные устройства для игрового сетапа.',
    },
]

COUPONS = [
    {
        'code': 'GAMEZONE10',
        'kind': Coupon.Kind.PERCENT,
        'value': Decimal('10'),
        'min_total': Decimal('1000'),
        'usage_limit': None,
    },
    {
        'code': 'WELCOME200',
        'kind': Coupon.Kind.FIXED,
        'value': Decimal('200'),
        'min_total': Decimal('2000'),
        'usage_limit': 50,
    },
]

PRODUCTS = [
    {
        'name': 'Logitech G102',
        'category': 'mouse',
        'price': 899,
        'stock': 25,
        'is_featured': True,
        'description': 'Лёгкая игровая мышь с сенсором до 8000 DPI, настраиваемой RGB-подсветкой '
                       'и шестью программируемыми кнопками. Хороший выбор для первых игровых сетапов.',
        'specifications': {
            'Тип подключения': 'USB (проводной)',
            'Сенсор': 'Механический, до 8000 DPI',
            'Кнопки': '6 программируемых',
            'Подсветка': 'RGB LIGHTSYNC',
            'Совместимость': 'Windows, macOS',
        },
    },
    {
        'name': 'Logitech G502 HERO',
        'category': 'mouse',
        'price': 2499,
        'stock': 15,
        'is_featured': True,
        'description': 'Игровая мышь с сенсором HERO до 25600 DPI, 11 программируемых кнопок '
                       'и регулируемыми грузиками для балансировки веса.',
        'specifications': {
            'Тип подключения': 'USB (проводной)',
            'Сенсор': 'HERO 25K, до 25600 DPI',
            'Кнопки': '11 программируемых',
            'Вес': 'Регулируемый, до 121 г',
            'Совместимость': 'Windows, macOS',
        },
    },
    {
        'name': 'Razer DeathAdder Essential',
        'category': 'mouse',
        'price': 1299,
        'stock': 20,
        'description': 'Классическая эргономичная игровая мышь с сенсором до 6400 DPI '
                       'и прочными механическими переключателями.',
        'specifications': {
            'Тип подключения': 'USB (проводной)',
            'Сенсор': 'Оптический, до 6400 DPI',
            'Кнопки': '5 программируемых',
            'Подсветка': 'Зелёная',
            'Совместимость': 'Windows',
        },
    },
    {
        'name': 'HyperX Alloy Origins Core',
        'category': 'keyboard',
        'price': 3299,
        'stock': 12,
        'is_featured': True,
        'description': 'Компактная механическая клавиатура формата TKL с алюминиевым корпусом, '
                       'RGB-подсветкой и переключателями HyperX Red.',
        'specifications': {
            'Тип переключателей': 'HyperX Red (линейные)',
            'Формат': 'TKL (без цифрового блока)',
            'Подсветка': 'RGB, 3 уровня яркости',
            'Корпус': 'Алюминиевый',
            'Подключение': 'USB Type-C',
        },
    },
    {
        'name': 'Redragon K552 Kumara',
        'category': 'keyboard',
        'price': 1499,
        'stock': 18,
        'description': 'Недорогая механическая клавиатура формата TKL с синими переключателями '
                       'и металлической платой.',
        'specifications': {
            'Тип переключателей': 'Синие (clicky)',
            'Формат': 'TKL (87 клавиш)',
            'Подсветка': 'RGB',
            'Корпус': 'Металл + ABS',
            'Подключение': 'USB',
        },
    },
    {
        'name': 'Logitech G Pro X',
        'category': 'headset',
        'price': 4299,
        'stock': 10,
        'description': 'Игровая гарнитура со съёмным микрофоном Blue VO!CE, пространственным звуком '
                       'и лёгким корпусом из алюминия и стали.',
        'specifications': {
            'Тип подключения': 'USB / 3.5 мм',
            'Динамики': '50 мм, PRO-G',
            'Микрофон': 'Съёмный, Blue VO!CE',
            'Частотный диапазон': '20 Гц – 20 кГц',
            'Совместимость': 'ПК, PlayStation, Xbox, Nintendo Switch',
        },
    },
    {
        'name': 'HyperX Cloud II',
        'category': 'headset',
        'price': 2999,
        'stock': 16,
        'is_featured': True,
        'description': 'Легендарная игровая гарнитура с объёмным виртуальным звуком 7.1, '
                       'мягкими амбушюрами из память-пены и съёмным микрофоном.',
        'specifications': {
            'Тип подключения': 'USB / 3.5 мм',
            'Динамики': '53 мм',
            'Объёмный звук': 'Виртуальный 7.1',
            'Микрофон': 'Съёмный, с шумоподавлением',
            'Совместимость': 'ПК, PlayStation, Xbox, Nintendo Switch',
        },
    },
    {
        'name': 'Razer BlackShark V2',
        'category': 'headset',
        'price': 3199,
        'stock': 14,
        'description': 'Лёгкая гарнитура с драйверами TriForce 50 мм, картой звука USB '
                       'и микрофоном с продвинутым шумоподавлением.',
        'specifications': {
            'Тип подключения': '3.5 мм / USB (в комплекте)',
            'Динамики': '50 мм, TriForce',
            'Микрофон': 'Кардиоидный, с шумоподавлением',
            'Частотный диапазон': '12 Гц – 28 кГц',
            'Совместимость': 'ПК, PlayStation, Xbox, Nintendo Switch',
        },
    },
    {
        'name': 'Logitech G435',
        'category': 'headset',
        'price': 2499,
        'stock': 12,
        'description': 'Беспроводная лёгкая гарнитура (165 г) с двумя каналами подключения '
                       'и двумя направленными микрофонами.',
        'specifications': {
            'Тип подключения': 'Bluetooth / LIGHTSPEED 2.4 ГГц',
            'Динамики': '40 мм',
            'Микрофон': 'Двойной направленный',
            'Автономность': 'До 18 часов',
            'Совместимость': 'ПК, PlayStation, Nintendo Switch, смартфоны',
        },
    },
    {
        'name': 'Sony DualSense',
        'category': 'gamepad',
        'price': 2399,
        'stock': 11,
        'is_featured': True,
        'description': 'Беспроводной контроллер с тактильной отдачей, адаптивными триггерами '
                       'и встроенным микрофоном.',
        'specifications': {
            'Тип подключения': 'Bluetooth / USB-C',
            'Особенности': 'Тактильная отдача, адаптивные триггеры',
            'Аккумулятор': 'Встроенный, зарядка по USB-C',
            'Совместимость': 'PlayStation 5, ПК',
        },
    },
    {
        'name': 'Xbox Wireless Controller',
        'category': 'gamepad',
        'price': 2199,
        'stock': 13,
        'description': 'Беспроводной контроллер с текстурными ручками, крестовиной-геймпадом '
                       'и разъёмом 3.5 мм для гарнитуры.',
        'specifications': {
            'Тип подключения': 'Bluetooth / USB-C',
            'Питание': '2 батарейки AA / аккумулятор',
            'Разъём для гарнитуры': '3.5 мм',
            'Совместимость': 'Xbox Series X|S, Xbox One, ПК',
        },
    },
    {
        'name': 'Fifine AM8',
        'category': 'microphone',
        'price': 1899,
        'stock': 9,
        'description': 'USB-микрофон для стримов и подкастов с кардиоидной диаграммой направленности, '
                       'регулировкой громкости и RGB-подсветкой.',
        'specifications': {
            'Тип подключения': 'USB-C / XLR',
            'Диаграмма направленности': 'Кардиоидная',
            'Частотный диапазон': '50 Гц – 16 кГц',
            'Особенности': 'Регулятор громкости, RGB',
            'Совместимость': 'Windows, macOS',
        },
    },
    {
        'name': 'HyperX SoloCast',
        'category': 'microphone',
        'price': 1399,
        'stock': 10,
        'description': 'Компактный USB-микрофон с кардиоидной направленностью и сенсорным '
                       'отключением микрофона одним касанием.',
        'specifications': {
            'Тип подключения': 'USB-C',
            'Диаграмма направленности': 'Кардиоидная',
            'Частотный диапазон': '20 Гц – 20 кГц',
            'Особенности': 'Сенсорная кнопка mute, регулируемая подставка',
            'Совместимость': 'Windows, macOS',
        },
    },
    {
        'name': 'SteelSeries QcK Medium',
        'category': 'mousepad',
        'price': 599,
        'stock': 30,
        'description': 'Классический игровой коврик с тканевой поверхностью высокой плотности '
                       'и нескользящей резиновой основой.',
        'specifications': {
            'Размер': '320 × 270 × 2 мм',
            'Материал поверхности': 'Ткань',
            'Основа': 'Противоскользящая резина',
        },
    },
    {
        'name': 'Razer Gigantus V2',
        'category': 'mousepad',
        'price': 899,
        'stock': 22,
        'description': 'Большой коврик с плотной тканевой поверхностью для плавного скольжения '
                       'и толстой пенополиуретановой основой.',
        'specifications': {
            'Размер': '450 × 400 × 4 мм',
            'Материал поверхности': 'Ткань',
            'Основа': 'Пена с текстурой',
        },
    },
    {
        'name': 'Logitech C920 HD Pro',
        'category': 'accessories',
        'price': 2799,
        'stock': 8,
        'description': 'Веб-камера Full HD 1080p со стереомикрофонами, автофокусом '
                       'и коррекцией освещения — для стримов и видеосвязи.',
        'specifications': {
            'Разрешение': 'Full HD 1080p / 30 кадров/с',
            'Микрофон': 'Стерео, два микрофона',
            'Фокус': 'Автофокус',
            'Крепление': 'Универсальное, штатив 1/4"',
            'Совместимость': 'Windows, macOS, ChromeOS',
        },
    },
    {
        'name': 'HyperX ChargePlay Duo',
        'category': 'accessories',
        'price': 1299,
        'stock': 7,
        'description': 'Док-станция для одновременной зарядки двух контроллеров '
                       'с индикацией уровня заряда.',
        'specifications': {
            'Совместимость': 'Xbox Series X|S, Xbox One',
            'Заряжаемых устройств': '2 одновременно',
            'Индикация': 'Светодиодная',
            'Питание': 'USB / сеть',
        },
    },
]


class Command(BaseCommand):
    help = 'Заполнить базу демонстрационными категориями и товарами (безопасно при повторном запуске).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--if-empty',
            action='store_true',
            help='Заполнять только если в базе ещё нет ни одного товара '
                 '(сохраняет правки, сделанные через админ-панель).',
        )

    def handle(self, *args, **options):
        if options['if_empty'] and Product.objects.exists():
            self.stdout.write('В базе уже есть товары — заполнение пропущено.')
            return

        created_categories = 0
        for data in CATEGORIES:
            category, created = Category.objects.get_or_create(
                slug=data['slug'],
                defaults={
                    'name': data['name'],
                    'description': data['description'],
                },
            )
            if created:
                created_categories += 1
            else:
                category.description = data['description']
                category.save(update_fields=['description'])

        created_products = 0
        updated_products = 0
        for data in PRODUCTS:
            category = Category.objects.get(slug=data['category'])
            defaults = {
                'name': data['name'],
                'description': data['description'],
                'price': data['price'],
                'stock': data['stock'],
                'is_featured': data.get('is_featured', False),
                'specifications': data['specifications'],
                'is_available': True,
            }
            product, created = Product.objects.update_or_create(
                slug=slugify(data['name']) or data['name'].lower().replace(' ', '-'),
                defaults={**defaults, 'category': category},
            )
            if created:
                created_products += 1
            else:
                updated_products += 1

        created_coupons = 0
        for data in COUPONS:
            _coupon, created = Coupon.objects.get_or_create(
                code=data['code'],
                defaults={
                    'kind': data['kind'],
                    'value': data['value'],
                    'min_total': data['min_total'],
                    'usage_limit': data['usage_limit'],
                },
            )
            if created:
                created_coupons += 1

        self.stdout.write(self.style.SUCCESS(
            f'Готово: категорий создано {created_categories}, '
            f'товаров создано {created_products}, обновлено {updated_products}, '
            f'промокодов создано {created_coupons}.'
        ))
