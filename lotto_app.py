import streamlit as st
import requests
import random
import os
import json
import time
from collections import Counter
import streamlit.components.v1 as components
import base64

import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# [0] 설치형 앱 강제 적용 (PWA)
# ==========================================
앱_설정_정보 = """
{
  "name": "인공지능 로또",
  "short_name": "AI로또",
  "theme_color": "#2980B9",
  "background_color": "#ffffff",
  "display": "standalone",
  "start_url": "/",
  "icons": [
    {
      "src": "https://cdn-icons-png.flaticon.com/512/3063/3063822.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
"""
암호화된_정보 = base64.b64encode(앱_설정_정보.encode()).decode()

components.html(f"""
<script>
    if (!window.parent.document.getElementById('pwa-manifest')) {{
        const manifest = window.parent.document.createElement('link');
        manifest.id = 'pwa-manifest';
        manifest.rel = 'manifest';
        manifest.href = 'data:application/manifest+json;base64,{암호화된_정보}';
        window.parent.document.head.appendChild(manifest);
    }}
</script>
""", width=0, height=0)

# ==========================================
# [1] 구글 스프레드시트 데이터베이스 함수
# ==========================================
def get_gsheet_client():
    if "gcp_service_account" not in st.secrets or "sheet" not in st.secrets:
        return None
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    return gspread.authorize(creds)

