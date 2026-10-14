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
from datetime import datetime, timezone, timedelta

# Múi giờ Việt Nam (GMT+7)
ICT = timezone(timedelta(hours=7))

# =========================
# FLASK KEEP ALIVE (RENDER/RAILWAY)
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 LC79 BOT ONLINE"

@app.route("/health")
def health():
    return {"status": "online", "bot": "LC79", "server": "Railway"}

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

# Danh sách lệnh cho User thường
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

# Danh sách lệnh cho Admin
ADMIN_COMMANDS = USER_COMMANDS + [
    telebot.types.BotCommand("/lichsucau", "📊 [ADMIN] Xem lịch sử 30 phiên"),
    telebot.types.BotCommand("/xuatfile", "📁 [ADMIN] Xuất file TXT lịch sử"),
    telebot.types.BotCommand("/taokey", "👑 [ADMIN] Tạo key theo giờ"),
    telebot.types.BotCommand("/danhsachkey", "📋 [ADMIN] DS Key"),
    telebot.types.BotCommand("/thongbao", "📢 [ADMIN] Gửi thông báo All"),
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
all_known_users = set()
login_history = []
global_session_logs = deque(maxlen=200)

# ==========================================
# ⏱️ TỰ ĐỘNG XÓA TIN NHẮN RÁC
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
# 🧠 REALBRAIN THUẬT TOÁN
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
                    candidates.append((last, min(0.78, 0.55 + theo_rate * 0.30), f"Theo bệt {s}"))
        
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
# 🛡️ XÁC THỰC & TIỆN ÍCH
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
            "win_streak": 0, "lose_streak": 0, "total_win": 0, "total_lose": 0,
            "last_pred_msg_id": None, "last_bet_amount": 10000
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
            safe_send_and_clean(m.chat.id, f"🔒 **Chưa kích hoạt VIP!**\n🔑 Nhập key: `/nhapkey MÃ`\n📩 Liên hệ mua key: {ADMIN_USERNAME}", delay=6)
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
                f"🔹 **#{st['session_id']}** | 🤖 Dự đoán: **{result[0]}** ({dt}%)\n"
                f"💡 _{reason}_ | 💰 Cược: `{tien:,}` | X2: `{x2_st}`"
            )
            sent_msg = safe_send_and_clean(cid, msg, delay=0)
            if sent_msg:
                st["last_pred_msg_id"] = sent_msg.message_id

    @sio.on('tick-update', namespace='/txmd5')
    def tk(d):
        st = user_states[cid]
        if d.get("state") == "BETTING" and st["auto_bet_enabled"] and st["current_prediction"] and AUTO_BET_RUN_UNTIL_STOP:
            if not st["has_bet_this_session"]:
                tien = tinh_tien_cuoc(cid)
                st["last_bet_amount"] = tien
                sio.emit("bet", {"type": st["current_prediction"], "amount": tien}, namespace="/txmd5")
                st["has_bet_this_session"] = True
                
                if st.get("last_pred_msg_id"):
                    try:
                        edited_text = (
                            f"🔹 **#{st['session_id']}** | 🚀 **ĐÃ ĐẶT {st['current_prediction']}**\n"
                            f"💰 Tiền cược: **{tien:,} VNĐ**"
                        )
                        bot.edit_message_text(edited_text, cid, st["last_pred_msg_id"], parse_mode="Markdown")
                    except Exception:
                        pass

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
            
            pred = st["current_prediction"]
            has_bet = st.get("has_bet_this_session", False)
            bet_amt = st.get("last_bet_amount", 10000)
            
            if not has_bet:
                # Trường hợp không đặt cược thành công trong phiên
                if st.get("last_pred_msg_id"):
                    try:
                        final_text = (
                            f"🔹 **#{d.get('id')} | KQ: {res} ({sum(d['dices'])})**\n"
                            f"• Trạng thái: ⚠️ **Chưa đặt cược**\n"
                            f"• Số dư: **{st['balance']:,} VNĐ**"
                        )
                        bot.edit_message_text(final_text, cid, st["last_pred_msg_id"], parse_mode="Markdown")
                        delete_message_later(cid, st["last_pred_msg_id"], delay=8)
                    except Exception:
                        pass
                return

            is_win = (pred == res)
            profit = bet_amt if is_win else -bet_amt
            ai_tu_hoc(cid, pred, res)
            
            global_session_logs.append({
                "time": datetime.now(ICT).strftime("%d/%m/%Y %H:%M:%S"),
                "session": d.get("id"),
                "dice": d["dices"],
                "total": sum(d["dices"]),
                "result": res,
                "prediction": pred,
                "status": "THẮNG" if is_win else "THUA",
                "profit": profit,
                "balance": st["balance"]
            })
            
            if st.get("last_pred_msg_id"):
                try:
                    tt_icon = "🟢 THẮNG" if is_win else "🔴 THUA"
                    lai_lo_str = f"+{bet_amt:,}" if is_win else f"-{bet_amt:,}"
                    final_text = (
                        f"🎲 **#{d.get('id')} | KQ: {res} ({sum(d['dices'])})**\n"
                        f"• Đoán: {pred} → **{tt_icon}** ({lai_lo_str})\n"
                        f"• Số dư: **{st['balance']:,} VNĐ**"
                    )
                    bot.edit_message_text(final_text, cid, st["last_pred_msg_id"], parse_mode="Markdown")
                    delete_message_later(cid, st["last_pred_msg_id"], delay=8)
                except Exception:
                    pass

    try:
        sio.connect("https://wtxmd52.tele68.com", socketio_path="txmd5/", namespaces=["/txmd5"],
                    transports=["websocket"], auth={"token": token},
                    headers={"User-Agent": "Mozilla/5.0", "Origin": "https://lc79b.bet"})
        sio.wait()
    except Exception as e:
        pass

