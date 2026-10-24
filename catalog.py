# -*- coding: utf-8 -*-
"""Library catalog. A trailing * marks packages with native code
(they usually cannot be pip-installed on Android; bundle them at build time)."""
import json
import os
import re

RAW = {
    "AI / Machine Learning": """
numpy* scipy* pandas* scikit-learn* torch* torchvision* torchaudio* tensorflow* keras
jax* jaxlib* xgboost* lightgbm* catboost* transformers tokenizers* datasets accelerate
diffusers sentence-transformers openai anthropic google-generativeai cohere mistralai
groq ollama langchain langchain-core langchain-community langgraph llama-index
llama-cpp-python* onnx* onnxruntime* openvino* huggingface-hub safetensors* spacy*
nltk gensim* textblob stanza flair fasttext* tiktoken* chromadb faiss-cpu* pinecone-client
weaviate-client qdrant-client optuna hyperopt mlflow wandb shap lime statsmodels* sympy
pgmpy pyautogen crewai dspy-ai instructor guidance outlines peft trl bitsandbytes*
evaluate rouge-score sacrebleu seqeval imbalanced-learn category-encoders feature-engine
tpot pycaret ray* dask distributed modin vaex* skorch pytorch-lightning torchmetrics
timm* einops opt-einsum tensorboard
""",
    "Computer Vision / Audio / Video": """
opencv-python* opencv-python-headless* pillow* scikit-image* imageio imageio-ffmpeg
albumentations kornia mediapipe* ultralytics easyocr pytesseract face-recognition*
dlib* imgaug moviepy pydub librosa* soundfile* SpeechRecognition gTTS pyttsx3 vosk*
openai-whisper* audioread pyaudio* sounddevice* webrtcvad* noisereduce resampy*
numba* colorthief mutagen ffmpeg-python av* decord* pytube yt-dlp vidgear
pyzbar* qrcode python-barcode zxing-cpp* rembg* pypdfium2* wand* cairosvg svglib
""",
    "Graphics / Charts / Maps": """
matplotlib* seaborn plotly bokeh altair pygal plotnine holoviews panel dash streamlit
gradio folium geopandas* shapely* cartopy* networkx pyvis graphviz vispy* pyqtgraph*
vpython trimesh open3d* pyvista* wordcloud squarify mplfinance bqplot ipywidgets
cufflinks kaleido pydeck datashader* yellowbrick scikit-plot missingno geopy
contextily* mapclassify osmnx* branca drawsvg svgwrite cairocffi* pycairo* aggdraw*
pyfiglet ascii-magic pixelmatch
""",
    "GUI / Games / 3D": """
kivy kivymd kivy-garden plyer pyjnius oscpy pygame* pyglet arcade ursina panda3d*
pymunk* pysimplegui flet nicegui toga briefcase customtkinter ttkbootstrap pywebview
eel pyqt5* pyside6* wxpython* dearpygui* imgui* raylib* pyxel moderngl* glfw*
pygame-menu pygame-gui pytmx tcod* ppb pgzero cocos2d* renpy* pyopengl*
""",
    "Interaction / Terminal / CLI": """
textual rich prompt-toolkit urwid blessed colorama termcolor tqdm click typer questionary
npyscreen asciimatics inquirer pick halo alive-progress yaspin fire docopt cleo cement
pexpect sh plumbum pyperclip pynput* keyboard mouse pyautogui* readchar getch
tabulate prettytable texttable terminaltables
""",
    "Colors / Themes": """
colour webcolors colorspacious palettable colorcet colormath pastel colored pywal
colorful pylette extcolors cmasher cmocean colour-science
coloraide catppuccin tinycss2 cssselect cssutils
""",
    "Web / HTTP / Scraping": """
requests httpx aiohttp urllib3 flask django fastapi starlette uvicorn tornado bottle
sanic quart falcon pyramid cherrypy aiofiles websockets websocket-client python-socketio
flask-cors flask-sqlalchemy flask-login flask-wtf flask-restful flask-migrate jinja2
markupsafe werkzeug beautifulsoup4 lxml* html5lib selenium scrapy* mechanicalsoup parsel
pyquery requests-html cloudscraper feedparser newspaper3k trafilatura playwright*
httplib2 requests-oauthlib oauthlib authlib certifi chardet idna charset-normalizer
httpie hypercorn daphne gunicorn* waitress whitenoise djangorestframework django-cors-headers
django-environ graphene strawberry-graphql ariadne gql grpcio* protobuf
""",
    "Data / Databases / Files": """
sqlalchemy peewee pony tortoise-orm sqlmodel alembic psycopg2-binary* pymysql
mysql-connector-python pymongo redis motor aiosqlite databases duckdb* polars* pyarrow*
h5py* tables* openpyxl xlrd xlsxwriter python-docx pypdf PyPDF2 reportlab fpdf2
pdfminer.six pdfplumber pyyaml toml tomli tomli-w ujson orjson* simplejson msgpack
marshmallow pydantic attrs cattrs dataclasses-json jsonschema xmltodict python-pptx
tinydb diskcache sqlitedict dataset records cassandra-driver elasticsearch neo4j
influxdb-client clickhouse-driver pyodbc* ijson jmespath jsonpath-ng glom
pandas-profiling ydata-profiling sweetviz csvkit unicodecsv
""",
    "Dev Tools / Testing": """
pytest nose2 hypothesis coverage tox black isort flake8 pylint mypy ruff autopep8 yapf
pyflakes bandit pre-commit sphinx mkdocs docutils markdown mistune pygments jedi parso
rope python-lsp-server invoke fabric paramiko psutil loguru structlog python-dotenv
environs dynaconf pydantic-settings cachetools joblib tenacity retry backoff pytest-cov
pytest-mock pytest-asyncio pytest-xdist faker factory-boy responses requests-mock
freezegun mock behave robotframework locust vulture radon pydocstyle pycodestyle
pip setuptools wheel packaging virtualenv pipx poetry-core hatchling build twine
""",
    "Utilities / Text / Time": """
arrow pendulum python-dateutil pytz tzdata babel humanize inflect unidecode emoji regex
fuzzywuzzy rapidfuzz python-levenshtein* mimesis shortuuid nanoid hashids cryptography*
pycryptodome* bcrypt* passlib pyjwt itsdangerous pyotp keyring more-itertools toolz
funcy boltons sortedcontainers bidict ordered-set pyinputplus validators email-validator
phonenumbers pycountry python-slugify pyshorteners zxcvbn pyspellchecker langdetect
langid googletrans deep-translator translate polyglot jieba pypinyin pyarabic
arabic-reshaper python-bidi camel-tools farasapy hijri-converter convertdate lunardate
workalendar holidays dateparser parsedatetime tzlocal ftfy chardet cchardet* sh
python-magic filetype send2trash watchdog pathspec platformdirs appdirs
zipp py7zr rarfile zstandard* brotli* lz4* patool
""",
    "Network / Async / Cloud / Bots": """
celery apscheduler schedule croniter dramatiq rq huey kombu pika paho-mqtt pyserial
bleak scapy dnspython netaddr boto3 botocore google-cloud-storage azure-storage-blob
firebase-admin supabase twilio stripe pyTelegramBotAPI python-telegram-bot discord.py
slack-sdk tweepy praw instaloader aiogram telethon pyrogram python-binance ccxt sendgrid
yagmail imapclient exchangelib pysftp
asyncssh trio anyio asyncio-mqtt uvloop* gevent* eventlet greenlet* zeroconf
pyzmq* nats-py aiokafka kafka-python confluent-kafka* docker kubernetes ansible
""",
    "Math / Science": """
mpmath numexpr* uncertainties pint quantities astropy* biopython* rdkit* cvxpy* pulp
ortools* pymc* arviz emcee lmfit control* simpy deap igraph* python-igraph* galois
pyomo gekko scikit-fuzzy scikit-optimize nlopt* pywavelets* pandas-datareader
patsy linearmodels pmdarima prophet* tsfresh sktime darts lifelines
numpy-financial QuantLib* pyfftw* bitarray* gmpy2* sortednp
""",
    "Finance": """
yfinance ta pandas-ta backtrader forex-python finta quantstats empyrical alpha-vantage
fredapi investpy mplfinance vectorbt* zipline-reloaded freqtrade bt riskfolio-lib
pyfolio-reloaded ffn
""",
    "Android / Mobile": """
plyer pyjnius oscpy pyobjus kivy-garden.mapview
kivy-garden.graph kivy-garden.matplotlib buildozer python-for-android cython
pyinstaller nuitka briefcase
""",
}

