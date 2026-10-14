import telebot
import requests
import hashlib
import base64
import json
import logging
import threading
import socketio
import random
import string
import os
import statistics
from flask import Flask
from collections import deque, defaultdict
from datetime import datetime, timedelta

# =========================
# FLASK KEEP ALIVE (RENDER)
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 LC79 BOT ONLINE"

@app.route("/health")
def health():
    return {"status": "online", "bot": "LC79", "server": "Render"}

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ==========================================
# CẤU HÌNH HỆ THỐNG BOT & LOGGING
# ==========================================
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 8681721470))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@bulontaodihaha")
bot = telebot.TeleBot(BOT_TOKEN)

# Danh sách lệnh hiển thị cho User thường (Đã xóa /lichsucau và lệnh admin)
USER_COMMANDS = [
    telebot.types.BotCommand("/start", "🏠 Mở menu chính"),
    telebot.types.BotCommand("/huongdan", "📖 Hướng dẫn"),
    telebot.types.BotCommand("/nhapkey", "🔑 Nhập key VIP"),
    telebot.types.BotCommand("/thongtin", "💎 Thông tin tài khoản"),
    telebot.types.BotCommand("/login", "🔐 Đăng nhập game"),
    telebot.types.BotCommand("/autobet", "⚡ Bật/Tắt Auto"),
    telebot.types.BotCommand("/x2", "💸 Quản lý X2"),
    telebot.types.BotCommand("/stop", "⏹️ Ngắt kết nối"),
]

# Danh sách lệnh đầy đủ dành riêng cho Admin
ADMIN_COMMANDS = USER_COMMANDS + [
    telebot.types.BotCommand("/taokey", "👑 [ADMIN] Tạo key"),
    telebot.types.BotCommand("/danhsachkey", "📋 [ADMIN] DS Key"),
    telebot.types.BotCommand("/lichsulogin", "📋 [ADMIN] DS Login"),
]

bot.set_my_commands(USER_COMMANDS)

HISTORY_API_URL = "https://wtxmd52.tele68.com/v1/txmd5/sessions"
API_URL_FALLBACK = "https://living-telecommunications-start-consoles.trycloudflare.com/api/txmd5"
MAX_HISTORY_STORE = 500
MIN_CONFIDENCE_AUTO_BET = 55
AUTO_BET_RUN_UNTIL_STOP = True
MAX_MARTINGALE_LEVEL = 6
MARTINGALE_MULTIPLIER = 2

active_sockets = {}
user_states = {}
valid_keys = {}
authorized_users = {}
login_history = []

# ==========================================
# ⏱️ HỆ THỐNG TỰ ĐỘNG XÓA TIN NHẮN RÁC
# ==========================================
def delete_message_later(chat_id, message_id, delay=5):
    def _delete():
        time.sleep(delay)
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    threading.Thread(target=_delete, daemon=True).start()

def safe_send_and_clean(chat_id, text, parse_mode="Markdown", reply_markup=None, delay=6):
    try:
        msg = bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
        delete_message_later(chat_id, msg.message_id, delay)
        return msg
    except Exception:
        return None

