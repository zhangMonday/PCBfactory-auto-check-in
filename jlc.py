import os
import sys
import time
import json
import random
import requests
from datetime import datetime, timedelta
from serverchan_sdk import sc_send

# 全局变量用于收集总结日志
in_summary = False
summary_logs = []

# ======== 基础工具函数 (保留原风格) ========

def log(msg):
    """日志打印，同时收集到总结中"""
    full_msg = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(full_msg, flush=True)
    if in_summary:
        summary_logs.append(msg)

def format_nickname(nickname):
    """格式化昵称，只显示第一个字和最后一个字，中间用星号代替"""
    if not nickname or len(nickname.strip()) == 0:
        return "未知用户"
    
    nickname = nickname.strip()
    if len(nickname) == 1:
        return f"{nickname}*"
    elif len(nickname) == 2:
        return f"{nickname[0]}*"
    else:
        return f"{nickname[0]}{'*' * (len(nickname)-2)}{nickname[-1]}"

def is_sunday():
    """检查今天是否是周日"""
    return datetime.now().weekday() == 6

def is_last_day_of_month():
    """检查今天是否是当月最后一天"""
    today = datetime.now()
    next_month = today.replace(day=28) + timedelta(days=4)
    last_day = next_month - timedelta(days=next_month.day)
    return today.day == last_day.day

# ======== 接口交互逻辑 ========

class JLC_API:
    """嘉立创金豆相关接口逻辑"""
    def __init__(self, token, account_index):
        self.token = token
        self.account_index = account_index
        self.headers = {
            'X-JLC-AccessToken': token,
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Html5Plus/1.0 (Immersed/20) JlcMobileApp',
        }
        self.base_url = "https://m.jlc.com"

    def get_bean_count(self):
        """获取金豆数量 (兼做Token有效性检查)"""
        url = f"{self.base_url}/api/appPlatform/center/assets/selectPersonalAssetsInfo"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    return data.get('data', {}).get('integralVoucher', 0)
            log(f"账号 {self.account_index} - ❌ 获取金豆信息失败: {resp.text[:50]}")
            return None
        except Exception as e:
            log(f"账号 {self.account_index} - ❌ 获取金豆请求异常: {e}")
            return None

    def sign_in(self):
        """执行签到，返回 (bool是否成功, msg状态描述, gain_num获得数量)"""
        url = f"{self.base_url}/api/activity/sign/signIn?source=3"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code != 200:
                return False, f"请求失败HTTP {resp.status_code}", 0
            
            res = resp.json()
            if not res.get('success'):
                msg = res.get('message', '未知错误')
                if '已经签到' in msg:
                    return True, "已签到过", 0
                return False, msg, 0

            data = res.get('data', {})
            gain_num = data.get('gainNum', 0)
            status = data.get('status', 0)

            if status > 0:
                if gain_num and gain_num > 0:
                    return True, "签到成功", gain_num
                else:
                    # 尝试领取连签奖励
                    return self.receive_voucher()
            
            return False, "签到状态异常", 0
        except Exception as e:
            return False, f"签到异常 {e}", 0

    def receive_voucher(self):
        """领取七日连签奖励"""
        url = f"{self.base_url}/api/activity/sign/receiveVoucher"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            res = resp.json()
            if res.get('success'):
                # 假设连签奖励固定为8或者其他，接口未返回具体数值时默认处理
                log(f"账号 {self.account_index} - ✅ 成功领取连签奖励")
                return True, "领取奖励成功", 0 # 金豆数会在总数差值中体现
            else:
                return False, f"领取奖励失败: {res.get('message')}", 0
        except Exception as e:
            return False, f"领奖异常 {e}", 0

