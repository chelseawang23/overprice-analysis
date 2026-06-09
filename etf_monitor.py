#!/usr/bin/env python3
"""
亚太精选ETF (159687) 溢价监控 + Seatalk 提醒 + 交易成本
=====================================================
用法:
  python3 etf_monitor.py               # 运行一次分析并发送提醒
  python3 etf_monitor.py --intraday    # 盘中模式（14:30 cron 调用）
  python3 etf_monitor.py --daily       # 盘后模式（22:00 cron 调用）
  python3 etf_monitor.py --test        # 测试模式

环境变量（必填）:
  SEATALK_APP_ID       - Seatalk App ID
  SEATALK_APP_SECRET   - Seatalk App Secret

可选:
  SEATALK_USER_EMAIL   - 接收消息的用户邮箱（默认 huixia.huang@shopee.com）
  TRADE_CAPITAL        - 每笔交易资金量（默认 20000）
  COST_MODEL           - 成本模型: ideal/low/realistic/conservative

Token 管理:
  自动用 APP_ID + APP_SECRET 获取 access_token
  7200 秒过期，自动缓存到 /tmp/etf_seatalk_token.json
  过期前自动刷新

成本模型:
  ideal        - 免五+万一+无滑点 = 0.02%/笔
  low          - 免五+万1.5+0.05%滑点 = 0.08%/笔
  realistic    - 免五+万1.5+0.1%滑点 = 0.13%/笔 ★默认
  conservative - 万3+0.15%滑点+不免五 = 0.36%/笔
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta

# ====== 配置 ======
ETF_CODE = "159687"
TRADE_CAPITAL = float(os.environ.get("TRADE_CAPITAL", "20000"))
COST_MODEL = os.environ.get("COST_MODEL", "realistic")
SEATALK_APP_ID = os.environ.get("SEATALK_APP_ID", "")
SEATALK_APP_SECRET = os.environ.get("SEATALK_APP_SECRET", "")
SEATALK_USERS = os.environ.get("SEATALK_USER_EMAILS", "huixia.huang@shopee.com,jiayu.lin@shopee.com").split(",")
SEATALK_USERS = [u.strip() for u in SEATALK_USERS if u.strip()]
SEATALK_TOKEN_FILE = "/tmp/etf_seatalk_token.json"
SEATALK_EMP_CACHE = "/tmp/etf_seatalk_emp_codes.json"

# Seatalk API endpoints
SEATALK_AUTH_API = "https://openapi.seatalk.io/auth/app_access_token"
SEATALK_EMP_API = "https://openapi.seatalk.io/contacts/v2/get_employee_code_with_email"
SEATALK_SEND_API = "https://openapi.seatalk.io/messaging/v2/single_chat"

COST_MODELS = {
    "ideal":        {"name": "理想（免五+万一+无滑点）", "commission": 0.010*2, "min_fee": 0, "slippage": 0.00},
    "low":          {"name": "低佣金（免五+万1.5+0.05%滑点）", "commission": 0.015*2, "min_fee": 0, "slippage": 0.05},
    "realistic":    {"name": "实际预估（免五+万1.5+0.1%滑点）", "commission": 0.015*2, "min_fee": 0, "slippage": 0.10},
    "conservative": {"name": "保守（万3+0.15%滑点）", "commission": 0.030*2, "min_fee": 10, "slippage": 0.15},
}
# ==================


def get_access_token():
    """获取或刷新 Seatalk access token（自动缓存）"""
    # 1. 检查缓存文件
    try:
        with open(SEATALK_TOKEN_FILE) as f:
            cached = json.load(f)
            # 提前 5 分钟刷新
            if cached.get("expire_at", 0) > time.time() + 300:
                return cached["token"]
    except:
        pass

    # 2. 用 App ID + Secret 获取新 token
    if not SEATALK_APP_ID or not SEATALK_APP_SECRET:
        return None

    print(f"[Token] 获取新 access_token...")
    try:
        resp = requests.post(SEATALK_AUTH_API, json={
            "app_id": SEATALK_APP_ID,
            "app_secret": SEATALK_APP_SECRET,
        }, headers={"Content-Type": "application/json"}, timeout=15)

        data = resp.json()
        if data.get("code") == 0:
            token = data["app_access_token"]
            expire_in = data.get("expire", 7200)  # 默认 2 小时
            expire_at = time.time() + expire_in

            # 缓存
            with open(SEATALK_TOKEN_FILE, "w") as f:
                json.dump({"token": token, "expire_at": expire_at}, f)

            print(f"[Token] ✅ 获取成功，有效期到 {datetime.fromtimestamp(expire_at).strftime('%H:%M:%S')}")
            return token
        else:
            print(f"[Token] ❌ 获取失败: code={data.get('code')}, msg={data.get('message', data)}")
    except Exception as e:
        print(f"[Token] ❌ 异常: {e}")

    # 3. 如果有过期缓存也返回试试
    try:
        with open(SEATALK_TOKEN_FILE) as f:
            cached = json.load(f)
            print(f"[Token] ⚠️ 使用过期缓存")
            return cached["token"]
    except:
        pass
    return None


def calc_cost():
    """计算每笔交易成本"""
    m = COST_MODELS.get(COST_MODEL, COST_MODELS["realistic"])
    pct = m["commission"]
    if m["min_fee"] > 0 and TRADE_CAPITAL > 0:
        pct = max(pct, m["min_fee"] / TRADE_CAPITAL * 100)
    total = round(pct + m["slippage"], 3)
    return {
        "name": m["name"], "commission_pct": round(pct, 3),
        "slippage": m["slippage"], "total_pct": total,
        "capital": TRADE_CAPITAL,
        "total_yuan": round(TRADE_CAPITAL * total / 100, 2),
    }


def fetch_realtime():
    """获取实时行情"""
    url = "https://api-ddc-wscn.awtmt.com/market/real"
    params = {"fields": "prod_name,last_px,px_change,px_change_rate,high_px,low_px,open_px,preclose_px,iopv",
              "prod_code": f"{ETF_CODE}.SZ"}
    try:
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        d = r.json()
        if d.get("code") == 20000:
            s = d["data"]["snapshot"].get(f"{ETF_CODE}.SZ", [])
            if len(s) >= 9:
                return {"name": s[0], "price": s[1], "change": s[2], "change_pct": s[3],
                        "high": s[4], "low": s[5], "open": s[6], "preclose": s[7], "iopv": s[8]}
    except Exception as e:
        print(f"[ERROR] fetch_realtime: {e}")
    return None


def fetch_nav():
    """获取最新净值"""
    import akshare as ak
    try:
        today = datetime.now()
        start = (today - timedelta(days=30)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        df = ak.fund_etf_fund_info_em(fund=ETF_CODE, start_date=start, end_date=end)
        if len(df) >= 2:
            L, P = df.iloc[-1], df.iloc[-2]
            return {
                "date": str(L["净值日期"]), "nav": float(L["单位净值"]),
                "chg": float(L["日增长率"]) if L["日增长率"] else 0,
                "prev_date": str(P["净值日期"]), "prev_nav": float(P["单位净值"]),
            }
        elif len(df) == 1:
            L = df.iloc[-1]
            return {"date": str(L["净值日期"]), "nav": float(L["单位净值"]),
                    "chg": float(L["日增长率"]) if L["日增长率"] else 0,
                    "prev_date": None, "prev_nav": None}
    except Exception as e:
        print(f"[ERROR] fetch_nav: {e}")
    return None


def analyze():
    """完整分析"""
    data = fetch_realtime()
    if not data:
        return {"error": "无法获取实时行情"}

    nav = fetch_nav()
    cost = calc_cost()
    price = data["price"]
    iopv = data.get("iopv")
    preclose = data.get("preclose", price)

    r = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "price": price, "change_pct": data.get("change_pct", 0),
        "high": data["high"], "low": data["low"],
        "open": data["open"], "preclose": preclose, "iopv": iopv,
    }

    # IOPV 溢价
    if iopv and iopv > 0:
        r["iopv_premium"] = round((price - iopv) / iopv * 100, 2)

    # NAV 溢价 + Δ
    if nav and nav["nav"]:
        r["nav"] = nav["nav"]
        r["nav_date"] = nav["date"]
        r["nav_premium"] = round((price - nav["nav"]) / nav["nav"] * 100, 2)

        if nav.get("prev_nav") and preclose:
            prev_prem = (preclose - nav["prev_nav"]) / nav["prev_nav"] * 100
            cur_prem = r.get("iopv_premium") or r["nav_premium"]
            r["prev_premium"] = round(prev_prem, 2)
            r["delta"] = round(cur_prem - prev_prem, 2)

    # 信号判断
    delta = r.get("delta", 0)
    prem = r.get("iopv_premium") or r.get("nav_premium") or 0

    signal_map = [
        (lambda d, p: d > 2.0, "strong_buy", "🟢 强烈买入！", 1.40, "92.0%（25次）"),
        (lambda d, p: d > 1.0, "buy", "🟢 买入信号", 0.93, "82.5%（57次）"),
        (lambda d, p: d > 0.5, "weak_buy", "🟡 弱买入信号", 0.46, "66.9%（124次）"),
        (lambda d, p: p > 5 and d < 0, "danger", "🔴 高溢价见顶风险", 0, "不追"),
    ]
    for cond, sig, text, est_gross, conf in signal_map:
        if cond(delta, prem):
            r["signal"] = sig
            r["signal_text"] = f"{text} Δ溢价 {delta:+.2f}%"
            r["signal_conf"] = f"历史胜率 {conf}"
            r["est_gross"] = est_gross
            r["est_net"] = round(est_gross - cost["total_pct"], 2)
            r["cost"] = cost
            return r

    r["signal"] = "neutral"
    r["signal_text"] = "⚪ 无明确信号"
    r["signal_conf"] = "建议观望"
    r["est_gross"] = 0
    r["est_net"] = round(0 - cost["total_pct"], 2)
    r["cost"] = cost
    return r


def format_message(a):
    """格式化 Seatalk 消息（简洁版，兼容 Seatalk markdown）"""
    if "error" in a:
        return f"⚠️ ETF监控异常：{a['error']}"

    E = {"strong_buy": "🚨", "buy": "📈", "weak_buy": "📊", "danger": "⚠️", "neutral": "ℹ️"}
    emoji = E.get(a.get("signal", "neutral"), "ℹ️")
    cost = a.get("cost", {})

    m = f"""{emoji} **亚太精选ETF 溢价监控**
{a['time']}