# ============================================================
# 🧠 REALBRAIN TỐI ƯU
# ============================================================
class RealBrain:
    def __init__(self):
        self.results = deque(maxlen=500)
        self.sums = deque(maxlen=500)
        self.perf = deque(maxlen=100)
        self.pattern_memory = defaultdict(lambda: defaultdict(int))
        self.pattern_total = defaultdict(int)
        self.streak_memory = defaultdict(lambda: {"THEO": 0, "BE": 0})

    def push(self, data):
        for h in data:
            if isinstance(h, dict) and 'result' in h:
                res = h['result']
            elif isinstance(h, str):
                res = h
            else:
                continue
            if 'TÀI' in str(res).upper() or 'TAI' in str(res).upper() or res == 'T':
                self.results.append('TAI')
            elif 'XỈU' in str(res).upper() or 'XIU' in str(res).upper() or res == 'X':
                self.results.append('XIU')
            else:
                self.results.append(res)
            if isinstance(h, dict) and 'total' in h:
                self.sums.append(h['total'])
            else:
                self.sums.append(10)

    def learn(self):
        all_res = list(self.results)
        n = len(all_res)
        if n < 10:
            return
        
        self.pattern_memory.clear()
        self.pattern_total.clear()
        for i in range(n):
            for plen in [3, 4, 5, 6]:
                if i >= plen and i < n:
                    pat = tuple(all_res[i-plen:i])
                    nxt = all_res[i]
                    self.pattern_memory[pat][nxt] += 1
                    self.pattern_total[pat] += 1
        
        self.streak_memory.clear()
        i = 0
        while i < n:
            last = all_res[i]
            s = 1
            j = i + 1
            while j < n and all_res[j] == last:
                s += 1
                j += 1
            if j < n:
                nxt = all_res[j]
                if nxt == last:
                    self.streak_memory[s]["THEO"] += 1
                else:
                    self.streak_memory[s]["BE"] += 1
            i = j

    def predict(self, history):
        if len(history) < 10:
            return None, 0, "Đang nạp dữ liệu..."
        
        self.push(history)
        self.learn()
        r = list(self.results)
        s_list = list(self.sums)
        n = len(r)
        if n < 5:
            return None, 0, "Đang phân tích..."
        
        last = r[-1]
        last_sum = s_list[-1] if s_list else 10
        
        s = 1
        for x in reversed(r[:-1]):
            if x == last:
                s += 1
            else:
                break
        
        candidates = []
        
        for plen in [3, 4, 5, 6]:
            if n >= plen:
                pat = tuple(r[-plen:])
                if pat in self.pattern_memory and self.pattern_total[pat] >= 3:
                    data = self.pattern_memory[pat]
                    total = self.pattern_total[pat]
                    for side in ('TAI', 'XIU'):
                        count = data.get(side, 0)
                        rate = count / total if total > 0 else 0
                        if rate >= 0.58 and count >= 2:
                            conf = min(0.90, 0.55 + rate * 0.35)
                            candidates.append((side, conf, f"Mẫu {plen} ({count}/{total})"))
        
        if s in self.streak_memory:
            data = self.streak_memory[s]
            theo, be = data["THEO"], data["BE"]
            total = theo + be
            if total >= 3:
                theo_rate = theo / total
                be_rate = be / total
                if be_rate >= 0.60:
                    pred = 'XIU' if last == 'TAI' else 'TAI'
                    candidates.append((pred, min(0.88, 0.55 + be_rate * 0.30), f"Bẻ bệt {s}"))
                elif theo_rate >= 0.60:
                    candidates.append((last, min(0.85, 0.55 + theo_rate * 0.30), f"Theo bệt {s}"))
        
        if n >= 20:
            try:
                avg = statistics.mean(s_list[-30:]) if len(s_list) >= 30 else statistics.mean(s_list)
                std = statistics.stdev(s_list[-30:]) if len(s_list) >= 5 else 3.0
                if std > 0:
                    z = (last_sum - avg) / std
                    if z >= 2.2:
                        candidates.append(('XIU', 0.85, f"Z={z:.1f} cao"))
                    elif z <= -2.2:
                        candidates.append(('TAI', 0.85, f"Z={z:.1f} thấp"))
            except:
                pass
        
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            best = candidates[0]
            return best[0], best[1], best[2]
        
        r20 = r[-20:]
        t_cnt = r20.count('TAI')
        x_cnt = r20.count('XIU')
        if t_cnt > x_cnt:
            return "TAI", 0.58, f"Xu hướng TÀI"
        else:
            return "XIU", 0.58, f"Xu hướng XỈU"

    def update(self, pred, actual):
        if pred is None:
            return
        self.perf.append(1 if pred == actual else 0)

_brain = RealBrain()

def feed_history(history):
    _brain.push(history)

def pro_predict(history, **kw):
    return _brain.predict(history)

def update_result(pred, actual, **kw):
    _brain.update(pred, actual)

# ==========================================
# 🛡️ HỆ THỐNG & KIỂM TRA QUYỀN VIP
# ==========================================
def init_user_state(chat_id):
    if chat_id not in user_states:
        user_states[chat_id] = {
            "raw_hist": [], "history": [], "points_history": [],
            "auto_bet_enabled": False, "bet_amount": 10000,
            "base_bet": 10000,
            "martingale_enabled": False,
            "martingale_level": 0,
            "current_prediction": None, "waiting_for_result": False,
            "has_bet_this_session": False, "session_id": None, "balance": 0,
            "win_streak": 0, "lose_streak": 0, "total_win": 0, "total_lose": 0
        }

