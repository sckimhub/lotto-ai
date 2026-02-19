import streamlit as st
import requests
import random
from collections import Counter

# ==========================================
# [1] 계산 규칙
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
# [2] 정보 가져오기
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
# [3] 화면 구성
# ==========================================
st.set_page_config(page_title="인공지능 로또 분석기", page_icon="🎱")

st.markdown("""
<style>
html, body, [class*="css"] { font-family: "Malgun Gothic", sans-serif; }
.block-container { padding-top: 1.5rem; padding-bottom: 3rem; }
@media (max-width: 600px) {
    .block-container { padding-left: 0.5rem; padding-right: 0.5rem; }
}
</style>
""", unsafe_allow_html=True)

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

# --- 왼쪽 설정 메뉴 ---
with st.sidebar:
    st.header("⚙️ 분석 설정")
    
    count_val = st.number_input("과거 분석 데이터(회)", min_value=5, max_value=100, value=10, step=1)
    
    st.write("흐름 가중치(%) - 높을수록 최근 번호 우선")
    weight_val = st.number_input("가중치 입력", min_value=0, value=100, step=10, help="100%는 기본, 500% 이상은 강력 추천")
    
    st.markdown("---")
    st.subheader("거르기 조건")
    use_trend = st.checkbox("🔥 흐름 가중치", value=True)
    use_end = st.checkbox("⚡ 끝자리 일치", value=True)
    use_dead = st.checkbox("☠️ 제외 구간", value=True)
    use_stats = st.checkbox("📊 통계 정밀 거르기", value=True)
    use_consec = st.checkbox("🔗 이어지는 번호", value=True)

# --- 가운데 바탕 화면 ---
st.title("인공지능 로또 분석기")

# ★ 탭(Tab) 기능으로 홈 화면과 도움말 화면 분리
tab_home, tab_help = st.tabs(["🎯 분석기 홈", "📖 도움말 (옵션 설명)"])

full_data, history_info = fetch_lotto_api(count_val)

# ==========================================
# 첫 번째 탭: 분석기 메인 화면
# ==========================================
with tab_home:
    if full_data:
        # 1. 번호 뽑기 버튼
        generate_btn = st.button("🚀 번호 뽑기 시작", type="primary", use_container_width=True)
        st.markdown("---")

        # 2. 결과 나오는 곳
        if generate_btn:
            st.markdown("### 🤖 새로 뽑힌 추천 번호")
            options = {
                'use_trend': use_trend, 'use_end_digit': use_end,
                'use_dead_zone': use_dead, 'use_stats': use_stats,
                'use_consecutive': use_consec
            }
            
            with st.spinner(f"최근 기록과 {weight_val}% 가중치로 계산하고 있습니다..."):
                games = generate_ai_games(full_data, weight_val, options)
                
                for i, game in enumerate(games):
                    draw_row(f"세트 {i+1}", game, is_header=False)
                
                st.success("완료되었습니다! 좋은 결과 있으시길 바랍니다! 🍀")
            
            st.markdown("<br>", unsafe_allow_html=True)

        # 3. 과거 당첨 내역
        with st.expander(f"📋 최근 {count_val}회 당첨 결과 확인하기", expanded=True):
            for epsd, nums in reversed(history_info):
                draw_row(f"{epsd}회", nums, is_header=True)

    else:
        st.error("서버에서 정보를 가져오지 못했습니다.")

# ==========================================
# 두 번째 탭: 도움말 및 상세 설명
# ==========================================
with tab_help:
    st.subheader("💡 인공지능 분석 원리")
    st.write("이 프로그램은 단순한 무작위 뽑기가 아닙니다. 역대 당첨 번호의 통계적 사실을 바탕으로 당첨 확률이 극히 희박한 조합을 걸러내어, 가장 가능성 높은 번호만을 추천합니다.")
    st.markdown("---")

    st.markdown("#### 🔥 흐름 가중치 (Trend Weight)")
    st.info("**왜 필요한가요?**\n\n로또 기계도 물리적인 장치이므로 미세한 편향이나 흐름이 존재할 수 있습니다. 최근 15주 동안 자주 나온 번호('Hot Number')가 당분간 계속 나오는 경향성을 반영하여, 해당 번호가 뽑힐 확률을 인위적으로 높입니다. 가중치(%)를 올릴수록 최근에 자주 나온 번호 위주로 뽑히게 됩니다.")

    st.markdown("#### ⚡ 끝자리 일치 (End Digit Sync)")
    st.success("**통계적 팩트**\n\n로또 번호 6개가 모두 다른 끝수(예: 1, 12, 23, 34, 45...)를 가질 확률은 매우 낮습니다. 역대 당첨 번호의 약 **85% 이상**은 '12, 42' 처럼 끝자리가 같은 숫자가 최소 1쌍 이상 포함되어 있습니다. 이 옵션은 그 85%의 확률에 베팅하여 번호를 맞춥니다.")

    st.markdown("#### ☠️ 제외 구간 (Dead Zone)")
    st.error("**분산의 법칙**\n\n번호가 1번대부터 40번대까지 골고루 한 개씩 예쁘게 나오는 경우는 매우 드뭅니다. 보통 특정 번호대(예: 20번대)가 통째로 전멸하여 한 개도 나오지 않는 현상이 자주 발생합니다. 이 조건은 억지로 모든 구간을 채우지 않고, 자연스러운 '전멸 구간'을 인위적으로 만듭니다.")

    st.markdown("#### 📊 통계 정밀 거르기 (Statistical Filter)")
    st.warning("**가장 강력한 수학적 접근**\n\n6개 번호의 합이 100 미만이거나 175를 초과하는 경우는 전체의 10% 미만입니다. 또한 홀수나 짝수만 6개가 몰려서 나오는 경우도 2% 미만입니다. 이 필터는 나올 확률이 극히 희박한 '불량 조합'을 원천적으로 차단하여 돈 낭비를 막아줍니다.")

    st.markdown("#### 🔗 이어지는 번호 (Consecutive Rule)")
    st.info("**심리적 허점 공략**\n\n사람들은 '14, 15가 같이 나오겠어?'라고 생각해서 마킹을 피하지만, 실제로는 50% 이상의 회차에서 연속 번호가 등장합니다. 남들이 피해서 1등 당첨금이 쏠리는 이 패턴을 일부러 포함시켜 당첨 효율을 극대화합니다.")