class OSHWHUB_API:
    """开源平台相关接口逻辑"""
    def __init__(self, cookie, account_index):
        self.cookie = cookie
        self.account_index = account_index
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Cookie': cookie,
            'Referer': 'https://oshwhub.com/sign_in'
        }
        self.base_url = "https://oshwhub.com"

    def get_user_info(self):
        """获取用户信息（昵称和积分）"""
        url = f"{self.base_url}/api/users"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    result = data.get('result', {})
                    return {
                        'nickname': result.get('nickname', '未知'),
                        'points': result.get('points', 0),
                        'uuid': result.get('uuid')
                    }
            if resp.status_code == 401:
                log(f"账号 {self.account_index} - ❌ 开源平台Cookie已失效")
            return None
        except Exception as e:
            log(f"账号 {self.account_index} - ❌ 获取开源平台信息异常: {e}")
            return None

    def sign_in(self):
        """开源平台签到"""
        url = f"{self.base_url}/api/users/signIn"
        try:
            # Body 需要 _t 时间戳
            payload = {"_t": int(time.time() * 1000)}
            resp = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    return True, "签到成功"
                msg = data.get('message', '') if data else '未知'
                if "已签到" in str(data): # 有些接口返回错误但包含已签到信息
                    return True, "已签到过"
                return False, msg
            return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, f"异常 {e}"

    def check_and_claim_gifts(self):
        """检查并领取7天/月度好礼"""
        reward_logs = []
        if not is_sunday() and not is_last_day_of_month():
            return reward_logs

        # 获取礼包状态
        try:
            config_url = f"{self.base_url}/api/gift/goodGift"
            resp = requests.get(config_url, headers=self.headers, timeout=10)
            if resp.status_code != 200:
                return reward_logs
            
            data = resp.json()
            if not data.get('success'):
                return reward_logs
            
            result = data.get('result', {})
            seven_days = result.get('sevenDays', {})
            month_end = result.get('monthEnd', {})

            # 领取逻辑
            # 7天好礼
            if is_sunday() and seven_days:
                # 检查是否满足条件 (前端逻辑通常会检查 week_signIn_days，这里直接尝试调用领取接口)
                # 只有当 status 不为已领取时才领取，但简单起见直接调接口，接口会校验
                uuid = seven_days.get('uuid')
                if uuid:
                    res_msg = self._claim_good_gift(uuid, "7天好礼")
                    if res_msg: reward_logs.append(res_msg)

            # 月度好礼
            if is_last_day_of_month() and month_end:
                uuid = month_end.get('uuid')
                if uuid:
                    res_msg = self._claim_good_gift(uuid, "月度好礼")
                    if res_msg: reward_logs.append(res_msg)

        except Exception as e:
            log(f"账号 {self.account_index} - 检查礼包异常: {e}")

        return reward_logs

    def _claim_good_gift(self, uuid, gift_name):
        """内部函数：领取具体礼包"""
        url = f"{self.base_url}/api/gift/goodGift/{uuid}"
        try:
            # 尝试领取，根据接口定义这里可能是POST或GET，原JS脚本中是POST
            # 参考信息指出是 POST
            resp = requests.post(url, headers=self.headers, timeout=10)
            data = resp.json()
            
            if data.get('success'):
                # code 1: 优惠券, code 2: 积分
                res_code = data.get('result')
                msg = "优惠券" if res_code == 1 else "积分"
                log(f"账号 {self.account_index} - ✅ 成功领取{gift_name} ({msg})")
                return f"开源平台{gift_name}领取结果: 成功获取{msg}"
            else:
                msg = data.get('message', '未知原因')
                # 过滤掉常见的"不满足条件"的报错，避免日志太乱，或者作为Info输出
                if "未满足" in msg or "已领取" in msg:
                    log(f"账号 {self.account_index} - {gift_name}: {msg}")
                else:
                    log(f"账号 {self.account_index} - ❌ 领取{gift_name}失败: {msg}")
                return None
        except Exception as e:
            return None

# ======== 核心处理逻辑 ========