def parse_lines(data):
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

def fetch_history_from_api(limit=60):
    for url in (HISTORY_API_URL, API_URL_FALLBACK):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Origin": "https://lc79b.bet"}, timeout=10)
            if r.status_code != 200:
                continue
            d = r.json()
            arr = parse_lines(d)
            if arr:
                return arr[-limit:]
        except Exception:
            continue
    return []

def check_auth(chat_id):
    if chat_id == ADMIN_ID:
        return True
    if chat_id in authorized_users:
        if time.time() <= authorized_users[chat_id]:
            return True
        else:
            del authorized_users[chat_id]
    return False

def require_auth(fn):
    def wr(m, *a, **kw):
        if not check_auth(m.chat.id):
            safe_send_and_clean(m.chat.id, f"🔒 **Chưa kích hoạt VIP!**\n🔑 Nhập key: `/nhapkey MÃ`\n📩 Mua key liên hệ Admin: {ADMIN_USERNAME}", delay=6)
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
    if d > 0:
        return f"{d}n {h}g {m}p"
    return f"{h}g {m}p"

def tinh_tien_cuoc(cid):
    st = user_states[cid]
    if not st["martingale_enabled"]:
        return st["bet_amount"]
    lv = st["martingale_level"]
    if lv <= 0:
        return st["base_bet"]
    return min(st["base_bet"] * (MARTINGALE_MULTIPLIER ** lv), st["base_bet"] * (MARTINGALE_MULTIPLIER ** MAX_MARTINGALE_LEVEL))

def ai_tu_hoc(cid, du_doan, thuc_te):
    st = user_states[cid]
    update_result(du_doan, thuc_te)
    if du_doan == thuc_te:
        st["win_streak"] += 1
        st["lose_streak"] = 0
        st["total_win"] += 1
        st["martingale_level"] = 0
    else:
        st["lose_streak"] += 1
        st["win_streak"] = 0
        st["total_lose"] += 1
        if st["martingale_enabled"] and st["martingale_level"] < MAX_MARTINGALE_LEVEL:
            st["martingale_level"] += 1

# ==========================================
# 🌐 LOGIN + SOCKET
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