# ==========================================
# 🎮 LỆNH ĐIỀU KHIỂN BOT
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    cid = m.chat.id
    all_known_users.add(cid)
    init_user_state(cid)
    
    if cid == ADMIN_ID:
        bot.set_my_commands(ADMIN_COMMANDS, scope=telebot.types.BotCommandScopeChat(cid))
    else:
        bot.set_my_commands(USER_COMMANDS, scope=telebot.types.BotCommandScopeChat(cid))

    if check_auth(cid):
        han = "Vĩnh Viễn" if cid == ADMIN_ID else format_expire_time(authorized_users[cid])
        msg = f"💎 **LC79 VIP AUTO** | Hạn: `{han}`\nNhập `/huongdan` để xem lệnh."
        safe_send_and_clean(cid, msg, delay=10)
    else:
        msg = f"🔒 **Chưa kích hoạt VIP!**\n🔑 Nhập key: `/nhapkey MÃ`\n📩 Mua key liên hệ: {ADMIN_USERNAME}"
        safe_send_and_clean(cid, msg, delay=10)

@bot.message_handler(commands=['huongdan'])
def cmd_huongdan(m):
    all_known_users.add(m.chat.id)
    msg = (
        f"📖 **HƯỚNG DẪN SỬ DỤNG**\n"
        f"🔑 `/nhapkey MÃ` - Nhập key kích hoạt\n"
        f"🔐 `/login TK MK` - Đăng nhập tài khoản game\n"
        f"⚡ `/autobet on 10000` | `/autobet off` - Bật/Tắt Auto\n"
        f"💸 `/x2 on` | `/x2 off` - Quản lý X2 khi thua\n"
        f"💎 `/thongtin` - Xem thông tin số dư & hạn VIP\n"
        f"⏹️ `/stop` - Ngắt kết nối\n"
        f"📩 Hỗ trợ: {ADMIN_USERNAME}"
    )
    safe_send_and_clean(m.chat.id, msg, delay=12)

@bot.message_handler(commands=['lichsucau'])
def admin_view_history(m):
    if m.chat.id != ADMIN_ID:
        return safe_send_and_clean(m.chat.id, "⛔ Lệnh này chỉ dành cho Admin!", delay=4)
    
    st = user_states.get(m.chat.id)
    if not st or not st["history"]:
        return bot.reply_to(m, "📭 Chưa có dữ liệu lịch sử cầu nào được nạp.")
    
    recent_res = st["history"][-30:]
    s = "".join("🔵" if x == "TAI" else "🔴" for x in recent_res)
    tai_count = recent_res.count('TAI')
    xiu_count = recent_res.count('XIU')
    
    msg = (
        f"📊 **[ADMIN] 30 PHIÊN CẦU GẦN NHẤT**\n"
        f"----------------------------------\n"
        f"🔵 Tổng Tài: `{tai_count}` | 🔴 Tổng Xỉu: `{xiu_count}`\n\n"
        f"{s}"
    )
    bot.reply_to(m, msg, parse_mode="Markdown")

