import streamlit as st
import requests
import random
from collections import Counter

# ==========================================
# [1] 로직 엔진 (PC 버전과 100% 동일한 핵심 기능)
# ==========================================
class LotoAI:
    def __init__(self):
        self.raw_data = []

    # 트렌드 분석 (가중치 적용 핵심 로직)
    def analyze_recent_trend(self, data, scope=7):
        if not data: return {}
        recent_data = data[:scope*6] 
        counts = Counter(recent_data)
        weights = {i: 1.0 for i in range(1, 46)}
        for num, freq in counts.items():
            weights[num] += (freq * 0.5)
        return weights

    # 필터 1: 끝수 동기화
    def check_end_digit_sync(self, numbers):
        end_digits = [n % 10 for n in numbers]
        counts = Counter(end_digits)
        return any(c >= 2 for c in counts.values())

    # 필터 2: 죽음의 구간 (특정 번호대 전멸)
    def check_dead_zone(self, numbers):
        zones = [0] * 9
        for n in numbers:
            idx = (n - 1) // 5
            zones[idx] = 1
        return zones.count(0) >= 2

    # 필터 3: 통계적 정밀 필터 (합계, 홀짝 비율)
    def check_statistics(self, numbers):
        total_sum = sum(numbers)
        if not (100 <= total_sum <= 175): return False
        odd_count = sum(1 for n in numbers if n % 2 != 0)
        if odd_count == 0 or odd_count == 6: return False
        low_count = sum(1 for n in numbers if n <= 22)
        if low_count == 0 or low_count == 6: return False
        return True

    # 필터 4: 연속 번호 포함
    def apply_consecutive_rule(self, numbers):
        sorted_nums = sorted(numbers)
        for i in range(len(sorted_nums) - 1):
            if sorted_nums[i+1] == sorted_nums[i] + 1:
                return True
        return False

# ==========================================
# [2] 데이터 통신
# ==========================================
@st.cache_data
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
            history_info.append((epsd, nums))
        return full_data_flat, history_info
    except Exception as e:
        return None, str(e)

def generate_ai_games(full_data, weight_percent, options):
    ai = LotoAI()
    if options['use_trend']:
        recent_trend_data = full_data[:90] 
        weights_map = ai.analyze_recent_trend(recent_trend_data, scope=15)
        # 사용자가 입력한 가중치(%) 적용
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
    # 5게임 생성할 때까지 반복
    while len(final_games) < 5:
        attempts += 1
        if attempts > 5000: # 무한루프 방지
            game = sorted(random.sample(range(1, 46), 6))
            final_games.append(game)
            continue
        game = set()
        while len(game) < 6:
            pick = random.choices(range(1, 46), weights=final_weights, k=1)[0]
            game.add(pick)
        candidate = sorted(list(game))
        
        # 필터 적용
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
# [3] UI 디자인 (화면 깨짐 없는 최종 버전)
# ==========================================
st.set_page_config(page_title="Lotto AI Pro", page_icon="🎱")

# 기본 CSS 설정
st.markdown("""
<style>
html, body, [class*="css"] { font-family: "Malgun Gothic", sans-serif; }
.block-container { padding-top: 1.5rem; padding-bottom: 3rem; }
/* 모바일 좌우 여백 최적화 */
@media (max-width: 600px) {
    .block-container { padding-left: 0.5rem; padding-right: 0.5rem; }
}
</style>
""", unsafe_allow_html=True)

# 공 그리기 함수 (HTML 생성)
def get_ball_html(num):
    color = "#27AE60" # 40번대 (녹색)
    if num <= 10: color = "#F39C12" # 1~10 (노랑)
    elif num <= 20: color = "#3498DB" # 11~20 (파랑)
    elif num <= 30: color = "#E74C3C" # 21~30 (빨강)
    elif num <= 40: color = "#7F8C8D" # 31~40 (회색)
    
    # 공 스타일: 깨짐 방지를 위해 인라인 스타일 사용
    return f'<div style="display:inline-flex;justify-content:center;align-items:center;width:32px;height:32px;border-radius:50%;background-color:{color};color:white;font-weight:bold;font-size:13px;margin-right:3px;flex-shrink:0;box-shadow:1px 1px 2px rgba(0,0,0,0.3);">{num}</div>'