def start_websocket(cid, token, username=""):
    if cid in active_sockets:
        try:
            active_sockets[cid].disconnect()
        except Exception:
            pass
    sio = socketio.Client(reconnection=True, reconnection_attempts=99999, reconnection_delay=3, logger=False, engineio_logger=False)
    active_sockets[cid] = sio
    init_user_state(cid)

    @sio.event(namespace='/txmd5')
    def connect():
        arr = fetch_history_from_api(60)
        st = user_states[cid]
        if arr:
            st["raw_hist"] = arr
            st["history"] = [x["result"] for x in arr]
            st["points_history"] = [x["total"] for x in arr]
            feed_history(arr)
            safe_send_and_clean(cid, f"🟢 **Kết nối VIP OK** ({len(arr)} phiên)", delay=4)

    @sio.on('new-session', namespace='/txmd5')
    def new_sess(d):
        st = user_states[cid]
        st["session_id"] = d.get("id")
        st["has_bet_this_session"] = False
        result = pro_predict(st["raw_hist"]) if st["raw_hist"] else None
        if result and result[0]:
            st["current_prediction"] = result[0]
            dt = int(result[1] * 100)
            reason = result[2] if len(result) > 2 else ""
            tien = tinh_tien_cuoc(cid)
            x2_st = f"C{st['martingale_level']}" if st["martingale_enabled"] else "Tắt"
            
            msg = (
                f"🔹 **#{st['session_id']}** | 🤖 **{result[0]}** ({dt}%)\n"
                f"💡 _{reason}_ | 💰 `{tien:,}` | X2: `{x2_st}`"
            )
            safe_send_and_clean(cid, msg, delay=8)

    @sio.on('tick-update', namespace='/txmd5')
    def tk(d):
        st = user_states[cid]
        if d.get("state") == "BETTING" and st["auto_bet_enabled"] and st["current_prediction"] and AUTO_BET_RUN_UNTIL_STOP:
            if not st["has_bet_this_session"]:
                tien = tinh_tien_cuoc(cid)
                sio.emit("bet", {"type": st["current_prediction"], "amount": tien}, namespace="/txmd5")
                st["has_bet_this_session"] = True
                safe_send_and_clean(cid, f"🚀 **[AUTO]** Đặt **{st['current_prediction']}** | `{tien:,}`", delay=4)

    @sio.on('bet-result', namespace='/txmd5')
    def br(d):
        st = user_states[cid]
        if "postBalance" in d:
            st["balance"] = d["postBalance"]

    @sio.on('session-result', namespace='/txmd5')
    def sr(d):
        res = d.get("resultTruyenThong")
        st = user_states[cid]
        if res in ("TAI", "XIU"):
            rec = {"session": d.get("id"), "dice": d["dices"], "total": sum(d["dices"]), "result": res}
            st["raw_hist"].append(rec)
            st["history"].append(res)
            st["points_history"].append(rec["total"])
            if len(st["raw_hist"]) > MAX_HISTORY_STORE:
                st["raw_hist"].pop(0)
                st["history"].pop(0)
                st["points_history"].pop(0)
            feed_history([rec])
            ai_tu_hoc(cid, st["current_prediction"], res)
            tt = "🟢 **THẮNG**" if st["current_prediction"] == res else "🔴 **THUA**"
            
            msg = f"🎲 **KQ #{d.get('id')}**: **{res}** ({sum(d['dices'])}) → {tt} | Lệch: `{st['lose_streak']}`"
            safe_send_and_clean(cid, msg, delay=5)

    try:
        sio.connect("https://wtxmd52.tele68.com", socketio_path="txmd5/", namespaces=["/txmd5"],
                    transports=["websocket"], auth={"token": token},
                    headers={"User-Agent": "Mozilla/5.0", "Origin": "https://lc79b.bet"})
        sio.wait()
    except Exception as e:
        pass

# ==========================================
# 🎨 GIAO DIỆN MENU VIP
# ==========================================
def vip_menu():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("🔐 Đăng Nhập", callback_data="login"),
        telebot.types.InlineKeyboardButton("⚡ Auto Bet", callback_data="auto"),
        telebot.types.InlineKeyboardButton("💸 Quản Lý X2", callback_data="x2"),
        telebot.types.InlineKeyboardButton("💎 Thông Tin", callback_data="tt"),
        telebot.types.InlineKeyboardButton("⏹️ Ngắt Sốc", callback_data="stop")
    )
    return kb

@bot.message_handler(commands=['start'])
def cmd_start(m):
    cid = m.chat.id
    init_user_state(cid)
    
    if cid == ADMIN_ID:
        bot.set_my_commands(ADMIN_COMMANDS, scope=telebot.types.BotCommandScopeChat(cid))
    else:
        bot.set_my_commands(USER_COMMANDS, scope=telebot.types.BotCommandScopeChat(cid))

    if check_auth(cid):
        han = "Vĩnh Viễn" if cid == ADMIN_ID else format_expire_time(authorized_users[cid])
        msg = f"💎 **LC79 VIP** | Hạn: `{han}`\nChọn tính năng dưới đây:"
        safe_send_and_clean(cid, msg, reply_markup=vip_menu(), delay=10)
    else:
        msg = f"🔒 **Chưa kích hoạt VIP**\n🔑 Nhập key: `/nhapkey MÃ`\n📩 Liên hệ mua key: {ADMIN_USERNAME}"
        safe_send_and_clean(cid, msg, delay=10)

