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
# [0] PWA 설치형 앱 설정
# ==========================================
_PWA_MANIFEST = """
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
_PWA_MANIFEST_B64 = base64.b64encode(_PWA_MANIFEST.encode()).decode()

components.html(f"""
<script>
    if (!window.parent.document.getElementById('pwa-manifest')) {{
        const manifest = window.parent.document.createElement('link');
        manifest.id = 'pwa-manifest';
        manifest.rel = 'manifest';
        manifest.href = 'data:application/manifest+json;base64,{_PWA_MANIFEST_B64}';
        window.parent.document.head.appendChild(manifest);
    }}
</script>
""", width=0, height=0)


# ==========================================
# [1] 구글 스프레드시트 연동
# ==========================================
def get_gsheet_client():
    if "gcp_service_account" not in st.secrets or "sheet" not in st.secrets:
        return None
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    return gspread.authorize(creds)


def load_history():
    records = []

    # 구글 시트 우선 시도
    try:
        gc = get_gsheet_client()
        if gc:
            sheet_url = st.secrets["sheet"]["url"]
            worksheet = gc.open_by_url(sheet_url).sheet1
            for row in worksheet.get_all_values():
                if len(row) >= 2:
                    try:
                        records.append({
                            "epsd": int(row[0]),
                            "games": json.loads(row[1]),
                        })
                    except (ValueError, json.JSONDecodeError):
                        continue
            return records
    except Exception as e:
        st.warning(f"구글 시트 불러오기 실패, 로컬 파일로 대체합니다. ({e})")

    # 폴백: 로컬 파일
    if os.path.exists("lotto_history.jsonl"):
        with open("lotto_history.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def save_history(epsd: int, games: list, retries: int = 3, retry_delay: float = 1.5) -> bool:
    """
    구글 시트에 저장 시도 (최대 retries 회 재시도).
    저장 후 실제로 데이터가 들어갔는지 검증까지 수행.
    모두 실패 시 로컬 파일로 폴백. 성공 시 True 반환.
    """
    gc = get_gsheet_client()
    if gc:
        sheet_url = st.secrets["sheet"]["url"]
        row_data = [epsd, json.dumps(games)]

        for attempt in range(1, retries + 1):
            try:
                worksheet = gc.open_by_url(sheet_url).sheet1
                worksheet.append_row(row_data)

                # 저장 검증: 마지막 행이 실제로 기록됐는지 확인
                last_row = worksheet.get_all_values()[-1]
                if len(last_row) >= 2 and str(last_row[0]) == str(epsd):
                    return True  # 저장 + 검증 성공

                # 데이터는 들어갔으나 검증 불일치 → 재시도
                raise ValueError(f"검증 실패: 저장된 회차({last_row[0]}) ≠ 요청 회차({epsd})")

            except Exception as e:
                if attempt < retries:
                    time.sleep(retry_delay)
                else:
                    st.warning(f"구글 시트 저장 {retries}회 모두 실패, 로컬 파일에 저장합니다. (마지막 오류: {e})")

    # 폴백: 로컬 파일 (구글 시트 연결 없거나 모두 실패한 경우에만)
    with open("lotto_history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"epsd": epsd, "games": games}) + "\n")
    return False


# ==========================================
# [2] AI 분석 엔진
# ==========================================
class LottoAI:

    def analyze_recent_trend(self, data: list, scope: int = 15) -> dict:
        """최근 scope 회차 번호의 출현 빈도를 가중치로 반환."""
        recent = data[:scope * 6]
        counts = Counter(recent)
        weights = {i: 1.0 for i in range(1, 46)}
        for num, freq in counts.items():
            weights[num] += freq * 0.5
        return weights

    def has_end_digit_pair(self, numbers: list) -> bool:
        """끝자리가 같은 번호가 1쌍 이상 존재하는지 확인."""
        end_digits = [n % 10 for n in numbers]
        return any(c >= 2 for c in Counter(end_digits).values())

    def has_dead_zone(self, numbers: list) -> bool:
        """5구간 중 2개 이상이 비어있는지 확인 (분산 패턴)."""
        zones = [0] * 9
        for n in numbers:
            zones[(n - 1) // 5] = 1
        return zones.count(0) >= 2

    def passes_stat_filter(self, numbers: list) -> bool:
        """합계·홀짝·고저 분포가 통계 기준을 통과하는지 확인."""
        total = sum(numbers)
        if not (100 <= total <= 175):
            return False
        odd_count = sum(1 for n in numbers if n % 2 != 0)
        if odd_count in (0, 6):
            return False
        low_count = sum(1 for n in numbers if n <= 22)
        if low_count in (0, 6):
            return False
        return True

    def has_consecutive(self, numbers: list) -> bool:
        """연속 번호가 1쌍 이상 존재하는지 확인."""
        sorted_nums = sorted(numbers)
        return any(
            sorted_nums[i + 1] == sorted_nums[i] + 1
            for i in range(len(sorted_nums) - 1)
        )


def generate_ai_games(full_data: list, weight_percent: int, options: dict) -> list:
    ai = LottoAI()

    # 가중치 계산
    if options["use_trend"]:
        trend_weights = ai.analyze_recent_trend(full_data, scope=15)
        extra = weight_percent / 100.0
        final_weights = [
            trend_weights.get(i, 1.0) + extra if trend_weights.get(i, 1.0) > 1.0
            else 1.0
            for i in range(1, 46)
        ]
    else:
        final_weights = [1.0] * 45

    final_games = []
    attempts = 0
    max_attempts = 10_000

    while len(final_games) < 5:
        attempts += 1

        # 무한 루프 방지: 조건이 너무 까다로우면 필터 완화 후 추가
        if attempts > max_attempts:
            game = sorted(random.sample(range(1, 46), 6))
            final_games.append(game)
            st.warning("일부 번호는 조건 충족이 어려워 필터 없이 생성되었습니다.")
            continue

        candidate = sorted(random.choices(range(1, 46), weights=final_weights, k=6))
        if len(set(candidate)) < 6:  # 중복 제거
            continue

        if options["use_end_digit"] and not ai.has_end_digit_pair(candidate):
            continue
        if options["use_dead_zone"] and not ai.has_dead_zone(candidate):
            continue
        if options["use_stats"] and not ai.passes_stat_filter(candidate):
            continue
        if options["use_consecutive"]:
            # 초반 3세트는 70% 확률로 연속 번호 포함 강제
            if len(final_games) < 3 and not ai.has_consecutive(candidate):
                if random.random() < 0.7:
                    continue

        final_games.append(candidate)

    return final_games


# ==========================================
# [3] 데이터 가져오기 (1시간 캐시)
# ==========================================
@st.cache_data(ttl=3600)
def fetch_lotto_data(count: int):
    """동행복권 API에서 당첨 번호를 가져옵니다."""
    url = "https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do?srchLtEpsd=all"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        all_list = response.json().get("data", {}).get("list", [])
    except Exception as e:
        return None, str(e)

    # ltEpsd 기준 내림차순 정렬 (최신 회차 우선)
    all_list = sorted(all_list, key=lambda x: int(x.get("ltEpsd", 0)), reverse=True)

    full_data_flat = []
    for item in all_list:
        nums = [int(item.get(f"tm{i}WnNo", 0)) for i in range(1, 7)]
        full_data_flat.extend(nums)

    history_info = []
    for item in all_list[:count]:
        epsd = int(item.get("ltEpsd", 0))
        nums = [int(item.get(f"tm{i}WnNo", 0)) for i in range(1, 7)]
        bonus = int(item.get("bnusNo", 0))
        history_info.append((epsd, nums, bonus))

    return full_data_flat, history_info


@st.cache_data(ttl=3600)
def fetch_prize_info(epsd: int) -> dict:
    """특정 회차의 등수별 당첨 금액을 반환합니다."""
    default_prizes = {1: None, 2: 50_000_000, 3: 1_500_000, 4: 50_000, 5: 5_000}
    try:
        url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={epsd}"
        res = requests.get(url, timeout=5)
        res.raise_for_status()
        data = res.json()
        if data.get("returnValue") == "success":
            default_prizes[1] = data.get("firstWinamnt")
    except Exception as e:
        st.warning(f"{epsd}회차 당첨금 조회 실패: {e}")
    return default_prizes


# ==========================================
# [4] UI 헬퍼
# ==========================================
BALL_COLORS = {
    (1, 10): "#F39C12",
    (11, 20): "#3498DB",
    (21, 30): "#E74C3C",
    (31, 40): "#7F8C8D",
    (41, 45): "#27AE60",
}

def get_ball_color(num: int) -> str:
    for (lo, hi), color in BALL_COLORS.items():
        if lo <= num <= hi:
            return color
    return "#27AE60"

def get_ball_html(num: int) -> str:
    color = get_ball_color(num)
    return (
        f'<div style="display:inline-flex;justify-content:center;align-items:center;'
        f'width:32px;height:32px;border-radius:50%;background-color:{color};'
        f'color:white;font-weight:bold;font-size:13px;margin-right:3px;'
        f'flex-shrink:0;box-shadow:1px 1px 2px rgba(0,0,0,0.3);">{num}</div>'
    )

def draw_row(label: str, balls: list, is_header: bool = False):
    balls_html = "".join(get_ball_html(n) for n in balls)
    label_color = "#2980B9" if is_header else "#333"
    st.markdown(f"""