def process_single_account(jlc_token, oshwhub_cookie, index):
    """处理单个账号的所有逻辑"""
    
    result = {
        'account_index': index,
        'nickname': '未知',
        # 开源平台结果
        'oshwhub_status': '未启用',
        'oshwhub_success': False,
        'initial_points': 0,
        'final_points': 0,
        'points_reward': 0,
        'reward_results': [],
        # 金豆结果
        'jindou_status': '未启用',
        'jindou_success': False,
        'initial_jindou': 0,
        'final_jindou': 0,
        'jindou_reward': 0,
        'has_jindou_reward': False,
        'error_msg': ''
    }

    # 1. 开源平台流程
    if oshwhub_cookie:
        api_osh = OSHWHUB_API(oshwhub_cookie, index)
        
        # 获取初始信息
        user_info = api_osh.get_user_info()
        if user_info:
            result['nickname'] = format_nickname(user_info['nickname'])
            result['initial_points'] = user_info['points']
            log(f"账号 {index} - 👤 昵称: {result['nickname']}")
            log(f"账号 {index} - 签到前积分💰: {result['initial_points']}")

            # 执行签到
            time.sleep(random.randint(1, 3))
            success, msg = api_osh.sign_in()
            if success:
                result['oshwhub_status'] = msg
                result['oshwhub_success'] = True
                log(f"账号 {index} - ✅ 开源平台{msg}！")
                
                # 领取礼包
                time.sleep(1)
                result['reward_results'] = api_osh.check_and_claim_gifts()
            else:
                result['oshwhub_status'] = f"失败({msg})"
                log(f"账号 {index} - ❌ 开源平台签到失败: {msg}")

            # 获取最终积分
            time.sleep(1)
            final_info = api_osh.get_user_info()
            if final_info:
                result['final_points'] = final_info['points']
                result['points_reward'] = result['final_points'] - result['initial_points']
                log(f"账号 {index} - 签到后积分💰: {result['final_points']}")
                
                if result['points_reward'] > 0:
                    log(f"账号 {index} - 🎉 总积分增加: {result['initial_points']} → {result['final_points']} (+{result['points_reward']})")
                elif result['points_reward'] == 0:
                    log(f"账号 {index} - ⚠ 总积分无变化，可能今天已签到过: {result['initial_points']} → {result['final_points']} (0)")
        else:
            result['oshwhub_status'] = "Cookie失效或网络错误"
    else:
        log(f"账号 {index} - ⚠️ 未提供开源平台Cookie，跳过")
        result['oshwhub_status'] = "无Cookie跳过"
        result['oshwhub_success'] = True # 跳过不算失败

    log("-" * 30)

    # 2. 金豆签到流程
    if jlc_token:
        api_jlc = JLC_API(jlc_token, index)
        
        # 获取初始金豆
        initial_beans = api_jlc.get_bean_count()
        if initial_beans is not None:
            result['initial_jindou'] = initial_beans
            log(f"账号 {index} - 签到前金豆💰: {result['initial_jindou']}")
            
            # 执行签到
            time.sleep(random.randint(1, 3))
            success, msg, gain = api_jlc.sign_in()
            result['jindou_status'] = msg
            
            if success:
                result['jindou_success'] = True
                if "已签到" in msg:
                    log(f"账号 {index} - 今日已签到，跳过签到操作")
                else:
                    log(f"账号 {index} - ✅ 签到成功")
                    if "领取奖励成功" in msg:
                        result['has_jindou_reward'] = True

                # 获取最终金豆
                time.sleep(1)
                final_beans = api_jlc.get_bean_count()
                if final_beans is not None:
                    result['final_jindou'] = final_beans
                    result['jindou_reward'] = final_beans - initial_beans
                    
                    log(f"账号 {index} - 签到后金豆💰: {result['final_jindou']}")
                    
                    # 计算显示
                    reward_text = f" (+{result['jindou_reward']})"
                    if result['has_jindou_reward']:
                        reward_text += "（有奖励）"
                    
                    if result['jindou_reward'] > 0:
                        log(f"账号 {index} - 🎉 总金豆增加: {result['initial_jindou']} → {result['final_jindou']}{reward_text}")
                    else:
                        log(f"账号 {index} - ⚠ 总金豆无变化: {result['initial_jindou']} → {result['final_jindou']} (0)")
            else:
                log(f"账号 {index} - ❌ 金豆签到失败: {msg}")
        else:
            result['jindou_status'] = "Token失效"
            result['error_msg'] = "无法获取金豆信息"
    else:
        log(f"账号 {index} - ⚠️ 未提供JLC Token，跳过金豆签到")
        result['jindou_status'] = "无Token跳过"
        result['jindou_success'] = True # 跳过不算失败

    return result

