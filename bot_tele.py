
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
# FLASK KEEP ALIVE
# =========================
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

SYSTEM_ACTIVE = True

# Danh sách lệnh CHỈ dành cho User thường (Hoàn toàn không có lệnh Admin)
USER_COMMANDS = [
    telebot.types.BotCommand("/start", "🏠 Mở menu LCVIP"),
    telebot.types.BotCommand("/huongdan", "📖 Hướng dẫn"),
    telebot.types.BotCommand("/nhapkey", "🔑 Nhập key VIP"),
    telebot.types.BotCommand("/thongtin", "💎 Thông tin tài khoản"),
    telebot.types.BotCommand("/login", "🔐 Đăng nhập game"),
    telebot.types.BotCommand("/autobet", "⚡ Bật/Tắt Auto"),
    telebot.types.BotCommand("/x2", "💸 Quản lý X2"),
    telebot.types.BotCommand("/stop", "⏹️ Ngắt kết nối"),
]

# Danh sách lệnh đầy đủ dành RIÊNG cho Admin
ADMIN_COMMANDS = USER_COMMANDS + [
    telebot.types.BotCommand("/dsuser", "👥 [ADMIN] Thống kê User SD"),
    telebot.types.BotCommand("/tatbot", "🔴 [ADMIN] Tắt toàn bộ Bot"),
    telebot.types.BotCommand("/mobot", "🟢 [ADMIN] Mở lại Bot"),
    telebot.types.BotCommand("/lichsucau", "📊 [ADMIN] Xem lịch sử 30 phiên"),
    telebot.types.BotCommand("/xuatfile", "📁 [ADMIN] Xuất file TXT lịch sử"),
    telebot.types.BotCommand("/taokey", "👑 [ADMIN] Tạo key theo giờ"),
    telebot.types.BotCommand("/danhsachkey", "📋 [ADMIN] DS Key"),
    telebot.types.BotCommand("/thongbao", "📢 [ADMIN] Gửi thông báo All"),
    telebot.types.BotCommand("/lichsulogin", "📋 [ADMIN] DS Login"),
]

# Đặt mặc định Telegram chỉ thấy lệnh User thường
bot.set_my_commands(USER_COMMANDS, scope=telebot.types.BotCommandScopeDefault())

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
all_known_users = {}
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
            "last_pred_msg_id": None, "last_bet_amount": 10000, "current_conf": 50, "current_reason": ""
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
            try:
                bot.send_message(chat_id, "⚠️ **KEY CỦA MÀY HẾT HẠN RỒI NHÓC MUA MỚI ĐÊ!!!**", parse_mode="Markdown")
            except:
                pass
            if chat_id in active_sockets:
                try:
                    active_sockets[chat_id].disconnect()
                except:
                    pass
                del active_sockets[chat_id]
            if chat_id in user_states:
                user_states[chat_id]["auto_bet_enabled"] = False
    return False

