#!/usr/bin/python3

import datetime
import re
import logging
import os
import docker
import zlib
from flask import Flask, request, render_template, send_from_directory, flash, redirect, url_for
import requests
from requests.auth import HTTPBasicAuth

app = Flask(__name__)
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'

client = docker.from_env(timeout=None)
client.login(username="repouser", password="repouser",
             registry='10.3.10.10:5000')

# Configure logging
logging.basicConfig(filename="./logs/log.txt", level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/check', methods=['POST'])
def check():
    # Get the image name from the form
    image_name = request.form['image_name']
    if not image_name:
        flash("Забыли ввести имя образа", "error")
        return redirect(url_for("index"))

    # Check if compressed archive already exists
    short_image_name = image_name.split(':')[0]
    pattern = re.compile(f"{short_image_name}*")
    matches = [f for f in os.listdir("./images") if pattern.match(f)]

    if matches:
        flash(f"Найден архив для {short_image_name}:", "info")
    else:
        flash(f"Ни один архив для {short_image_name}: не найден", "info")

    return render_template('index.html', files=matches)


@app.route('/download_tar/<path:filename>', methods=['GET'])
def download_tar(filename):
    return send_from_directory(directory="./images", path=filename, as_attachment=True)


def compress_chunk(chunk):
    compress_obj = zlib.compressobj(wbits=zlib.MAX_WBITS + 16)
    compressed_chunk = compress_obj.compress(chunk)
    compressed_chunk += compress_obj.flush()
    return compressed_chunk


@app.route("/download", methods=['POST'])
def download():
    # Get the image name and new tag from the form
    image_name = request.form['image_name']
    new_tag = request.form.get('new_tag')
    image_tar_name = f"{image_name.replace('10.3.10.10:5000/', '').replace('path1/', '').replace('path2/', '')}"
    if not image_name:
        flash("Для начала нужно ввести правильное (оригинальное) имя Докер образа и нажать кнопку скачать!", "error")
        return redirect(url_for("index"))
    if not new_tag:
        try:
            new_tag = image_tar_name.split(':')[1]
            short_image_name = image_tar_name.split(':')[0]
            new_image_tag = f"{short_image_name}:{new_tag}"
        except IndexError as e:
            logger.info(
                f"Image: '{image_name}' without tag. Set default tag latest")
            new_tag = "latest"
            new_image_tag = f"{image_name}:{new_tag}"
            image_name = new_image_tag
    else:
        # concatenate the image name and the new tag
        short_image_name = image_tar_name.split(':')[0]
        new_image_tag = f"{short_image_name}:{new_tag}"

    # Check if the tar file already exists and save the image to a tar file if not
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H:%M")
    image_tar_path = f"./images/{image_name.replace(':', '_')}({timestamp}).tar"
    if os.path.exists(image_tar_path):
        logger.info(f"Image: '{image_name}' already exists. Downloading...")
        return send_from_directory("", image_tar_path, as_attachment=True)
    else:
        # Try to pull the image from the registry
        try:
            client.images.pull(image_name)
            logger.info(f"Image: '{image_name}' pulled from registry...")
        except docker.errors.NotFound as e:
            flash(
                f"Ошибка скачивания образа: {image_name}: {e}. Возможно ошибка в имени образа", 'error')
            return redirect(url_for('index'))
        except docker.errors.APIError as e:
            flash(
                f"Ошибка скачивания образа: {image_name}: {e}. Возможно ошибка в имени образа", 'error')
            return redirect(url_for('index'))

    # Changing tag
    if image_name != new_image_tag:
        image = client.images.get(image_name)
        image.tag(new_image_tag)
        client.images.remove(image_name)
        image_name = new_image_tag
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H:%M")
        image_tar_path = f"./images/{image_name.replace(':', '_')}({timestamp}).tar"
        logger.info(
            f"Тэг '{new_tag}' успешно добавлен к образу '{image_name}'")

    # Compress image to tar file
    with open(image_tar_path, "wb") as archive:
        for chunk in client.images.get(image_name).save(named=True, chunk_size=2097152):
            compressed_chunk = compress_chunk(chunk)
            archive.write(compressed_chunk)
    logger.info(f"Image: '{image_name}' saved to {image_tar_path}.")
    archive.close()

    # Remove image
    image = client.images.get(image_name)
    client.images.remove(image_name)

    # Send the tar file as a download
    return send_from_directory("", image_tar_path, as_attachment=True)


@app.route("/delete", methods=['POST'])
def delete():
    image_name = request.form['image_name']
    if not image_name:
        flash("Необходимо ввести имя архива для удаления", "error")
        return redirect(url_for("index"))

    # Regular expression for filename validation
    VALID_FILENAME_RE = re.compile(
        r'^[a-zA-Z0-9_-]+\(\d{4}-\d{2}-\d{2}_\d{2}:\d{2}\)\.(?:tar)$')

    if not VALID_FILENAME_RE.match(image_name):
        flash("Недопустимое имя архива. Используйте только буквы, цифры, тире и подчеркивания, за которыми следует дата и время в формате (YYYY-MM-DD_hh:mm), и расширение файла (.tar)", "error")
        return redirect(url_for("index"))

    image_tar_path = f"./images/{image_name}"

    try:
        os.remove(image_tar_path)
        flash(
            f"'{image_name}' -  сжатый архив был успешно удален из сервера.", "info")
    except FileNotFoundError:
        flash(f"Архив: {image_name} - не найден или удален ранее", "info")

    return redirect(url_for("index"))

# Search imageNames and there tags in local registry


def list_local_registry_images(registry_url, repository=None, username=None, password=None):
    catalog_api_url = f"{registry_url}/v2/_catalog"
    tags_api_url = f"{registry_url}/v2/{repository}/tags/list" if repository else None

    try:
        if username and password:
            catalog_response = requests.get(
                catalog_api_url, auth=HTTPBasicAuth(username, password))
            if tags_api_url:
                tags_response = requests.get(
                    tags_api_url, auth=HTTPBasicAuth(username, password))
        else:
            catalog_response = requests.get(catalog_api_url)
            if tags_api_url:
                tags_response = requests.get(tags_api_url)

        catalog_response.raise_for_status()
        catalog_data = catalog_response.json()
        repositories = catalog_data.get("repositories", [])

        tags = []
        if tags_api_url and tags_response:
            tags_response.raise_for_status()
            tags_data = tags_response.json()
            tags = tags_data.get("tags", [])

        return repositories, tags
    except requests.exceptions.HTTPError as e:
        print(f"Error: {e}")
        return []


def search_images_in_repositories(registry_url, search_terms, username=None, password=None):
    found_images = []
    repositories, _ = list_local_registry_images(
        registry_url, username=username, password=password)

    for repo in repositories:
        for term in search_terms:
            if term.lower() in repo.lower():
                found_images.append(repo)

    return found_images


@app.route('/registry', methods=['GET', 'POST'])
def registry():
    found_images = []
    image_tags = {}
    if request.method == 'POST':
        image_name = request.form['image_name']
        search_terms = image_name.split(',')
        if not image_name:
            flash(f"Необходимо ввести имя для поиска!", "error")
            return redirect(url_for("index"))
        found_images = search_images_in_repositories(
            registry_url, search_terms, username, password)
        for image in found_images:
            _, tags = list_local_registry_images(
                registry_url, image, username, password)
            image_tags[image] = tags
    return render_template('index.html', image_name=image_name, found_images=found_images, image_tags=image_tags)


if __name__ == '__main__':
    registry_url = 'http://10.3.10.10:5000'
    username = 'repouser'  # Замените на свои учетные данные
    password = 'repouser'  # Замените на свои учетные данные
    app.run(host='0.0.0.0', port=5005, debug=True)