# 한 줄 그리기 함수 (라벨 + 공들)
def draw_row(label_text, balls_list, is_header=False):
    balls_html = "".join([get_ball_html(n) for n in balls_list])
    
    label_color = "#2980B9" if is_header else "#333"
    label_bg = "transparent" if is_header else "#f1f3f5"
    
    # HTML 구조: 들여쓰기 제거하여 코드 블록 인식 문제 해결
    # white-space: nowrap -> 줄바꿈 절대 금지
    # overflow-x: auto -> 공간 부족 시 가로 스크롤
    html_code = f"""
<div style="background-color:white;padding:10px;border-radius:8px;margin-bottom:8px;border:1px solid #ddd;display:flex;flex-direction:row;align-items:center;justify-content:flex-start;overflow-x:auto;">
<div style="font-weight:800;color:{label_color};font-size:14px;min-width:60px;margin-right:10px;white-space:nowrap;flex-shrink:0;text-align:left;background-color:{label_bg};padding:5px;border-radius:5px;text-align:center;">{label_text}</div>
<div style="display:flex;flex-direction:row;flex-wrap:nowrap;gap:2px;">{balls_html}</div>
</div>
"""
    st.markdown(html_code, unsafe_allow_html=True)

# --- 사이드바 (설정) ---
with st.sidebar:
    st.header("⚙️ AI 설정")
    
    # [수정] 제한 없이 입력 가능한 숫자 입력창으로 변경
    count_val = st.number_input("과거 분석 데이터(회)", min_value=5, max_value=100, value=10, step=1)
    
    # [수정] 가중치 슬라이더 대신 숫자 입력 (무제한)
    st.write("트렌드 가중치(%) - 높을수록 최근 번호 선호")
    weight_val = st.number_input("가중치 입력", min_value=0, value=100, step=10, help="100%는 기본, 500% 이상은 강력 추천")
    
    st.markdown("---")
    st.subheader("필터 옵션")
    use_trend = st.checkbox("🔥 트렌드 가중치", value=True)
    use_end = st.checkbox("⚡ 끝수 동기화", value=True)
    use_dead = st.checkbox("☠️ 죽음의 구간", value=True)
    use_stats = st.checkbox("📊 통계 정밀 필터", value=True)
    use_consec = st.checkbox("🔗 연속 번호 포함", value=True)
    
    st.markdown("---")
    generate_btn = st.button("🚀 AI 번호 생성", type="primary", use_container_width=True)

# --- 메인 화면 ---
st.title("AI Lotto Pro")

full_data, history_info = fetch_lotto_api(count_val)

if full_data:
    # 1. 히스토리 영역
    with st.expander(f"📋 최근 {count_val}회 당첨 결과", expanded=True):
        for epsd, nums in reversed(history_info):
            draw_row(f"{epsd}회", nums, is_header=True)

    # 2. 결과 생성 영역
    st.markdown("### 🤖 AI 추천 번호 (Top 5)")

    if generate_btn:
        options = {
            'use_trend': use_trend, 'use_end_digit': use_end,
            'use_dead_zone': use_dead, 'use_stats': use_stats,
            'use_consecutive': use_consec
        }
        
        with st.spinner(f"최근 데이터와 {weight_val}% 가중치로 분석 중..."):
            games = generate_ai_games(full_data, weight_val, options)
            
            for i, game in enumerate(games):
                draw_row(f"SET {i+1}", game, is_header=False)
            
            st.success("분석 완료! 행운을 빕니다! 🍀")

else:
    st.error("서버에서 데이터를 불러오지 못했습니다.")