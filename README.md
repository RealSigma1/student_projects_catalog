# Collaborative Platform for Student Projects

Веб-приложение для публикации студенческих проектов, поиска команды и управления откликами. Проект реализован на `FastAPI` с фронтендом на `HTML/CSS/JavaScript`, хранением данных в `SQLite` и авторизацией через `OAuth2 Password Bearer + JWT`.

## Возможности

- регистрация и вход по `username` или `email`
- bearer-аутентификация через `JWT`
- профиль пользователя с именем, био, ролями, навыками, ссылками и фото
- публикация проектов с описанием, тегами, ролями, ссылками и контактами
- каталог проектов с поиском, фильтрацией, сортировкой и пагинацией
- отклики на проекты
- уведомления о новых откликах и смене статуса заявки
- архивирование проектов
- ограничение доступа к архивным проектам: публично видны только активные
- отдельные страницы каталога, профиля, карточки проекта и создания проекта
- набор API-тестов на основные сценарии

## Стек

- `Python 3.11`
- `FastAPI`
- `SQLAlchemy`
- `SQLite`
- `bcrypt`
- `Uvicorn`
- `pytest`

## Структура проекта

```text
temp_stud_proj/
├── app/
│   ├── auth.py
│   ├── config.py
│   ├── database.py
│   ├── errors.py
│   ├── models.py
│   ├── schemas.py
│   ├── serializers.py
│   ├── services.py
│   ├── utils.py
│   └── routers/
│       ├── auth.py
│       ├── notifications.py
│       ├── pages.py
│       ├── profile.py
│       └── projects.py
├── static/
│   ├── auth.js
│   ├── create_project.html
│   ├── index.html
│   ├── login.html
│   ├── notifications.js
│   ├── profile.html
│   ├── project.html
│   ├── register.html
│   └── theme.css
├── tests/
│   ├── conftest.py
│   └── test_api.py
├── Dockerfile
├── docker-compose.yml
├── main.py
└── requirements.txt
```

## Архитектура

- [main.py](C:\Users\Admin\Desktop\temp_stud_proj\main.py) содержит только точку входа и экспорт `app`.
- [app/__init__.py](C:\Users\Admin\Desktop\temp_stud_proj\app\__init__.py) собирает приложение, подключает роутеры и статику.
- [app/config.py](C:\Users\Admin\Desktop\temp_stud_proj\app\config.py) хранит конфигурацию и переменные окружения.
- [app/database.py](C:\Users\Admin\Desktop\temp_stud_proj\app\database.py) отвечает за подключение к БД и инициализацию схемы.
- [app/models.py](C:\Users\Admin\Desktop\temp_stud_proj\app\models.py) содержит модели `User`, `Project`, `Application`, `Notification`.
- [app/schemas.py](C:\Users\Admin\Desktop\temp_stud_proj\app\schemas.py) содержит схемы валидации запросов.
- [app/auth.py](C:\Users\Admin\Desktop\temp_stud_proj\app\auth.py) реализует `OAuth2 Password Bearer`, JWT и зависимости авторизации.
- [app/routers](C:\Users\Admin\Desktop\temp_stud_proj\app\routers) разделяет API и page routes по областям ответственности.

## Основные сущности

- `User`
  Поля: `username`, `email`, `hashed_password`, `full_name`, `bio`, `skills`, `roles`, `links`, `photo_url`
- `Project`
  Поля: `title`, `description`, `tags`, `required_roles`, `github_url`, `demo_url`, `contact_info`, `status`, `owner_id`
- `Application`
  Поля: `project_id`, `applicant_id`, `message`, `status`
- `Notification`
  Поля: `user_id`, `type`, `title`, `message`, `is_read`

## Локальный запуск

### 1. Создать виртуальное окружение

```powershell
cd C:\Users\Admin\Desktop\temp_stud_proj
python -m venv .venv
```

### 2. Установить зависимости

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Запустить сервер

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

После запуска приложение будет доступно по адресу:

[http://127.0.0.1:8000](http://127.0.0.1:8000)

## Запуск тестов

```powershell
cd C:\Users\Admin\Desktop\temp_stud_proj
.\.venv\Scripts\python.exe -m pytest -v
```

Тесты используют временную изолированную SQLite-базу и не трогают рабочую `projects.db`.

## Что покрывают тесты

- регистрация и вход
- выдача bearer token
- доступ к защищённым маршрутам
- обновление профиля и загрузка фото
- создание и просмотр проектов
- скрытие архивных проектов от посторонних
- отклики на проекты
- уведомления и mark-as-read
- права доступа владельца и обычного пользователя
- сортировка, фильтрация и пагинация каталога

## Переменные окружения

Проект читает `.env` из корня. Основные переменные:

```env
APP_SECRET=replace-with-a-long-random-secret
ACCESS_TOKEN_TTL_HOURS=72
APP_DATA_DIR=./runtime
DATABASE_PATH=./runtime/projects.db
MEDIA_DIR=./runtime/media
MAX_PROFILE_PHOTO_BYTES=5242880
COOKIE_SECURE=false
```

## Основные маршруты API

### Auth

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/token`
- `POST /api/auth/logout`
- `GET /api/me`

### Profile

- `GET /api/profile/me`
- `PUT /api/profile/me`
- `POST /api/profile/me/photo`
- `GET /api/profile/{username}`

### Projects

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{project_id}`
- `PUT /api/projects/{project_id}`
- `DELETE /api/projects/{project_id}`

### Applications

- `POST /api/projects/{project_id}/applications`
- `GET /api/projects/{project_id}/applications`
- `PATCH /api/applications/{application_id}`
- `GET /api/applications/me`

### Notifications

- `GET /api/notifications`
- `POST /api/notifications/{notification_id}/read`

## Frontend

Интерфейс построен на статических страницах:

- [static/index.html](C:\Users\Admin\Desktop\temp_stud_proj\static\index.html) — каталог проектов
- [static/create_project.html](C:\Users\Admin\Desktop\temp_stud_proj\static\create_project.html) — создание проекта
- [static/profile.html](C:\Users\Admin\Desktop\temp_stud_proj\static\profile.html) — профиль пользователя
- [static/project.html](C:\Users\Admin\Desktop\temp_stud_proj\static\project.html) — карточка проекта
- [static/login.html](C:\Users\Admin\Desktop\temp_stud_proj\static\login.html) — вход
- [static/register.html](C:\Users\Admin\Desktop\temp_stud_proj\static\register.html) — регистрация

Bearer token на клиенте хранится в `localStorage` через [static/auth.js](C:\Users\Admin\Desktop\temp_stud_proj\static\auth.js).