📊 **实时行情**
• 现价: **{a['price']:.4f}** ({a.get('change_pct', 0):+.2f}%)
• IOPV: {a.get('iopv', 'N/A')}
• IOPV溢价: **{a.get('iopv_premium', 'N/A')}%**
"""

    if "nav" in a:
        m += f"• 最新NAV: {a['nav']:.4f}（{a.get('nav_date', '')}）  \n"
    if "prev_premium" in a:
        m += f"• 昨日收盘溢价: {a['prev_premium']:.2f}%  \n"
    if "delta" in a:
        m += f"• **Δ溢价变动: {a['delta']:+.2f}%**  \n"

    m += f"""
🎯 **信号: {a.get('signal_text', 'N/A')}**
{a.get('signal_conf', '')}

💰 **交易成本**（{cost.get('name', 'N/A')}）
• 资金: ¥{cost.get('capital', 0):,.0f}/笔
• 佣金+滑点: **{cost.get('total_pct', 0):.3f}%**（约¥{cost.get('total_yuan', 0):.2f}）
"""

    if a.get("signal") in ("strong_buy", "buy", "weak_buy"):
        net_yuan = a['est_net'] * cost.get('capital', 20000) / 100
        m += f"""
📈 **预估收益**
• 历史毛收益: +{a['est_gross']:.2f}%/笔
• 扣除成本净收益: **+{a['est_net']:.2f}%/笔** ≈ **¥{net_yuan:.2f}**