ALIASES = {
    "scikit-learn": "sklearn", "opencv-python": "cv2", "opencv-python-headless": "cv2",
    "pillow": "PIL", "beautifulsoup4": "bs4", "pyyaml": "yaml", "python-dateutil": "dateutil",
    "pyserial": "serial", "python-docx": "docx", "python-pptx": "pptx", "pypdf2": "PyPDF2",
    "scikit-image": "skimage", "faiss-cpu": "faiss", "pyjwt": "jwt", "pyqt5": "PyQt5",
    "pyside6": "PySide6", "wxpython": "wx", "pyopengl": "OpenGL", "python-telegram-bot": "telegram",
    "pytelegrambotapi": "telebot", "discord.py": "discord", "google-generativeai": "google.generativeai",
    "huggingface-hub": "huggingface_hub", "sentence-transformers": "sentence_transformers",
    "speechrecognition": "speech_recognition", "python-slugify": "slugify", "pycryptodome": "Crypto",
    "python-socketio": "socketio", "python-dotenv": "dotenv", "msgpack": "msgpack",
    "pinecone-client": "pinecone", "python-igraph": "igraph", "pyzmq": "zmq", "pymongo": "pymongo",
    "mysql-connector-python": "mysql.connector", "psycopg2-binary": "psycopg2",
    "pywavelets": "pywt", "ffmpeg-python": "ffmpeg", "python-levenshtein": "Levenshtein",
    "openai-whisper": "whisper", "dspy-ai": "dspy", "pyautogen": "autogen", "pytorch-lightning": "pytorch_lightning",
}


def norm(name):
    return re.sub(r"[-_.]+", "_", name).lower()


def import_name(name):
    return ALIASES.get(name.lower(), re.sub(r"-", "_", name))


def _builtin():
    items, seen = [], set()
    for category, blob in RAW.items():
        for tok in blob.split():
            native = tok.endswith("*")
            name = tok.rstrip("*")
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append({"name": name, "category": category, "native": native,
                          "import": import_name(name)})
    return items


def load_catalog(plugin_dir):
    """Built-in list + every *.json file inside plugin_dir.
    JSON format: [{"name": "pkg", "category": "My libs", "native": false, "import": "pkg"}]"""
    items = _builtin()
    seen = {e["name"].lower() for e in items}
    if plugin_dir and os.path.isdir(plugin_dir):
        for fn in sorted(os.listdir(plugin_dir)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(plugin_dir, fn), encoding="utf-8") as f:
                    data = json.load(f)
                for e in data:
                    name = str(e["name"]).strip()
                    if not name or name.lower() in seen:
                        continue
                    seen.add(name.lower())
                    items.append({"name": name, "category": e.get("category", "Custom"),
                                  "native": bool(e.get("native", False)),
                                  "import": e.get("import") or import_name(name)})
            except Exception:
                continue
    return items