# ======== 推送逻辑 (保留原程序) ========

def push_summary():
    if not summary_logs:
        return
    
    title = "嘉立创签到总结"
    text = "\n".join(summary_logs)
    full_text = f"{title}\n{text}"
    
    # Telegram
    telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if telegram_bot_token and telegram_chat_id:
        try:
            url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
            params = {'chat_id': telegram_chat_id, 'text': full_text}
            requests.get(url, params=params, timeout=10)
            log("Telegram-日志已推送")
        except: pass

    # 企业微信
    wechat_webhook_key = os.getenv('WECHAT_WEBHOOK_KEY')
    if wechat_webhook_key:
        try:
            url = wechat_webhook_key if wechat_webhook_key.startswith('https://') else f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={wechat_webhook_key}"
            requests.post(url, json={"msgtype": "text", "text": {"content": full_text}}, timeout=10)
            log("企业微信-日志已推送")
        except: pass

    # 钉钉
    dingtalk_webhook = os.getenv('DINGTALK_WEBHOOK')
    if dingtalk_webhook:
        try:
            url = dingtalk_webhook if dingtalk_webhook.startswith('https://') else f"https://oapi.dingtalk.com/robot/send?access_token={dingtalk_webhook}"
            requests.post(url, json={"msgtype": "text", "text": {"content": full_text}}, timeout=10)
            log("钉钉-日志已推送")
        except: pass

    # PushPlus
    pushplus_token = os.getenv('PUSHPLUS_TOKEN')
    if pushplus_token:
        try:
            requests.post("http://www.pushplus.plus/send", json={"token": pushplus_token, "title": title, "content": text}, timeout=10)
            log("PushPlus-日志已推送")
        except: pass

    # Server酱
    serverchan_sckey = os.getenv('SERVERCHAN_SCKEY')
    if serverchan_sckey:
        try:
            requests.post(f"https://sctapi.ftqq.com/{serverchan_sckey}.send", data={"title": title, "desp": text}, timeout=10)
            log("Server酱-日志已推送")
        except: pass
    
    # Server酱3
    serverchan3_sckey = os.getenv('SERVERCHAN3_SCKEY') 
    if serverchan3_sckey:
        try:
            response = sc_send(serverchan3_sckey, title, text, {"tags": "嘉立创|签到"})            
            if response.get("code") == 0:
                log("Server酱3-日志已推送")
        except: pass

    # 酷推
    coolpush_skey = os.getenv('COOLPUSH_SKEY')
    if coolpush_skey:
        try:
            requests.get(f"https://push.xuthus.cc/send/{coolpush_skey}?c={full_text}", timeout=10)
            log("酷推-日志已推送")
        except: pass
        
    # 自定义WebHook
    custom_webhook = os.getenv('CUSTOM_WEBHOOK')
    if custom_webhook:
        try:
            requests.post(custom_webhook, json={"title": title, "content": text}, timeout=10)
            log("自定义API-日志已推送")
        except: pass

# ======== 主程序入口 ========

