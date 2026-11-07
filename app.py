"""센터 고객 CRM: authenticated Streamlit UI backed exclusively by Firestore."""
import copy
import json
import threading
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

import legacy_core as core
import place_lookup
from service import add_consultation, can_access, load_responses, reports_for_card, serialize_card, sync_surveys, today
from storage import ConflictError, Store


st.set_page_config(page_title="센터 고객 CRM", page_icon="📇", layout="centered", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container{max-width:900px;padding-top:1.2rem;padding-bottom:3rem}
div.stButton>button,div.stFormSubmitButton>button{min-height:46px;border-radius:12px}
@media(max-width:600px){.block-container{padding-left:1rem;padding-right:1rem}
div[data-testid="stHorizontalBlock"]{flex-wrap:wrap}div[data-testid="stColumn"]{min-width:140px!important}}
</style>""", unsafe_allow_html=True)


def owner_gate():
    """Run before initializing the database, polling sheets or rendering private data."""
    try:
        owner = st.secrets["owner_email"]
        auth = st.secrets["auth"]
        if not owner or not auth.get("client_id") or not auth.get("client_secret"):
            raise ValueError
    except (KeyError, FileNotFoundError, ValueError):
        st.title("센터 고객 CRM")
        st.info("관리자가 로그인 연결을 준비하고 있습니다. 고객 정보는 로그인 후에만 표시됩니다.")
        st.stop()
    if not st.user.is_logged_in:
        st.title("📇 센터 고객 CRM")
        st.write("PC와 휴대폰에서 사용하는 나만의 고객 관리")
        st.caption("허용된 본인 Google 계정으로 로그인해 주세요.")
        if st.button("Google로 로그인", type="primary", use_container_width=True):
            st.login()
        st.stop()
    if not can_access(st.user, owner):
        st.error("접근 권한이 없는 계정입니다. 본인 계정으로 다시 로그인해 주세요.")
        if st.button("로그아웃"):
            st.logout()
        st.stop()
    return owner


OWNER = owner_gate()


@st.cache_resource
def resources(owner):
    return Store(dict(st.secrets["google_service_account"]), owner,
                 st.secrets.get("firestore_database", "(default)")), threading.Lock()


try:
    store, sync_lock = resources(OWNER)
except Exception:
    st.error("영구 저장소 연결을 확인해 주세요. 저장소가 연결되기 전에는 고객 정보를 변경할 수 없습니다.")
    st.stop()


def show_error(exc):
    if isinstance(exc, (ValueError, ConflictError)):
        st.error(str(exc))
    else:
        st.error("작업을 완료하지 못했습니다. 저장소 연결을 확인한 후 다시 시도해 주세요. 입력 내용은 이 화면에 남아 있습니다.")


@st.fragment(run_every="10s")
def survey_sync_status():
    if not can_access(st.user, OWNER):
        st.stop()
    if not sync_lock.acquire(blocking=False):
        st.caption("다른 화면에서 설문을 확인하고 있습니다.")
        return
    try:
        cfg = st.secrets.get("survey", {})
        records = load_responses(st.secrets["google_service_account"], cfg["url"], cfg["tab"])
        result = sync_surveys(store, records) if cfg.get("auto_register", True) else {"added": 0, "errors": []}
        st.session_state["survey_records"] = records
        st.caption(f"설문 연결 정상 · 응답 {len(records)}건 · 최근 확인 {datetime.now(ZoneInfo('Asia/Seoul')).strftime('%H:%M:%S')} · 접속 중 10초마다 확인")
        if result["added"]:
            st.rerun()
        if result["errors"]:
            with st.expander(f"입력 확인이 필요한 설문 {len(result['errors'])}건"):
                for error in result["errors"]:
                    st.write(f"{error['row']}행: {error['error']}")
    except Exception:
        st.warning("설문 연결을 확인하지 못했습니다. 기존 고객 카드는 계속 사용할 수 있습니다.")
    finally:
        sync_lock.release()


st.title("📇 센터 고객 CRM")
st.caption("고객 정보와 상담 기록을 PC·휴대폰에서 함께 관리합니다.")
with st.sidebar:
    st.write(OWNER)
    st.caption("자료는 Google Firestore에 저장됩니다.")
    if st.button("로그아웃", use_container_width=True):
        st.logout()
survey_sync_status()
page = st.radio("메뉴", ["고객", "설문", "KT 가입자", "휴지통", "보관함"], horizontal=True, label_visibility="collapsed")


def clear_snapshot(ident):
    st.session_state.pop("snapshot_" + ident, None)


@st.fragment
def report_viewer(card):
    reports = reports_for_card(card, store.list_assets())
    if not reports:
        st.info("연결된 보고서 파일을 찾지 못했습니다. 보관함에서 파일을 확인해 주세요.")
        return
    chosen = st.selectbox("열어볼 SEO 보고서", reports, format_func=lambda a: a['name'],
                          key="report_choice_" + card['id'])
    try:
        meta, raw = store.get_asset(chosen['id'])
        st.download_button("SEO 보고서 MD 내려받기", raw, meta['name'].replace('\\', '/').rsplit('/', 1)[-1],
                           "text/markdown", key="report_download_" + card['id'], on_click="ignore")
        st.markdown(raw.decode('utf-8-sig'))
    except Exception as exc:
        show_error(exc)


def card_editor(ident):
    key = "snapshot_" + ident
    if key not in st.session_state:
        st.session_state[key] = store.get(ident)
    card = st.session_state[key]
    if not card or card.get("deleted"):
        st.info("삭제되거나 이동된 카드입니다. 목록을 다시 읽어 주세요.")
        return
    fm = card["fm"]
    st.subheader(fm.get("상호", "고객 카드"))
    st.caption(" · ".join(filter(None, [fm.get("지역"), fm.get("상태"), fm.get("업종") or fm.get("상품")])))
    if st.button("이 카드 다시 읽기", key="reload_" + ident):
        clear_snapshot(ident)
        st.rerun()
    with st.form("edit_" + ident):
        edited = copy.deepcopy(fm)
        fields = [("상호", "매장명"), ("지역", "지역"), ("업종", "업종"),
                  ("연락처", "연락처"), ("이메일주소", "이메일주소"), ("담당", "담당"),
                  ("다음할일", "다음 할 일"), ("다음날짜", "다음 날짜 (YYYY-MM-DD)"), ("플레이스", "네이버 플레이스 주소")]
        if card["kind"] == "kt":
            fields += [("상품", "상품"), ("접수번호", "접수번호"), ("접수일", "접수일"), ("개통일", "개통일"),
                       ("사전개통일", "사전개통일"), ("본개통일", "본개통일")]
        for field, label in fields:
            edited[field] = st.text_input(label, str(fm.get(field) or ""))
        states = core.KT_STATES_ALL if card["kind"] == "kt" else core.STATES
        options = list(dict.fromkeys(states + ([fm["상태"]] if fm.get("상태") else [])))
        edited["상태"] = st.selectbox("상태", options, index=options.index(fm.get("상태")) if fm.get("상태") in options else 0)
        if st.form_submit_button("고객 정보 저장", type="primary", use_container_width=True):
            try:
                error = core.validate_store_fields(edited)
                if error:
                    raise ValueError(error)
                if not edited["상호"].strip():
                    raise ValueError("매장명을 입력해 주세요.")
                store.update(ident, card["revision"], fm=edited)
                clear_snapshot(ident)
                st.rerun()
            except Exception as exc:
                show_error(exc)
    if not fm.get("플레이스"):
        search_key = "place_search_" + ident + "_" + str(card["revision"])
        if search_key not in st.session_state:
            try:
                found = place_lookup.search(fm.get("상호", ""), fm.get("지역", ""))
                st.session_state[search_key] = found
                if found.get("auto"):
                    updated = {**fm, "플레이스": found["auto"]["url"], "플레이스ID": found["auto"]["id"]}
                    store.update(ident, card["revision"], fm=updated)
                    clear_snapshot(ident)
                    st.rerun()
            except Exception:
                st.caption("플레이스 주소 자동 검색을 완료하지 못했습니다.")
        candidates = st.session_state.get(search_key, {}).get("candidates", [])
        if candidates:
            candidate = st.selectbox("플레이스 매장 후보", candidates, format_func=lambda c: c["name"] + " · " + c["address"])
            if st.button("선택한 플레이스 주소 저장"):
                try:
                    store.update(ident, card["revision"], fm={**fm, "플레이스": candidate["url"], "플레이스ID": candidate["id"]})
                    clear_snapshot(ident)
                    st.rerun()
                except Exception as exc:
                    show_error(exc)
    tabs = st.tabs(["상담 기록", "카드 본문", "리뷰·보고서", "삭제"])
    with tabs[0]:
        with st.form("consult_" + ident):
            how = st.selectbox("연락 방식", ["전화", "방문", "문자·메신저", "메일"])
            note = st.text_area("상담 내용", height=140)
            if st.form_submit_button("상담 기록 남기기", type="primary", use_container_width=True):
                try:
                    next_fm, body = add_consultation(card, note, how)
                    store.update(ident, card["revision"], fm=next_fm, body=body)
                    clear_snapshot(ident)
                    st.rerun()
                except Exception as exc:
                    show_error(exc)
        st.markdown(core.split_sections(card["body"]).get("오간 이야기", "아직 상담 기록이 없습니다."))
    with tabs[1]:
        with st.form("body_" + ident):
            body = st.text_area("소개·메모·기록 (Markdown)", card["body"], height=320)
            if st.form_submit_button("본문 저장", use_container_width=True):
                try:
                    store.update(ident, card["revision"], body=body)
                    clear_snapshot(ident)
                    st.rerun()
                except Exception as exc:
                    show_error(exc)
        st.download_button("고객 카드 내려받기", serialize_card(card), fm.get("상호", "고객") + ".md", mime="text/markdown", use_container_width=True)
    with tabs[2]:
        if fm.get("리뷰자산ID"):
            with st.expander("SEO·GEO·AEO 프롬프트 만들기"):
                import streamlit.components.v1 as components
                generator = components.declare_component("prompt_forge", path=str(Path(__file__).parent / "prompt_component"))
                _, raw_result = store.get_asset(fm["리뷰자산ID"])
                prompt = generator(result=json.loads(raw_result), key="prompt_" + ident, default=None)
                if prompt:
                    st.download_button("프롬프트 내려받기", prompt, fm["상호"] + "_프롬프트.md", on_click="ignore")
                    if st.button("프롬프트 영구 저장", key="save_prompt_" + ident):
                        store.put_asset(fm["상호"] + "_프롬프트_" + today() + ".md", prompt.encode(), "text/markdown", "prompt")
                        st.success("보관함에 저장했습니다.")
        if fm.get("플레이스"):
            st.link_button("네이버 플레이스 열기", fm["플레이스"], use_container_width=True)
            cap = st.number_input("수집할 최대 리뷰 수", 10, 500, 100, step=10)
            if st.button("리뷰 수집", use_container_width=True):
                try:
                    with st.spinner("플레이스 리뷰를 수집하고 있습니다. 잠시 기다려 주세요."):
                        import naver_review_crawler
                        result = naver_review_crawler.Crawler(log=lambda _: None).crawl(fm["플레이스"], int(cap))
                        pay = core.collect_payload(result)
                        review_name = f"리뷰_{fm['상호']}_{today()}.json"
                        asset = store.put_asset(review_name, json.dumps(result, ensure_ascii=False).encode(), "application/json", "review")
                        next_fm = {**fm, "리뷰파일": review_name, "리뷰자산ID": asset, "리뷰수집일": today(),
                                   "평균별점": str(pay.get("평균별점", "")), "방문자리뷰수": str(pay.get("방문자리뷰수", ""))}
                        body = core.apply_collection_to_body(card["body"], fm["상호"], pay)
                        store.update(ident, card["revision"], fm=next_fm, body=body)
                        clear_snapshot(ident)
                        st.rerun()
                except Exception as exc:
                    show_error(exc)
        with st.form("report_" + ident):
            report = st.text_area("AI가 작성한 SEO 보고서 붙여넣기", height=180)
            if st.form_submit_button("보고서 영구 저장", use_container_width=True):
                try:
                    if not report.strip():
                        raise ValueError("보고서 내용을 입력해 주세요.")
                    name = f"{fm['상호']}_SEO_{today()}_{datetime.now().strftime('%H%M%S')}.md"
                    asset = store.put_asset(name, report.encode(), "text/markdown", "report")
                    sections = core.split_sections(card["body"])
                    sections["SEO 보고서"] = f"### {today()}\n보고서: {name}\n" + sections.get("SEO 보고서", "")
                    store.update(ident, card["revision"], fm={**fm, "최근보고서ID": asset, "SEO발행일": today()}, body=core.assemble_body(fm["상호"], sections))
                    clear_snapshot(ident)
                    st.rerun()
                except Exception as exc:
                    show_error(exc)
        for section in ("플레이스 진단", "플레이스 리뷰", "SEO 보고서"):
            content = core.split_sections(card["body"]).get(section)
            if content:
                with st.expander(section, expanded=section == "SEO 보고서"):
                    if section == "SEO 보고서":
                        report_viewer(card)
                    else:
                        st.markdown(content)
    with tabs[3]:
        st.write("카드를 휴지통으로 옮기면 설문 자동 등록으로 다시 생성되지 않습니다.")
        confirmed = st.checkbox("「" + fm.get("상호", "") + "」 카드를 휴지통으로 이동합니다.")
        if st.button("카드 삭제", disabled=not confirmed, use_container_width=True):
            try:
                store.update(ident, card["revision"], deleted=True)
                clear_snapshot(ident)
                st.rerun()
            except Exception as exc:
                show_error(exc)


try:
    if page in ("고객", "KT 가입자"):
        kind = "kt" if page == "KT 가입자" else "customer"
        with st.expander("＋ 새 " + page + " 등록"):
            with st.form("new_" + kind):
                name = st.text_input("매장명 *")
                region = st.text_input("지역 *")
                phone = st.text_input("연락처")
                email = st.text_input("이메일주소")
                product = st.text_input("KT 상품") if kind == "kt" else ""
                next_task = st.text_input("다음 할 일", "첫 상담")
                next_day = st.date_input("다음 날짜", date.fromisoformat(today()))
                if st.form_submit_button("카드 만들기", type="primary", use_container_width=True):
                    try:
                        fm, body = __import__("service").survey_card({"상호": name, "지역": region, "연락처": phone, "이메일주소": email})
                        fm.update({"다음할일": next_task, "다음날짜": next_day.isoformat(), "등록경로": "직접 등록"})
                        if kind == "kt":
                            fm.update({"구분": "KT가입자", "상품": product, "상태": "접수"})
                        ident, created = store.create(fm, body, kind=kind)
                        st.success("등록했습니다." if created else "이미 등록된 고객입니다.")
                    except Exception as exc:
                        show_error(exc)
        query = st.text_input("고객 검색", placeholder="매장명·지역·담당·연락처")
        if st.button("목록 다시 읽기", use_container_width=True):
            st.rerun()
        cards = store.list_cards(kind)
        visible = [c for c in cards if query.casefold() in " ".join(str(v) for v in c["fm"].values()).casefold()]
        st.caption(f"전체 {len(cards)}곳 · 검색 결과 {len(visible)}곳")
        if visible:
            selected = st.selectbox("고객 선택", [c["id"] for c in visible],
                format_func=lambda ident: next(c["fm"].get("상호", "") + " · " + c["fm"].get("지역", "") for c in visible if c["id"] == ident))
            card_editor(selected)
        else:
            st.info("표시할 고객 카드가 없습니다.")
    elif page == "설문":
        st.subheader("설문 응답")
        st.caption("접속 중에는 자동 확인합니다. 앱이 잠든 동안의 응답은 다음 접속 때 한꺼번에 가져옵니다.")
        if st.button("최신 응답 확인", use_container_width=True):
            st.rerun()
        known = store.survey_state()
        for number, data, source_id in st.session_state.get("survey_records", []):
            with st.container(border=True):
                st.write("**" + data.get("상호", "이름 없음") + "**")
                st.write(data.get("지역", ""))
                st.caption(data.get("설문접수일시", ""))
                st.text(data.get("연락처", "") + " · " + data.get("이메일주소", ""))
                if source_id in known:
                    card = store.get(known[source_id]["card_id"])
                    st.success("휴지통에 있는 응답" if card and card.get("deleted") else "고객 카드 등록됨")
                elif st.button("고객 카드 등록", key="import_" + source_id, use_container_width=True):
                    try:
                        result = sync_surveys(store, [(number, data, source_id)])
                        if result["errors"]:
                            st.error(result["errors"][0]["error"])
                        else:
                            st.rerun()
                    except Exception as exc:
                        show_error(exc)
    elif page == "휴지통":
        st.subheader("고객 카드 휴지통")
        for kind in ("customer", "kt"):
            for card in store.list_cards(kind, deleted=True):
                with st.container(border=True):
                    st.write(card["fm"].get("상호", ""))
                    st.caption(card.get("deleted_at", "이전된 삭제 카드"))
                    if st.button("복구", key="restore_" + card["id"], use_container_width=True):
                        store.update(card["id"], card["revision"], deleted=False)
                        clear_snapshot(card["id"])
                        st.rerun()
    elif page == "보관함":
        st.subheader("보고서·수집 원본·프롬프트")
        for item in sorted(store.list_assets(), key=lambda x: x["name"]):
            with st.expander(item["name"]):
                if st.button("파일 불러오기", key="asset_" + item["id"]):
                    meta, raw = store.get_asset(item["id"])
                    st.download_button("내려받기", raw, meta["name"], meta["content_type"], key="dl_" + item["id"], use_container_width=True, on_click="ignore")
                    if meta["content_type"].startswith("text/"):
                        st.markdown(raw.decode("utf-8"))
except Exception as exc:
    show_error(exc)