@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    cid = c.message.chat.id
    if not check_auth(cid):
        return safe_send_and_clean(cid, f"🔒 **Cần kích hoạt VIP để sử dụng!**\n📩 Liên hệ: {ADMIN_USERNAME}", delay=5)

    if c.data == "login":
        safe_send_and_clean(cid, "🔐 `/login TAIKHOAN MATKHAU`", delay=6)
    elif c.data == "auto":
        safe_send_and_clean(cid, "⚡ Bật: `/autobet on 10000` | Tắt: `/autobet off`", delay=6)
    elif c.data == "x2":
        safe_send_and_clean(cid, "💸 Bật: `/x2 on` | Tắt: `/x2 off` (Max 6 cấp)", delay=6)
    elif c.data == "tt":
        safe_send_and_clean(cid, "💎 Xem nhanh: `/thongtin`", delay=6)
    elif c.data == "stop":
        safe_send_and_clean(cid, "⏹️ Dừng: `/stop`", delay=6)

@bot.message_handler(commands=['huongdan'])
def cmd_hd(m):
    msg = (
        f"📖 **HƯỚNG DẪN NHANH**\n"
        f"🔑 `/nhapkey [Mã]`\n"
        f"🔐 `/login [TK] [MK]`\n"
        f"⚡ `/autobet on [Tiền]` | `off`\n"
        f"💸 `/x2 on` | `off`\n"
        f"💎 `/thongtin` | ⏹️ `/stop`\n"
        f"📩 Mua key: {ADMIN_USERNAME}"
    )
    safe_send_and_clean(m.chat.id, msg, delay=8)

@bot.message_handler(commands=['taokey'])
def gk(m):
    if m.chat.id != ADMIN_ID:
        return
    try:
        p = m.text.split()
        d = int(p[1]) if len(p) > 1 else 30
        k = "VIP-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        valid_keys[k] = d
        ht = (datetime.now() + timedelta(days=d)).strftime("%d/%m %H:%M")
        bot.reply_to(m, f"👑 Key: `<code>{k}</code>` ({d}n - {ht})", parse_mode="HTML")
    except:
        bot.reply_to(m, "`/taokey 30`", parse_mode="Markdown")

@bot.message_handler(commands=['danhsachkey'])
def lk(m):
    if m.chat.id != ADMIN_ID:
        return
    if not valid_keys:
        return bot.reply_to(m, "📭 Trống")
    ds = "\n".join([f"🔑 `<code>{k}</code>`: {v}n" for k, v in valid_keys.items()])
    bot.reply_to(m, f"📋 **DS KEY** ({len(valid_keys)}):\n{ds}", parse_mode="HTML")

@bot.message_handler(commands=['lichsulogin'])
def view_login_history(m):
    if m.chat.id != ADMIN_ID:
        return
    if not login_history:
        return bot.reply_to(m, "📭 Chưa có login nào.")
    txt = "\n".join([f"🕒 `{i['time']}` | ID:`{i['chat_id']}`\n👤 `{i['username']}` | `{i['nickname']}`" for i in login_history[-15:]])
    bot.reply_to(m, f"📋 **LỊCH SỬ LOGIN**:\n{txt}", parse_mode="Markdown")

@bot.message_handler(commands=['nhapkey'])
def ak(m):
    p = m.text.split()
    if len(p) < 2:
        return safe_send_and_clean(m.chat.id, f"⚠️ `/nhapkey VIP-XXX`\n📩 Mua key: {ADMIN_USERNAME}", delay=5)
    k = p[1].upper()
    if k in valid_keys:
        authorized_users[m.chat.id] = time.time() + valid_keys[k] * 86400
        del valid_keys[k]
        ht = datetime.fromtimestamp(authorized_users[m.chat.id]).strftime("%d/%m %H:%M")
        safe_send_and_clean(m.chat.id, f"✅ **Kích hoạt VIP thành công!** Hạn: `{ht}`", delay=6, reply_markup=vip_menu())
    else:
        safe_send_and_clean(m.chat.id, f"❌ Key không hợp lệ hoặc đã dùng!\n📩 Mua key: {ADMIN_USERNAME}", delay=5)

@bot.message_handler(commands=['thongtin'])
@require_auth
def tt(m):
    cid = m.chat.id
    init_user_state(cid)
    st = user_states[cid]
    han = "Vĩnh Viễn" if cid == ADMIN_ID else format_expire_time(authorized_users[cid])
    x2 = f"Cấp {st['martingale_level']}" if st["martingale_enabled"] else "Tắt"
    
    msg = (
        f"💎 **THÔNG TIN VIP**\n"
        f"• Hạn: {han} | Auto: `{'Bật' if st['auto_bet_enabled'] else 'Tắt'}`\n"
        f"• X2: {x2} | Gốc: `{st['base_bet']:,}`\n"
        f"• Số dư: `{st['balance']:,}`\n"
        f"• Thắng/Thua: `{st['total_win']}` / `{st['total_lose']}`"
    )
    safe_send_and_clean(cid, msg, delay=10)

