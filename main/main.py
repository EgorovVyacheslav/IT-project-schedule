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
import tkinter as tk
from tkinter import ttk, scrolledtext
from tkinter.messagebox import showinfo


class MAIScheduleApp:
    def __init__(self, root, parser):
        self.root = root
        self.parser = parser
        self.setup_ui()

    def setup_ui(self):
        self.root.title("Парсер расписания МАИ")
        self.root.geometry("800x600")
        self.root.resizable(True, True)

        # Стили
        style = ttk.Style()
        style.configure('TFrame', background='#f0f0f0')
        style.configure('TLabel', background='#f0f0f0', font=('Arial', 10))
        style.configure('TButton', font=('Arial', 10))
        style.configure('Header.TLabel', font=('Arial', 12, 'bold'))

        # Главный контейнер
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Верхняя панель ввода
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X, pady=5)

        ttk.Label(input_frame, text="Номер группы:").grid(row=0, column=0, padx=5, sticky=tk.W)
        self.group_entry = ttk.Entry(input_frame, width=20)
        self.group_entry.grid(row=0, column=1, padx=5)
        self.group_entry.insert(0, "М8О-104БВ-24")  # Пример по умолчанию

        ttk.Label(input_frame, text="Номер недели:").grid(row=0, column=2, padx=5, sticky=tk.W)
        self.week_entry = ttk.Entry(input_frame, width=5)
        self.week_entry.grid(row=0, column=3, padx=5)
        self.week_entry.insert(0, "1")  # Пример по умолчанию

        fetch_btn = ttk.Button(input_frame, text="Получить расписание", command=self.fetch_schedule)
        fetch_btn.grid(row=0, column=4, padx=10)

        # Панель информации о группе
        self.info_frame = ttk.LabelFrame(main_frame, text="Информация о группе", padding=10)
        self.info_frame.pack(fill=tk.X, pady=5)

        ttk.Label(self.info_frame, text="Институт:").grid(row=0, column=0, sticky=tk.W)
        self.institute_label = ttk.Label(self.info_frame, text="")
        self.institute_label.grid(row=0, column=1, sticky=tk.W)

        ttk.Label(self.info_frame, text="Тип обучения:").grid(row=1, column=0, sticky=tk.W)
        self.education_label = ttk.Label(self.info_frame, text="")
        self.education_label.grid(row=1, column=1, sticky=tk.W)

        ttk.Label(self.info_frame, text="Курс:").grid(row=2, column=0, sticky=tk.W)
        self.course_label = ttk.Label(self.info_frame, text="")
        self.course_label.grid(row=2, column=1, sticky=tk.W)

        # Область вывода расписания
        schedule_frame = ttk.LabelFrame(main_frame, text="Расписание", padding=10)
        schedule_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.schedule_text = scrolledtext.ScrolledText(
            schedule_frame,
            wrap=tk.WORD,
            width=80,
            height=20,
            font=('Consolas', 10)
        )
        self.schedule_text.pack(fill=tk.BOTH, expand=True)

        # Нижняя панель кнопок
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=5)

        self.add_to_calendar_btn = ttk.Button(
            button_frame,
            text="Добавить в Google Calendar",
            state=tk.DISABLED,
            command=self.add_to_calendar
        )
        self.add_to_calendar_btn.pack(side=tk.RIGHT, padx=5)

        ttk.Button(button_frame, text="Очистить", command=self.clear_schedule).pack(side=tk.RIGHT, padx=5)

        # Переменные для хранения данных
        self.current_schedule = None
        self.group_info = None

    def fetch_schedule(self):
        group = self.group_entry.get().strip()
        week = self.week_entry.get().strip()

        if not group or not week:
            showinfo("Ошибка", "Введите номер группы и недели")
            return

        try:
            # Декодируем информацию о группе
            inst_num, edu_type, course = self.parser.decode_group(group)

            # Обновляем информацию о группе
            self.institute_label.config(text=f"Институт №{inst_num}")
            self.education_label.config(text=edu_type)
            self.course_label.config(text=course)

            # Получаем расписание
            self.group_info = {
                'group': group,
                'week': week,
                'institute': f"Институт №{inst_num}",
                'course': course,
                'education_type': edu_type
            }

            # Проверяем кэш и базу данных
            cached = self.parser.get_cached_schedule(group, week)
            db_schedule = self.parser.db.get_schedule(group, week)

            if cached:
                self.current_schedule = cached["schedule"]
                self.display_schedule()
                self.add_to_calendar_btn.config(state=tk.NORMAL)
                showinfo("Успех", "Расписание загружено из кэша")
                return

            if db_schedule:
                self.current_schedule = db_schedule
                self.display_schedule()
                self.add_to_calendar_btn.config(state=tk.NORMAL)
                showinfo("Успех", "Расписание загружено из базы данных")
                return

            # Если нет в кэше и БД, загружаем с сайта
            self.schedule_text.delete(1.0, tk.END)
            self.schedule_text.insert(tk.END, "Загрузка расписания... Пожалуйста, подождите...")
            self.root.update()

            html = self.parser.fetch_schedule(
                group, week,
                f"Институт №{inst_num}",
                course,
                edu_type
            )

            if html:
                self.current_schedule = self.parser.parse_schedule(html)
                self.parser.save_to_cache(group, week, {
                    "education_type": edu_type,
                    "schedule": self.current_schedule
                })
                self.parser.db.save_schedule(self.group_info, self.current_schedule)
                self.display_schedule()
                self.add_to_calendar_btn.config(state=tk.NORMAL)
                showinfo("Успех", "Расписание успешно загружено")
            else:
                showinfo("Ошибка", "Не удалось загрузить расписание")

        except Exception as e:
            showinfo("Ошибка", f"Произошла ошибка: {str(e)}")

    def display_schedule(self):
        if not self.current_schedule:
            return

        self.schedule_text.delete(1.0, tk.END)

        for day in self.current_schedule:
            self.schedule_text.insert(tk.END, f"\n{day['date']}\n", 'header')
            self.schedule_text.insert(tk.END, "-" * 60 + "\n")

            if not day['lessons']:
                self.schedule_text.insert(tk.END, "Нет занятий\n")
                continue

            for i, lesson in enumerate(day['lessons'], 1):
                self.schedule_text.insert(tk.END, f"\nЗанятие {i}:\n")
                self.schedule_text.insert(tk.END, f"Время: {lesson['time']}\n")
                self.schedule_text.insert(tk.END, f"Предмет: {lesson['subject']}\n")
                self.schedule_text.insert(tk.END, f"Тип: {lesson['type']}\n")
                self.schedule_text.insert(tk.END, f"Преподаватель: {lesson['teacher']}\n")
                self.schedule_text.insert(tk.END, f"Аудитория: {lesson['classroom']}\n")

            self.schedule_text.insert(tk.END, "-" * 60 + "\n")

        # Настройка тегов для форматирования
        self.schedule_text.tag_config('header', foreground='blue', font=('Arial', 11, 'bold'))

    def add_to_calendar(self):
        if not self.current_schedule or not self.group_info:
            showinfo("Ошибка", "Сначала загрузите расписание")
            return

        group = self.group_info['group']
        try:
            self.parser._add_to_google_calendar(group, self.current_schedule)
            showinfo("Успех", "Расписание добавлено в Google Calendar")
        except Exception as e:
            showinfo("Ошибка", f"Не удалось добавить в календарь: {str(e)}")

    def clear_schedule(self):
        self.schedule_text.delete(1.0, tk.END)
        self.current_schedule = None
        self.group_info = None
        self.add_to_calendar_btn.config(state=tk.DISABLED)
        self.institute_label.config(text="")
        self.education_label.config(text="")
        self.course_label.config(text="")

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
            pass


