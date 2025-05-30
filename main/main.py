import json
import os
import time
import sqlite3
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pytz
import os

# Настройки Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']
CALENDAR_ID = 'primary'
TIMEZONE = 'Europe/Moscow'

class GoogleCalendarManager:
    def __init__(self):
        self.creds = None
        self.service = None
        self._authenticate()

    def _authenticate(self):
        if os.path.exists('token.json'):
            self.creds = Credentials.from_authorized_user_file('token.json', SCOPES)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                credentials_path = os.path.join(os.path.dirname(__file__), 'credentials.json')
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                self.creds = flow.run_local_server(port=0)

            with open('token.json', 'w') as token:
                token.write(self.creds.to_json())

        self.service = build('calendar', 'v3', credentials=self.creds)

    def create_event(self, summary, start_time, end_time, description=None, location=None, reminders=True):
        event = {
            'summary': summary,
            'start': {
                'dateTime': start_time,
                'timeZone': TIMEZONE,
            },
            'end': {
                'dateTime': end_time,
                'timeZone': TIMEZONE,
            },
            'description': description,
            'location': location,
        }

        if reminders:
            event['reminders'] = {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 10},  # Напоминание за 10 минут
                ],
            }

        try:
            event = self.service.events().insert(
                calendarId=CALENDAR_ID,
                body=event,
                sendNotifications=True
            ).execute()
            return event.get('htmlLink')
        except Exception as e:
            print(f"Ошибка при создании события: {e}")
            return None

    def clear_old_events(self, days_to_keep=14):
        now = datetime.now(pytz.timezone(TIMEZONE))
        time_min = (now - timedelta(days=days_to_keep)).isoformat()

        try:
            events_result = self.service.events().list(
                calendarId=CALENDAR_ID,
                timeMin=time_min,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])

            for event in events:
                if 'summary' in event and 'расписание МАИ' in event['summary']:
                    self.service.events().delete(
                        calendarId=CALENDAR_ID,
                        eventId=event['id']
                    ).execute()
        except Exception as e:
            print(f"Ошибка при удалении старых событий: {e}")


