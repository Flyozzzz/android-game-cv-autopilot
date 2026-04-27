"""
Генерация данных для регистрации Google-аккаунта.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass


FIRST_NAMES = [
    "Alex", "Nikita", "Daniil", "Roman", "Artem", "Ivan", "Maksim", "Kirill",
    "Andrey", "Pavel", "Mikhail", "Egor", "Timur", "Sergey", "Denis",
]

LAST_NAMES = [
    "Ivanov", "Petrov", "Sidorov", "Smirnov", "Kuznetsov", "Popov", "Volkov",
    "Sokolov", "Lebedev", "Morozov", "Novikov", "Fedorov", "Orlov",
]


@dataclass
class GeneratedCredentials:
    first_name: str
    last_name: str
    username: str
    full_email: str
    password: str
    birth_day: int
    birth_month: int
    birth_year: int
    gender: str


def _rand_digits(n: int) -> str:
    return "".join(random.choice(string.digits) for _ in range(n))


def _generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    core = "".join(random.choice(alphabet) for _ in range(11))
    # Добавляем символ для соответствия типичным правилам сложности
    return core + "!"


def generate_google_credentials() -> GeneratedCredentials:
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    username = f"{first.lower()}{last.lower()}{_rand_digits(4)}"
    full_email = f"{username}@gmail.com"
    password = _generate_password()

    # 20-36 лет — обычно безопасный диапазон для регистрации
    year = random.randint(1989, 2005)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    gender = random.choice(["Male", "Female"])

    return GeneratedCredentials(
        first_name=first,
        last_name=last,
        username=username,
        full_email=full_email,
        password=password,
        birth_day=day,
        birth_month=month,
        birth_year=year,
        gender=gender,
    )
"""
Генератор учётных данных для новых Google-аккаунтов.
Создаёт реалистичные имена, email, пароли.
"""
import random
import string
import time


# Пулы имён для генерации (реалистичные английские имена)
FIRST_NAMES_MALE = [
    "James", "John", "Robert", "Michael", "David", "William", "Richard",
    "Joseph", "Thomas", "Christopher", "Charles", "Daniel", "Matthew",
    "Anthony", "Mark", "Steven", "Paul", "Andrew", "Joshua", "Kevin",
    "Brian", "Edward", "Ronald", "Timothy", "Jason", "Jeffrey", "Ryan",
    "Jacob", "Gary", "Nicholas", "Eric", "Jonathan", "Stephen", "Larry",
    "Justin", "Scott", "Brandon", "Benjamin", "Samuel", "Raymond",
]

FIRST_NAMES_FEMALE = [
    "Mary", "Patricia", "Jennifer", "Linda", "Barbara", "Elizabeth",
    "Susan", "Jessica", "Sarah", "Karen", "Lisa", "Nancy", "Betty",
    "Margaret", "Sandra", "Ashley", "Dorothy", "Kimberly", "Emily",
    "Donna", "Michelle", "Carol", "Amanda", "Melissa", "Deborah",
    "Stephanie", "Rebecca", "Sharon", "Laura", "Cynthia", "Kathleen",
    "Amy", "Angela", "Shirley", "Anna", "Brenda", "Pamela", "Emma",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
]


class CredentialsGenerator:
    """Генерирует полный набор данных для регистрации Google-аккаунта."""

    def __init__(self):
        self._generated = None

    def generate(self) -> dict:
        """
        Сгенерировать полный набор учётных данных.

        Возвращает:
        {
            "first_name": "John",
            "last_name": "Smith",
            "email_username": "johnsmith8472",
            "full_email": "johnsmith8472@gmail.com",
            "password": "Kx9$mPqW2!nB",
            "birth_year": "1995",
            "birth_month": "03",     # March
            "birth_day": "15",
            "gender": "male",
        }
        """
        # Пол
        gender = random.choice(["male", "female"])

        # Имя
        if gender == "male":
            first_name = random.choice(FIRST_NAMES_MALE)
        else:
            first_name = random.choice(FIRST_NAMES_FEMALE)

        last_name = random.choice(LAST_NAMES)

        # Gmail local part: только a-z, 0-9 и точка (подчёркивание запрещено).
        # Use a high-entropy numeric suffix: short 4-digit suffixes collide too
        # often with common first/last names and Google may keep the flow on the
        # username page while local ADB XML is unavailable.
        suffix = random.randint(10_000_000_000, 99_999_999_999)
        separator = random.choice(["", "."])
        email_username = f"{first_name.lower()}{separator}{last_name.lower()}{suffix}"

        # Пароль (сложный, 12-16 символов)
        password = self._generate_password()

        # Дата рождения (18-40 лет)
        birth_year = str(random.randint(1985, 2006))
        birth_month = str(random.randint(1, 12)).zfill(2)
        birth_day = str(random.randint(1, 28)).zfill(2)

        self._generated = {
            "first_name": first_name,
            "last_name": last_name,
            "email_username": email_username,
            "full_email": f"{email_username}@gmail.com",
            "password": password,
            "birth_year": birth_year,
            "birth_month": birth_month,
            "birth_day": birth_day,
            "birth_month_index": int(birth_month),  # 1-12 для выбора из списка
            "gender": gender,
            "generated_at": time.time(),
        }

        return self._generated

    @staticmethod
    def _generate_password(length: int = 14) -> str:
        """
        Генерация безопасного пароля.
        Содержит: заглавные, строчные, цифры, спецсимволы.
        """
        lower = string.ascii_lowercase
        upper = string.ascii_uppercase
        digits = string.digits
        # ADB-stable special only. Other symbols may be accepted by Google but
        # have caused local `adb shell input text` to leave the WebView password
        # in a visibly invalid/weak state on Android 16.
        special = "!"

        # Гарантируем хотя бы по одному из каждого типа
        password = [
            random.choice(upper),
            random.choice(upper),
            random.choice(lower),
            random.choice(lower),
            random.choice(lower),
            random.choice(digits),
            random.choice(digits),
            random.choice(digits),
            random.choice(special),
        ]

        # Добаваляем до нужной длины
        all_chars = lower + upper + digits + special
        while len(password) < length:
            password.append(random.choice(all_chars))

        random.shuffle(password)
        return "".join(password)

    @property
    def last_generated(self) -> dict:
        return self._generated


# Месяцы для Google-формы (английские названия)
MONTHS = [
    "January", "February", "March", "April",
    "May", "June", "July", "August",
    "September", "October", "November", "December",
]