class MAIScheduleDB:
    def __init__(self, db_name='schedule.db'):
        self.db_name = db_name
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,  
                    institute TEXT,              
                    course INTEGER,              
                    education_type TEXT          
                )
            ''')

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

            cursor.execute('''
                INSERT OR IGNORE INTO groups (name, institute, course, education_type)
                VALUES (?, ?, ?, ?)
            ''', (
                group_info['group'],
                group_info.get('institute'),
                group_info.get('course'),
                group_info.get('education_type')
            ))

            cursor.execute('SELECT id FROM groups WHERE name = ?', (group_info['group'],))
            group_id = cursor.fetchone()[0]

            for day in schedule_data:
                datetime_str = f"{day['date']}"

                for lesson in day['lessons']:
                    time_parts = lesson.get('time', '').split(' – ')
                    time_str = '-'.join(time_parts) if len(time_parts) > 1 else lesson.get('time', '')

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

    def get_schedule(self, group_name, week_number=None):
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, name, institute, course, education_type 
                FROM groups 
                WHERE name = ?
            ''', (group_name,))
            group_data = cursor.fetchone()

            if not group_data:
                return None

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
    def __init__(self):
        self.cache_dir = "schedule_cache"
        os.makedirs(self.cache_dir, exist_ok=True)

        chrome_options = Options()
        chrome_options.add_argument("--headless")
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

        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.javascript": 1,
            "profile.default_content_setting_values.notifications": 2,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False
        }
        chrome_options.add_experimental_option("prefs", prefs)

        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )

        self.driver.set_page_load_timeout(30)
        self.driver.implicitly_wait(5)
        self.db = MAIScheduleDB()
        self.gcal = GoogleCalendarManager()

    def parse_schedule(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        schedule = []

        days = soup.find_all('div', class_='step-content')

        for day in days:
            date_element = day.find('span', class_='step-title')
            date = date_element.get_text(strip=True) if date_element else "Дата не указана"

            lessons = []
            for lesson in day.find_all('div', class_='mb-4'):
                time_element = lesson.find('li', class_='list-inline-item')
                time = time_element.get_text(strip=True) if time_element else "Время не указано"

                subject_element = lesson.find('p', class_='mb-2 fw-semi-bold text-dark')
                subject1 = subject_element.get_text(strip=True)[:-2] if subject_element else "Предмет не указан"

                subject_el2 = lesson.find('span', class_='text-nowrap')
                subject2 = subject_el2.get_text(strip=True)[:-2] if subject_el2 else ""
                subject = subject1.replace(subject2, "", 1) + " " + subject2

                teacher_element = lesson.find('a', class_='text-body')
                teacher = teacher_element.get_text(strip=True) if teacher_element else "Преподаватель не указан"

                type_element = lesson.find('span', class_='badge')
                lesson_type = type_element.get_text(strip=True) if type_element else "Тип не указан"

                text_nodes = lesson.find_all(string=True)
                candidates = [text.strip() for text in text_nodes if '-' in text.strip()]

                classroom = "Не указана"
                for i in candidates:
                    if any([j in "012345689" for j in i]):
                        classroom = i

                lessons.append({
                    "time": time,
                    "subject": subject,
                    "teacher": teacher,
                    "type": lesson_type,
                    "classroom": classroom
                })

            schedule.append({
                "date": date,
                "lessons": lessons
            })

        return schedule

    def get_cached_schedule(self, group, week):
        cache_file = os.path.join(self.cache_dir, f"{group}_week{week}.json")
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def save_to_cache(self, group, week, schedule):
        cache_file = os.path.join(self.cache_dir, f"{group}_week{week}.json")
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)

    def click_week_button(self):
        try:
            week_button = WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.XPATH,
                                                "//a[contains(@class, 'btn-outline-primary') and contains(., 'Выбрать учебную неделю')]"))
            )

            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});",
                                       week_button)
            time.sleep(1)

            self.driver.execute_script("arguments[0].style.border = '2px solid red';", week_button)
            time.sleep(0.5)

            self.driver.execute_script("arguments[0].click();", week_button)

            WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "collapseWeeks")))
            return True

        except Exception as e:
            return False

    def fetch_schedule(self, group, week, faculty_name, course_number, education_type):
        try:
            self.driver.get("https://mai.ru/education/studies/schedule/")

            try:
                cookie_banner = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.ID, "cookie_message"))
                )
                accept_button = cookie_banner.find_element(By.XPATH, ".//button[contains(text(), 'Принять')]")
                accept_button.click()
                time.sleep(1)
            except:
                pass

            department_select = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "department"))
            )
            department_select.click()

            try:
                department_option = self.driver.find_element(By.XPATH,
                                                             f"//select[@id='department']/option[contains(text(), '{faculty_name}')]")
                department_option.click()
            except:
                pass

            course_select = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "course"))
            )
            course_select.click()

            try:
                course_option = self.driver.find_element(By.XPATH,
                                                         f"//select[@id='course']/option[@value='{course_number}']")
                course_option.click()
            except:
                pass

            show_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Отобразить')]"))
            )
            show_button.click()
            time.sleep(2)

            nav_tabs = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "nav-segment"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", nav_tabs)
            time.sleep(1)

            education_tab = self.driver.find_element(By.XPATH, f"//a[contains(text(), '{education_type}')]")
            self.driver.execute_script("arguments[0].click();", education_tab)

            time.sleep(1)

            group_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, f"//a[contains(@href, 'group={group}')]"))
            )
            group_button.click()

            self.click_week_button()

            week_element = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH,
                                            f"//div[@id='collapseWeeks']//a[contains(@href, 'week={week}')]"))
            )
            week_element.click()

            return self.driver.page_source
        except Exception as e:
            return None

    def decode_group(self, group):
        group = group.split("-")
        inst = ""
        type_obr = ""
        course = ""

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

        course = group[1][0]

        for i in group[0]:
            if i in "0123456789":
                inst += i

        return (inst, type_obr, course)

    def _parse_date(self, date_str):
        months = {
            'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04',
            'мая': '05', 'июня': '06', 'июля': '07', 'августа': '08',
            'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12'
        }

        try:
            date_part = date_str.split(',')[-1].strip()
            parts = date_part.split()
            if len(parts) == 2:
                day, month_name = parts
            else:
                date_part = date_str.split(',')[0].strip()
                day, month_name = date_part.split()[-2:]

            month = months.get(month_name.lower(), '01')
            day = day.zfill(2)
            year = datetime.now().year

            parsed_date = f"{year}-{month}-{day}"
            return parsed_date
        except Exception as e:
            return datetime.now().strftime("%Y-%m-%d")

    def _parse_time(self, time_str):
        try:
            time_str = time_str.replace(' ', '').replace('–', '-').replace('—', '-')
            start_time, end_time = time_str.split('-')
            return f"{start_time}:00", f"{end_time}:00"
        except Exception as e:
            return "09:00:00", "10:30:00"

    def _add_to_google_calendar(self, group_name, schedule_data):
        self.gcal.clear_old_events()

        for lesson_day in schedule_data:
            original_date = lesson_day['date']
            try:
                date_str = self._parse_date(original_date)

                for lesson in lesson_day['lessons']:
                    try:
                        start_time, end_time = self._parse_time(lesson['time'])
                        start_datetime = f"{date_str}T{start_time}+03:00"
                        end_datetime = f"{date_str}T{end_time}+03:00"

                        self.gcal.create_event(
                            summary=f"{lesson.get('subject', 'Занятие')} ({lesson.get('type', '')})",
                            start_time=start_datetime,
                            end_time=end_datetime,
                            description=f"Группа: {group_name}\nПреподаватель: {lesson.get('teacher', 'не указан')}",
                            location=f"Аудитория: {lesson.get('classroom', 'не указана')}"
                        )

                    except Exception as e:
                        continue

            except Exception as e:
                continue

    def run(self):
        root = tk.Tk()
        app = MAIScheduleApp(root, self)
        root.mainloop()


if __name__ == "__main__":
    parser = MAIScheduleParser()
    parser.run()