class MAIScheduleDB:
    """
    Класс для работы с базой данных SQLite.
    Хранит информацию о группах и их расписании.
    """
    def __init__(self, db_name='schedule.db'):
        self.db_name = db_name
        self._init_db()  # Инициализация базы данных при создании


    #эта функция создаёт таблицу, если её не существует
    def _init_db(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            # Таблица групп
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,  
                    institute TEXT,              
                    course INTEGER,              
                    education_type TEXT          
                )
            ''')

            # Таблица расписания
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS schedule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER,
                    week_number INTEGER,
                    datetime TEXT,
                    time TEXT,
                    subject TEXT,
                    teacher TEXT,
                    classroom TEXT, 
                    lesson_type TEXT,
                    FOREIGN KEY (group_id) REFERENCES groups (id),
                    UNIQUE(group_id, week_number, datetime, time)
                )
            ''')
            conn.commit()

    def save_schedule(self, group_info, schedule_data):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()

            # Добавляем группу, если ее нет в базе
            cursor.execute('''
                INSERT OR IGNORE INTO groups (name, institute, course, education_type)
                VALUES (?, ?, ?, ?)
            ''', (
                group_info['group'],
                group_info.get('institute'),
                group_info.get('course'),
                group_info.get('education_type')
            ))

            # Получаем ID группы
            cursor.execute('SELECT id FROM groups WHERE name = ?', (group_info['group'],))
            group_id = cursor.fetchone()[0]

            # Сохраняем каждое занятие
            for day in schedule_data:
                datetime_str = f"{day['date']}"

                for lesson in day['lessons']:
                    # Форматируем время (заменяем разделитель на дефис)
                    time_parts = lesson.get('time', '').split(' – ')
                    time_str = '-'.join(time_parts) if len(time_parts) > 1 else lesson.get('time', '')

                    # Вставляем или обновляем запись о занятии
                    cursor.execute('''
                        INSERT OR REPLACE INTO schedule (
                            group_id, week_number, datetime, time,
                            subject, teacher, classroom, lesson_type
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        group_id,
                        group_info['week'],
                        datetime_str,
                        time_str,
                        lesson.get('subject'),
                        lesson.get('teacher'),
                        lesson.get('classroom'),
                        lesson.get('type')
                    ))

            conn.commit()

    #получаем расписание из базы данных
    def get_schedule(self, group_name, week_number=None):
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row  # Возвращать результаты как словари
            cursor = conn.cursor()

            # Получаем информацию о группе
            cursor.execute('''
                SELECT id, name, institute, course, education_type 
                FROM groups 
                WHERE name = ?
            ''', (group_name,))
            group_data = cursor.fetchone()

            if not group_data:
                return None

            # Формируем запрос для получения расписания
            query = '''
                SELECT datetime, time, subject, teacher, 
                       classroom, lesson_type
                FROM schedule s
                WHERE s.group_id = ?
            '''
            params = [group_data['id']]

            if week_number:
                query += ' AND s.week_number = ?'
                params.append(week_number)

            query += ' ORDER BY datetime, time'

            cursor.execute(query, params)
            lessons = [dict(row) for row in cursor.fetchall()]

            # Форматируем результат в тот же формат, что возвращает parse_schedule
            schedule = []
            current_date = None
            day_lessons = []

            for lesson in lessons:
                if lesson['datetime'] != current_date:
                    if current_date is not None:
                        schedule.append({
                            "date": current_date,
                            "lessons": day_lessons.copy()
                        })
                        day_lessons.clear()
                    current_date = lesson['datetime']

                day_lessons.append({
                    "time": lesson['time'],
                    "subject": lesson['subject'],
                    "teacher": lesson['teacher'],
                    "type": lesson['lesson_type'],
                    "classroom": lesson['classroom']
                })

            if current_date is not None:
                schedule.append({
                    "date": current_date,
                    "lessons": day_lessons
                })

            return schedule


class MAIScheduleParser:
    """
    Основной класс парсера расписания МАИ.
    Обеспечивает загрузку, парсинг и обработку расписания.
    """
    def __init__(self):
        self.cache_dir = "schedule_cache"  # Директория для кэширования
        os.makedirs(self.cache_dir, exist_ok=True)

        # Настройки браузера Chrome для Selenium
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Без графического интерфейса
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        # Дополнительные настройки
        prefs = {
            "profile.managed_default_content_settings.images": 2,  # Загрузка изображений
            "profile.managed_default_content_settings.javascript": 1,  # JavaScript
            "profile.default_content_setting_values.notifications": 2,  # Уведомления
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False
        }
        chrome_options.add_experimental_option("prefs", prefs)

        # Инициализация драйвера Chrome
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )

        self.driver.set_page_load_timeout(30)  # Таймаут загрузки страницы(после 30 секунд бездействия, окно закрывается)
        self.driver.implicitly_wait(5)  # Неявное ожидание элементов
        self.db = MAIScheduleDB()  # Экземпляр класса для работы с БД
        self.gcal = GoogleCalendarManager()  # Экземпляр класса для работы с Google Calendar


    #выделяем(парсим) данные из уже готового html, который мы получили с помошью selenium, тыкая по кнопкам сайта
    def parse_schedule(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        schedule = []

        # Находим все дни с занятиями
        days = soup.find_all('div', class_='step-content')

        #обрабатываем каждый день
        for day in days:
            # Извлекаем дату
            date_element = day.find('span', class_='step-title')
            date = date_element.get_text(strip=True) if date_element else "Дата не указана"

            lessons = []
            # Обрабатываем каждое занятие
            for lesson in day.find_all('div', class_='mb-4'):
                # Время занятия
                time_element = lesson.find('li', class_='list-inline-item')
                time = time_element.get_text(strip=True) if time_element else "Время не указано"

                # Название предмета, тут запарная логика: название предмета иногда хранится по частям в двух селекторах
                subject_element = lesson.find('p', class_='mb-2 fw-semi-bold text-dark')
                subject1 = subject_element.get_text(strip=True)[:-2] if subject_element else "Предмет не указан"

                subject_el2 = lesson.find('span', class_='text-nowrap')
                subject2 = subject_el2.get_text(strip=True)[:-2] if subject_el2 else ""
                subject = subject1.replace(subject2, "", 1) + " " + subject2

                # Преподаватель
                teacher_element = lesson.find('a', class_='text-body')
                teacher = teacher_element.get_text(strip=True) if teacher_element else "Преподаватель не указан"

                # Тип занятия (лекция, практика и т.д.)
                type_element = lesson.find('span', class_='badge')
                lesson_type = type_element.get_text(strip=True) if type_element else "Тип не указан"

                # Поиск аудитории: тут сайт тоже не даёт так просто получить номер аудитории, я заметил,
                # что в любых обозначениях аудитории есть символ "-", мы собираем список всех селекторов с этим символом
                # ищим среди них те, где есть цифры(во всех указанных аудиториях есть цифры), чтобы исключить
                # Бояра-созоновича из списка аудиторий
                text_nodes = lesson.find_all(string=True)
                candidates = [text.strip() for text in text_nodes if '-' in text.strip()]

                classroom = "Не указана"
                for i in candidates:
                    if any([j in "012345689" for j in i]):  # Ищем строку с цифрами
                        classroom = i

                # Добавляем занятие в список
                lessons.append({
                    "time": time,
                    "subject": subject,
                    "teacher": teacher,
                    "type": lesson_type,
                    "classroom": classroom
                })

            # Добавляем день в расписание
            schedule.append({
                "date": date,
                "lessons": lessons
            })
            #ВАЖНО: в таком формате словаря у нас в программе хранится расписания, именно такой формат мы передаём в функции

        return schedule


    #выводим расписание
    def print_schedule(self, params, schedule):
        print("\n" + "=" * 60)
        print(f"РАСПИСАНИЕ ГРУППЫ {params['group']}".center(60))
        print(f"Неделя {params['week']}".center(60))
        print("=" * 60 + "\n")

        for day in schedule:
            print(f"\n {day['date']}")
            print("-" * 60)

            if not day['lessons']:
                print("Нет занятий")
                continue

            # Выводим каждое занятие
            for i, lesson in enumerate(day['lessons'], 1):
                print(f"\nЗанятие {i}:")
                print(f"Время: {lesson['time']}")
                print(f"Предмет: {lesson['subject']}")
                print(f"Тип: {lesson['type']}")
                print(f"Преподаватель: {lesson['teacher']}")
                print(f"Аудитория: {lesson['classroom']}")

            print("-" * 60)


    #возвращает расписание из кэша
    def get_cached_schedule(self, group, week):
        cache_file = os.path.join(self.cache_dir, f"{group}_week{week}.json")
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    #сохраняем полученное расписание в json(кэш)
    def save_to_cache(self, group, week, schedule):
        cache_file = os.path.join(self.cache_dir, f"{group}_week{week}.json")
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)


    """
    отдельная функция для нажатия кнопки "выбрать неделю" понадобится в блоке, где мы будем тыкать по кнопочкам через
    selenium, запихана в отдельную функцию так как именно эту кнопку нажимать запарно
    """
    def click_week_button(self):
        try:
            # Ожидаем появления кнопки
            week_button = WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.XPATH,
                                                "//a[contains(@class, 'btn-outline-primary') and contains(., 'Выбрать учебную неделю')]"))
            )

            # Прокручиваем страницу к кнопке
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});",
                                       week_button)
            time.sleep(1)

            # Подсвечиваем кнопку (для отладки)
            self.driver.execute_script("arguments[0].style.border = '2px solid red';", week_button)
            time.sleep(0.5)

            # Кликаем по кнопке
            self.driver.execute_script("arguments[0].click();", week_button)

            # Ожидаем появления меню выбора недели
            WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "collapseWeeks")))
            return True

        except Exception as e:
            print(f"Ошибка при клике по кнопке: {str(e)}")
            return False

    def fetch_schedule(self, group, week, faculty_name, course_number, education_type):
        # в этой функции мы открываем в скрытом режиме хром и тыкаем на кнопочки, заходя на нужную страницу расписания
        try:
            #тут я пытался сделать значёк загрузки но не вышло
            print("[         ]", end="\r")
            self.driver.get("https://mai.ru/education/studies/schedule/")
            print("[-        ]", end="\r")

            # закрываем куки банер
            try:
                cookie_banner = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.ID, "cookie_message"))
                )
                accept_button = cookie_banner.find_element(By.XPATH, ".//button[contains(text(), 'Принять')]")
                accept_button.click()
                print("[--       ]", end="\r")
                time.sleep(1)
            except:
                print("Куки-баннер не найден или уже закрыт")

            # Выбор института
            department_select = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "department"))
            )
            department_select.click()

            try:
                department_option = self.driver.find_element(By.XPATH,
                                                             f"//select[@id='department']/option[contains(text(), '{faculty_name}')]")
                department_option.click()
                print("[---      ]", end="\r")
            except:
                print(f"Институт '{faculty_name}' не найден!")

            # Выбор курса
            course_select = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "course"))
            )
            course_select.click()

            try:
                course_option = self.driver.find_element(By.XPATH,
                                                         f"//select[@id='course']/option[@value='{course_number}']")
                course_option.click()
                print("[----     ]", end="\r")
            except:
                print(f"Курс {course_number} не найден!")

            # Нажатие кнопки "Отобразить"
            show_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Отобразить')]"))
            )
            show_button.click()
            print("[-----    ]", end="\r")
            time.sleep(2)

            # Выбор типа обучения
            nav_tabs = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "nav-segment"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", nav_tabs)
            time.sleep(1)

            education_tab = self.driver.find_element(By.XPATH, f"//a[contains(text(), '{education_type}')]")
            self.driver.execute_script("arguments[0].click();", education_tab)

            print("[------   ]", end="\r")
            time.sleep(1)

            # Выбор группы
            group_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, f"//a[contains(@href, 'group={group}')]"))
            )
            group_button.click()
            print("[-------  ]", end="\r")

            # Выбор недели
            self.click_week_button()
            print("[-------- ]", end="\r")

            week_element = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH,
                                            f"//div[@id='collapseWeeks']//a[contains(@href, 'week={week}')]"))
            )
            week_element.click()
            print("[---------]", end="\r")

            return self.driver.page_source
        except Exception as e:
            print(f"Ошибка при загрузке расписания: {e}")
            return None

    #по группе определяем курс инстетут и тд
    def decode_group(self, group):
        group = group.split("-")
        inst = ""
        type_obr = ""
        course = ""

        # Определение типа обучения по коду группы
        if "БВ" in group[1]:
            type_obr = "Базовое высшее образование"
        if "СВ" in group[1]:
            type_obr = "Специализированное высшее образование"
        if "Бк" in group[1]:
            type_obr = "Бакалавриат"
        if "М" in group[1]:
            type_obr = "Магистратура"
        if "А" in group[1]:
            type_obr = "Аспирантура"

        # Первая цифра в коде группы - курс
        course = group[1][0]

        # Извлекаем номер института из первой части номера группы
        for i in group[0]:
            if i in "0123456789":
                inst += i

        return (inst, type_obr, course)

    #преобразуем дату из формата сайта в страндартный формат
    def _parse_date(self, date_str):
        months = {
            'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04',
            'мая': '05', 'июня': '06', 'июля': '07', 'августа': '08',
            'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12'
        }

        try:
            # Удаляем день недели и запятую
            date_part = date_str.split(',')[-1].strip()

            # Разбиваем на число и месяц
            parts = date_part.split()
            if len(parts) == 2:
                day, month_name = parts
            else:
                # Альтернативный формат, если день недели в конце
                date_part = date_str.split(',')[0].strip()
                day, month_name = date_part.split()[-2:]

            month = months.get(month_name.lower(), '01')
            day = day.zfill(2)
            year = datetime.now().year

            parsed_date = f"{year}-{month}-{day}"
            print(f"Парсинг даты: '{date_str}' -> '{parsed_date}'")  # Отладочный вывод
            return parsed_date
        except Exception as e:
            print(f"Ошибка парсинга даты '{date_str}': {e}")
            return datetime.now().strftime("%Y-%m-%d")

    def _parse_time(self, time_str):
        """
        Преобразует время занятия в стандартный формат
        принимает время как строку в формате '09:00-10:30'
        возвращает Кортеж (время начала, время окончания)
        """
        try:
            # Удаляем лишние пробелы и заменяем разные типы тире
            time_str = time_str.replace(' ', '').replace('–', '-').replace('—', '-')
            start_time, end_time = time_str.split('-')
            return f"{start_time}:00", f"{end_time}:00"
        except Exception as e:
            print(f"Ошибка парсинга времени '{time_str}': {e}")
            return "09:00:00", "10:30:00"

    def _add_to_google_calendar(self, group_name, schedule_data):
        """
        Добавляет расписание в Google Calendar
        принимет Номер группы и Данные расписания
        """
        self.gcal.clear_old_events()  # Очищаем старые события

        for lesson_day in schedule_data:
            original_date = lesson_day['date']
            try:
                date_str = self._parse_date(original_date)
                print(f"\nОбрабатываем: исходная дата '{original_date}' -> преобразованная '{date_str}'")

                # Создаем событие для каждого занятия
                for lesson in lesson_day['lessons']:
                    try:
                        start_time, end_time = self._parse_time(lesson['time'])
                        start_datetime = f"{date_str}T{start_time}+03:00"  # Формат для Google Calendar
                        end_datetime = f"{date_str}T{end_time}+03:00"

                        print(f"Создаем событие на {date_str} {start_time}-{end_time}:")
                        print(f"  Предмет: {lesson.get('subject', 'Без названия')}")
                        print(f"  Аудитория: {lesson.get('classroom', 'не указана')}")

                        # Создаем событие в календаре
                        event_link = self.gcal.create_event(
                            summary=f"{lesson.get('subject', 'Занятие')} ({lesson.get('type', '')})",
                            start_time=start_datetime,
                            end_time=end_datetime,
                            description=f"Группа: {group_name}\nПреподаватель: {lesson.get('teacher', 'не указан')}",
                            location=f"Аудитория: {lesson.get('classroom', 'не указана')}"
                        )

                        if event_link:
                            print(f"✅ Успешно создано: {event_link}")
                        else:
                            print("❌ Не удалось создать событие")

                    except Exception as e:
                        print(f"❌ Ошибка в занятии: {str(e)}")
                        continue

            except Exception as e:
                print(f"❌ Ошибка обработки дня '{original_date}': {str(e)}")
                continue

    def run(self):
        """
        Основной метод для запуска парсера.
        Обрабатывает пользовательский ввод, загружает и отображает расписание.
        """
        print("\n" + "=" * 40)
        print(" ПАРСЕР РАСПИСАНИЯ МАИ ".center(40))
        print("=" * 40 + "\n")

        # Получаем входные данные от пользователя
        group = input("Введите номер группы (например, М8О-104БВ-24): ")
        week = input("Введите номер недели: ")
        dg = self.decode_group(group)  # Анализируем номер группы

        faculty_name = "Институт №" + dg[0]  # Формируем название института
        course_number = dg[2]  # Номер курса
        education_type = dg[1]  # Тип обучения

        # Проверяем кэш
        cached = self.get_cached_schedule(group, week)
        if cached:
             self.print_schedule({"group": group, "week": week, "education_type": cached["education_type"]},
                                 cached["schedule"])
             if input("\nЗагрузить новые данные? (y/n): ").lower() != 'y':
                 if input("Добавить расписание в Google Calendar? (y/n): ").lower() == 'y':
                     self._add_to_google_calendar(group, cached["schedule"])
                 return

        # проверка в базе данных
        db_schedule = self.db.get_schedule(group, week)
        if db_schedule:
            print("\nНайдено расписание в локальной базе данных:")
            self.print_schedule({
                "group": group,
                "week": week,
                "education_type": education_type
            }, db_schedule)

            if input("\nЗагрузить новые данные с сайта? (y/n): ").lower() != 'y':
                if input("Добавить расписание в Google Calendar ? (y/n): ").lower() == 'y':
                    self._add_to_google_calendar(group, db_schedule)
                return

        # Если данных нет в кэше и локальной бд, загружаем с сайта
        print("\nДанные не найдены в кэше, дождитесь загрузки...")
        html = self.fetch_schedule(group, week, faculty_name, course_number, education_type)
        if not html:
            return

        # Парсим HTML и сохраняем результаты
        schedule = self.parse_schedule(html) #его формат - словарь из даты и списка пар

        self.save_to_cache(group, week, {
            "education_type": education_type,
            "schedule": schedule
        })

        # Выводим расписание
        self.print_schedule({
            "group": group,
            "week": week,
            "education_type": education_type
        }, schedule)

        # Сохраняем в базу данных
        group_info = {
            'group': group,
            'week': week,
            'institute': "Институт №" + dg[0],
            'course': course_number,
            'education_type': education_type
        }

        self.db.save_schedule(group_info, schedule)
        print("Данные успешно сохранены в базу данных")

        # Предлагаем добавить в Google Calendar
        if input("\nДобавить расписание в Google Calendar? (y/n): ").lower() == 'y':
            self._add_to_google_calendar(group, schedule)



if __name__ == "__main__":
    # Создаем и запускаем парсер
    parser = MAIScheduleParser()
    parser.run()