@bot.message_handler(commands=['xuatfile'])
def admin_export_txt(m):
    if m.chat.id != ADMIN_ID:
        return safe_send_and_clean(m.chat.id, "⛔ Lệnh này chỉ dành cho Admin!", delay=4)
    
    if not global_session_logs:
        return bot.reply_to(m, "📭 Chưa có dữ liệu phiên giao dịch nào để xuất file.")
    
    filename = f"lich_su_giao_dich_{datetime.now(ICT).strftime('%Y%m%d_%H%M%S')}.txt"
    filepath = f"/tmp/{filename}" if os.path.exists("/tmp") else filename
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("==================================================\n")
            f.write("      BÁO CÁO LỊCH SỬ KẾT QUẢ & GIAO DỊCH BOT LC79    \n")
            f.write("==================================================\n\n")
            for log in global_session_logs:
                f.write(f"Thời gian: {log['time']}\n")
                f.write(f"Phiên: #{log['session']} | Xúc xắc: {log['dice']} (Tổng: {log['total']})\n")
                f.write(f"Kết quả thực tế: {log['result']} | Bot dự đoán: {log['prediction']}\n")
                f.write(f"Trạng thái: {log['status']} | Lãi/Lỗ: {log['profit']:,} VNĐ\n")
                f.write(f"Số dư tài khoản: {log['balance']:,} VNĐ\n")
                f.write("--------------------------------------------------\n")
        
        with open(filepath, "rb") as doc:
            bot.send_document(m.chat.id, doc, caption="📁 **File báo cáo lịch sử giao dịch chi tiết hệ thống**", parse_mode="Markdown")
        
        if os.path.exists("/tmp") and os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        bot.reply_to(m, f"❌ Lỗi khi xuất file: {e}")

@bot.message_handler(commands=['taokey'])
def gk(m):
    if m.chat.id != ADMIN_ID:
        return
    try:
        p = m.text.split()
        hours = int(p[1]) if len(p) > 1 else 720
        k = "ongchusunwin-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        valid_keys[k] = hours * 3600
        
        exp_dt = datetime.now(ICT) + timedelta(hours=hours)
        ht = exp_dt.strftime("%d/%m/%Y %H:%M")
        bot.reply_to(m, f"👑 Key mới ({hours} giờ):\n`<code>{k}</code>`\n📅 Hết hạn: `{ht} (ICT)`", parse_mode="HTML")
    except:
        bot.reply_to(m, "Cú pháp: `/taokey 24` (tạo key 24 giờ)", parse_mode="Markdown")

@bot.message_handler(commands=['danhsachkey'])
def lk(m):
    if m.chat.id != ADMIN_ID:
        return
    if not valid_keys:
        return bot.reply_to(m, "📭 Danh sách key trống.")
    ds = "\n".join([f"🔑 `<code>{k}</code>`: {v//3600} giờ" for k, v in valid_keys.items()])
    bot.reply_to(m, f"📋 **DS KEY CÒN LẠI** ({len(valid_keys)}):\n{ds}", parse_mode="HTML")

@bot.message_handler(commands=['thongbao'])
def broadcast_msg(m):
    if m.chat.id != ADMIN_ID:
        return
    content = m.text.replace("/thongbao", "").strip()
    if not content:
        return bot.reply_to(m, "⚠️ Cú pháp: `/thongbao [Nội dung thông báo]`", parse_mode="Markdown")
    
    success = 0
    fail = 0
    for uid in all_known_users:
        try:
            bot.send_message(uid, f"📢 **THÔNG BÁO TỪ ADMIN**\n\n{content}", parse_mode="Markdown")
            success += 1
            time.sleep(0.1)
        except:
            fail += 1
    bot.reply_to(m, f"✅ Đã gửi thông báo thành công tới `{success}` user (Lỗi: `{fail}`)", parse_mode="Markdown")

@bot.message_handler(commands=['lichsulogin'])
def view_login_history(m):
    if m.chat.id != ADMIN_ID:
        return
    if not login_history:
        return bot.reply_to(m, "📭 Chưa có lượt đăng nhập nào.")
    txt = "\n".join([f"🕒 `{i['time']}` | ID:`{i['chat_id']}`\n👤 `{i['username']}` | `{i['nickname']}`" for i in login_history[-15:]])
    bot.reply_to(m, f"📋 **LỊCH SỬ LOGIN**:\n{txt}", parse_mode="Markdown")

@bot.message_handler(commands=['nhapkey'])
def ak(m):
    all_known_users.add(m.chat.id)
    p = m.text.split()
    if len(p) < 2:
        return safe_send_and_clean(m.chat.id, f"⚠️ Cú pháp: `/nhapkey MÃ_KEY`\n📩 Mua key: {ADMIN_USERNAME}", delay=5)
    k = p[1].strip()
    if k in valid_keys:
        duration_seconds = valid_keys[k]
        authorized_users[m.chat.id] = time.time() + duration_seconds
        del valid_keys[k]
        
        exp_dt = datetime.now(ICT) + timedelta(seconds=duration_seconds)
        ht = exp_dt.strftime("%d/%m/%Y lúc %H:%M")
        safe_send_and_clean(m.chat.id, f"✅ **Kích hoạt VIP thành công!**\n📅 Hạn dùng đến: `{ht} (ICT)`", delay=8)
    else:
        safe_send_and_clean(m.chat.id, f"❌ Key không chính xác hoặc đã được dùng!\n📩 Mua key: {ADMIN_USERNAME}", delay=5)

