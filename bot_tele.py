import telebot
import requests
import hashlib
import base64
import json
import logging
import html
import threading
import time
import socketio
import random
import string
import os
from flask import Flask
from collections import deque
from datetime import datetime, timezone, timedelta

ICT = timezone(timedelta(hours=7))

app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 LCVIP BY ONGCHUSUNWIN ONLINE"

@app.route("/health")
def health():
    return {"status": "online", "bot": "LCVIP", "server": "Railway"}

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ==========================================
# CONFIG
# ==========================================
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 8681721470))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@bulontaodihaha")
bot = telebot.TeleBot(BOT_TOKEN)
ADMIN_DB_PATH = os.environ.get("ADMIN_DB_PATH", "lcvip_admins.json")
def load_admins():
    try:
        with open(ADMIN_DB_PATH, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {"uids": [], "usernames": []}
admin_db = load_admins()
def is_admin(uid, username=None):
    return int(uid) == ADMIN_ID or int(uid) in admin_db["uids"] or (bool(username) and username.lower().lstrip("@") in admin_db["usernames"])
def save_admins():
    tmp = ADMIN_DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(admin_db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ADMIN_DB_PATH)
def is_simulation(cid):
    return is_admin(cid) and int(user_states.get(cid, {}).get("balance", 0) or 0) < MIN_BET


SYSTEM_ACTIVE = True

USER_COMMANDS = [
    telebot.types.BotCommand("/start", "🏠 Menu LCVIP"),
    telebot.types.BotCommand("/huongdan", "📖 Hướng dẫn"),
    telebot.types.BotCommand("/nhapkey", "🔑 Nhập key VIP"),
    telebot.types.BotCommand("/thongtin", "💎 Thông tin tài khoản"),
    telebot.types.BotCommand("/login", "🔐 Đăng nhập game"),
    telebot.types.BotCommand("/autobetmd5", "⚡ Auto cược MD5"),
    telebot.types.BotCommand("/autobethu", "🎲 Auto cược Hũ"),
    telebot.types.BotCommand("/stop", "⏹️ Ngắt tất cả"),
]

ADMIN_COMMANDS = USER_COMMANDS + [
    telebot.types.BotCommand("/themadmin", "👑 Thêm admin"),
    telebot.types.BotCommand("/xoaadmin", "🗑 Xóa admin"),
    telebot.types.BotCommand("/dsadmin", "👥 Danh sách admin"),
    telebot.types.BotCommand("/dsuser", "👥 [ADMIN] DS User"),
    telebot.types.BotCommand("/tatbot", "🔴 [ADMIN] Tắt Bot"),
    telebot.types.BotCommand("/mobot", "🟢 [ADMIN] Mở Bot"),
    telebot.types.BotCommand("/xuatfile", "📁 [ADMIN] Xuất TXT"),
    telebot.types.BotCommand("/taokey", "👑 [ADMIN] Tạo key"),
    telebot.types.BotCommand("/danhsachkey", "📋 [ADMIN] DS Key"),
    telebot.types.BotCommand("/thongbao", "📢 [ADMIN] Thông báo All"),
    telebot.types.BotCommand("/lichsulogin", "📋 [ADMIN] DS Login"),
]

bot.set_my_commands(USER_COMMANDS, scope=telebot.types.BotCommandScopeDefault())

# ============ GAME CONFIG (PARALLEL) ============
MD5_HISTORY_API_URL = "https://wtxmd52.tele68.com/v1/txmd5/sessions"
MD5_API_URL_FALLBACK = "https://living-telecommunications-start-consoles.trycloudflare.com/api/txmd5"
MD5_SOCKET_URL = "https://wtxmd52.tele68.com"
MD5_SOCKET_PATH = "txmd5/"
MD5_NAMESPACE = "/txmd5"
MD5_ORIGIN = "https://lc79b.bet"

HU_SOCKET_URL = "https://wtx.tele68.com"
HU_SOCKET_NAMESPACE = "/tx"
HU_SOCKET_PATH = "tx/"
HU_ORIGIN = "https://play.lc79.bet"
HU_HISTORY_DB_PATH = os.environ.get("HU_HISTORY_DB_PATH", "lcvip_hu_history.json")

# Chung cho cả 2 game
WARMUP_SESSIONS = 5
MAX_HISTORY_STORE = 500
MAX_MARTINGALE_LEVEL = 6
MARTINGALE_MULTIPLIER = 2
MIN_BET = 1000
MIN_HISTORY = 30

active_sockets = {}
hu_sockets = {}
user_states = {}
KEY_DB_PATH = os.environ.get("KEY_DB_PATH", "lcvip_keys.json")

def load_keys():
    try:
        with open(KEY_DB_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {str(k): int(v) for k, v in raw.items() if int(v) > 0}
    except Exception:
        return {}

def save_keys():
    tmp = KEY_DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(valid_keys, f, ensure_ascii=False)
    os.replace(tmp, KEY_DB_PATH)

valid_keys = load_keys()
authorized_users = {}
all_known_users = {}
login_history = []
global_session_logs = deque(maxlen=200)

# ==========================================
# HELPERS
# ==========================================
def delete_message_later(chat_id, message_id, delay=5):
    def _delete():
        time.sleep(delay)
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    threading.Thread(target=_delete, daemon=True).start()

def safe_send_and_clean(chat_id, text, parse_mode="Markdown", delay=6):
    try:
        msg = bot.send_message(chat_id, text, parse_mode=parse_mode)
        if delay > 0:
            delete_message_later(chat_id, msg.message_id, delay)
        return msg
    except Exception:
        return None

# ============================================================
# 🧠 REALBRAIN
# ============================================================
class RealBrain:
    def __init__(self):
        self.perf = deque(maxlen=200)

    @staticmethod
    def normalize(value):
        v = str(value).strip().upper()
        if v in ("TAI", "TÀI", "T"):
            return "TAI"
        if v in ("XIU", "XỈU", "X"):
            return "XIU"
        return None

    def clean(self, history):
        keyed, unkeyed = {}, []
        for row in history:
            if isinstance(row, dict):
                side = self.normalize(row.get("result"))
                session = row.get("session", row.get("id"))
                if not side:
                    continue
                if session is not None:
                    keyed[str(session)] = (session, side)
                else:
                    unkeyed.append(side)
            else:
                side = self.normalize(row)
                if side:
                    unkeyed.append(side)
        if keyed:
            def order(it):
                try:
                    return (0, int(it[0]))
                except (ValueError, TypeError):
                    return (1, str(it[0]))
            return [s for _, s in sorted(keyed.values(), key=order)][-500:]
        return unkeyed[-500:]

    @staticmethod
    def _beta_p(tai, total):
        return (tai + 2.0) / (total + 4.0)

    def _pattern_vote(self, r, length, min_support=8):
        n = len(r)
        if n <= length:
            return None
        pattern = tuple(r[-length:])
        follow = [r[i] for i in range(length, n) if tuple(r[i-length:i]) == pattern]
        if len(follow) < min_support:
            return None
        return self._beta_p(follow.count("TAI"), len(follow)), len(follow)

    def _markov2_vote(self, r, min_support=8):
        if len(r) < 8:
            return None
        pattern = tuple(r[-2:])
        follow = [r[i] for i in range(2, len(r)) if tuple(r[i-2:i]) == pattern]
        if len(follow) < min_support:
            return None
        return self._beta_p(follow.count("TAI"), len(follow)), len(follow)

    def _streak_vote(self, r, min_support=6):
        if len(r) < 6:
            return None
        cur = r[-1]
        sl = 1
        for x in reversed(r[:-1]):
            if x == cur:
                sl += 1
            else:
                break
        samples = []
        i, n = 0, len(r)
        while i < n - 1:
            if r[i] == cur:
                j = i
                while j < n - 1 and r[j] == cur:
                    j += 1
                if (j - i) >= sl and j < n:
                    samples.append(r[j])
                i = j
            else:
                i += 1
        if len(samples) < min_support:
            return None
        return self._beta_p(samples.count("TAI"), len(samples)), len(samples)

    def predict(self, history):
        r = self.clean(history)
        n = len(r)
        if n < 30:
            return None, 0, f"Thiếu dữ liệu ({n}/30 phiên)"

        votes = []
        for length, w in ((2, 1.0), (3, 1.2), (4, 1.4), (5, 1.5)):
            v = self._pattern_vote(r, length)
            if v:
                p, sup = v
                edge = abs(p - 0.5)
                if edge >= 0.10:
                    votes.append(("TAI" if p > 0.5 else "XIU", w * sup * edge, p, f"P{length}x{sup}"))

        v = self._markov2_vote(r)
        if v:
            p, sup = v
            edge = abs(p - 0.5)
            if edge >= 0.10:
                votes.append(("TAI" if p > 0.5 else "XIU", 1.3 * sup * edge, p, f"MK2x{sup}"))

        v = self._streak_vote(r)
        if v:
            p, sup = v
            edge = abs(p - 0.5)
            if edge >= 0.10:
                votes.append(("TAI" if p > 0.5 else "XIU", 1.0 * sup * edge, p, f"STx{sup}"))

        if not votes:
            return None, 0, "Không có mẫu đủ mạnh"

        w_tai = sum(w for s, w, *_ in votes if s == "TAI")
        w_xiu = sum(w for s, w, *_ in votes if s == "XIU")
        total_w = w_tai + w_xiu
        if total_w <= 0:
            return None, 0, "Trọng số rỗng"

        ratio_tai, ratio_xiu = w_tai / total_w, w_xiu / total_w
        side, ratio = ("TAI", ratio_tai) if ratio_tai >= ratio_xiu else ("XIU", ratio_xiu)

        if ratio < 0.65:
            return None, 0, f"Tín hiệu phân tán ({ratio:.0%})"

        detail = ", ".join(tag for _, _, _, tag in votes[:3])
        return side, ratio, f"Đồng thuận {ratio:.0%} • {detail}"

    def update(self, pred, actual):
        p, a = self.normalize(pred), self.normalize(actual)
        if p and a:
            self.perf.append(int(p == a))

_md5_brain = RealBrain()
_hu_brain = RealBrain()

def feed_history(_): return None
def pro_predict(h, **kw): return _md5_brain.predict(h)
def update_result(p, a, **kw): _md5_brain.update(p, a)
def hu_pro_predict(h): return _hu_brain.predict(h)
def hu_update_result(p, a): _hu_brain.update(p, a)

# ==========================================
# 🎲 HŨ SHARED HISTORY
# ==========================================
_hu_history_lock = threading.Lock()
_hu_recent_fps = deque(maxlen=50)

def _load_hu_history():
    try:
        with open(HU_HISTORY_DB_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            return deque(maxlen=MAX_HISTORY_STORE)
        clean = []
        for row in raw[-MAX_HISTORY_STORE:]:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result", "")).upper()
            dices = row.get("dice") or row.get("dices") or []
            if result not in ("TAI", "XIU") or not isinstance(dices, list) or len(dices) != 3:
                continue
            try:
                dices = [int(x) for x in dices]
            except Exception:
                continue
            clean.append({
                "session": row.get("session"), "dice": dices,
                "total": int(row.get("total", sum(dices))),
                "result": result, "time": row.get("time")
            })
        return deque(clean, maxlen=MAX_HISTORY_STORE)
    except Exception:
        return deque(maxlen=MAX_HISTORY_STORE)

def _save_hu_history():
    try:
        tmp = HU_HISTORY_DB_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(hu_shared_history), f, ensure_ascii=False)
        os.replace(tmp, HU_HISTORY_DB_PATH)
    except Exception as exc:
        logger.warning("Lưu Hũ lỗi: %s", exc)

hu_shared_history = _load_hu_history()

# ==========================================
# STATE (PARALLEL)
# ==========================================
def init_user_state(chat_id):
    if chat_id not in user_states:
        user_states[chat_id] = {
            # ===== MD5 =====
            "md5_raw_hist": [], "md5_history": [],
            "md5_enabled": False,           # prediction_enabled
            "md5_auto_bet": False,          # auto_bet_enabled
            "md5_bet_amount": 10000, "md5_base_bet": 10000,
            "md5_martingale_enabled": False, "md5_martingale_level": 0,
            "md5_current_prediction": None,
            "md5_has_bet_this_session": False,
            "md5_session_id": None,
            "md5_round_open": False,
            "md5_synced": False,
            "md5_last_subtick": None,
            "md5_warmup_remaining": 0,
            "md5_last_pred_msg_id": None,
            "md5_last_bet_amount": 10000,
            "md5_current_conf": 0, "md5_current_reason": "",
            "md5_total_win": 0, "md5_total_lose": 0,
            "md5_win_streak": 0, "md5_lose_streak": 0,
            "md5_net_profit": 0, "md5_peak_profit": 0,
            "md5_ready_notified": False,
            # ===== HŨ =====
            "hu_enabled": False,
            "hu_auto_bet": False,           # giữ cho tương thích, luôn True khi bật
            "hu_connected": False,
            "hu_synced": False,
            "hu_round_open": False,
            "hu_session_id": None,
            "hu_last_subtick": None,
            "hu_current_prediction": None,
            "hu_current_conf": 0, "hu_current_reason": "",
            "hu_last_pred_msg_id": None,
            "hu_bet_amount": 10000, "hu_base_bet": 10000,
            "hu_has_bet_this_session": False,
            "hu_last_bet_amount": 10000,
            "hu_martingale_enabled": False, "hu_martingale_level": 0,
            "hu_warmup_remaining": 0,
            "hu_total_win": 0, "hu_total_lose": 0,
            "hu_win_streak": 0, "hu_lose_streak": 0,
            "hu_net_profit": 0, "hu_peak_profit": 0,
            "hu_ready_notified": False,
            # ===== CHUNG =====
            "balance": 0,
            "game_token": None,
        }
    return user_states[chat_id]

def _parse_lines(data):
    if not data or not isinstance(data.get("list"), list):
        return []
    arr = sorted(data["list"], key=lambda x: x["id"])
    out = []
    for it in arr:
        p = it.get("point", sum(it.get("dices", [0, 0, 0])))
        r = it.get("resultTruyenThong")
        if r in ("TAI", "XIU"):
            out.append({"session": it["id"], "dice": it["dices"], "total": p, "result": r})
    return out

def fetch_md5_history(limit=60):
    for url in (MD5_HISTORY_API_URL, MD5_API_URL_FALLBACK):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Origin": MD5_ORIGIN}, timeout=10)
            if r.status_code != 200:
                continue
            arr = _parse_lines(r.json())
            if arr:
                return arr[-limit:]
        except Exception:
            continue
    return []

def _hu_result_from_payload(data):
    if not isinstance(data, dict):
        return None
    dices = data.get("dices") or []
    if not isinstance(dices, (list, tuple)) or len(dices) != 3:
        return None
    try:
        dices = [int(x) for x in dices]
    except Exception:
        return None
    total = sum(dices)
    result = str(data.get("resultTruyenThong") or "").upper()
    if result not in ("TAI", "XIU"):
        result = "TAI" if total > 10 else "XIU"
    return {
        "session": data.get("id") or data.get("sessionId") or data.get("session"),
        "dice": dices, "total": total, "result": result,
        "time": datetime.now(ICT).strftime("%d/%m/%Y %H:%M:%S"),
    }

def _append_hu_shared_history(rec):
    if not rec:
        return False
    now = time.time()
    session = rec.get("session")
    fp = ("session", str(session)) if session is not None else ("result", tuple(rec.get("dice", [])), rec.get("result"))
    with _hu_history_lock:
        if session is not None:
            if any(str(x.get("session")) == str(session) for x in reversed(hu_shared_history)):
                return False
        else:
            for old_fp, ts in list(_hu_recent_fps):
                if old_fp == fp and now - ts < 8:
                    return False
        _hu_recent_fps.append((fp, now))
        hu_shared_history.append(rec)
        _save_hu_history()
        return True

def _hu_history_text(limit=20):
    rows = list(hu_shared_history)[-max(1, min(int(limit), 50)):]
    if not rows:
        return "📭 Chưa có lịch sử Hũ."
    lines = ["🎲 *LỊCH SỬ HŨ REALTIME*", "━━━━━━━━━━━━━━━━━━━━"]
    for row in reversed(rows):
        sid = row.get("session") or "?"
        d = row.get("dice") or [0, 0, 0]
        lines.append(f"#{sid} • *{row.get('result','?')}* • `{d[0]}-{d[1]}-{d[2]}={row.get('total',0)}`")
    lines += ["━━━━━━━━━━━━━━━━━━━━", f"Đã lưu: `{len(hu_shared_history)}/{MAX_HISTORY_STORE}`"]
    return "\n".join(lines)

# ==========================================
# AUTH
# ==========================================
def check_auth(chat_id):
    if is_admin(chat_id):
        return True
    if chat_id in authorized_users:
        if time.time() <= authorized_users[chat_id]:
            return True
        else:
            del authorized_users[chat_id]
            try:
                bot.send_message(chat_id, "⚠️ **KEY HẾT HẠN!!!**", parse_mode="Markdown")
            except:
                pass
            for sock_dict in (active_sockets, hu_sockets):
                if chat_id in sock_dict:
                    try:
                        sock_dict[chat_id].disconnect()
                    except Exception:
                        pass
                    del sock_dict[chat_id]
            if chat_id in user_states:
                st = user_states[chat_id]
                st["md5_auto_bet"] = False
                st["md5_enabled"] = False
                st["hu_enabled"] = False
    return False

def require_auth(fn):
    def wr(m, *a, **kw):
        if not SYSTEM_ACTIVE and not is_admin(m.chat.id, m.from_user.username):
            safe_send_and_clean(m.chat.id, "🔴 **Hệ thống đang tắt!**", delay=5)
            return
        if not check_auth(m.chat.id):
            safe_send_and_clean(m.chat.id, f"🔒 **Chưa kích hoạt!**\n🔑 `/nhapkey MÃ`\n📩 {ADMIN_USERNAME}", delay=6)
            return
        return fn(m, *a, **kw)
    return wr

def format_expire_time(ts):
    r = ts - time.time()
    if r <= 0:
        return "Hết hạn"
    d = int(r // 86400)
    h = int((r % 86400) // 3600)
    m = int((r % 3600) // 60)
    return f"{d}n {h}g {m}p" if d > 0 else f"{h}g {m}p"

# ==========================================
# TÍNH TIỀN CƯỢC (GENERIC)
# ==========================================
def _tinh_tien_cuoc(st, prefix, max_level, multiplier, min_bet):
    base = max(min_bet, int(st.get(f"{prefix}_base_bet", min_bet)))
    if not st.get(f"{prefix}_martingale_enabled"):
        amount = base
    else:
        lv = max(0, min(int(st.get(f"{prefix}_martingale_level", 0)), max_level))
        amount = base * (multiplier ** lv)
    bal = int(st.get("balance", 0) or 0)
    if bal > 0:
        amount = min(amount, bal)
    if amount < min_bet:
        amount = min_bet if bal >= min_bet else bal
    return int(amount)

def tinh_tien_cuoc_md5(cid):
    return _tinh_tien_cuoc(user_states[cid], "md5", MAX_MARTINGALE_LEVEL, MARTINGALE_MULTIPLIER, MIN_BET)

def tinh_tien_cuoc_hu(cid):
    return _tinh_tien_cuoc(user_states[cid], "hu", MAX_MARTINGALE_LEVEL, MARTINGALE_MULTIPLIER, MIN_BET)

# ==========================================
# AI TỰ HỌC (GENERIC)
# ==========================================
def _ai_tu_hoc(st, prefix, pred, actual, bet_amount, max_level, game_label, cid):
    bet_amount = int(bet_amount or 0)
    if pred == actual:
        st[f"{prefix}_win_streak"] += 1
        st[f"{prefix}_lose_streak"] = 0
        st[f"{prefix}_total_win"] += 1
        st[f"{prefix}_net_profit"] = int(st.get(f"{prefix}_net_profit", 0)) + bet_amount
        st[f"{prefix}_martingale_level"] = 0
    else:
        st[f"{prefix}_lose_streak"] += 1
        st[f"{prefix}_win_streak"] = 0
        st[f"{prefix}_total_lose"] += 1
        st[f"{prefix}_net_profit"] = int(st.get(f"{prefix}_net_profit", 0)) - bet_amount
        if st.get(f"{prefix}_martingale_enabled") and st.get(f"{prefix}_martingale_level", 0) < max_level:
            st[f"{prefix}_martingale_level"] += 1
        if st.get(f"{prefix}_martingale_level", 0) >= max_level and st.get(f"{prefix}_martingale_enabled"):
            st[f"{prefix}_martingale_enabled"] = False
            try:
                bot.send_message(cid, f"🛑 *{game_label}: Chạm cấp X2 tối đa và vẫn thua — TỰ ĐỘNG TẮT X2.*", parse_mode="Markdown")
            except Exception:
                pass
    if st[f"{prefix}_net_profit"] > st.get(f"{prefix}_peak_profit", 0):
        st[f"{prefix}_peak_profit"] = st[f"{prefix}_net_profit"]

def ai_tu_hoc_md5(cid, pred, actual, bet_amount=0):
    _ai_tu_hoc(user_states[cid], "md5", pred, actual, bet_amount, MAX_MARTINGALE_LEVEL, "MD5", cid)
    _md5_brain.update(pred, actual)

def ai_tu_hoc_hu(cid, pred, actual, bet_amount=0):
    _ai_tu_hoc(user_states[cid], "hu", pred, actual, bet_amount, MAX_MARTINGALE_LEVEL, "Hũ", cid)
    _hu_brain.update(pred, actual)

# ==========================================
# LOGIN
# ==========================================
def md5_hash(t):
    return hashlib.md5(t.encode()).hexdigest()

def login_and_get_token(u, p):
    try:
        r = requests.get(f"https://apifo88daigia.tele68.com/api?c=3&un={u}&pw={md5_hash(p)}&cp=R&cl=R&pf=web&at=", timeout=12).json()
        if not r.get("success"):
            return {"_error": "Sai TK/MK!"}
        sk = r["sessionKey"] + "=" * ((4 - len(r["sessionKey"]) % 4) % 4)
        nn = json.loads(base64.b64decode(sk)).get("nickname")
        r2 = requests.post("https://wlb.tele68.com/v1/lobby/auth/login?cp=R&cl=R&pf=web&at=",
                           json={"nickName": nn, "accessToken": r["accessToken"]}, timeout=12).json()
        if not r2.get("token"):
            return {"_error": "Không lấy được token."}
        return {"token": r2["token"], "nickname": nn, "money": r2.get("remoteLoginResp", {}).get("money", 0), "username": u}
    except Exception as e:
        return {"_error": str(e)}

# ==========================================
# 🌐 MD5 SOCKET (SONG SONG VỚI HŨ)
# ==========================================
def start_md5_websocket(cid, token):
    if cid in active_sockets:
        try:
            active_sockets[cid].disconnect()
        except Exception:
            pass
    sio = socketio.Client(reconnection=True, reconnection_attempts=99999, reconnection_delay=3, logger=False, engineio_logger=False)
    active_sockets[cid] = sio
    st = init_user_state(cid)

    @sio.event(namespace=MD5_NAMESPACE)
    def connect():
        st["md5_synced"] = True
        arr = fetch_md5_history(60)
        if arr:
            st["md5_raw_hist"] = arr
            st["md5_history"] = [x["result"] for x in arr]

    @sio.event(namespace=MD5_NAMESPACE)
    def disconnect():
        st["md5_synced"] = False

    @sio.on("connect_error", namespace=MD5_NAMESPACE)
    def connect_error(data):
        st["md5_synced"] = False
        if st.get("md5_enabled") and "Unauthorized" in str(data):
            safe_send_and_clean(cid, "⚠️ MD5: token phiên hết hạn. `/login` lại.", delay=6)

    @sio.on("bet-result", namespace=MD5_NAMESPACE)
    def md5_bet_result(data):
        if not isinstance(data, dict):
            return
        new_bal = data.get("postBalance") or data.get("balance") or data.get("money")
        if new_bal is not None:
            try:
                st["balance"] = int(new_bal)
            except Exception:
                pass
        err = data.get("error") or data.get("message")
        if err and st.get("md5_enabled"):
            safe_send_and_clean(cid, f"⚠️ MD5 • Lỗi cược: `{err}`", delay=8)

    @sio.on("tick-update", namespace=MD5_NAMESPACE)
    def md5_tick(data):
        if not check_auth(cid) or not st.get("md5_enabled") or not isinstance(data, dict):
            return
        state = str(data.get("state") or "").upper()
        sub_tick = data.get("subTick")
        st["md5_last_subtick"] = sub_tick

        if state != "BETTING" or not st.get("md5_synced") or st.get("md5_round_open"):
            return

        st["md5_round_open"] = True
        st["md5_session_id"] = data.get("id") or data.get("sessionId") or data.get("session")
        st["md5_current_prediction"] = None
        st["md5_has_bet_this_session"] = False
        st["md5_last_pred_msg_id"] = None

        # ===== WARMUP =====
        if st.get("md5_warmup_remaining", 0) > 0:
            done = WARMUP_SESSIONS - st["md5_warmup_remaining"]
            msg = (
                f"⏳ *MD5 • TÍCH LŨY DỮ LIỆU*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *PHIÊN* `{st['md5_session_id'] or '?'}`\n"
                f"📊 *Tiến độ:* `{done + 1}/{WARMUP_SESSIONS}`\n"
                f"💤 Chưa dự đoán — đang hiệu chỉnh mẫu MD5\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            sent = safe_send_and_clean(cid, msg, delay=0)
            if sent:
                st["md5_last_pred_msg_id"] = sent.message_id
            return

        # ===== PREDICT =====
        hist = st["md5_raw_hist"]
        if len(hist) < MIN_HISTORY:
            return
        pred = pro_predict(hist)
        if not pred or not pred[0]:
            return

        side, conf, reason = pred[0], int(pred[1] * 100), pred[2]
        st["md5_current_prediction"] = side
        st["md5_current_conf"] = conf
        st["md5_current_reason"] = reason

        # ===== BET =====
        st["md5_simulated"] = False
        bet_amount = tinh_tien_cuoc_md5(cid)
        balance = int(st.get("balance", 0) or 0)
        if balance < bet_amount and not is_admin(cid):
            bet_amount = balance if balance >= MIN_BET else 0

        if bet_amount > 0 and st.get("md5_auto_bet") and balance >= bet_amount:
            try:
                sio.emit("bet", {"type": side, "amount": bet_amount}, namespace=MD5_NAMESPACE)
                st["md5_has_bet_this_session"] = True
                st["md5_last_bet_amount"] = bet_amount
            except Exception as exc:
                logger.warning("MD5 emit bet lỗi: %s", exc)

        # ===== CARD =====
        x2_st = f"Cấp {st['md5_martingale_level']}" if st.get("md5_martingale_enabled") else "Tắt"
        if is_admin(cid) and balance < bet_amount:
            st["md5_simulated"] = True
            st["md5_has_bet_this_session"] = True
            st["md5_last_bet_amount"] = bet_amount
            bet_line = f"🧪 *MÔ PHỎNG ADMIN:* `{bet_amount:,}đ` (không gửi cược thật)"
        elif bet_amount == 0:
            bet_line = "⚠️ *SỐ DƯ KHÔNG ĐỦ* — bỏ qua phiên này"
        elif st["md5_has_bet_this_session"]:
            bet_line = f"💵 *ĐÃ GỬI CƯỢC:* `{bet_amount:,}đ`"
        else:
            bet_line = "⚪ *Chưa gửi cược*"

        sid = st.get("md5_session_id") or "?"
        msg = (
            f"⚡ *LCVIP • MD5 MD5*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *DỰ ĐOÁN:* {'🟢' if side == 'TAI' else '🔴'} *{side}*\n"
            f"📈 *Đồng thuận mẫu:* `{conf}%`\n"
            f"🧠 _{reason}_\n"
            f"⏱ *Còn:* `{sub_tick if sub_tick is not None else '?'}s` • Phiên `{sid}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{bet_line}\n"
            f"🔁 *X2:* `{x2_st}`\n"
            f"🏦 *Số dư:* `{st.get('balance',0):,}đ`\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        sent = safe_send_and_clean(cid, msg, delay=0)
        if sent:
            st["md5_last_pred_msg_id"] = sent.message_id

    @sio.on("session-result", namespace=MD5_NAMESPACE)
    def md5_result(data):
        if not check_auth(cid):
            return
        res = data.get("resultTruyenThong")
        st["md5_synced"] = True
        st["md5_round_open"] = False

        if res not in ("TAI", "XIU"):
            return

        dices = data.get("dices", [0, 0, 0])
        total_pts = sum(dices) if dices else 0
        sess_id = data.get("id") or st.get("md5_session_id") or "MD5"

        rec = {"session": sess_id, "dice": dices, "total": total_pts, "result": res}
        st["md5_raw_hist"].append(rec)
        st["md5_history"].append(res)
        if len(st["md5_raw_hist"]) > MAX_HISTORY_STORE:
            st["md5_raw_hist"].pop(0)
            st["md5_history"].pop(0)

        # Ready notification
        if st.get("md5_enabled") and len(st["md5_raw_hist"]) >= MIN_HISTORY and not st.get("md5_ready_notified"):
            st["md5_ready_notified"] = True
            safe_send_and_clean(cid, f"✅ *MD5 đủ dữ liệu:* `{len(st['md5_raw_hist'])}` phiên.", delay=8)

        pred = st.get("md5_current_prediction")

        # ===== WARMUP RESULT =====
        if st.get("md5_warmup_remaining", 0) > 0:
            st["md5_warmup_remaining"] -= 1
            done = WARMUP_SESSIONS - st["md5_warmup_remaining"]
            if st.get("md5_last_pred_msg_id"):
                try:
                    if st["md5_warmup_remaining"] > 0:
                        txt = (
                            f"✅ *MD5 • Tích lũy*\n"
                            f"🎲 `#{sess_id}` • *{res}* • `{dices[0]}-{dices[1]}-{dices[2]}={total_pts}`\n"
                            f"📊 Tiến độ: `{done}/{WARMUP_SESSIONS}`"
                        )
                    else:
                        txt = (
                            f"🎉 *HOÀN TẤT TÍCH LŨY MD5!*\n"
                            f"🎲 `#{sess_id}` • *{res}* • `{dices[0]}-{dices[1]}-{dices[2]}={total_pts}`\n"
                            f"🚀 Bắt đầu dự đoán + cược từ phiên tới!"
                        )
                    bot.edit_message_text(txt, cid, st["md5_last_pred_msg_id"], parse_mode="Markdown")
                except Exception:
                    pass
            return
        # =========================

        if pred not in ("TAI", "XIU"):
            return

        has_bet = bool(st.get("md5_has_bet_this_session"))
        bet_amount = int(st.get("md5_last_bet_amount", 0) or 0)
        is_win = (pred == res)

        profit = 0
        if has_bet and bet_amount > 0:
            ai_tu_hoc_md5(cid, pred, res, bet_amount=bet_amount)
            profit = bet_amount if is_win else -bet_amount
            global_session_logs.append({
                "time": datetime.now(ICT).strftime("%d/%m/%Y %H:%M:%S"),
                "game": "MD5", "session": sess_id, "dice": dices, "total": total_pts,
                "result": res, "prediction": pred,
                "mode": "MÔ PHỎNG" if st.get("md5_simulated", False) else "THẬT", "status": "THẮNG" if is_win else "THUA",
                "profit": profit, "balance": st.get("balance", 0)
            })

        if st.get("md5_last_pred_msg_id"):
            try:
                if has_bet and bet_amount > 0:
                    status = (
                        f"{'✅ HÚP' if is_win else '❌ GÃY'} | "
                        f"💵 `{bet_amount:,}đ` → `{profit:+,}đ`\n"
                        f"📊 Ròng MD5: `{st.get('md5_net_profit', 0):+,}đ`\n"
                        f"🏦 Số dư: `{st.get('balance',0):,}đ`\n"
                        f"🔥 `{st.get('md5_win_streak',0)}T/{st.get('md5_lose_streak',0)}B`"
                    )
                else:
                    status = "⚪ Không cược phiên này"

                final = (
                    f"⚡ *MD5* • `#{sess_id}`\n"
                    f"🎯 *{pred}* ➜ *{res}* • `{dices[0]}-{dices[1]}-{dices[2]}={total_pts}`\n"
                    f"{status}"
                )
                if st.get("md5_simulated"): final += "\n🧪 *CHỈ MÔ PHỎNG — KHÔNG CƯỢC THẬT*"
                bot.edit_message_text(final, cid, st["md5_last_pred_msg_id"], parse_mode="Markdown")
            except Exception:
                pass

        st["md5_current_prediction"] = None
        st["md5_has_bet_this_session"] = False

    try:
        sio.connect(MD5_SOCKET_URL, socketio_path=MD5_SOCKET_PATH, namespaces=[MD5_NAMESPACE],
                    transports=["websocket"], auth={"token": token},
                    headers={"User-Agent": "Mozilla/5.0", "Origin": MD5_ORIGIN})
        sio.wait()
    except Exception as exc:
        st["md5_synced"] = False
        logger.warning("MD5 socket dừng cho %s: %s", cid, exc)
    finally:
        if active_sockets.get(cid) is sio:
            active_sockets.pop(cid, None)

# ==========================================
# 🎲 HŨ SOCKET (SONG SONG)
# ==========================================
def start_hu_websocket(cid, token):
    if cid in hu_sockets:
        try:
            hu_sockets[cid].disconnect()
        except Exception:
            pass
        hu_sockets.pop(cid, None)
    sio = socketio.Client(reconnection=True, reconnection_attempts=99999, reconnection_delay=3, logger=False, engineio_logger=False)
    hu_sockets[cid] = sio
    st = init_user_state(cid)
    st["hu_connected"] = False
    st["hu_synced"] = False
    st["hu_round_open"] = False

    @sio.event(namespace=HU_SOCKET_NAMESPACE)
    def connect():
        st["hu_connected"] = True

    @sio.event(namespace=HU_SOCKET_NAMESPACE)
    def disconnect():
        st["hu_connected"] = False

    @sio.on("connect_error", namespace=HU_SOCKET_NAMESPACE)
    def connect_error(data):
        st["hu_connected"] = False
        if st.get("hu_enabled") and "Unauthorized" in str(data):
            safe_send_and_clean(cid, "⚠️ Hũ: token phiên hết hạn. `/login` lại.", delay=6)

    @sio.on("bet-result", namespace=HU_SOCKET_NAMESPACE)
    def hu_bet_result(data):
        if not isinstance(data, dict):
            return
        new_bal = data.get("postBalance") or data.get("balance") or data.get("money")
        if new_bal is not None:
            try:
                st["balance"] = int(new_bal)
            except Exception:
                pass
        err = data.get("error") or data.get("message")
        if err and st.get("hu_enabled"):
            safe_send_and_clean(cid, f"⚠️ Hũ • Lỗi cược: `{err}`", delay=8)

    @sio.on("tick-update", namespace=HU_SOCKET_NAMESPACE)
    def hu_tick(data):
        if not check_auth(cid) or not st.get("hu_enabled") or not isinstance(data, dict):
            return
        state = str(data.get("state") or "").upper()
        sub_tick = data.get("subTick")
        st["hu_last_subtick"] = sub_tick

        if state != "BETTING" or not st.get("hu_synced") or st.get("hu_round_open"):
            return

        st["hu_round_open"] = True
        st["hu_session_id"] = data.get("id") or data.get("sessionId") or data.get("session")
        st["hu_current_prediction"] = None
        st["hu_has_bet_this_session"] = False
        st["hu_last_pred_msg_id"] = None

        # ===== WARMUP =====
        if st.get("hu_warmup_remaining", 0) > 0:
            done = WARMUP_SESSIONS - st["hu_warmup_remaining"]
            msg = (
                f"⏳ *HŨ • TÍCH LŨY DỮ LIỆU*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *PHIÊN* `{st['hu_session_id'] or '?'}`\n"
                f"📊 *Tiến độ:* `{done + 1}/{WARMUP_SESSIONS}`\n"
                f"💤 Chưa dự đoán — đang hiệu chỉnh mẫu Hũ\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            sent = safe_send_and_clean(cid, msg, delay=0)
            if sent:
                st["hu_last_pred_msg_id"] = sent.message_id
            return

        # ===== PREDICT =====
        hist = list(hu_shared_history)
        if len(hist) < MIN_HISTORY:
            return
        pred = hu_pro_predict(hist)
        if not pred or not pred[0]:
            return

        side, conf, reason = pred[0], int(pred[1] * 100), pred[2]
        st["hu_current_prediction"] = side
        st["hu_current_conf"] = conf
        st["hu_current_reason"] = reason

        # ===== BET =====
        st["hu_simulated"] = False
        bet_amount = tinh_tien_cuoc_hu(cid)
        balance = int(st.get("balance", 0) or 0)
        if balance < bet_amount and not is_admin(cid):
            bet_amount = balance if balance >= MIN_BET else 0

        if bet_amount > 0 and balance >= bet_amount:
            try:
                sio.emit("bet", {"type": side, "amount": bet_amount}, namespace=HU_SOCKET_NAMESPACE)
                st["hu_has_bet_this_session"] = True
                st["hu_last_bet_amount"] = bet_amount
            except Exception as exc:
                logger.warning("Hũ emit bet lỗi: %s", exc)

        # ===== CARD =====
        x2_st = f"Cấp {st['hu_martingale_level']}" if st.get("hu_martingale_enabled") else "Tắt"
        if is_admin(cid) and balance < bet_amount:
            st["hu_simulated"] = True
            st["hu_has_bet_this_session"] = True
            st["hu_last_bet_amount"] = bet_amount
            bet_line = f"🧪 *MÔ PHỎNG ADMIN:* `{bet_amount:,}đ` (không gửi cược thật)"
        elif bet_amount == 0:
            bet_line = "⚠️ *SỐ DƯ KHÔNG ĐỦ* — bỏ qua phiên này"
        else:
            bet_line = f"💵 *ĐÃ GỬI CƯỢC:* `{bet_amount:,}đ`"

        sid = st.get("hu_session_id") or "?"
        msg = (
            f"🎲 *LCVIP • BÀN HŨ*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *DỰ ĐOÁN:* {'🟢' if side == 'TAI' else '🔴'} *{side}*\n"
            f"📈 *Đồng thuận mẫu:* `{conf}%`\n"
            f"🧠 _{reason}_\n"
            f"⏱ *Còn:* `{sub_tick if sub_tick is not None else '?'}s` • Phiên `{sid}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{bet_line}\n"
            f"🔁 *X2:* `{x2_st}`\n"
            f"🏦 *Số dư:* `{st.get('balance',0):,}đ`\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        sent = safe_send_and_clean(cid, msg, delay=0)
        if sent:
            st["hu_last_pred_msg_id"] = sent.message_id

    @sio.on("session-result", namespace=HU_SOCKET_NAMESPACE)
    def hu_result(data):
        if not check_auth(cid):
            return
        rec = _hu_result_from_payload(data)
        st["hu_synced"] = True
        st["hu_round_open"] = False
        if not rec:
            return

        _append_hu_shared_history(rec)
        if rec.get("session") is not None:
            st["hu_session_id"] = rec.get("session")

        if st.get("hu_enabled") and len(hu_shared_history) >= MIN_HISTORY and not st.get("hu_ready_notified"):
            st["hu_ready_notified"] = True
            safe_send_and_clean(cid, f"✅ *Hũ đủ dữ liệu:* `{len(hu_shared_history)}` phiên.", delay=8)

        pred = st.get("hu_current_prediction")

        # ===== WARMUP RESULT =====
        if st.get("hu_warmup_remaining", 0) > 0:
            st["hu_warmup_remaining"] -= 1
            done = WARMUP_SESSIONS - st["hu_warmup_remaining"]
            if st.get("hu_last_pred_msg_id"):
                try:
                    if st["hu_warmup_remaining"] > 0:
                        txt = (
                            f"✅ *Hũ • Tích lũy*\n"
                            f"🎲 `#{rec.get('session') or '?'}` • *{rec['result']}* • `{rec['dice'][0]}-{rec['dice'][1]}-{rec['dice'][2]}={rec['total']}`\n"
                            f"📊 Tiến độ: `{done}/{WARMUP_SESSIONS}`"
                        )
                    else:
                        txt = (
                            f"🎉 *HOÀN TẤT TÍCH LŨY HŨ!*\n"
                            f"🎲 `#{rec.get('session') or '?'}` • *{rec['result']}* • `{rec['dice'][0]}-{rec['dice'][1]}-{rec['dice'][2]}={rec['total']}`\n"
                            f"🚀 Bắt đầu dự đoán + cược từ phiên tới!"
                        )
                    bot.edit_message_text(txt, cid, st["hu_last_pred_msg_id"], parse_mode="Markdown")
                except Exception:
                    pass
            return
        # =========================

        if pred not in ("TAI", "XIU"):
            return

        actual = rec["result"]
        dices = rec["dice"]
        total = rec["total"]
        sid = rec.get("session") or st.get("hu_session_id") or "HŨ"
        bet_amount = int(st.get("hu_last_bet_amount", 0) or 0)
        has_bet = bool(st.get("hu_has_bet_this_session"))
        is_win = (pred == actual)

        profit = 0
        if has_bet and bet_amount > 0:
            ai_tu_hoc_hu(cid, pred, actual, bet_amount=bet_amount)
            profit = bet_amount if is_win else -bet_amount
            global_session_logs.append({
                "time": datetime.now(ICT).strftime("%d/%m/%Y %H:%M:%S"),
                "game": "HU", "session": sid, "dice": dices, "total": total,
                "result": actual, "prediction": pred,
                "mode": "MÔ PHỎNG" if st.get("hu_simulated", False) else "THẬT", "status": "THẮNG" if is_win else "THUA",
                "profit": profit, "balance": st.get("balance", 0)
            })

        if st.get("hu_last_pred_msg_id"):
            try:
                if has_bet and bet_amount > 0:
                    status = (
                        f"{'✅ HÚP' if is_win else '❌ GÃY'} | "
                        f"💵 `{bet_amount:,}đ` → `{profit:+,}đ`\n"
                        f"📊 Ròng Hũ: `{st.get('hu_net_profit', 0):+,}đ`\n"
                        f"🏦 Số dư: `{st.get('balance',0):,}đ`\n"
                        f"🔥 `{st.get('hu_win_streak',0)}T/{st.get('hu_lose_streak',0)}B`"
                    )
                else:
                    status = "⚪ Không cược phiên này"

                final = (
                    f"🎲 *HŨ* • `#{sid}`\n"
                    f"🎯 *{pred}* ➜ *{actual}* • `{dices[0]}-{dices[1]}-{dices[2]}={total}`\n"
                    f"{status}"
                )
                if st.get("hu_simulated"): final += "\n🧪 *CHỈ MÔ PHỎNG — KHÔNG CƯỢC THẬT*"
                bot.edit_message_text(final, cid, st["hu_last_pred_msg_id"], parse_mode="Markdown")
            except Exception:
                pass

        st["hu_current_prediction"] = None
        st["hu_has_bet_this_session"] = False

    try:
        sio.connect(HU_SOCKET_URL, socketio_path=HU_SOCKET_PATH, namespaces=[HU_SOCKET_NAMESPACE],
                    transports=["websocket"], auth={"token": token},
                    headers={"User-Agent": "Mozilla/5.0", "Origin": HU_ORIGIN})
        sio.wait()
    except Exception as exc:
        st["hu_connected"] = False
        logger.warning("Hũ socket dừng cho %s: %s", cid, exc)
    finally:
        if hu_sockets.get(cid) is sio:
            hu_sockets.pop(cid, None)

# ==========================================
# 🎮 MENU
# ==========================================
def main_menu(cid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        telebot.types.InlineKeyboardButton("🔐 Đăng nhập", callback_data="menu_login"),
        telebot.types.InlineKeyboardButton("🔑 Nhập key", callback_data="menu_key"),
        telebot.types.InlineKeyboardButton("💎 Tài khoản", callback_data="menu_info"),
        telebot.types.InlineKeyboardButton("⚡ Auto MD5", callback_data="menu_md5"),
        telebot.types.InlineKeyboardButton("🎲 Auto Hũ", callback_data="menu_hu"),
        telebot.types.InlineKeyboardButton("📖 Hướng dẫn", callback_data="menu_help"),
        telebot.types.InlineKeyboardButton("⏹ Ngắt", callback_data="menu_stop"),
        telebot.types.InlineKeyboardButton("🔄 Làm mới", callback_data="menu_home"),
    ]
    for i in range(0, len(buttons), 2):
        kb.row(*buttons[i:i+2])
    if is_admin(cid):
        kb.row(telebot.types.InlineKeyboardButton("👑 Admin", callback_data="menu_admin"))
    return kb

def menu_text(cid):
    active = check_auth(cid)
    expiry = ("Vĩnh viễn" if is_admin(cid) else format_expire_time(authorized_users[cid])) if active else "Chưa kích hoạt"
    status = "🟢 <b>ĐÃ KÍCH HOẠT</b>" if active else "🟠 <b>CHƯA KÍCH HOẠT</b>"
    lines = [
        "👑 <b>LCVIP BY ONGCHUSUNWIN</b> 👑",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📡 {status} | ⏳ <b>{html.escape(str(expiry))}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "🏠 <b>LỆNH CƠ BẢN</b>",
        "🏡 /start | 📚 /huongdan",
        "🗝️ /nhapkey <code>KEY</code>",
        "🔐 /login <code>TK MK</code>",
        "💎 /thongtin",
        "━━━━━━━━━━━━━━━━━━━━",
        "⚡ <b>AUTO MD5</b>",
        "🟢 /autobetmd5 <code>on 1000</code>",
        "🔴 /autobetmd5 <code>off</code>",
        "🔁 /autobetmd5 <code>x2</code>",
        "━━━━━━━━━━━━━━━━━━━━",
        "🎲 <b>AUTO HŨ</b>",
        "🟢 /autobethu <code>on 1000</code>",
        "🔴 /autobethu <code>off</code>",
        "🔁 /autobethu <code>x2</code>",
        "━━━━━━━━━━━━━━━━━━━━",
        "🔌 /stop",
        f"<i>⚠️ MD5 &amp; Hũ đều tích lũy {WARMUP_SESSIONS} phiên trước khi dự đoán.</i>",
    ]
    if is_admin(cid):
        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━", "👑 <b>ADMIN</b>",
            "👥 /dsuser | 🔴 /tatbot | 🟢 /mobot",
            "📂 /xuatfile | 🔑 /taokey | 🗂️ /danhsachkey",
            "📢 /thongbao | 📋 /lichsulogin",
        ])
    lines.extend(["━━━━━━━━━━━━━━━━━━━━", f"🆘 <b>{html.escape(str(ADMIN_USERNAME))}</b>"])
    return "\n".join(lines)

@bot.message_handler(commands=['start', 'menu'])
def cmd_start(m):
    cid = m.chat.id
    uname = m.from_user.username or m.from_user.first_name or "Unknown"
    all_known_users[cid] = f"@{uname}" if m.from_user.username else uname
    init_user_state(cid)
    if not SYSTEM_ACTIVE and not is_admin(cid):
        return bot.send_message(cid, "🔴 Hệ thống tạm dừng!")
    try:
        bot.set_my_commands(ADMIN_COMMANDS if is_admin(cid) else USER_COMMANDS,
                            scope=telebot.types.BotCommandScopeChat(cid))
    except Exception as exc:
        logger.warning("Set commands lỗi: %s", exc)
    bot.send_message(cid, menu_text(cid), parse_mode="HTML", disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_'))
def menu_callback(call):
    cid = call.message.chat.id
    action = call.data[5:]
    bot.answer_callback_query(call.id)
    if not SYSTEM_ACTIVE and not is_admin(cid):
        return bot.send_message(cid, "🔴 Hệ thống tạm dừng!")
    if action == 'home':
        try:
            bot.edit_message_text(menu_text(cid), cid, call.message.message_id, parse_mode="HTML")
        except Exception:
            bot.send_message(cid, menu_text(cid), parse_mode="HTML")
        return
    prompts = {
        'login': "🔐 `/login TAIKHOAN MATKHAU`",
        'key': "🔑 `/nhapkey MA_KEY`",
        'md5': f"⚡ *AUTO MD5:*\n`/autobetmd5 on 10000`\n`/autobetmd5 off`\n`/autobetmd5 x2`\n⏳ Tích lũy {WARMUP_SESSIONS} phiên.",
        'hu': f"🎲 *AUTO HŨ:*\n`/autobethu on 10000`\n`/autobethu off`\n`/autobethu x2`\n⏳ Tích lũy {WARMUP_SESSIONS} phiên.",
        'admin': "👑 /taokey /danhsachkey /dsuser\n/themadmin /xoaadmin /dsadmin\n/tatbot /mobot /thongbao /xuatfile /lichsulogin",
    }
    if action == 'admin' and not is_admin(cid):
        return bot.send_message(cid, "⛔ Chỉ admin.")
    if action in prompts:
        return bot.send_message(cid, prompts[action], reply_markup=main_menu(cid))
    if action in ('info', 'stop', 'help'):
        from types import SimpleNamespace
        fake = SimpleNamespace(chat=call.message.chat, from_user=call.from_user,
                               text='/' + {'info':'thongtin','stop':'stop','help':'huongdan'}[action])
        {'info':tt, 'stop':sp, 'help':cmd_huongdan}[action](fake)

@bot.message_handler(commands=['huongdan'])
def cmd_huongdan(m):
    cid = m.chat.id
    uname = m.from_user.username or m.from_user.first_name or "Unknown"
    all_known_users[cid] = f"@{uname}" if m.from_user.username else uname
    if not SYSTEM_ACTIVE and not is_admin(cid):
        return safe_send_and_clean(cid, "🔴 Hệ thống tạm tắt!", delay=5)
    msg = (
        f"📖 **HƯỚNG DẪN LCVIP**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 `/nhapkey MÃ`\n"
        f"🔐 `/login TK MK`\n"
        f"💎 `/thongtin`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ **AUTO MD5**\n"
        f"`/autobetmd5 on 10000`\n"
        f"`/autobetmd5 off`\n"
        f"`/autobetmd5 x2`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎲 **AUTO HŨ**\n"
        f"`/autobethu on 10000`\n"
        f"`/autobethu off`\n"
        f"`/autobethu x2`\n"
        f""
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔌 `/stop`\n"
        f"🧪 Cả MD5 và Hũ đều tích lũy {WARMUP_SESSIONS} phiên trước khi dự đoán.\n"
        f"📩 Hỗ trợ: {ADMIN_USERNAME}"
    )
    safe_send_and_clean(cid, msg, delay=15)

# ==========================================
# ADMIN
# ==========================================
@bot.message_handler(commands=['themadmin', 'xoaadmin', 'dsadmin'])
def manage_admin(m):
    if m.from_user.id != ADMIN_ID:
        return bot.reply_to(m, "⛔ Chỉ admin gốc được quản lý admin.")
    parts = m.text.split()
    cmd = parts[0].split('@')[0].lower()
    if cmd == '/dsadmin':
        return bot.reply_to(m, "👑 ADMIN\nUID: " + str([ADMIN_ID]+admin_db['uids']) + "\nUsername: " + str(admin_db['usernames']))
    if len(parts) != 2:
        return bot.reply_to(m, "Dùng /themadmin @username hoặc /themadmin UID\n/xoaadmin @username hoặc /xoaadmin UID")
    value = parts[1].strip()
    if value.lstrip('@').isdigit():
        group, item = 'uids', int(value)
    else:
        group, item = 'usernames', value.lower().lstrip('@')
    if cmd == '/themadmin' and item not in admin_db[group]: admin_db[group].append(item)
    if cmd == '/xoaadmin' and item in admin_db[group]: admin_db[group].remove(item)
    save_admins()
    bot.reply_to(m, f"✅ Đã cập nhật {value}.\n⚠️ Username có thể đổi; nên dùng UID để cấp quyền ổn định.")


@bot.message_handler(commands=['dsuser'])
def admin_list_users(m):
    if not is_admin(m.chat.id, m.from_user.username):
        return safe_send_and_clean(m.chat.id, "⛔ Chỉ admin!", delay=4)
    if not all_known_users:
        return bot.reply_to(m, "📭 Chưa có user.")
    s = "\n".join([f"• `{uid}` | `{u}`" for uid, u in all_known_users.items()])
    bot.reply_to(m, f"👥 **USERS** ({len(all_known_users)}):\n{s}", parse_mode="Markdown")

@bot.message_handler(commands=['tatbot'])
def admin_turn_off_bot(m):
    global SYSTEM_ACTIVE
    if not is_admin(m.chat.id, m.from_user.username): return
    SYSTEM_ACTIVE = False
    bot.reply_to(m, "🔴 **Đã tắt Bot!**", parse_mode="Markdown")
    for uid in all_known_users.keys():
        try:
            bot.send_message(uid, "📢 **BỐ ĐÃ TẮT BOT NÀO MỞ TUỲ DUYÊN OK**", parse_mode="Markdown")
            time.sleep(0.05)
        except: pass

@bot.message_handler(commands=['mobot'])
def admin_turn_on_bot(m):
    global SYSTEM_ACTIVE
    if not is_admin(m.chat.id, m.from_user.username): return
    SYSTEM_ACTIVE = True
    bot.reply_to(m, "🟢 **Đã mở Bot!**", parse_mode="Markdown")

@bot.message_handler(commands=['xuatfile'])
def admin_export_txt(m):
    if not is_admin(m.chat.id, m.from_user.username):
        return safe_send_and_clean(m.chat.id, "⛔ Chỉ admin!", delay=4)
    if not global_session_logs:
        return bot.reply_to(m, "📭 Chưa có dữ liệu.")
    fn = f"lcvip_{datetime.now(ICT).strftime('%Y%m%d_%H%M%S')}.txt"
    fp = f"/tmp/{fn}" if os.path.exists("/tmp") else fn
    try:
        with open(fp, "w", encoding="utf-8") as f:
            f.write("LCVIP | BÁO CÁO PHIÊN GIAO DỊCH\n" + "="*64 + "\n")
            f.write(f"Ngày xuất: {datetime.now(ICT):%d/%m/%Y %H:%M:%S} (GMT+7)\n")
            f.write(f"Tổng số phiên: {len(global_session_logs)}\n")
            f.write("Lưu ý: MÔ PHỎNG không phải tiền thắng/thua thực tế.\n")
            f.write("="*64 + "\n\n")
            for n, log in enumerate(global_session_logs, 1):
                dice = log.get("dice", [])
                dice_text = " - ".join(map(str, dice)) if isinstance(dice, (list, tuple)) else str(dice)
                f.write(f"[{n:04}] {log.get('game','MD5')} | #{log.get('session','?')} | {log.get('time','?')}\n")
                f.write(f"       Chế độ    : {log.get('mode','THẬT')}\n")
                f.write(f"       Dự đoán   : {log.get('prediction','?')}\n")
                f.write(f"       Kết quả   : {log.get('result','?')} | Xúc xắc: {dice_text} = {log.get('total','?')}\n")
                f.write(f"       Đánh giá  : {log.get('status','?')}\n")
                f.write(f"       Lãi/lỗ    : {int(log.get('profit',0)):+,} đ\n")
                f.write(f"       Số dư game: {int(log.get('balance',0)):,} đ\n")
                f.write("-"*64 + "\n")
        with open(fp, "rb") as doc:
            bot.send_document(m.chat.id, doc, caption="📁 Báo cáo LCVIP", parse_mode="Markdown")
        if os.path.exists("/tmp") and os.path.exists(fp):
            os.remove(fp)
    except Exception as e:
        bot.reply_to(m, f"❌ Lỗi: {e}")

@bot.message_handler(commands=['taokey'])
def gk(m):
    if not is_admin(m.chat.id, m.from_user.username): return
    try:
        p = m.text.split()
        hours = int(p[1]) if len(p) > 1 else 720
        k = "ongchusunwin-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        valid_keys[k] = hours * 3600
        save_keys()
        bot.reply_to(m, f"👑 Key ({hours}h):\n<code>{k}</code>", parse_mode="HTML")
    except:
        bot.reply_to(m, "`/taokey 24`", parse_mode="Markdown")

@bot.message_handler(commands=['danhsachkey'])
def lk(m):
    if not is_admin(m.chat.id, m.from_user.username): return
    if not valid_keys:
        return bot.reply_to(m, "📭 Trống.")
    ds = "\n".join([f"🔑 `<code>{k}</code>`: {v//3600}h" for k, v in valid_keys.items()])
    bot.reply_to(m, f"📋 **KEY** ({len(valid_keys)}):\n{ds}", parse_mode="HTML")

@bot.message_handler(commands=['thongbao'])
def broadcast_msg(m):
    if not is_admin(m.chat.id, m.from_user.username): return
    content = m.text.replace("/thongbao", "").strip()
    if not content:
        return bot.reply_to(m, "⚠️ `/thongbao [Nội dung]`", parse_mode="Markdown")
    s, f_ = 0, 0
    for uid in all_known_users.keys():
        try:
            bot.send_message(uid, f"📢 **THÔNG BÁO TỪ ADMIN**\n\n{content}", parse_mode="Markdown")
            s += 1
            time.sleep(0.1)
        except: f_ += 1
    bot.reply_to(m, f"✅ `{s}` (Lỗi: `{f_}`)", parse_mode="Markdown")

@bot.message_handler(commands=['lichsulogin'])
def view_login_history(m):
    if not is_admin(m.chat.id, m.from_user.username): return
    if not login_history:
        return bot.reply_to(m, "📭 Chưa có login.")
    txt = "\n".join([f"🕒 `{i['time']}` | `{i['chat_id']}`\n👤 `{i['username']}` | `{i['nickname']}`" for i in login_history[-15:]])
    bot.reply_to(m, f"📋 **LOGIN**:\n{txt}", parse_mode="Markdown")

# ==========================================
# USER
# ==========================================
@bot.message_handler(commands=['nhapkey'])
def ak(m):
    cid = m.chat.id
    uname = m.from_user.username or m.from_user.first_name or "Unknown"
    all_known_users[cid] = f"@{uname}" if m.from_user.username else uname
    if not SYSTEM_ACTIVE and not is_admin(cid):
        return safe_send_and_clean(cid, "🔴 Hệ thống tạm tắt!", delay=5)
    p = m.text.split()
    if len(p) < 2:
        return bot.send_message(cid, f"⚠️ `/nhapkey MÃ`\n📩 {ADMIN_USERNAME}", parse_mode="Markdown")
    k = p[1].strip()
    if k in valid_keys:
        duration_seconds = valid_keys[k]
        authorized_users[cid] = time.time() + duration_seconds
        del valid_keys[k]
        save_keys()
        exp_dt = datetime.now(ICT) + timedelta(seconds=duration_seconds)
        bot.send_message(cid, f"✅ Kích hoạt VIP!\n📅 Hạn: {exp_dt.strftime('%d/%m/%Y %H:%M')} (ICT)")
    else:
        bot.send_message(cid, f"❌ Key không hợp lệ.\n📩 {ADMIN_USERNAME}")

@bot.message_handler(commands=['thongtin'])
@require_auth
def tt(m):
    cid = m.chat.id
    uname = m.from_user.username or m.from_user.first_name or "Unknown"
    all_known_users[cid] = f"@{uname}" if m.from_user.username else uname
    st = init_user_state(cid)
    han = "Vĩnh Viễn" if is_admin(cid) else datetime.fromtimestamp(authorized_users[cid], ICT).strftime('%d/%m/%Y %H:%M') + " (ICT)"

    x2_md5 = f"Cấp {st['md5_martingale_level']}" if st["md5_martingale_enabled"] else "Tắt"
    x2_hu = f"Cấp {st['hu_martingale_level']}" if st["hu_martingale_enabled"] else "Tắt"
    warm_md5 = "Xong" if st.get("md5_warmup_remaining", 0) == 0 else f"{WARMUP_SESSIONS - st['md5_warmup_remaining']}/{WARMUP_SESSIONS}"
    warm_hu = "Xong" if st.get("hu_warmup_remaining", 0) == 0 else f"{WARMUP_SESSIONS - st['hu_warmup_remaining']}/{WARMUP_SESSIONS}"

    msg = (
        f"👑 **LCVIP BY ONGCHUSUNWIN**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• Hạn VIP: `{han}`\n"
        f"• Số dư: `{st['balance']:,} VNĐ`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ **MD5**\n"
        f"• Auto: `{'BẬT' if st['md5_auto_bet'] else 'TẮT'}` | X2: `{x2_md5}`\n"
        f"• Cược/phiên: `{st.get('md5_bet_amount',0):,}đ`\n"
        f"• W/L: `{st['md5_total_win']}/{st['md5_total_lose']}` | Ròng: `{st['md5_net_profit']:+,}`\n"
        f"• Chuỗi: `{st['md5_win_streak']}T/{st['md5_lose_streak']}B` | Warmup: `{warm_md5}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎲 **HŨ**\n"
        f"• Auto: `{'BẬT' if st['hu_enabled'] else 'TẮT'}` | X2: `{x2_hu}`\n"
        f"• Cược/phiên: `{st.get('hu_bet_amount',0):,}đ`\n"
        f"• W/L: `{st['hu_total_win']}/{st['hu_total_lose']}` | Ròng: `{st['hu_net_profit']:+,}`\n"
        f"• Chuỗi: `{st['hu_win_streak']}T/{st['hu_lose_streak']}B` | Warmup: `{warm_hu}`"
    )
    safe_send_and_clean(cid, msg, delay=10)

@bot.message_handler(commands=['login'])
@require_auth
def lg(m):
    cid = m.chat.id
    uname = m.from_user.username or m.from_user.first_name or "Unknown"
    all_known_users[cid] = f"@{uname}" if m.from_user.username else uname
    p = m.text.split()
    if len(p) != 3:
        return safe_send_and_clean(cid, "⚠️ `/login TAIKHOAN MATKHAU`", delay=5)

    mm = bot.send_message(cid, "🔄 Đang kết nối...")
    res = login_and_get_token(p[1], p[2])
    if "_error" in res:
        try: bot.delete_message(cid, mm.message_id)
        except: pass
        return safe_send_and_clean(cid, f"❌ {res['_error']}", delay=5)

    login_history.append({
        "time": datetime.now(ICT).strftime("%d/%m %H:%M"),
        "chat_id": cid, "username": p[1], "nickname": res['nickname']
    })

    for d in (active_sockets, hu_sockets):
        if cid in d:
            try: d[cid].disconnect()
            except Exception: pass
            d.pop(cid, None)

    st = init_user_state(cid)
    # Reset toàn bộ
    st.update({
        "balance": res["money"], "game_token": res["token"],
        "md5_raw_hist": [], "md5_history": [], "md5_enabled": False, "md5_auto_bet": False,
        "md5_martingale_enabled": False, "md5_martingale_level": 0,
        "md5_bet_amount": 10000, "md5_base_bet": 10000,
        "md5_warmup_remaining": 0, "md5_net_profit": 0, "md5_peak_profit": 0,
        "md5_total_win": 0, "md5_total_lose": 0, "md5_win_streak": 0, "md5_lose_streak": 0,
        "md5_ready_notified": False, "md5_round_open": False, "md5_synced": False,
        "hu_enabled": False, "hu_connected": False, "hu_martingale_enabled": False,
        "hu_martingale_level": 0, "hu_bet_amount": 10000, "hu_base_bet": 10000,
        "hu_warmup_remaining": 0, "hu_net_profit": 0, "hu_peak_profit": 0,
        "hu_total_win": 0, "hu_total_lose": 0, "hu_win_streak": 0, "hu_lose_streak": 0,
        "hu_ready_notified": False, "hu_round_open": False, "hu_synced": False,
    })

    try: bot.delete_message(cid, mm.message_id)
    except: pass

    msg = (
        f"✅ *Đăng nhập LCVIP thành công!*\n"
        f"📛 `{res['nickname']}` | Số dư: `{res['money']:,} VNĐ`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ MD5: `/autobetmd5 on 1000`\n"
        f"🎲 Hũ: `/autobethu on 1000`"
    )
    safe_send_and_clean(cid, msg, delay=10)
    threading.Thread(target=start_md5_websocket, args=(cid, res["token"]), daemon=True).start()

# ==========================================
# ⚡ AUTO MD5 (SONG SONG VỚI HŨ)
# ==========================================
@bot.message_handler(commands=['autobetmd5'])
@require_auth
def cmd_autobetmd5(m):
    cid = m.chat.id
    st = init_user_state(cid)
    p = m.text.split()

    if len(p) < 2:
        x2 = "BẬT" if st["md5_martingale_enabled"] else "TẮT"
        return safe_send_and_clean(
            cid,
            f"⚡ *AUTO MD5:* `{'BẬT' if st['md5_auto_bet'] else 'TẮT'}` | X2: `{x2}`\n"
            f"• `/autobetmd5 on 1000`\n• `/autobetmd5 off`\n• `/autobetmd5 x2`",
            delay=10
        )

    action = p[1].lower()

    if action == "on":
        if cid not in active_sockets:
            return safe_send_and_clean(cid, "⚠️ Hãy `/login` trước.", delay=4)
        if len(p) != 3:
            return safe_send_and_clean(cid, "⚠️ `/autobetmd5 on 1000`", delay=8)
        try:
            amt = int(p[2])
        except ValueError:
            return safe_send_and_clean(cid, "❌ Tiền cược phải là số.", delay=8)
        if amt < MIN_BET:
            return safe_send_and_clean(cid, f"❌ Tối thiểu `{MIN_BET:,}đ`.", delay=8)
        if amt > int(st.get("balance", 0)) and not is_admin(cid):
            return safe_send_and_clean(cid, "⚠️ Số dư không đủ.", delay=8)

        st["md5_bet_amount"] = amt
        st["md5_base_bet"] = amt
        st["md5_martingale_level"] = 0
        st["md5_auto_bet"] = True
        st["md5_enabled"] = True
        st["md5_ready_notified"] = len(st.get("md5_raw_hist", [])) >= MIN_HISTORY
        st["md5_warmup_remaining"] = WARMUP_SESSIONS

        need = max(0, MIN_HISTORY - len(st.get("md5_raw_hist", [])))
        data_line = f"📚 Có `{len(st.get('md5_raw_hist', []))}` phiên, cần thêm `{need}`." if need else f"📚 Đủ `{len(st.get('md5_raw_hist', []))}` phiên."
        return safe_send_and_clean(
            cid,
            f"🔴 *BẬT AUTO MD5*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Cược/phiên: `{amt:,}đ`\n"
            f"⏳ Tích lũy: `{WARMUP_SESSIONS}` phiên\n"
            f"{data_line}\n"
            f"⚙️ `/autobetmd5 x2` để bật gấp đôi\n"
            f"⏹ `/autobetmd5 off` để dừng",
            delay=0
        )

    elif action == "off":
        st["md5_enabled"] = False
        st["md5_auto_bet"] = False
        st["md5_current_prediction"] = None
        st["md5_has_bet_this_session"] = False
        st["md5_round_open"] = False
        st["md5_warmup_remaining"] = 0
        return safe_send_and_clean(cid, "🔴 *Đã tắt Auto MD5.*", delay=0)

    elif action == "x2":
        st["md5_martingale_enabled"] = not st.get("md5_martingale_enabled", False)
        st["md5_martingale_level"] = 0
        if st["md5_martingale_enabled"]:
            safe_send_and_clean(cid, f"🔁 *BẬT X2 MD5* (Max {MAX_MARTINGALE_LEVEL} cấp ×{MARTINGALE_MULTIPLIER})", delay=6)
        else:
            safe_send_and_clean(cid, "🔴 *TẮT X2 MD5*", delay=5)
    else:
        safe_send_and_clean(cid, "⚠️ Dùng `on 1000` | `off` | `x2`", delay=8)

# ==========================================
# 🎲 AUTO HŨ (SONG SONG)
# ==========================================
@bot.message_handler(commands=['autobethu'])
@require_auth
def cmd_autobethu(m):
    cid = m.chat.id
    st = init_user_state(cid)
    p = m.text.split()

    if len(p) < 2:
        x2 = "BẬT" if st["hu_martingale_enabled"] else "TẮT"
        return safe_send_and_clean(
            cid,
            f"🎲 *AUTO HŨ:* `{'BẬT' if st['hu_enabled'] else 'TẮT'}` | X2: `{x2}`\n"
            f"• `/autobethu on 1000`\n• `/autobethu off`\n• `/autobethu x2`",
            delay=10
        )

    action = p[1].lower()

    if action == "on":
        if not st.get("game_token"):
            return safe_send_and_clean(cid, "⚠️ Hãy `/login` trước.", delay=6)
        amount = st.get("hu_bet_amount", 10000)
        if len(p) >= 3:
            try:
                amount = int(p[2])
            except ValueError:
                return safe_send_and_clean(cid, "❌ Cú pháp: `/autobethu on 10000`", delay=6)
        if amount < MIN_BET:
            return safe_send_and_clean(cid, f"❌ Tối thiểu `{MIN_BET:,}đ`.", delay=6)
        if amount > int(st.get("balance", 0)) and not is_admin(cid):
            return safe_send_and_clean(cid, "❌ Số dư không đủ.", delay=6)

        st["hu_bet_amount"] = amount
        st["hu_base_bet"] = amount
        st["hu_enabled"] = True
        st["hu_martingale_level"] = 0
        st["hu_ready_notified"] = len(hu_shared_history) >= MIN_HISTORY
        st["hu_warmup_remaining"] = WARMUP_SESSIONS

        if cid not in hu_sockets:
            threading.Thread(target=start_hu_websocket, args=(cid, st["game_token"]), daemon=True).start()

        need = max(0, MIN_HISTORY - len(hu_shared_history))
        data_line = f"📚 Có `{len(hu_shared_history)}` phiên, cần thêm `{need}`." if need else f"📚 Đủ `{len(hu_shared_history)}` phiên."
        return safe_send_and_clean(
            cid,
            f"🔴 *BẬT AUTO HŨ*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Cược/phiên: `{amount:,}đ`\n"
            f"⏳ Tích lũy: `{WARMUP_SESSIONS}` phiên\n"
            f"{data_line}\n"
            f"⚙️ `/autobethu x2` để bật gấp đôi\n"
            f"⏹ `/autobethu off` để dừng",
            delay=0
        )

    elif action == "off":
        st["hu_enabled"] = False
        st["hu_current_prediction"] = None
        st["hu_has_bet_this_session"] = False
        st["hu_round_open"] = False
        st["hu_warmup_remaining"] = 0
        if cid in hu_sockets:
            try: hu_sockets[cid].disconnect()
            except Exception: pass
            hu_sockets.pop(cid, None)
        st["hu_connected"] = False
        return safe_send_and_clean(cid, "🔴 *Đã tắt Auto Hũ.*", delay=0)

    elif action == "x2":
        st["hu_martingale_enabled"] = not st.get("hu_martingale_enabled", False)
        st["hu_martingale_level"] = 0
        if st["hu_martingale_enabled"]:
            safe_send_and_clean(cid, f"🔁 *BẬT X2 HŨ* (Max {MAX_MARTINGALE_LEVEL} cấp ×{MARTINGALE_MULTIPLIER})", delay=6)
        else:
            safe_send_and_clean(cid, "🔴 *TẮT X2 HŨ*", delay=5)
    else:
        safe_send_and_clean(cid, "⚠️ Dùng `on 1000` | `off` | `x2`", delay=8)

@bot.message_handler(commands=['stop'])
@require_auth
def sp(m):
    cid = m.chat.id
    for d in (active_sockets, hu_sockets):
        if cid in d:
            try: d[cid].disconnect()
            except Exception: pass
            d.pop(cid, None)
    st = init_user_state(cid)
    st.update({
        "md5_enabled": False, "md5_auto_bet": False, "md5_martingale_enabled": False,
        "md5_martingale_level": 0, "md5_warmup_remaining": 0, "md5_round_open": False,
        "md5_has_bet_this_session": False, "md5_current_prediction": None,
        "hu_enabled": False, "hu_connected": False, "hu_martingale_enabled": False,
        "hu_martingale_level": 0, "hu_warmup_remaining": 0, "hu_round_open": False,
        "hu_has_bet_this_session": False, "hu_current_prediction": None,
    })
    safe_send_and_clean(cid, "⏹️ *Đã ngắt toàn bộ MD5 + Hũ!*", delay=5)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("👑 LCVIP BY ONGCHUSUNWIN - MD5 & HŨ SONG SONG")
    bot.infinity_polling()