<div style="background-color:white;padding:10px;border-radius:8px;margin-bottom:8px;
            border:1px solid #ddd;display:flex;align-items:center;overflow-x:auto;">
  <div style="font-weight:800;color:{label_color};font-size:14px;min-width:60px;
              margin-right:10px;white-space:nowrap;flex-shrink:0;text-align:center;
              padding:5px;border-radius:5px;">{label}</div>
  <div style="display:flex;flex-wrap:nowrap;gap:2px;">{balls_html}</div>
</div>
""", unsafe_allow_html=True)

def stat_box(value: str, title: str, color: str = "#333"):
    return (
        f'<div class="stat-box">'
        f'<div class="stat-number" style="color:{color};">{value}</div>'
        f'<div class="stat-title">{title}</div>'
        f'</div>'
    )


# ==========================================
# [5] 페이지 설정 및 스타일
# ==========================================
st.set_page_config(page_title="인공지능 로또 분석기", page_icon="🎱")

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
.stat-title  { font-size: 13px; color: #666; margin-top: 5px; }
[data-testid="stToolbar"] { visibility: hidden !important; display: none !important; }
header  { visibility: hidden !important; }
footer  { visibility: hidden !important; }
</style>
""", unsafe_allow_html=True)


# ==========================================
# [6] 세션 상태 초기화
# ==========================================
if "is_generating" not in st.session_state:
    st.session_state.is_generating = False