@bot.message_handler(commands=['thongtin'])
@require_auth
def tt(m):
    cid = m.chat.id
    all_known_users.add(cid)
    init_user_state(cid)
    st = user_states[cid]
    
    if cid == ADMIN_ID:
        han = "Vĩnh Viễn"
    else:
        exp_ts = authorized_users[cid]
        exp_dt = datetime.fromtimestamp(exp_ts, ICT)
        han = exp_dt.strftime("%d/%m/%Y %H:%M") + " (ICT)"
        
    x2 = f"Cấp {st['martingale_level']}" if st["martingale_enabled"] else "Tắt"
    
    msg = (
        f"💎 **THÔNG TIN TÀI KHOẢN**\n"
        f"• Hạn VIP: `{han}`\n"
        f"• Auto Bet: `{'Bật' if st['auto_bet_enabled'] else 'Tắt'}`\n"
        f"• X2: `{x2}` | Gốc: `{st['base_bet']:,}`\n"
        f"• Số dư: `{st['balance']:,} VNĐ`\n"
        f"• Thắng/Thua: `{st['total_win']}` / `{st['total_lose']}`"
    )
    safe_send_and_clean(cid, msg, delay=10)

@bot.message_handler(commands=['login'])
@require_auth
def lg(m):
    cid = m.chat.id
    all_known_users.add(cid)
    p = m.text.split()
    if len(p) != 3:
        return safe_send_and_clean(cid, "⚠️ Cú pháp: `/login TAIKHOAN MATKHAU`", delay=5)
    
    mm = bot.send_message(cid, "🔄 Đang kết nối server game...")
    res = login_and_get_token(p[1], p[2])
    if "_error" in res:
        try: bot.delete_message(cid, mm.message_id)
        except: pass
        return safe_send_and_clean(cid, f"❌ Lỗi: {res['_error']}", delay=5)
    
    login_history.append({
        "time": datetime.now(ICT).strftime("%d/%m %H:%M"),
        "chat_id": cid,
        "username": p[1],
        "nickname": res['nickname']
    })

    init_user_state(cid)
    st = user_states[cid]
    st["balance"] = res["money"]
    st["base_bet"] = st["bet_amount"]
    
    try: bot.delete_message(cid, mm.message_id)
    except: pass

    msg = f"✅ **Đăng nhập OK!**\n📛 `{res['nickname']}` | Dư: `{res['money']:,} VNĐ`"
    safe_send_and_clean(cid, msg, delay=8)
    threading.Thread(target=start_websocket, args=(cid, res["token"], p[1]), daemon=True).start()

@bot.message_handler(commands=['autobet'])
@require_auth
def ab(m):
    cid = m.chat.id
    if cid not in active_sockets:
        return safe_send_and_clean(cid, "⚠️ Hãy thực hiện `/login` trước!", delay=4)
    p = m.text.split()
    if len(p) < 2:
        return safe_send_and_clean(cid, "⚠️ Cú pháp: `/autobet on 10000` hoặc `/autobet off`", delay=4)
    st = user_states[cid]
    if p[1].lower() == "on":
        amt = int(p[2]) if len(p) > 2 else 10000
        st["auto_bet_enabled"] = True
        st["bet_amount"] = amt
        st["base_bet"] = amt
        st["martingale_level"] = 0
        safe_send_and_clean(cid, f"🟢 **Auto Bật** | Mức: `{amt:,} VNĐ`", delay=6)
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
        return safe_send_and_clean(cid, f"💸 **X2**: {tt} | Dùng `/x2 on` hoặc `/x2 off`", delay=5)
    if p[1].lower() == "on":
        st["martingale_enabled"] = True
        st["martingale_level"] = 0
        safe_send_and_clean(cid, "💸 **Đã Bật X2 Khi Thua** (Max 6 cấp)", delay=6)
    else:
        st["martingale_enabled"] = False
        st["martingale_level"] = 0
        safe_send_and_clean(cid, "🔴 **Đã Tắt X2**", delay=5)

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
    print("👑 LC79 ELITE PRO MAX - CHUA DAT CUOC UPDATE READY")
    bot.infinity_polling()