def require_auth(fn):
    def wr(m, *a, **kw):
        if not SYSTEM_ACTIVE and m.chat.id != ADMIN_ID:
            safe_send_and_clean(m.chat.id, "🔴 **Hệ thống LCVIP đang tạm tắt bởi Admin!**", delay=5)
            return
        if not check_auth(m.chat.id):
            safe_send_and_clean(m.chat.id, f"🔒 **Chưa kích hoạt LCVIP!**\n🔑 Nhập key: `/nhapkey MÃ`\n📩 Liên hệ mua key: {ADMIN_USERNAME}", delay=6)
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
            safe_send_and_clean(cid, f"🟢 **Kết nối LCVIP OK** ({len(arr)} phiên)", delay=4)

    @sio.on('new-session', namespace='/txmd5')
    def new_sess(d):
        if not check_auth(cid):
            try:
                sio.disconnect()
            except:
                pass
            return

        st = user_states[cid]
        st["session_id"] = d.get("id")
        st["has_bet_this_session"] = False
        result = pro_predict(st["raw_hist"]) if st["raw_hist"] else None
        if result and result[0]:
            st["current_prediction"] = result[0]
            st["current_conf"] = int(result[1] * 100)
            st["current_reason"] = result[2] if len(result) > 2 else ""
            tien = tinh_tien_cuoc(cid)
            x2_st = f"Cấp {st['martingale_level']}" if st["martingale_enabled"] else "Tắt"
            auto_st = "🟢 BẬT" if st["auto_bet_enabled"] else "🔴 TẮT"
            
            msg = (
                f"👑 *LCVIP BY ONGCHUSUNWIN* 👑\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎲 *PHIÊN*  `#{st['session_id']}`\n"
                f"🎯 *DỰ ĐOÁN*  {'🟢' if result[0] == 'TAI' else '🔴'} *{result[0]}*\n"
                f"📈 *Tín hiệu thuật toán:* `{st['current_conf']}%`\n"
                f"🧠 *Phân tích:* _{st['current_reason']}_\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💵 *Cược dự kiến:* `{tien:,}đ`\n"
                f"⚡ *Auto:* {auto_st}   |   🔁 *X2:* `{x2_st}`\n"
                f"📡 *Trạng thái:* ⏳ Chờ xác nhận cược\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            sent_msg = safe_send_and_clean(cid, msg, delay=0)
            if sent_msg:
                st["last_pred_msg_id"] = sent_msg.message_id

    @sio.on('tick-update', namespace='/txmd5')
    def tk(d):
        if not check_auth(cid):
            return
        st = user_states[cid]
        if d.get("state") == "BETTING" and st["auto_bet_enabled"] and st["current_prediction"] and AUTO_BET_RUN_UNTIL_STOP:
            if not st["has_bet_this_session"]:
                tien = tinh_tien_cuoc(cid)
                st["last_bet_amount"] = tien
                sio.emit("bet", {"type": st["current_prediction"], "amount": tien}, namespace="/txmd5")
                st["has_bet_this_session"] = True
                x2_st = f"Cấp {st['martingale_level']}" if st["martingale_enabled"] else "Tắt"
                
                if st.get("last_pred_msg_id"):
                    try:
                        edited_text = (
                            f"👑 *LCVIP BY ONGCHUSUNWIN* 👑\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"🎲 *PHIÊN*  `#{st['session_id']}`\n"
                            f"🎯 *DỰ ĐOÁN*  {'🟢' if st['current_prediction'] == 'TAI' else '🔴'} *{st['current_prediction']}*\n"
                            f"📈 *Tín hiệu thuật toán:* `{st['current_conf']}%`\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"💵 *Tiền cược yêu cầu:* `{tien:,}đ`\n"
                            f"🔁 *X2:* `{x2_st}`\n"
                            f"📡 *Trạng thái:* 🟡 Đã gửi lệnh cược, chờ xác nhận\n"
                            f"━━━━━━━━━━━━━━━━━━━━"
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
        sess_id = d.get("id") or (st.get("session_id") if st.get("session_id") else "LCVIP")
        
        if res in ("TAI", "XIU"):
            dices = d.get("dices", [0, 0, 0])
            total_pts = sum(dices) if dices else 0
            dice_str = f"{dices[0]}-{dices[1]}-{dices[2]}" if len(dices) == 3 else "N/A"
            
            rec = {"session": sess_id, "dice": dices, "total": total_pts, "result": res}
            st["raw_hist"].append(rec)
            st["history"].append(res)
            st["points_history"].append(total_pts)
            if len(st["raw_hist"]) > MAX_HISTORY_STORE:
                st["raw_hist"].pop(0)
                st["history"].pop(0)
                st["points_history"].pop(0)
            feed_history([rec])
            
            pred = st["current_prediction"]
            has_bet = st.get("has_bet_this_session", False)
            bet_amt = st.get("last_bet_amount", 10000)
            
            if not has_bet:
                if st.get("last_pred_msg_id"):
                    try:
                        final_text = (
                            f"👑 *LCVIP BY ONGCHUSUNWIN* 👑\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"🎲 *PHIÊN*  `#{sess_id}`\n"
                            f"🎯 *DỰ ĐOÁN*  *{pred or 'KHÔNG CÓ'}*\n"
                            f"🎲 *KẾT QUẢ*  *{res}* • `{dice_str}` = `{total_pts}`\n"
                            f"⚪ *CHƯA CƯỢC* • Không tính lãi/lỗ\n"
                            f"💰 *Số dư:* `{st['balance']:,}đ`\n"
                            f"━━━━━━━━━━━━━━━━━━━━"
                        )
                        bot.edit_message_text(final_text, cid, st["last_pred_msg_id"], parse_mode="Markdown")
                    except Exception:
                        pass
                return

            is_win = (pred == res)
            profit = bet_amt if is_win else -bet_amt
            ai_tu_hoc(cid, pred, res)
            
            global_session_logs.append({
                "time": datetime.now(ICT).strftime("%d/%m/%Y %H:%M:%S"),
                "session": sess_id,
                "dice": dices,
                "total": total_pts,
                "result": res,
                "prediction": pred,
                "status": "THẮNG" if is_win else "THUA",
                "profit": profit,
                "balance": st["balance"]
            })
            
            if st.get("last_pred_msg_id"):
                try:
                    tt_icon = "🟢 THẮNG KHỦNG" if is_win else "🔴 THUA CƯỢC"
                    lai_lo_str = f"+{bet_amt:,}" if is_win else f"-{bet_amt:,}"
                    final_text = (
                        f"👑 *LCVIP BY ONGCHUSUNWIN* 👑\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🎲 *PHIÊN*  `#{sess_id}`\n"
                        f"🎯 *DỰ ĐOÁN*  *{pred}*  ➜  *{res}*\n"
                        f"🎲 *Xúc xắc:* `{dice_str}` = `{total_pts}` điểm\n"
                        f"{'✅ *HÚP*' if is_win else '❌ *GÃY*'}\n"
                        f"💵 *Cược yêu cầu:* `{bet_amt:,}đ`\n"
                        f"💰 *Lãi/lỗ ước tính:* `{lai_lo_str}đ`\n"
                        f"🏦 *Số dư:* `{st['balance']:,}đ`\n"
                        f"━━━━━━━━━━━━━━━━━━━━"
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
def main_menu(cid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        telebot.types.InlineKeyboardButton("🔐 Đăng nhập", callback_data="menu_login"),
        telebot.types.InlineKeyboardButton("🔑 Nhập key", callback_data="menu_key"),
        telebot.types.InlineKeyboardButton("💎 Tài khoản", callback_data="menu_info"),
        telebot.types.InlineKeyboardButton("⚡ Auto cược", callback_data="menu_auto"),
        telebot.types.InlineKeyboardButton("💸 Chế độ X2", callback_data="menu_x2"),
        telebot.types.InlineKeyboardButton("📖 Hướng dẫn", callback_data="menu_help"),
        telebot.types.InlineKeyboardButton("⏹ Ngắt kết nối", callback_data="menu_stop"),
        telebot.types.InlineKeyboardButton("🔄 Làm mới", callback_data="menu_home"),
    ]
    for i in range(0, len(buttons), 2):
        kb.row(*buttons[i:i+2])
    if cid == ADMIN_ID:
        kb.row(telebot.types.InlineKeyboardButton("👑 Lệnh quản trị", callback_data="menu_admin"))
    return kb


def menu_text(cid):
    active = check_auth(cid)
    expiry = ("Vĩnh viễn" if cid == ADMIN_ID else format_expire_time(authorized_users[cid])) if active else "Chưa kích hoạt"
    lines = [
        "👑 LCVIP BY ONGCHUSUNWIN",
        "━━━━━━━━━━━━━━━━━━",
        f"🔐 Trạng thái: {'VIP đang hoạt động' if active else 'Chưa kích hoạt VIP'}",
        f"⏳ Hạn dùng: {expiry}",
        "", "📋 DANH SÁCH LỆNH", "",
        "/start - Xem danh sách lệnh",
        "/huongdan - Hướng dẫn sử dụng",
        "/nhapkey - Nhập key VIP",
        "/thongtin - Thông tin tài khoản",
        "/login - Đăng nhập game",
        "/autobet - Bật/tắt auto cược",
        "/x2 - Quản lý chế độ X2",
        "/stop - Ngắt kết nối",
    ]
    if cid == ADMIN_ID:
        lines.extend(["", "👑 LỆNH QUẢN TRỊ", "",
            "/dsuser - Thống kê người dùng",
            "/tatbot - Tắt bot", "/mobot - Mở bot",
            "/lichsucau - Lịch sử 30 phiên",
            "/xuatfile - Xuất lịch sử TXT",
            "/taokey - Tạo key", "/danhsachkey - Danh sách key",
            "/thongbao - Thông báo toàn bộ",
            "/lichsulogin - Danh sách đăng nhập"])
    lines.extend(["", "━━━━━━━━━━━━━━━━━━", f"📩 Hỗ trợ: {ADMIN_USERNAME}"])
    return "\n".join(lines)


@bot.message_handler(commands=['start', 'menu'])
def cmd_start(m):
    cid = m.chat.id
    uname = m.from_user.username or m.from_user.first_name or "Unknown"
    all_known_users[cid] = f"@{uname}" if m.from_user.username else uname
    init_user_state(cid)
    if not SYSTEM_ACTIVE and cid != ADMIN_ID:
        return bot.send_message(cid, "🔴 Hệ thống đang tạm dừng!")
    scope = telebot.types.BotCommandScopeChat(cid)
    try:
        bot.set_my_commands(ADMIN_COMMANDS if cid == ADMIN_ID else USER_COMMANDS, scope=scope)
    except Exception as exc:
        logger.warning("Không cập nhật được danh sách lệnh Telegram: %s", exc)
    bot.send_message(cid, menu_text(cid))


@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_'))
def menu_callback(call):
    cid = call.message.chat.id
    action = call.data[5:]
    bot.answer_callback_query(call.id)
    if not SYSTEM_ACTIVE and cid != ADMIN_ID:
        return bot.send_message(cid, "🔴 Hệ thống đang tạm dừng!")
    if action == 'home':
        try:
            bot.edit_message_text(menu_text(cid), cid, call.message.message_id, reply_markup=main_menu(cid))
        except Exception:
            bot.send_message(cid, menu_text(cid), reply_markup=main_menu(cid))
        return
    prompts = {
        'login': "🔐 Đăng nhập bằng lệnh:\n/login TAIKHOAN MATKHAU\n⚠️ Không chia sẻ mật khẩu trong nhóm.",
        'key': "🔑 Kích hoạt VIP:\n/nhapkey MA_KEY",
        'auto': "⚡ Điều khiển tự động cược:\n/autobet on 10000\n/autobet off\n⚠️ Cần đăng nhập game trước.",
        'x2': "💸 Chế độ X2:\n/x2 on\n/x2 off\n⚠️ Tăng cược khi thua có rủi ro mất tiền nhanh.",
        'admin': "👑 Quản trị:\n/taokey /danhsachkey /dsuser\n/tatbot /mobot /thongbao\n/lichsucau /xuatfile /lichsulogin",
    }
    if action == 'admin' and cid != ADMIN_ID:
        return bot.send_message(cid, "⛔ Chỉ dành cho admin.")
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
    
    if not SYSTEM_ACTIVE and cid != ADMIN_ID:
        return safe_send_and_clean(cid, "🔴 **Hệ thống LCVIP đang tạm tắt bởi Admin!**", delay=5)

    msg = (
        f"📖 **HƯỚNG DẪN LCVIP BY ONGCHUSUNWIN**\n"
        f"----------------------------------\n"
        f"🔑 `/nhapkey MÃ` - Nhập key kích hoạt\n"
        f"🔐 `/login TK MK` - Đăng nhập tài khoản game\n"
        f"⚡ `/autobet on 10000` | `/autobet off` - Bật/Tắt Auto\n"
        f"💸 `/x2 on` | `/x2 off` - Quản lý X2 khi thua\n"
        f"💎 `/thongtin` - Xem thông tin số dư & hạn VIP\n"
        f"⏹️ `/stop` - Ngắt kết nối\n"
        f"📩 Hỗ trợ: {ADMIN_USERNAME}"
    )
    safe_send_and_clean(cid, msg, delay=12)

@bot.message_handler(commands=['dsuser'])
def admin_list_users(m):
    if m.chat.id != ADMIN_ID:
        return safe_send_and_clean(m.chat.id, "⛔ Lệnh này chỉ dành cho Admin!", delay=4)
    
    if not all_known_users:
        return bot.reply_to(m, "📭 Chưa có user nào tương tác với bot.")
    
    user_list_str = "\n".join([f"• UID: `{uid}` | Tên: `{uname}`" for uid, uname in all_known_users.items()])
    bot.reply_to(m, f"👥 **DANH SÁCH USER ĐÃ SỬ DỤNG BOT** ({len(all_known_users)}):\n----------------------------------\n{user_list_str}", parse_mode="Markdown")

@bot.message_handler(commands=['tatbot'])
def admin_turn_off_bot(m):
    global SYSTEM_ACTIVE
    if m.chat.id != ADMIN_ID:
        return
    SYSTEM_ACTIVE = False
    bot.reply_to(m, "🔴 **Đã tắt toàn bộ hệ thống Bot thành công!**", parse_mode="Markdown")
    
    for uid in all_known_users.keys():
        try:
            bot.send_message(uid, "📢 **BỐ ĐÃ TẮT BOT NÀO MỞ TUỲ DUYÊN OK**", parse_mode="Markdown")
            time.sleep(0.05)
        except:
            pass

@bot.message_handler(commands=['mobot'])
def admin_turn_on_bot(m):
    global SYSTEM_ACTIVE
    if m.chat.id != ADMIN_ID:
        return
    SYSTEM_ACTIVE = True
    bot.reply_to(m, "🟢 **Đã mở lại hệ thống Bot hoạt động bình thường!**", parse_mode="Markdown")

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
            f.write("    BÁO CÁO LỊCH SỬ GIAO DỊCH LCVIP BY ONGCHUSUNWIN\n")
            f.write("==================================================\n\n")
            for log in global_session_logs:
                f.write(f"Thời gian: {log['time']}\n")
                f.write(f"Phiên: #{log['session']} | Xúc xắc: {log['dice']} (Tổng: {log['total']})\n")
                f.write(f"Kết quả thực tế: {log['result']} | Bot dự đoán: {log['prediction']}\n")
                f.write(f"Trạng thái: {log['status']} | Lãi/Lỗ: {log['profit']:,} VNĐ\n")
                f.write(f"Số dư tài khoản: {log['balance']:,} VNĐ\n")
                f.write("--------------------------------------------------\n")
        
        with open(filepath, "rb") as doc:
            bot.send_document(m.chat.id, doc, caption="📁 **File báo cáo lịch sử giao dịch LCVIP**", parse_mode="Markdown")
        
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
    for uid in all_known_users.keys():
        try:
            bot.send_message(uid, f"📢 **THÔNG BÁO TỪ ADMIN (LCVIP)**\n\n{content}", parse_mode="Markdown")
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
    cid = m.chat.id
    uname = m.from_user.username or m.from_user.first_name or "Unknown"
    all_known_users[cid] = f"@{uname}" if m.from_user.username else uname
    
    if not SYSTEM_ACTIVE and cid != ADMIN_ID:
        return safe_send_and_clean(cid, "🔴 **Hệ thống LCVIP đang tạm tắt bởi Admin!**", delay=5)

    p = m.text.split()
    if len(p) < 2:
        return safe_send_and_clean(cid, f"⚠️ Cú pháp: `/nhapkey MÃ_KEY`\n📩 Mua key: {ADMIN_USERNAME}", delay=5)
    k = p[1].strip()
    if k in valid_keys:
        duration_seconds = valid_keys[k]
        authorized_users[cid] = time.time() + duration_seconds
        del valid_keys[k]
        
        exp_dt = datetime.now(ICT) + timedelta(seconds=duration_seconds)
        ht = exp_dt.strftime("%d/%m/%Y lúc %H:%M")
        safe_send_and_clean(cid, f"✅ **Kích hoạt LCVIP thành công!**\n📅 Hạn dùng đến: `{ht} (ICT)`", delay=8)
    else:
        safe_send_and_clean(cid, f"❌ Key không chính xác hoặc đã được dùng!\n📩 Mua key: {ADMIN_USERNAME}", delay=5)

@bot.message_handler(commands=['thongtin'])
@require_auth
def tt(m):
    cid = m.chat.id
    uname = m.from_user.username or m.from_user.first_name or "Unknown"
    all_known_users[cid] = f"@{uname}" if m.from_user.username else uname
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
        f"👑 **LCVIP BY ONGCHUSUNWIN** 👑\n"
        f"----------------------------------\n"
        f"• Hạn VIP: `{han}`\n"
        f"• Auto Bet: `{'Bật' if st['auto_bet_enabled'] else 'Tắt'}`\n"
        f"• Chế độ X2: `{x2}` | Cược gốc: `{st['base_bet']:,}`\n"
        f"• Số dư: `{st['balance']:,} VNĐ`\n"
        f"• Thắng/Thua: `{st['total_win']}` / `{st['total_lose']}`"
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

    msg = f"✅ **Đăng nhập LCVIP OK!**\n📛 `{res['nickname']}` | Dư: `{res['money']:,} VNĐ`"
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
    print("👑 LCVIP BY ONGCHUSUNWIN - ADMIN COMMANDS HIDDEN SECURELY")
    bot.infinity_polling()