if "recent_generated_games" not in st.session_state:
    st.session_state.recent_generated_games = []
if "last_save_to_sheet" not in st.session_state:
    st.session_state.last_save_to_sheet = None


# ==========================================
# [7] 사이드바 (PC) — 데스크탑에서는 사이드바에 표시
# ==========================================
with st.sidebar:
    st.header("⚙️ 분석 설정")
    sb_count_val  = st.number_input("과거 분석 정보(회)", min_value=5, max_value=100, value=10, step=1, key="sb_count")
    st.write("흐름 가중치(%) — 높을수록 최근 번호 우선")
    sb_weight_val = st.number_input("가중치 입력", min_value=0, value=100, step=10, key="sb_weight")

    st.markdown("---")
    st.subheader("거르기 조건")
    sb_use_trend  = st.checkbox("🔥 흐름 가중치",      value=True, key="sb_trend")
    sb_use_end    = st.checkbox("⚡ 끝자리 일치",      value=True, key="sb_end")
    sb_use_dead   = st.checkbox("☠️ 제외 구간",        value=True, key="sb_dead")
    sb_use_stats  = st.checkbox("📊 통계 정밀 거르기", value=True, key="sb_stats")
    sb_use_consec = st.checkbox("🔗 이어지는 번호",    value=True, key="sb_consec")

    st.markdown("---")
    st.subheader("🔥 최근 핫넘버 TOP 5")
    hot_numbers_slot = st.empty()


# ==========================================
# [8] 데이터 로드
# ==========================================
full_data, history_info = fetch_lotto_data(sb_count_val)