def main():
    global in_summary
    
    if len(sys.argv) < 3:
        print("用法: python jlc.py \"Token1,Token2...\" \"Cookie1,Cookie2...\" \"true/false\"")
        print("说明: Token对应X-JLC-AccessToken, Cookie对应开源平台Cookie")
        sys.exit(1)
    
    tokens_str = sys.argv[1]
    cookies_str = sys.argv[2]
    
    # 解析失败退出标志
    enable_failure_exit = False
    if len(sys.argv) >= 4:
        enable_failure_exit = (sys.argv[3].lower() == 'true')
    
    tokens = [t.strip() for t in tokens_str.split(',')]
    cookies = [c.strip() for c in cookies_str.split(',')]
    
    # 允许列表末尾有空项（如 "a,b," split后会有空字串），去除它们
    if tokens and not tokens[-1]: tokens.pop()
    if cookies and not cookies[-1]: cookies.pop()

    if len(tokens) != len(cookies):
        log(f"❌ 错误: JLC Token数量({len(tokens)}) 与 开源平台Cookie数量({len(cookies)}) 不一致!")
        log("请确保两者一一对应，如果某账号不需要某项功能，请在对应位置留空(例如 'token1,,token3')")
        sys.exit(1)
    
    total_accounts = len(tokens)
    log(f"失败退出功能: {'开启' if enable_failure_exit else '关闭'}")
    log(f"开始处理 {total_accounts} 个账号的签到任务")
    
    all_results = []
    
    for i, (token, cookie) in enumerate(zip(tokens, cookies), 1):
        log(f"开始处理第 {i} 个账号")
        result = process_single_account(token, cookie, i)
        all_results.append(result)
        
        if i < total_accounts:
            wait_time = random.randint(3, 5)
            log(f"等待 {wait_time} 秒后处理下一个账号...")
            time.sleep(wait_time)
            
    # ======== 总结输出 (逻辑复刻) ========
    log("=" * 70)
    in_summary = True
    log("📊 详细签到任务完成总结")
    log("=" * 70)
    
    oshwhub_success_count = 0
    jindou_success_count = 0
    total_points_reward = 0
    total_jindou_reward = 0
    failed_accounts = []
    
    for result in all_results:
        idx = result['account_index']
        # 统计失败 (跳过的不算失败)
        is_osh_fail = (not result['oshwhub_success']) and (result['oshwhub_status'] != "无Cookie跳过")
        is_jlc_fail = (not result['jindou_success']) and (result['jindou_status'] != "无Token跳过")
        
        if is_osh_fail or is_jlc_fail:
            failed_accounts.append(idx)
            
        log(f"账号 {idx} ({result.get('nickname', '未知')}) 详细结果:")
        log(f"  ├── 开源平台: {result['oshwhub_status']}")
        
        if result['initial_points'] > 0 or result['final_points'] > 0:
            change = f"(+{result['points_reward']})" if result['points_reward'] > 0 else f"({result['points_reward']})"
            log(f"  ├── 积分变化: {result['initial_points']} → {result['final_points']} {change}")
        else:
            log(f"  ├── 积分状态: 未获取")
            
        log(f"  ├── 金豆签到: {result['jindou_status']}")
        
        if result['initial_jindou'] > 0 or result['final_jindou'] > 0:
            change = f"(+{result['jindou_reward']})" if result['jindou_reward'] > 0 else f"({result['jindou_reward']})"
            if result['has_jindou_reward']: change += "（有奖励）"
            log(f"  ├── 金豆变化: {result['initial_jindou']} → {result['final_jindou']} {change}")
        else:
            log(f"  ├── 金豆状态: 未获取")
            
        for rr in result['reward_results']:
            log(f"  ├── {rr}")
            
        if result['oshwhub_success']: oshwhub_success_count += 1
        if result['jindou_success']: jindou_success_count += 1
        
        total_points_reward += result['points_reward']
        total_jindou_reward += result['jindou_reward']
        log("  " + "-" * 50)

    log("📈 总体统计:")
    log(f"  ├── 总账号数: {total_accounts}")
    log(f"  ├── 开源平台签到成功: {oshwhub_success_count}/{total_accounts}")
    log(f"  ├── 金豆签到成功: {jindou_success_count}/{total_accounts}")
    if total_points_reward > 0: log(f"  ├── 总计获得积分: +{total_points_reward}")
    if total_jindou_reward > 0: log(f"  ├── 总计获得金豆: +{total_jindou_reward}")
    
    if failed_accounts:
        log(f"  ⚠ 存在异常的账号: {', '.join(map(str, failed_accounts))}")
    else:
        log("  🎉 所有账号处理完毕")
        
    log("=" * 70)
    
    push_summary()
    
    if enable_failure_exit and failed_accounts:
        log("❌ 由于存在失败账号且开启了失败退出，程序将返回错误码")
        sys.exit(1)
    else:
        log("✅ 程序正常退出")
        sys.exit(0)

if __name__ == "__main__":
    main()