def load_history():
    records = []
    try:
        gc = get_gsheet_client()
        if gc:
            sheet_url = st.secrets["sheet"]["url"]
            doc = gc.open_by_url(sheet_url)
            worksheet = doc.sheet1
            data = worksheet.get_all_values()
            
            for row in data:
                if len(row) >= 2:
                    try:
                        epsd = int(row[0])
                        games = json.loads(row[1])
                        records.append({"epsd": epsd, "games": games})
                    except: pass
            return records
    except: pass
        
    if os.path.exists("lotto_history.jsonl"):
        with open("lotto_history.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except: pass
    return records

def save_history(epsd, games):
    try:
        gc = get_gsheet_client()
        if gc:
            sheet_url = st.secrets["sheet"]["url"]
            doc = gc.open_by_url(sheet_url)
            worksheet = doc.sheet1
            worksheet.append_row([epsd, json.dumps(games)])
            return True
    except Exception as e:
        pass
    
    log_data = {"epsd": epsd, "games": games}
    with open("lotto_history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(log_data) + "\n")
    return False

# ==========================================
# [2] 계산 규칙
# ==========================================
class LotoAI:
    def __init__(self):
        self.raw_data = []

    def analyze_recent_trend(self, data, scope=7):
        if not data: return {}
        recent_data = data[:scope*6] 
        counts = Counter(recent_data)
        weights = {i: 1.0 for i in range(1, 46)}
        for num, freq in counts.items():
            weights[num] += (freq * 0.5)
        return weights

    def check_end_digit_sync(self, numbers):
        end_digits = [n % 10 for n in numbers]
        counts = Counter(end_digits)
        return any(c >= 2 for c in counts.values())

    def check_dead_zone(self, numbers):
        zones = [0] * 9
        for n in numbers:
            idx = (n - 1) // 5
            zones[idx] = 1
        return zones.count(0) >= 2

    def check_statistics(self, numbers):
        total_sum = sum(numbers)
        if not (100 <= total_sum <= 175): return False
        odd_count = sum(1 for n in numbers if n % 2 != 0)
        if odd_count == 0 or odd_count == 6: return False
        low_count = sum(1 for n in numbers if n <= 22)
        if low_count == 0 or low_count == 6: return False
        return True

    def apply_consecutive_rule(self, numbers):
        sorted_nums = sorted(numbers)
        for i in range(len(sorted_nums) - 1):
            if sorted_nums[i+1] == sorted_nums[i] + 1:
                return True
        return False

# ==========================================
# [3] 정보 가져오기 (매시간 갱신 적용)
# ==========================================
@st.cache_data(ttl=3600)  
def fetch_lotto_api(count):
    url = "https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do?srchLtEpsd=all"
    try:
        response = requests.get(url, timeout=3)
        data = response.json()
        all_list = data.get("data", {}).get("list", [])
        
        full_data_flat = []
        for item in all_list:
             nums = [int(item.get(f"tm{i}WnNo")) for i in range(1, 7)]
             full_data_flat.extend(nums)
             
        display_list = all_list[::-1][:count] 
        history_info = []
        for item in display_list:
            epsd = item.get("ltEpsd")
            nums = [int(item.get(f"tm{i}WnNo")) for i in range(1, 7)]
            bonus = int(item.get("bnusNo", 0))
            history_info.append((epsd, nums, bonus))
        return full_data_flat, history_info
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=3600)  
def fetch_prize_info(epsd):
    prizes = {1: 2000000000, 2: 50000000, 3: 1500000, 4: 50000, 5: 5000}
    try:
        url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={epsd}"
        res = requests.get(url, timeout=3).json()
        if res.get("returnValue") == "success":
            prizes[1] = res.get("firstWinamnt", 2000000000)
    except: pass
    return prizes

def generate_ai_games(full_data, weight_percent, options):
    ai = LotoAI()
    if options['use_trend']:
        recent_trend_data = full_data[:90] 
        weights_map = ai.analyze_recent_trend(recent_trend_data, scope=15)
        user_weight_factor = weight_percent / 100.0
    else:
        weights_map = {}
        user_weight_factor = 0

    final_weights = []
    for i in range(1, 46):
        w = weights_map.get(i, 1.0)
        if w > 1.0: final_weights.append(w + user_weight_factor)
        else: final_weights.append(1.0)

    final_games = []
    attempts = 0
    while len(final_games) < 5:
        attempts += 1
        if attempts > 5000: 
            game = sorted(random.sample(range(1, 46), 6))
            final_games.append(game)
            continue
        game = set()
        while len(game) < 6:
            pick = random.choices(range(1, 46), weights=final_weights, k=1)[0]
            game.add(pick)
        candidate = sorted(list(game))
        
        if options['use_end_digit'] and not ai.check_end_digit_sync(candidate): continue
        if options['use_dead_zone'] and not ai.check_dead_zone(candidate): continue
        if options['use_stats'] and not ai.check_statistics(candidate): continue
        if options['use_consecutive']:
            if len(final_games) < 3:
                if not ai.apply_consecutive_rule(candidate):
                    if random.random() < 0.7: continue 
        final_games.append(candidate)
    return final_games

# ==========================================
# [4] 화면 구성 및 통계 계산 로직
# ==========================================
st.set_page_config(page_title="인공지능 로또 분석기", page_icon="🎱")

# 👇👇 여기서부터 복사해서 기존 style 부분을 덮어쓰세요 👇👇
st.markdown("""
<style>
html, body, [class*="css"] { font-family: "Malgun Gothic", sans-serif; }
.block-container { padding-top: 1.5rem; padding-bottom: 3rem; }
@media (max-width: 600px) {
    .block-container { padding-left: 0.5rem; padding-right: 0.5rem; }
}
.stat-box {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 10px;
    padding: 15px;
    text-align: center;
    margin-bottom: 10px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}
.stat-number { font-size: 22px; font-weight: bold; }
.stat-title { font-size: 13px; color: #666; margin-top: 5px; }

/* 🚀 우측 상단 툴바(Share, GitHub 등) 강제 삭제 */
[data-testid="stToolbar"] {
    visibility: hidden !important;
    display: none !important;
}
/* 🚀 기본 헤더 여백 숨기기 */
header {
    visibility: hidden !important;
}
/* 🚀 하단 Streamlit 워터마크 숨기기 (보너스) */
footer {
    visibility: hidden !important;
}
</style>
""", unsafe_allow_html=True)
# 👆👆 여기까지 👆👆

# ---------------------------------------------------------
# 세션 상태 초기화 (버튼 연속 클릭 방지 및 화면 유지용)
# ---------------------------------------------------------
if 'is_generating' not in st.session_state:
    st.session_state.is_generating = False
if 'recent_generated_games' not in st.session_state:
    st.session_state.recent_generated_games = []

def start_generation():
    st.session_state.is_generating = True

def get_ball_html(num):
    color = "#27AE60" 
    if num <= 10: color = "#F39C12" 
    elif num <= 20: color = "#3498DB" 
    elif num <= 30: color = "#E74C3C" 
    elif num <= 40: color = "#7F8C8D" 
    
    return f'<div style="display:inline-flex;justify-content:center;align-items:center;width:32px;height:32px;border-radius:50%;background-color:{color};color:white;font-weight:bold;font-size:13px;margin-right:3px;flex-shrink:0;box-shadow:1px 1px 2px rgba(0,0,0,0.3);">{num}</div>'

def draw_row(label_text, balls_list, is_header=False):
    balls_html = "".join([get_ball_html(n) for n in balls_list])
    label_color = "#2980B9" if is_header else "#333"
    label_bg = "transparent" if is_header else "#f1f3f5"
    
    html_code = f"""
<div style="background-color:white;padding:10px;border-radius:8px;margin-bottom:8px;border:1px solid #ddd;display:flex;flex-direction:row;align-items:center;justify-content:flex-start;overflow-x:auto;">
<div style="font-weight:800;color:{label_color};font-size:14px;min-width:60px;margin-right:10px;white-space:nowrap;flex-shrink:0;text-align:left;background-color:{label_bg};padding:5px;border-radius:5px;text-align:center;">{label_text}</div>
<div style="display:flex;flex-direction:row;flex-wrap:nowrap;gap:2px;">{balls_html}</div>
</div>
"""
    st.markdown(html_code, unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 분석 설정")
    count_val = st.number_input("과거 분석 정보(회)", min_value=5, max_value=100, value=10, step=1)
    st.write("흐름 가중치(%) - 높을수록 최근 번호 우선")
    weight_val = st.number_input("가중치 입력", min_value=0, value=100, step=10)
    
    st.markdown("---")
    st.subheader("거르기 조건")
    use_trend = st.checkbox("🔥 흐름 가중치", value=True)
    use_end = st.checkbox("⚡ 끝자리 일치", value=True)
    use_dead = st.checkbox("☠️ 제외 구간", value=True)
    use_stats = st.checkbox("📊 통계 정밀 거르기", value=True)
    use_consec = st.checkbox("🔗 이어지는 번호", value=True)
    
    st.markdown("---")
    st.subheader("🔥 최근 핫넘버 TOP 5")
    st.caption(f"(최근 {count_val}회 기준)")
    top_numbers_placeholder = st.empty()

full_data, history_info = fetch_lotto_api(count_val)

if full_data and history_info:
    recent_nums_only = []
    for epsd, nums, bonus in history_info:
        recent_nums_only.extend(nums)
    top_5 = Counter(recent_nums_only).most_common(5)
    
    top_html = ""
    for num, freq in top_5:
        top_html += f"<div style='margin-bottom:5px;'>{get_ball_html(num)} <span style='font-size:14px; font-weight:bold; color:#555;'>({freq}회 출현)</span></div>"
    top_numbers_placeholder.markdown(top_html, unsafe_allow_html=True)

st.title("인공지능 로또 분석기")

tab_home, tab_stats, tab_help = st.tabs(["🎯 분석기 홈", "📊 이번 주 수익률/통계", "📖 설명서"])

if full_data:
    latest_epsd = history_info[0][0]     
    target_epsd = latest_epsd + 1        
    
    history_records = load_history()

    # ==========================================
    # 탭 1: 분석기 메인 화면
    # ==========================================
    with tab_home:
        generate_btn = st.button(
            f"🚀 {target_epsd}회차 번호 뽑기 시작", 
            type="primary", 
            use_container_width=True,
            disabled=st.session_state.is_generating,
            on_click=start_generation
        )
        st.markdown("---")

        if st.session_state.is_generating:
            options = {
                'use_trend': use_trend, 'use_end_digit': use_end,
                'use_dead_zone': use_dead, 'use_stats': use_stats,
                'use_consecutive': use_consec
            }
            
            with st.spinner("번호 분석 및 구글 시트에 안전하게 저장 중입니다..."):
                games = generate_ai_games(full_data, weight_val, options)
                save_history(target_epsd, games)
                time.sleep(1.5)
                
                st.session_state.recent_generated_games = games
                st.session_state.is_generating = False
                st.rerun()

        if st.session_state.recent_generated_games and not st.session_state.is_generating:
            st.markdown(f"### 🤖 새로 뽑힌 추천 번호 ({target_epsd}회차용)")
            for i, game in enumerate(st.session_state.recent_generated_games):
                draw_row(f"세트 {i+1}", game, is_header=False)
            st.success(f"생성 및 DB 저장 완료! 최신 데이터가 '통계 탭'에 반영되었습니다. 🍀")
            st.markdown("<br>", unsafe_allow_html=True)

        with st.expander(f"📋 최근 {count_val}회 당첨 결과 확인하기", expanded=True):
            for epsd, nums, bonus in reversed(history_info):
                draw_row(f"{epsd}회", nums, is_header=True)

    # ==========================================
    # 탭 2: 수익률 및 당첨 통계 화면
    # ==========================================
    with tab_stats:
        latest_nums = set(history_info[0][1])
        latest_bonus = history_info[0][2]
        
        total_games_last_week = 0 
        this_week_usage_count = 0  
        prize_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, "fail": 0}
        winning_games = [] 
        
        for data in history_records:
            if data.get("epsd") == target_epsd:
                this_week_usage_count += len(data.get("games", []))
            
            if data.get("epsd") == latest_epsd:
                for game in data.get("games", []):
                    total_games_last_week += 1
                    match_count = len(set(game) & latest_nums)
                    has_bonus = latest_bonus in game
                    
                    if match_count == 6: 
                        prize_counts[1] += 1
                        winning_games.append(("🎉 1등 당첨!", game))
                    elif match_count == 5 and has_bonus: 
                        prize_counts[2] += 1
                        winning_games.append(("✨ 2등 당첨!", game))
                    elif match_count == 5: 
                        prize_counts[3] += 1
                        winning_games.append(("👍 3등 당첨", game))
                    elif match_count == 4: prize_counts[4] += 1
                    elif match_count == 3: prize_counts[5] += 1
                    else: prize_counts["fail"] += 1
        
        st.markdown(f"""
            <div style="background: linear-gradient(135deg, #2c3e50 0%, #3498db 100%); padding: 20px; border-radius: 10px; text-align: center; color: white; margin-bottom: 20px;">
                <div style="font-size: 15px; opacity: 0.9; margin-bottom: 5px;">현재 준비 중인 {target_epsd}회차 대비</div>
                <div style="font-size: 24px; font-weight: bold;">이번 주 총 <span style="font-size: 32px; color: #f1c40f;">{this_week_usage_count}</span> 게임의 분석이 진행되었습니다.</div>
            </div>
        """, unsafe_allow_html=True)
        st.markdown("---")

        st.subheader(f"📈 {latest_epsd}회차 투자 대비 수익률 (ROI)")
        
        if total_games_last_week == 0:
            st.info(f"아직 데이터베이스에 {latest_epsd}회차 생성 기록이 없습니다.")
        else:
            prizes = fetch_prize_info(latest_epsd)
            total_spent = total_games_last_week * 1000
            total_won = (
                (prize_counts[1] * prizes[1]) +
                (prize_counts[2] * prizes[2]) +
                (prize_counts[3] * prizes[3]) +
                (prize_counts[4] * prizes[4]) +
                (prize_counts[5] * prizes[5])
            )
            roi = (total_won / total_spent * 100) if total_spent > 0 else 0
            
            st.markdown(f"""
            <div style="display:flex; flex-direction:row; justify-content:space-around; background-color:#f1f3f5; padding:20px; border-radius:10px; margin-bottom:20px;">
                <div style="text-align:center;">
                    <div style="font-size:14px; color:#555;">총 투자 금액 (비용)</div>
                    <div style="font-size:22px; font-weight:bold; color:#333;">{total_spent:,} 원</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:14px; color:#555;">총 당첨 금액 (수익)</div>
                    <div style="font-size:22px; font-weight:bold; color:#E74C3C;">{total_won:,} 원</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:14px; color:#555;">프로그램 수익률 (ROI)</div>
                    <div style="font-size:22px; font-weight:bold; color:#2980B9;">{roi:,.1f} %</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"**총 {total_games_last_week:,}게임 중 당첨 내역**")
            c1, c2, c3 = st.columns(3)
            with c1: st.markdown(f'<div class="stat-box"><div class="stat-number" style="color:#C0392B;">{prize_counts[1]:,} 회</div><div class="stat-title">1등 (약 {prizes[1]//100000000}억)</div></div>', unsafe_allow_html=True)
            with c2: st.markdown(f'<div class="stat-box"><div class="stat-number" style="color:#8E44AD;">{prize_counts[2]:,} 회</div><div class="stat-title">2등 (약 5천만)</div></div>', unsafe_allow_html=True)
            with c3: st.markdown(f'<div class="stat-box"><div class="stat-number" style="color:#2980B9;">{prize_counts[3]:,} 회</div><div class="stat-title">3등 (약 150만)</div></div>', unsafe_allow_html=True)
            
            c4, c5, c6 = st.columns(3)
            with c4: st.markdown(f'<div class="stat-box"><div class="stat-number" style="color:#F39C12;">{prize_counts[4]:,} 회</div><div class="stat-title">4등 (5만 원)</div></div>', unsafe_allow_html=True)
            with c5: st.markdown(f'<div class="stat-box"><div class="stat-number" style="color:#27AE60;">{prize_counts[5]:,} 회</div><div class="stat-title">5등 (5천 원)</div></div>', unsafe_allow_html=True)
            with c6: st.markdown(f'<div class="stat-box"><div class="stat-number" style="color:#7F8C8D;">{prize_counts["fail"]:,} 회</div><div class="stat-title">낙첨</div></div>', unsafe_allow_html=True)

            if winning_games:
                st.markdown("---")
                st.markdown("#### ✨ 축하합니다! 상위권 당첨 번호")
                for label, game in winning_games:
                    draw_row(label, game, is_header=False)

    # ==========================================
    # 탭 3: 설명서 및 주의사항 (원래대로 100% 복구 완료!)
    # ==========================================
    with tab_help:
        st.subheader("💡 인공지능 분석 원리")
        st.write("이 프로그램은 단순한 무작위 픽이 아닙니다. 역대 당첨 번호의 통계적 사실을 바탕으로 당첨 확률이 극히 희박한 조합을 걸러내어, 효율적인 번호를 추천합니다.")
        st.markdown("---")
        
        st.markdown("#### 🔥 흐름 가중치 (Trend Weight)")
        st.info("**왜 필요한가요?**\n로또 기계도 물리적인 장치이므로 미세한 편향이나 흐름이 존재할 수 있습니다. 최근 15주 동안 자주 나온 번호('Hot Number')가 당분간 계속 나오는 경향성을 반영하여, 해당 번호가 뽑힐 확률을 인위적으로 높입니다.")

        st.markdown("#### ⚡ 끝자리 일치 (End Digit Sync)")
        st.success("**통계적 팩트**\n로또 번호 6개가 모두 다른 끝수(예: 1, 12, 23, 34, 45...)를 가질 확률은 매우 낮습니다. 역대 당첨 번호의 약 **85% 이상**은 '12, 42' 처럼 끝자리가 같은 숫자가 최소 1쌍 이상 포함되어 있습니다. 이 옵션은 그 85%의 확률에 베팅하여 번호를 맞춥니다.")

        st.markdown("#### ☠️ 제외 구간 (Dead Zone)")
        st.error("**분산의 법칙**\n번호가 1번대부터 40번대까지 골고루 한 개씩 예쁘게 나오는 경우는 매우 드뭅니다. 보통 특정 번호대(예: 20번대)가 통째로 전멸하여 한 개도 나오지 않는 현상이 자주 발생합니다. 이 조건은 억지로 모든 구간을 채우지 않고, 자연스러운 '전멸 구간'을 인위적으로 만듭니다.")

        st.markdown("#### 📊 통계 정밀 거르기 (Statistical Filter)")
        st.warning("**가장 강력한 수학적 접근**\n6개 번호의 합이 100 미만이거나 175를 초과하는 경우는 전체의 10% 미만입니다. 또한 홀수나 짝수만 6개가 몰려서 나오는 경우도 2% 미만입니다. 이 필터는 나올 확률이 극히 희박한 '불량 조합'을 원천적으로 차단하여 헛돈 쓰는 것을 막아줍니다.")

        st.markdown("#### 🔗 이어지는 번호 (Consecutive Rule)")
        st.info("**심리적 허점 공략**\n사람들은 '14, 15가 같이 나오겠어?'라고 생각해서 마킹을 피하지만, 실제로는 50% 이상의 회차에서 연속 번호가 등장합니다. 남들이 피해서 1등 당첨금이 쏠리는 이 패턴을 일부러 포함시켜 당첨 효율을 극대화합니다.")

        st.markdown("---")
        
        st.error("""
        ### ⚠️ 꼭 읽어주세요 (면책 조항)
        이 프로그램은 불필요한 조합을 제외하고 수학적 확률을 높이기 위해 설계되었지만, **로또 번호 추첨은 독립 시행이며 궁극적으로 '운(Luck)'에 의해 결정됩니다.**
        
        아무리 뛰어난 인공지능이나 통계 기법을 사용하더라도 100% 당첨을 보장하는 방법은 이 세상에 존재하지 않습니다. 본 프로그램을 통해 생성된 번호로 발생한 결과에 대한 책임은 전적으로 사용자 본인에게 있습니다. **로또는 반드시 부담 없는 소액으로, 건전하고 즐거운 마음으로만 즐겨 주시기 바랍니다.**
        """)

else:
    st.error("서버에서 정보를 가져오지 못했습니다.")