if full_data and history_info:
    # 사이드바 핫넘버 표시
    recent_nums = [n for _, nums, _ in history_info for n in nums]
    top5 = Counter(recent_nums).most_common(5)
    hot_html = "".join(
        f"<div style='margin-bottom:5px;'>{get_ball_html(num)}"
        f" <span style='font-size:14px;font-weight:bold;color:#555;'>({freq}회 출현)</span></div>"
        for num, freq in top5
    )
    hot_numbers_slot.markdown(hot_html, unsafe_allow_html=True)

    latest_epsd = history_info[0][0]
    target_epsd = latest_epsd + 1
    history_records = load_history()

    st.title("인공지능 로또 분석기")
    tab_home, tab_stats, tab_help = st.tabs(["🎯 분석기 홈", "📊 이번 주 수익률/통계", "📖 설명서"])

    # ==========================================
    # 모바일용 설정 패널 (탭 내부 상단에 expander로 표시)
    # ==========================================
    with tab_home:
        with st.expander("⚙️ 분석 설정 (모바일 전용)", expanded=False):
            col_a, col_b = st.columns(2)
            with col_a:
                mb_count_val  = st.number_input("분석 회수(회)", min_value=5, max_value=100,
                                                value=sb_count_val, step=1, key="mb_count")
                mb_weight_val = st.number_input("흐름 가중치(%)", min_value=0,
                                                value=sb_weight_val, step=10, key="mb_weight")
            with col_b:
                mb_use_trend  = st.checkbox("🔥 흐름 가중치",      value=sb_use_trend,  key="mb_trend")
                mb_use_end    = st.checkbox("⚡ 끝자리 일치",      value=sb_use_end,    key="mb_end")
                mb_use_dead   = st.checkbox("☠️ 제외 구간",        value=sb_use_dead,   key="mb_dead")
                mb_use_stats  = st.checkbox("📊 통계 거르기",      value=sb_use_stats,  key="mb_stats")
                mb_use_consec = st.checkbox("🔗 이어지는 번호",    value=sb_use_consec, key="mb_consec")

            # 모바일 핫넘버
            st.markdown(f"**🔥 최근 핫넘버 TOP 5** (최근 {mb_count_val}회 기준)")
            mb_recent = fetch_lotto_data(mb_count_val)
            if mb_recent[1]:
                mb_nums = [n for _, nums, _ in mb_recent[1] for n in nums]
                mb_top5 = Counter(mb_nums).most_common(5)
                mb_hot_html = "".join(
                    f"<div style='display:inline-block;margin-right:8px;'>{get_ball_html(num)}"
                    f"<span style='font-size:12px;color:#555;'> {freq}회</span></div>"
                    for num, freq in mb_top5
                )
                st.markdown(mb_hot_html, unsafe_allow_html=True)

        # 실제 사용할 값: 모바일 expander 값 우선
        count_val  = mb_count_val
        weight_val = mb_weight_val
        use_trend  = mb_use_trend
        use_end    = mb_use_end
        use_dead   = mb_use_dead
        use_stats  = mb_use_stats
        use_consec = mb_use_consec

        st.button(
            f"🚀 {target_epsd}회차 번호 뽑기 시작",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.is_generating,
            on_click=lambda: st.session_state.update(is_generating=True),
        )
        st.markdown("---")

        if st.session_state.is_generating:
            options = {
                "use_trend":       use_trend,
                "use_end_digit":   use_end,
                "use_dead_zone":   use_dead,
                "use_stats":       use_stats,
                "use_consecutive": use_consec,
            }
            with st.spinner("번호 분석 중..."):
                games = generate_ai_games(full_data, weight_val, options)

            with st.spinner("구글 시트에 저장 중... (최대 3회 재시도)"):
                saved_to_sheet = save_history(target_epsd, games)

            st.session_state.recent_generated_games = games
            st.session_state.last_save_to_sheet = saved_to_sheet
            st.session_state.is_generating = False
            st.rerun()

        if st.session_state.recent_generated_games and not st.session_state.is_generating:
            st.markdown(f"### 🤖 새로 뽑힌 추천 번호 ({target_epsd}회차용)")
            for i, game in enumerate(st.session_state.recent_generated_games):
                draw_row(f"세트 {i + 1}", game)
            if st.session_state.get("last_save_to_sheet"):
                st.success("생성 및 구글 시트 저장 완료! 최신 데이터가 '통계 탭'에 반영되었습니다. 🍀")
            else:
                st.warning("번호 생성 완료. 구글 시트 저장에 실패하여 로컬 파일에 저장했습니다. 📁")
            st.markdown("<br>", unsafe_allow_html=True)

        with st.expander(f"📋 최근 {mb_count_val}회 당첨 결과 확인하기", expanded=True):
            for epsd, nums, _ in reversed(history_info):
                draw_row(f"{epsd}회", nums, is_header=True)

    # ==========================================
    # 탭 2: 수익률/통계
    # ==========================================
    with tab_stats:
        latest_nums  = set(history_info[0][1])
        latest_bonus = history_info[0][2]

        total_games_last_week = 0
        this_week_usage_count = 0
        prize_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, "fail": 0}
        winning_games = []

        for record in history_records:
            epsd  = record.get("epsd")
            games = record.get("games", [])

            if epsd == target_epsd:
                this_week_usage_count += len(games)

            if epsd == latest_epsd:
                for game in games:
                    total_games_last_week += 1
                    match = len(set(game) & latest_nums)
                    has_bonus = latest_bonus in game

                    if   match == 6:                  prize_counts[1] += 1; winning_games.append(("🎉 1등 당첨!", game))
                    elif match == 5 and has_bonus:    prize_counts[2] += 1; winning_games.append(("✨ 2등 당첨!", game))
                    elif match == 5:                  prize_counts[3] += 1; winning_games.append(("👍 3등 당첨", game))
                    elif match == 4:                  prize_counts[4] += 1
                    elif match == 3:                  prize_counts[5] += 1
                    else:                             prize_counts["fail"] += 1

        st.markdown(f"""
<div style="background:linear-gradient(135deg,#2c3e50 0%,#3498db 100%);padding:20px;
            border-radius:10px;text-align:center;color:white;margin-bottom:20px;">
  <div style="font-size:15px;opacity:0.9;margin-bottom:5px;">
    현재 준비 중인 {target_epsd}회차 대비
  </div>
  <div style="font-size:24px;font-weight:bold;">
    이번 주 총 <span style="font-size:32px;color:#f1c40f;">{this_week_usage_count}</span> 게임의 분석이 진행되었습니다.
  </div>
</div>
""", unsafe_allow_html=True)
        st.markdown("---")
        st.subheader(f"📈 {latest_epsd}회차 투자 대비 수익률 (ROI)")

        if total_games_last_week == 0:
            st.info(f"아직 데이터베이스에 {latest_epsd}회차 생성 기록이 없습니다.")
        else:
            prizes = fetch_prize_info(latest_epsd)
            total_spent = total_games_last_week * 1_000
            first_prize = prizes[1] if prizes[1] is not None else 0
            total_won = (
                prize_counts[1] * first_prize +
                prize_counts[2] * prizes[2] +
                prize_counts[3] * prizes[3] +
                prize_counts[4] * prizes[4] +
                prize_counts[5] * prizes[5]
            )
            roi = (total_won / total_spent * 100) if total_spent > 0 else 0
            first_prize_label = f"약 {first_prize // 100_000_000}억" if first_prize else "확인불가"

            st.markdown(f"""
<div style="display:flex;flex-direction:row;justify-content:space-around;
            background-color:#f1f3f5;padding:20px;border-radius:10px;margin-bottom:20px;">
  <div style="text-align:center;">
    <div style="font-size:14px;color:#555;">총 투자 금액</div>
    <div style="font-size:22px;font-weight:bold;color:#333;">{total_spent:,} 원</div>
  </div>
  <div style="text-align:center;">
    <div style="font-size:14px;color:#555;">총 당첨 금액</div>
    <div style="font-size:22px;font-weight:bold;color:#E74C3C;">{total_won:,} 원</div>
  </div>
  <div style="text-align:center;">
    <div style="font-size:14px;color:#555;">프로그램 수익률 (ROI)</div>
    <div style="font-size:22px;font-weight:bold;color:#2980B9;">{roi:,.1f} %</div>
  </div>
</div>
""", unsafe_allow_html=True)

            st.markdown(f"**총 {total_games_last_week:,}게임 중 당첨 내역**")
            c1, c2, c3 = st.columns(3)
            with c1: st.markdown(stat_box(f"{prize_counts[1]:,} 회", f"1등 ({first_prize_label})", "#C0392B"), unsafe_allow_html=True)
            with c2: st.markdown(stat_box(f"{prize_counts[2]:,} 회", "2등 (약 5천만)",          "#8E44AD"), unsafe_allow_html=True)
            with c3: st.markdown(stat_box(f"{prize_counts[3]:,} 회", "3등 (약 150만)",           "#2980B9"), unsafe_allow_html=True)

            c4, c5, c6 = st.columns(3)
            with c4: st.markdown(stat_box(f"{prize_counts[4]:,} 회", "4등 (5만 원)",  "#F39C12"), unsafe_allow_html=True)
            with c5: st.markdown(stat_box(f"{prize_counts[5]:,} 회", "5등 (5천 원)",  "#27AE60"), unsafe_allow_html=True)
            with c6: st.markdown(stat_box(f"{prize_counts['fail']:,} 회", "낙첨",     "#7F8C8D"), unsafe_allow_html=True)

            if winning_games:
                st.markdown("---")
                st.markdown("#### ✨ 축하합니다! 상위권 당첨 번호")
                for label, game in winning_games:
                    draw_row(label, game)

    # ==========================================
    # 탭 3: 설명서
    # ==========================================
    with tab_help:
        st.subheader("💡 인공지능 분석 원리")
        st.write(
            "이 프로그램은 단순한 무작위 픽이 아닙니다. "
            "역대 당첨 번호의 통계적 사실을 바탕으로 당첨 확률이 극히 희박한 조합을 걸러내어 "
            "효율적인 번호를 추천합니다."
        )
        st.markdown("---")

        st.markdown("#### 🔥 흐름 가중치 (Trend Weight)")
        st.info(
            "**왜 필요한가요?**\n"
            "로또 기계도 물리적인 장치이므로 미세한 편향이나 흐름이 존재할 수 있습니다. "
            "최근 15주 동안 자주 나온 번호('Hot Number')가 당분간 계속 나오는 경향성을 반영하여 "
            "해당 번호가 뽑힐 확률을 인위적으로 높입니다."
        )

        st.markdown("#### ⚡ 끝자리 일치 (End Digit Sync)")
        st.success(
            "**통계적 팩트**\n"
            "로또 번호 6개가 모두 다른 끝수를 가질 확률은 매우 낮습니다. "
            "역대 당첨 번호의 약 **85% 이상**은 끝자리가 같은 숫자가 최소 1쌍 이상 포함되어 있습니다. "
            "이 옵션은 그 85%의 확률에 베팅합니다."
        )

        st.markdown("#### ☠️ 제외 구간 (Dead Zone)")
        st.error(
            "**분산의 법칙**\n"
            "번호가 1번대부터 40번대까지 골고루 나오는 경우는 매우 드뭅니다. "
            "특정 번호대가 통째로 전멸하는 현상이 자주 발생합니다. "
            "이 조건은 자연스러운 '전멸 구간'을 인위적으로 만듭니다."
        )

        st.markdown("#### 📊 통계 정밀 거르기 (Statistical Filter)")
        st.warning(
            "**가장 강력한 수학적 접근**\n"
            "6개 번호의 합이 100 미만이거나 175를 초과하는 경우는 전체의 10% 미만입니다. "
            "홀수나 짝수만 6개가 몰려서 나오는 경우도 2% 미만입니다. "
            "이 필터는 나올 확률이 극히 희박한 '불량 조합'을 원천 차단합니다."
        )

        st.markdown("#### 🔗 이어지는 번호 (Consecutive Rule)")
        st.info(
            "**심리적 허점 공략**\n"
            "사람들은 연속 번호를 피하는 경향이 있지만, "
            "실제로는 50% 이상의 회차에서 연속 번호가 등장합니다. "
            "이 패턴을 일부러 포함시켜 당첨 효율을 극대화합니다."
        )

        st.markdown("---")
        st.error(
            "### ⚠️ 꼭 읽어주세요 (면책 조항)\n"
            "이 프로그램은 불필요한 조합을 제외하고 수학적 확률을 높이기 위해 설계되었지만, "
            "**로또 번호 추첨은 독립 시행이며 궁극적으로 '운(Luck)'에 의해 결정됩니다.**\n\n"
            "아무리 뛰어난 인공지능이나 통계 기법을 사용하더라도 100% 당첨을 보장하는 방법은 "
            "이 세상에 존재하지 않습니다. 본 프로그램을 통해 생성된 번호로 발생한 결과에 대한 "
            "책임은 전적으로 사용자 본인에게 있습니다. "
            "**로또는 반드시 부담 없는 소액으로, 건전하고 즐거운 마음으로만 즐겨 주시기 바랍니다.**"
        )

else:
    st.error("서버에서 데이터를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")
