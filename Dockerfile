# Устанавливаем базовый образ
FROM python:3.11-slim-bullseye

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install -r requirements.txt

# Копируем все файлы приложения в контейнер
COPY . .

RUN mkdir images logs

# Устанавливаем рабочую директорию
#WORKDIR /puller

# Открываем порт 5005 для взаимодействия с приложением
EXPOSE 5005

# Запускаем приложение
CMD ["python", "pull.py"]