> 🟢 14:55 尾盘买入 → 次日 9:25 开盘卖出
"""

    m += """
---
📌 历史回测仅供参考，不构成投资建议
"""
    return m


def get_employee_codes():
    """获取所有收件人的 employee_code（批量查询，自动缓存）"""
    # 1. 检查缓存
    try:
        with open(SEATALK_EMP_CACHE) as f:
            cached = json.load(f)
            # 检查是否覆盖所有用户
            if all(u in cached for u in SEATALK_USERS):
                return [cached[u] for u in SEATALK_USERS]
    except:
        pass

    # 2. 批量查询
    token = get_access_token()
    if not token:
        return SEATALK_USERS  # fallback

    try:
        resp = requests.post(SEATALK_EMP_API,
            json={"emails": SEATALK_USERS},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            cache = {}
            codes = []
            for emp in data.get("employees", []):
                email = emp.get("email", "")
                code = emp.get("employee_code", "")
                if emp.get("code") == 0 and code:
                    cache[email] = code
                    codes.append(code)
                    print(f"[Emp] {email} → employee_code: {code}")
                else:
                    print(f"[Emp] {email} → 未找到, code={emp.get('code')}")
            # 保存缓存
            with open(SEATALK_EMP_CACHE, "w") as f:
                json.dump(cache, f)
            return codes
    except Exception as e:
        print(f"[Emp] 查询失败: {e}")

    return SEATALK_USERS  # fallback


def send_seatalk(message):
    """通过 Seatalk Open API 发送消息给所有收件人"""
    if not SEATALK_APP_ID or not SEATALK_APP_SECRET:
        print("\n⚠️  未配置 SEATALK_APP_ID / SEATALK_APP_SECRET")
        print("=" * 50)
        print(message)
        print("=" * 50)
        return False

    token = get_access_token()
    emp_codes = get_employee_codes()
    if not token:
        print("\n⚠️  无法获取 access token")
        print("=" * 50)
        print(message)
        print("=" * 50)
        return False

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    def send_one(emp_code):
        body = {
            "employee_code": emp_code,
            "message": {
                "tag": "markdown",
                "markdown": {"content": message},
            }
        }
        resp = requests.post(SEATALK_SEND_API, json=body, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("code") == 0, data
        return False, {"code": -1, "message": f"HTTP {resp.status_code}"}

    success_count = 0
    for emp_code in emp_codes:
        ok, data = send_one(emp_code)
        if ok:
            print(f"[Seatalk] ✅ 已发送到 {emp_code}")
            success_count += 1
        elif data.get("code") in (100, 3001):
            # Token 过期，清除缓存重试
            print(f"[Seatalk] 清除缓存重试...")
            try:
                os.remove(SEATALK_TOKEN_FILE)
            except:
                pass
            try:
                os.remove(SEATALK_EMP_CACHE)
            except:
                pass
            token = get_access_token()
            emp_codes = get_employee_codes()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                ok2, _ = send_one(emp_code)
                if ok2:
                    print(f"[Seatalk] ✅ 重试成功 {emp_code}")
                    success_count += 1
                    continue
            print(f"[Seatalk] ❌ 重试失败 {emp_code}")
        else:
            print(f"[Seatalk] ❌ 发送失败 {emp_code}: {data.get('message', '')}")

    if success_count > 0:
        print(f"[Seatalk] 发送完成: {success_count}/{len(emp_codes)} 成功")
        return True
    else:
        print("\n⚠️  全部发送失败，消息内容:")
        print("=" * 50)
        print(message)
        print("=" * 50)
        return False


def main():
    now = datetime.now()

    if now.weekday() >= 5 and "--test" not in sys.argv:
        print("Weekend - skipping")
        return

    mode = "daily"
    if "--intraday" in sys.argv:
        mode = "intraday"
    elif "--test" in sys.argv:
        mode = "test"
    elif "--daily" in sys.argv:
        mode = "daily"

    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] ETF Monitor | mode={mode} | cost={COST_MODEL}")

    analysis = analyze()
    message = format_message(analysis)

    if mode == "intraday" and analysis.get("signal") not in ("strong_buy", "buy", "weak_buy"):
        print(f"  信号: {analysis.get('signal_text')} - 不够强，跳过发送")
        return

    if mode == "test":
        print("\n" + "=" * 50)
        print("📡 数据源检查")
        print(f"  行情: {'✅' if 'price' in analysis else '❌'} price={analysis.get('price', 'N/A')}")
        print(f"  IOPV: {analysis.get('iopv', 'N/A')}")
        print(f"  NAV: {'✅' if 'nav' in analysis else '❌'} {analysis.get('nav', 'N/A')}")
        print(f"  溢价: {analysis.get('iopv_premium', 'N/A')}%")
        print(f"  Δ溢价: {analysis.get('delta', 'N/A')}%")
        cost = analysis.get("cost", {})
        print(f"  成本: {cost.get('total_pct', 'N/A')}%/笔 ≈ ¥{cost.get('total_yuan', 'N/A')}")
        print(f"  信号: {analysis.get('signal_text', 'N/A')}")
        has_id = bool(SEATALK_APP_ID)
        has_secret = bool(SEATALK_APP_SECRET)
        print(f"  Seatalk 收件人: {', '.join(SEATALK_USERS)}")
        print(f"  App ID: {'✅' if has_id else '⚠️ 未设置'}")
        print(f"  App Secret: {'✅' if has_secret else '⚠️ 未设置'}")
        if has_id and has_secret:
            token = get_access_token()
            print(f"  Token: {'✅' if token else '❌ 获取失败'}")
        if analysis.get("est_net"):
            net_yuan = analysis['est_net'] * cost.get('capital', 20000) / 100
            print(f"  预估净收益: +{analysis['est_net']:.2f}%/笔 ≈ ¥{net_yuan:.2f}")

    send_seatalk(message)
    print("Done.")


if __name__ == "__main__":
    main()