@bot.message_handler(commands=['login'])
@require_auth
def lg(m):
    p = m.text.split()
    if len(p) != 3:
        return safe_send_and_clean(m.chat.id, "⚠️ `/login TAIKHOAN MATKHAU`", delay=5)
    
    mm = bot.send_message(m.chat.id, "🔄 Đang kết nối...")
    res = login_and_get_token(p[1], p[2])
    if "_error" in res:
        try: bot.delete_message(m.chat.id, mm.message_id)
        except: pass
        return safe_send_and_clean(m.chat.id, f"❌ {res['_error']}", delay=5)
    
    login_history.append({
        "time": datetime.now().strftime("%d/%m %H:%M"),
        "chat_id": m.chat.id,
        "username": p[1],
        "nickname": res['nickname']
    })

    init_user_state(m.chat.id)
    st = user_states[m.chat.id]
    st["balance"] = res["money"]
    st["base_bet"] = st["bet_amount"]
    
    try: bot.delete_message(m.chat.id, mm.message_id)
    except: pass

    msg = f"✅ **Đăng nhập OK**: `{res['nickname']}` | Dư: `{res['money']:,}`"
    safe_send_and_clean(m.chat.id, msg, delay=8, reply_markup=vip_menu())
    threading.Thread(target=start_websocket, args=(m.chat.id, res["token"], p[1]), daemon=True).start()

@bot.message_handler(commands=['autobet'])
@require_auth
def ab(m):
    cid = m.chat.id
    if cid not in active_sockets:
        return safe_send_and_clean(cid, "⚠️ Cần `/login` trước!", delay=4)
    p = m.text.split()
    if len(p) < 2:
        return safe_send_and_clean(cid, "⚠️ `/autobet on 10000` hoặc `off`", delay=4)
    st = user_states[cid]
    if p[1].lower() == "on":
        amt = int(p[2]) if len(p) > 2 else 10000
        st["auto_bet_enabled"] = True
        st["bet_amount"] = amt
        st["base_bet"] = amt
        st["martingale_level"] = 0
        safe_send_and_clean(cid, f"🟢 **Auto Bật** | Mức: `{amt:,}`", delay=6)
    else:
        st["auto_bet_enabled"] = False
        safe_send_and_clean(cid, "🔴 **Auto Tắt**", delay=5)

@bot.message_handler(commands=['x2'])
@require_auth
def cmd_x2(m):
    cid = m.chat.id
    st = user_states[cid]
    p = m.text.split()
    if len(p) < 2:
        tt = f"Cấp {st['martingale_level']}" if st["martingale_enabled"] else "Tắt"
        return safe_send_and_clean(cid, f"💸 **X2**: {tt} | `/x2 on` hoặc `off`", delay=5)
    if p[1].lower() == "on":
        st["martingale_enabled"] = True
        st["martingale_level"] = 0
        safe_send_and_clean(cid, "💸 **Đã bật X2 khi thua** (Max 6 cấp)", delay=6)
    else:
        st["martingale_enabled"] = False
        st["martingale_level"] = 0
        safe_send_and_clean(cid, "🔴 **Đã tắt X2**", delay=5)

@bot.message_handler(commands=['stop'])
@require_auth
def sp(m):
    cid = m.chat.id
    if cid in active_sockets:
        try:
            active_sockets[cid].disconnect()
        except Exception:
            pass
        del active_sockets[cid]
    st = user_states[cid]
    st["auto_bet_enabled"] = False
    st["martingale_enabled"] = False
    st["martingale_level"] = 0
    safe_send_and_clean(cid, "⏹️ **Đã ngắt kết nối an toàn!**", delay=5)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("👑 LC79 ELITE PRO MAX - CLEAN & SECURE")
    bot.infinity_polling()
