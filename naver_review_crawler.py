# -*- coding: utf-8 -*-
"""
네이버 플레이스 리뷰 수집기
- 플레이스 URL을 입력하면 방문자 리뷰(본문 + 별점 + 작성일 + 키워드)와
  SEO 보고서용 업체 정보(카테고리/주소/전화번호/키워드 리뷰 통계 등)를 수집하여
  review 폴더에 JSON 파일로 저장합니다.
- 사용법: python naver_review_crawler.py  (GUI 실행)
         python naver_review_crawler.py --cli <URL> [최대개수]  (터미널 테스트용)
"""

import json
import re
import sys
import threading
import queue
import time
import urllib.request
from datetime import datetime
from pathlib import Path

VERSION = "1.8.1"

# '프롬프트 생성기' 버튼이 여는 페이지
PROMPT_GENERATOR_URL = "https://idea1478.tistory.com/20"

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991N) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# URL → 플레이스 ID 추출
# ---------------------------------------------------------------------------

_ID_PATTERNS = [
    re.compile(r"/(?:restaurant|cafe|place|hospital|hairshop|beauty|accommodation|attraction|pharmacy|clinic)/(\d+)"),
    re.compile(r"entry/place/(\d+)"),
    re.compile(r"[?&]id=(\d+)"),
    re.compile(r"place[/=](\d{5,})"),
]


def resolve_short_url(url: str) -> str:
    """naver.me 단축 URL이면 리다이렉트를 따라가 실제 URL을 반환."""
    if "naver.me" not in url:
        return url
    req = urllib.request.Request(url, headers={"User-Agent": MOBILE_UA})
    with urllib.request.urlopen(req, timeout=15) as res:
        return res.geturl()


def extract_place_id(url: str) -> str | None:
    for pat in _ID_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# 리뷰 데이터 추출 헬퍼
# ---------------------------------------------------------------------------

_BODY_KEYS = ("body", "originalBody", "contents", "reviewBody")
_CREATED_KEYS = ("created", "createdString", "createdDate", "regDate")
_VISITED_KEYS = ("visited", "visitDate", "visitedDate")


def _pick(d: dict, keys) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_review(item: dict, resolve=None) -> dict | None:
    """리뷰 객체(dict)에서 본문/별점/작성일/키워드를 뽑아 표준 형태로 반환.

    resolve: Apollo 캐시의 {"__ref": ...} 참조를 실제 객체로 바꿔주는 함수(선택).
    """
    if not isinstance(item, dict):
        return None
    body = _pick(item, _BODY_KEYS)
    created = _pick(item, _CREATED_KEYS)
    visited = _pick(item, _VISITED_KEYS)
    if not body and not created:
        return None
    rating = item.get("rating") or item.get("score") or ""
    visit_count = item.get("visitCount") or ""
    reply = item.get("reply")
    reply_body = ""
    if isinstance(reply, dict):
        reply_body = (reply.get("body") or "").strip()
    media = item.get("media")
    media_count = len(media) if isinstance(media, list) else 0
    origin = item.get("originType") or ""
    keywords: list[str] = []
    vk = item.get("votedKeywords")
    if isinstance(vk, list):
        for k in vk:
            if isinstance(k, dict) and "__ref" in k and resolve:
                k = resolve(k["__ref"]) or {}
            if isinstance(k, dict):
                name = k.get("displayName") or k.get("name") or ""
                if name:
                    keywords.append(name)
    rid = item.get("id") or item.get("reviewId") or f"{created}|{body[:30]}"
    return {
        "_id": str(rid),
        "본문": body,
        "별점": rating,
        "작성일": created,
        "방문일": visited,
        "방문차수": visit_count,
        "키워드": keywords,
        "사장님답글": reply_body,
        "미디어수": media_count,
        "리뷰출처": origin,
    }


def _walk_for_reviews(node, found: dict):
    """graphql 응답 JSON을 재귀 탐색하여 visitorReviews items를 수집."""
    if isinstance(node, dict):
        items = node.get("items")
        if isinstance(items, list) and (
            "visitorReviews" in str(node.get("__typename", "")).lower()
            or any(isinstance(i, dict) and "body" in i for i in items)
        ):
            for i in items:
                r = _extract_review(i)
                if r:
                    found[r["_id"]] = r
        for v in node.values():
            _walk_for_reviews(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_for_reviews(v, found)


# ---------------------------------------------------------------------------
# 리뷰 API 직접 호출 ('더보기'가 막혔을 때의 대체 수단)
# ---------------------------------------------------------------------------

GRAPHQL_URL = "https://pcmap-api.place.naver.com/graphql"

_API_QUERY = """query getVisitorReviews($input: VisitorReviewsInput) {
  visitorReviews(input: $input) {
    items {
      id
      cursor
      rating
      body
      created
      visited
      visitCount
      votedKeywords { name }
      reply { body created }
      media { type }
      originType
    }
    starDistribution { score count }
    total
  }
}"""


def _api_fetch_reviews(input_vars: dict, after: str | None, size: int = 10):
    """pcmap GraphQL API를 직접 호출해 리뷰 한 페이지를 가져온다.

    after: 이전 페이지 마지막 리뷰의 cursor (None이면 첫 페이지부터)
    반환: (리뷰 item 리스트, visitorReviews 응답 전체)
    """
    inp = dict(input_vars)
    inp["size"] = size
    inp.pop("after", None)
    if after:
        inp["after"] = after
    payload = [{
        "operationName": "getVisitorReviews",
        "variables": {"input": inp},
        "query": _API_QUERY,
    }]
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": DESKTOP_UA,
            "Referer": f"https://pcmap.place.naver.com/place/{inp.get('businessId', '')}/review/visitor",
            "Accept": "*/*",
            "Accept-Language": "ko",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        data = json.loads(res.read().decode())
    vr = (data[0].get("data") or {}).get("visitorReviews") or {}
    return vr.get("items") or [], vr


# ---------------------------------------------------------------------------
# SEO 보고서용 업체 정보 / 리뷰 통계 추출
# ---------------------------------------------------------------------------

def _find_first(node, pred):
    """JSON 트리를 재귀 탐색해 pred(dict)가 truthy 값을 반환하는 첫 결과를 돌려준다."""
    if isinstance(node, dict):
        r = pred(node)
        if r:
            return r
        for v in node.values():
            r = _find_first(v, pred)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_first(v, pred)
            if r:
                return r
    return None


def _extract_place_info(state: dict) -> dict:
    """Apollo 캐시에서 업체 기본 정보(SEO 보고서용)를 추출."""
    info: dict = {}
    for key, val in state.items():
        if key.startswith("PlaceDetailBase") and isinstance(val, dict):
            info["업체명"] = val.get("name") or ""
            info["카테고리"] = val.get("category") or ""
            info["주소"] = val.get("address") or ""
            info["도로명주소"] = val.get("roadAddress") or ""
            info["전화번호"] = val.get("phone") or val.get("virtualPhone") or ""
            micro = val.get("microReview")
            if isinstance(micro, list):
                info["한줄소개"] = " ".join(m for m in micro if isinstance(m, str))
            kw = val.get("keywords")
            if isinstance(kw, list):
                info["대표키워드"] = [k for k in kw if isinstance(k, str)]
            conv = val.get("conveniences")
            if isinstance(conv, list):
                info["편의시설"] = [c for c in conv if isinstance(c, str)]
            break

    def homepage_of(node):
        hp = node.get("homepages")
        if isinstance(hp, dict):
            repr_ = hp.get("repr")
            if isinstance(repr_, dict) and repr_.get("url"):
                return repr_["url"]
            etc = hp.get("etc")
            if isinstance(etc, list):
                for e in etc:
                    if isinstance(e, dict) and e.get("url"):
                        return e["url"]
        return None

    hp = _find_first(state, homepage_of)
    if hp:
        info["홈페이지"] = hp

    desc = _find_first(
        state,
        lambda n: n.get("description")
        if isinstance(n.get("description"), str) and len(n["description"]) > 5 else None,
    )
    if desc:
        info["소개"] = desc

    return {k: v for k, v in info.items() if v}


def _extract_place_extras(state: dict) -> tuple[dict, dict]:
    """홈 Apollo 캐시에서 예약/톡톡/주문/영업시간/홈페이지·SNS/사진 정보를 추출.

    반환: (업체정보에 합칠 dict, 사진통계 dict)
    """
    info: dict = {}
    photo: dict = {}

    # 톡톡 문의
    for k, v in state.items():
        if k.startswith("PlaceDetailBase") and isinstance(v, dict):
            info["톡톡문의"] = bool(v.get("talktalkUrl"))
            if v.get("talktalkUrl"):
                info["톡톡URL"] = v["talktalkUrl"]
            break

    root = state.get("ROOT_QUERY") or {}
    pd = None
    for k, v in root.items():
        if isinstance(k, str) and k.startswith("placeDetail") and isinstance(v, dict):
            pd = v
            break
    if not isinstance(pd, dict):
        return info, photo

    # 네이버 예약
    for k, v in pd.items():
        if isinstance(k, str) and k.startswith("naverBooking") and isinstance(v, dict):
            url_ = v.get("naverBookingUrl") or v.get("naverBookingHubUrl")
            info["예약가능"] = bool(url_)
            if url_:
                info["예약URL"] = url_
            break

    # 네이버 주문 (포장/테이블/배달)
    order = pd.get("naverOrder")
    if isinstance(order, dict):
        info["네이버주문"] = [
            name for key, name in (
                ("isPickup", "포장"), ("isTableOrder", "테이블주문"),
                ("isPreOrder", "미리주문"), ("isDelivery", "배달"),
            ) if order.get(key)
        ]

    if "hasCoupon" in pd:
        info["쿠폰"] = bool(pd.get("hasCoupon"))

    # 영업시간 (요일별)
    for k, v in pd.items():
        if isinstance(k, str) and k.startswith("newBusinessHours") and isinstance(v, list) and v:
            first = v[0] if isinstance(v[0], dict) else {}
            desc = first.get("businessStatusDescription")
            if isinstance(desc, dict):
                status = " · ".join(x for x in (desc.get("status"), desc.get("description")) if x)
                if status:
                    info["영업상태"] = status
            hours = []
            for h in first.get("businessHours") or []:
                if not isinstance(h, dict):
                    continue
                se = h.get("businessHours")
                t = f"{se.get('start', '')}~{se.get('end', '')}" if isinstance(se, dict) else ""
                lo = ", ".join(
                    x.get("time", "") for x in (h.get("lastOrderTimes") or []) if isinstance(x, dict)
                )
                br = ", ".join(
                    f"{b.get('start', '')}~{b.get('end', '')}"
                    for b in (h.get("breakHours") or []) if isinstance(b, dict)
                )
                hours.append({"요일": h.get("day") or "", "영업시간": t,
                              "라스트오더": lo, "브레이크타임": br})
            if hours:
                info["영업시간"] = hours
            break

    # 홈페이지 / SNS 링크 전체 (대표 + 기타)
    hp = pd.get("homepages")
    if isinstance(hp, dict):
        cands = []
        if isinstance(hp.get("repr"), dict):
            cands.append((hp["repr"], True))
        for e in hp.get("etc") or []:
            if isinstance(e, dict):
                cands.append((e, False))
        links = [
            {"유형": h.get("type") or "홈페이지", "URL": h["url"], "대표": is_rep}
            for h, is_rep in cands if h.get("url")
        ]
        if links:
            info["홈페이지목록"] = links

    # 사진 통계 + 클립(숏폼) 등록 여부
    tp = pd.get("topPhotos")
    if isinstance(tp, dict):
        if isinstance(tp.get("total"), int):
            photo["전체사진수"] = tp["total"]
        comp: dict[str, int] = {}
        has_clip = False
        for ref in tp.get("items") or []:
            item = state.get(ref["__ref"]) if isinstance(ref, dict) and "__ref" in ref else ref
            if isinstance(item, dict):
                ptype = item.get("photoType") or ""
                label = {"business": "업체", "visitor": "방문자", "clip": "클립"}.get(ptype, ptype or "기타")
                comp[label] = comp.get(label, 0) + 1
                if ptype == "clip":
                    has_clip = True
        if comp:
            photo["대표사진구성"] = comp
        photo["클립등록"] = has_clip
    vmt = pd.get("visitorReviewMediasTotal")
    if isinstance(vmt, int):
        photo["방문자등록사진수"] = vmt

    # 업체가 직접 등록한 사진 수 (사진 탭 → '업체' 카테고리의 총 개수)
    img = pd.get("images")
    if isinstance(img, dict) and isinstance(img.get("totalImages"), int):
        photo["업체등록사진수"] = img["totalImages"]

    return info, photo


def _extract_menus(state: dict) -> list:
    """Apollo 캐시에서 메뉴 목록 추출 (음식점 Menu / 미용실 등 BizItem)."""
    menus = []
    for key, val in state.items():
        if (key.startswith("Menu:") or key.startswith("BizItem:")) and isinstance(val, dict):
            name = (val.get("name") or "").strip()
            if not name:
                continue
            order = val.get("index") if isinstance(val.get("index"), int) else 9999
            menus.append((order, {
                "메뉴명": name,
                "가격": val.get("price") or "",
                "설명": (val.get("description") or "").strip(),
                "대표메뉴": bool(val.get("recommend")),
            }))
    menus.sort(key=lambda x: x[0])
    return [m for _, m in menus]


def _extract_menu_images(state: dict) -> list:
    """이미지로 등록된 메뉴판(menuImages) URL 목록. (치킨·프랜차이즈 등 이미지 메뉴)"""
    root = state.get("ROOT_QUERY") or {}
    pd = next((v for k, v in root.items()
               if isinstance(k, str) and k.startswith("placeDetail") and isinstance(v, dict)), None)
    if not isinstance(pd, dict):
        return []
    mi = pd.get("menuImages")
    if not isinstance(mi, list):
        return []
    urls = []
    for m in mi:
        if isinstance(m, dict) and m.get("imageUrl"):
            urls.append(m["imageUrl"])
    return urls


def _extract_feeds(state: dict) -> list:
    """Apollo 캐시에서 소식(공지/이벤트) 목록 추출."""
    feeds = []
    for key, val in state.items():
        if key.startswith("Feed:") and isinstance(val, dict):
            title = (val.get("title") or "").strip()
            desc = (val.get("desc") or "").strip()
            if not title and not desc:
                continue
            created = val.get("createdString") or val.get("relativeCreated") or ""
            if isinstance(created, str) and len(created) == 8 and created.isdigit():
                created = f"{created[:4]}-{created[4:6]}-{created[6:]}"
            feeds.append({
                "제목": title,
                "내용": desc,
                "분류": val.get("category") or "",
                "작성일": created,
                "고정": bool(val.get("isPinned")),
            })
    feeds.sort(key=lambda f: f["작성일"], reverse=True)
    return feeds


def _extract_stats(state: dict) -> dict:
    """Apollo 캐시에서 평균 별점 / 리뷰 수 / 키워드 리뷰 통계를 추출."""
    stats: dict = {}
    kw_counts: dict[str, int] = {}

    def walk(node):
        if isinstance(node, dict):
            score = node.get("visitorReviewsScore") or node.get("avgRating")
            if score and "평균별점" not in stats:
                stats["평균별점"] = score
            irc = node.get("imageReviewCount")
            if isinstance(irc, int) and irc > 0 and "사진리뷰수" not in stats:
                stats["사진리뷰수"] = irc
            total = node.get("visitorReviewsTotal")
            if total and "방문자리뷰수" not in stats:
                stats["방문자리뷰수"] = total
            # '이런 점이 좋았어요' 키워드 리뷰 (displayName + count)
            name, cnt = node.get("displayName"), node.get("count")
            if isinstance(name, str) and isinstance(cnt, int) and cnt > 0:
                kw_counts[name] = max(kw_counts.get(name, 0), cnt)
            # 별점 분포
            sd = node.get("starDistribution")
            if isinstance(sd, list) and sd and "별점분포" not in stats:
                dist = [
                    {"별점": s.get("score"), "개수": s.get("count")}
                    for s in sd
                    if isinstance(s, dict) and s.get("count")
                ]
                if dist:
                    stats["별점분포"] = dist
            for k, v in node.items():
                if isinstance(v, dict) and isinstance(v.get("total"), int):
                    if k.startswith("visitorReviews") and "방문자리뷰수" not in stats:
                        stats["방문자리뷰수"] = v["total"]
                    elif k.startswith("fsasReviews") and "블로그리뷰수" not in stats:
                        stats["블로그리뷰수"] = v["total"]
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(state)
    if kw_counts:
        stats["키워드리뷰"] = [
            {"키워드": n, "선택수": c}
            for n, c in sorted(kw_counts.items(), key=lambda x: -x[1])
        ]
    return stats


# ---------------------------------------------------------------------------
# 크롤러 본체
# ---------------------------------------------------------------------------

class Crawler:
    def __init__(self, log=print, stop_event: threading.Event | None = None):
        self.log = log
        self.stop_event = stop_event or threading.Event()
        self.reviews: dict[str, dict] = {}  # id → review (중복 제거)
        self.api_input: dict | None = None  # 사이트가 쓰는 리뷰 API 파라미터 (자동 학습)

    # -- 네트워크 요청에서 리뷰 API 파라미터 학습 --------------------------
    def _on_request(self, request):
        if self.api_input is not None or "graphql" not in request.url:
            return
        post = request.post_data
        if not post or "getVisitorReviews" not in post:
            return
        try:
            arr = json.loads(post)
        except Exception:
            return
        for op in (arr if isinstance(arr, list) else [arr]):
            if isinstance(op, dict) and op.get("operationName") == "getVisitorReviews":
                inp = (op.get("variables") or {}).get("input")
                if isinstance(inp, dict) and inp.get("businessId"):
                    self.api_input = inp
                    return

    # -- 네트워크 응답에서 리뷰 수집 --------------------------------------
    def _on_response(self, response):
        if "graphql" not in response.url:
            return
        try:
            data = response.json()
        except Exception:
            return
        before = len(self.reviews)
        _walk_for_reviews(data, self.reviews)
        if len(self.reviews) > before:
            self.log(f"  리뷰 {len(self.reviews)}개 수집됨...")

    # -- Apollo 캐시(SSR 데이터) 읽기 --------------------------------------
    def _get_apollo(self, page) -> dict | None:
        try:
            state = page.evaluate("() => window.__APOLLO_STATE__ || null")
        except Exception:
            return None
        return state if isinstance(state, dict) else None

    def _harvest_state(self, state: dict):
        """Apollo 캐시에서 리뷰 수집 (votedKeywords의 __ref 참조도 해석)."""
        for key, val in state.items():
            if key.startswith("VisitorReview") and isinstance(val, dict):
                r = _extract_review(val, resolve=state.get)
                if r:
                    self.reviews.setdefault(r["_id"], r)

    def _harvest_apollo(self, page):
        state = self._get_apollo(page)
        if state:
            self._harvest_state(state)

    # -- Apollo 캐시의 ROOT_QUERY 키에서 API 파라미터 추출 (요청 캡처 실패 시) --
    def _learn_api_input_from_state(self, state: dict):
        if self.api_input is not None:
            return
        root = state.get("ROOT_QUERY")
        if not isinstance(root, dict):
            return
        for key in root:
            if isinstance(key, str) and key.startswith("visitorReviews("):
                m = re.search(r"visitorReviews\((\{.*\})\)\s*$", key)
                if not m:
                    continue
                try:
                    obj = json.loads(m.group(1))
                except Exception:
                    continue
                inp = obj.get("input")
                if isinstance(inp, dict) and inp.get("businessId"):
                    self.api_input = inp
                    return

    # -- API 직접 호출로 리뷰 수집 ('더보기'가 막혔을 때) -------------------
    def _crawl_via_api(self, place_id: str, max_reviews: int) -> dict:
        """커서 기반 리뷰 API를 직접 호출해 수집. 수집한 통계(dict)를 반환."""
        if not self.api_input:
            self.api_input = {
                "businessId": place_id, "businessType": "restaurant",
                "item": "0", "isPhotoUsed": False,
                "includeContent": True, "sort": "recent",
            }
        self.log("리뷰 API 직접 호출 방식으로 전환합니다...")
        api_stats: dict = {}
        after: str | None = None
        last_cursor: str | None = None
        total: int | None = None
        fail = 0
        pages = 0
        max_pages = 2000  # 안전장치 (첫 응답의 total 확인 후 재조정)
        while len(self.reviews) < max_reviews and not self.stop_event.is_set():
            try:
                items, vr = _api_fetch_reviews(self.api_input, after)
            except Exception as e:
                fail += 1
                if fail >= 3:
                    self.log(f"  API 호출 실패: {e}")
                    break
                time.sleep(3 * fail)
                continue
            fail = 0
            if not api_stats:
                api_stats = _extract_stats(vr)
            if total is None and isinstance(vr.get("total"), int):
                total = vr["total"]
                max_pages = total // 10 + 10  # 전체 리뷰 수 기준으로 상한 조정
            if not items:
                self.log("  더 이상 리뷰가 없습니다. (마지막 페이지)")
                break
            before = len(self.reviews)
            for it in items:
                r = _extract_review(it)
                if r:
                    self.reviews.setdefault(r["_id"], r)
            if len(self.reviews) > before:
                self.log(f"  리뷰 {len(self.reviews)}개 수집됨... (API)")

            # 종료 판정: 마지막 페이지 / 커서 정체(진전 없음)
            # ※ 중복 페이지(브라우저가 이미 모은 리뷰)여도 커서는 계속 전진하므로
            #    '신규 0개'로는 끊지 않고, 커서가 멈추거나 마지막 페이지일 때만 종료.
            new_after = items[-1].get("cursor")
            if len(items) < 10:
                self.log("  더 이상 리뷰가 없습니다. (마지막 페이지)")
                break
            if not new_after or new_after == last_cursor:
                self.log("  더 이상 리뷰가 없습니다. (마지막 페이지)")
                break
            last_cursor = new_after
            after = new_after
            pages += 1
            if pages >= max_pages:
                break
            time.sleep(1.0)  # 서버 부하 방지
        return api_stats

    # -- '더보기' 버튼 클릭 (리뷰 목록 하단의 페이지네이션 버튼만) ---------
    def _click_more(self, page) -> bool:
        clicked = page.evaluate(
            """() => {
                // '리뷰 NNN' 제목을 가진 섹션(방문자 리뷰 목록)을 찾는다
                const sections = [...document.querySelectorAll('.place_section')];
                const reviewSection = sections.find(s => {
                    const h2 = s.querySelector('h2');
                    return h2 && /^리뷰\\s*[\\d,]/.test(h2.textContent.trim());
                });
                const scope = reviewSection || document;
                // 목록(li) 바깥에 있는 '더보기' 버튼 = 페이지네이션
                const btn = [...scope.querySelectorAll('a, button')].find(el =>
                    el.textContent.includes('더보기') && !el.closest('li'));
                if (btn) { btn.scrollIntoView(); btn.click(); return true; }
                return false;
            }"""
        )
        return bool(clicked)

    # -- 메인 흐름 ---------------------------------------------------------
    def crawl(self, url: str, max_reviews: int = 100) -> dict:
        from playwright.sync_api import sync_playwright

        self.log("URL 확인 중...")
        url = resolve_short_url(url.strip())
        place_id = extract_place_id(url)
        if not place_id:
            raise ValueError(
                "URL에서 플레이스 ID를 찾지 못했습니다.\n"
                "네이버 지도에서 업체 페이지를 연 뒤 주소창의 URL 또는 "
                "'공유 → URL 복사' 링크를 사용해 주세요."
            )
        self.log(f"플레이스 ID: {place_id}")

        review_url = f"https://pcmap.place.naver.com/place/{place_id}/review/visitor?reviewSort=recent"
        home_url = f"https://pcmap.place.naver.com/place/{place_id}/home"
        place_info: dict = {}
        stats: dict = {}
        photo_stats: dict = {}
        menus: list = []
        feeds: list = []
        place_name = ""

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                if "Executable doesn't exist" not in str(e):
                    raise
                if getattr(sys, "frozen", False):
                    # 패키지(exe) 실행에서는 자동 설치를 하지 않는다(함께 묶은 브라우저 사용).
                    raise RuntimeError(
                        "크로미움 브라우저를 찾지 못했습니다. 프로그램 폴더의 _internal\\pw-browsers 가 "
                        "함께 복사됐는지 확인해 주세요."
                    )
                # 크로미움 미설치 → 자동 설치 후 1회 재시도
                self.log("크로미움 브라우저가 없어 자동 설치합니다... (1~2분 소요)")
                import subprocess
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self.log("설치 완료. 다시 시도합니다...")
                browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=DESKTOP_UA,
                viewport={"width": 1280, "height": 900},
                locale="ko-KR",
            )
            page = ctx.new_page()
            page.on("request", self._on_request)
            page.on("response", self._on_response)

            # 1) 홈 화면 → 업체 기본 정보 (SEO 보고서용)
            self.log("업체 정보 수집 중...")
            try:
                page.goto(home_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                state = self._get_apollo(page)
                if state:
                    place_info = _extract_place_info(state)
                    extras, photo_stats = _extract_place_extras(state)
                    place_info.update(extras)
                    stats.update(_extract_stats(state))
            except Exception as e:
                self.log(f"  업체 정보 수집 실패 (리뷰 수집은 계속 진행): {e}")

            # 2) 메뉴·소식 수집
            #    메뉴는 menu/list 페이지가 가장 완전하고, 소식은 feed 페이지에 있으므로
            #    두 페이지 모두 방문해 각 항목의 '가장 많은' 결과를 채택한다.
            self.log("메뉴·소식 수집 중...")
            menu_images: list = []
            for sub in ("menu/list", "feed"):
                if self.stop_event.is_set():
                    break
                try:
                    page.goto(f"https://pcmap.place.naver.com/place/{place_id}/{sub}",
                              wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    state = self._get_apollo(page)
                    if state:
                        m = _extract_menus(state)
                        if len(m) > len(menus):
                            menus = m
                        f = _extract_feeds(state)
                        if len(f) > len(feeds):
                            feeds = f
                        mi = _extract_menu_images(state)
                        if len(mi) > len(menu_images):
                            menu_images = mi
                except Exception:
                    pass
                if menus and feeds:  # 둘 다 확보되면 조기 종료
                    break
            if menu_images:
                photo_stats["메뉴판이미지수"] = len(menu_images)
            self.log(f"  메뉴 {len(menus)}개 / 메뉴판이미지 {len(menu_images)}장 / 소식 {len(feeds)}건")

            # 3) 리뷰 페이지
            self.log("리뷰 페이지 여는 중...")
            page.goto(review_url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            state = self._get_apollo(page)
            if state:
                self._harvest_state(state)
                self._learn_api_input_from_state(state)
                for k, v in _extract_place_info(state).items():
                    place_info.setdefault(k, v)
                stats.update(_extract_stats(state))

            place_name = place_info.get("업체명", "")
            if not place_name or place_name == "네이버 플레이스":
                try:
                    title = page.title()
                    place_name = re.sub(r"\s*:\s*네이버.*$", "", title).strip()
                except Exception:
                    pass
            if place_name:
                self.log(f"업체명: {place_name}")
            if stats.get("평균별점"):
                self.log(f"평균 별점: {stats['평균별점']}")
            self.log(f"현재 {len(self.reviews)}개 수집됨. '더보기' 클릭 시작...")

            no_progress = 0
            use_api = False
            while len(self.reviews) < max_reviews and not self.stop_event.is_set():
                before = len(self.reviews)
                if not self._click_more(page):
                    self.log("'더보기' 버튼이 더 이상 없습니다. (마지막 페이지)")
                    break
                # 새 리뷰 로딩 대기
                page.wait_for_timeout(2000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                self._harvest_apollo(page)
                if len(self.reviews) == before:
                    # 요청이 차단됐을 수 있음 → 1회 재시도 후 API 방식으로 전환
                    no_progress += 1
                    if no_progress >= 2:
                        self.log("'더보기' 응답이 없어 다른 방법으로 전환합니다.")
                        use_api = True
                        break
                    self.log("  응답 없음. 5초 대기 후 재시도...")
                    for _ in range(10):
                        if self.stop_event.is_set():
                            break
                        time.sleep(0.5)
                else:
                    no_progress = 0
                    time.sleep(1.0)  # 서버 부하 방지 (요청 간격 유지)

            browser.close()

        # '더보기'가 막혔으면 리뷰 API 직접 호출로 이어서 수집
        if use_api and len(self.reviews) < max_reviews and not self.stop_event.is_set():
            api_stats = self._crawl_via_api(place_id, max_reviews)
            for k, v in api_stats.items():
                stats.setdefault(k, v)

        if self.stop_event.is_set():
            self.log("사용자에 의해 중지됨.")

        review_list = [
            {
                "본문": r["본문"],
                "별점": r.get("별점", ""),
                "작성일": r["작성일"],
                "방문일": r["방문일"],
                "방문차수": r.get("방문차수", ""),
                "키워드": r.get("키워드", []),
                "사장님답글": r.get("사장님답글", ""),
                "미디어수": r.get("미디어수", 0),
                "리뷰출처": r.get("리뷰출처", ""),
            }
            for r in self.reviews.values()
        ][:max_reviews]

        # 답글율 / 영수증 리뷰 비중 (수집한 리뷰 기준)
        if review_list:
            n = len(review_list)
            replied = sum(1 for r in review_list if r["사장님답글"])
            stats["답글수_수집리뷰중"] = replied
            stats["답글율_수집리뷰중"] = f"{replied / n * 100:.1f}%"
            receipt = sum(
                1 for r in review_list
                if "영수증" in str(r["리뷰출처"]) or "receipt" in str(r["리뷰출처"]).lower()
            )
            stats["영수증리뷰수_수집리뷰중"] = receipt
            stats["영수증리뷰비중_수집리뷰중"] = f"{receipt / n * 100:.1f}%"
            with_media = sum(1 for r in review_list if r["미디어수"])
            stats["사진첨부리뷰수_수집리뷰중"] = with_media

        place_info.pop("업체명", None)  # 최상위 '업체명'과 중복 방지

        return {
            "업체명": place_name,
            "플레이스ID": place_id,
            "URL": url,
            "수집일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "업체정보": place_info,
            "리뷰통계": stats,
            "사진통계": photo_stats,
            "메뉴": menus,
            "소식통계": {
                "소식수_수집기준": len(feeds),
                "최근소식일": feeds[0]["작성일"] if feeds else "",
            },
            "소식": feeds,
            "리뷰수": len(review_list),
            "리뷰": review_list,
        }


def save_json(result: dict, out_dir: Path, prefix: str = "리뷰") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = result.get("업체명") or result.get("플레이스ID") or "reviews"
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{prefix}_{safe}_{stamp}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    # ---- 색상 팔레트 (모던 라이트 테마) ----
    BG = "#F2F4F7"            # 창 배경
    CARD = "#FFFFFF"          # 입력 카드
    FIELD = "#F7F9FB"         # 입력 필드
    ACCENT = "#03C75A"        # 포인트 (네이버 그린)
    ACCENT_HOVER = "#02B152"
    STOP = "#FF6B6B"
    STOP_HOVER = "#E85B5B"
    NEUTRAL = "#EEF1F5"
    NEUTRAL_HOVER = "#E2E6EC"
    TEXT = "#1B1F27"
    SUB = "#8B95A1"
    BORDER = "#E4E8EE"
    LOG_BG = "#20242E"
    LOG_FG = "#D9E0EA"
    DISABLED = "#C9CED6"
    FONT = "맑은 고딕"

    root = tk.Tk()
    root.title("네이버 플레이스 리뷰 수집기")
    root.geometry("640x640")
    root.minsize(560, 520)
    root.configure(bg=BG)

    log_q: queue.Queue[str] = queue.Queue()
    stop_event = threading.Event()
    state = {"running": False}

    # ---- 정보 다이얼로그 ----
    def show_about():
        win = tk.Toplevel(root)
        win.title("프로그램 정보")
        win.configure(bg=CARD)
        win.resizable(False, False)
        win.transient(root)
        win.grab_set()

        body = tk.Frame(win, bg=CARD)
        body.pack(padx=36, pady=26)
        tk.Label(body, text="네이버 플레이스 리뷰 수집기", bg=CARD, fg=TEXT,
                 font=(FONT, 12, "bold")).pack()
        tk.Label(body, text=f"버전 v{VERSION}", bg=CARD, fg=SUB,
                 font=(FONT, 9)).pack(pady=(4, 14))
        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(0, 14))
        tk.Label(body, text="AI지원센터", bg=CARD, fg=ACCENT,
                 font=(FONT, 12, "bold")).pack()
        tk.Label(body,
                 text="소상공인의 온라인 마케팅을 돕는 AI 활용 지원 센터입니다.\n"
                      "네이버 플레이스 리뷰 수집·분석, 블로그 마케팅 등\n"
                      "AI 기반 마케팅 도구를 제공합니다.",
                 bg=CARD, fg=TEXT, font=(FONT, 9), justify="center").pack(pady=(8, 12))
        tk.Label(body, text="문의: kchobjt@gmail.com", bg=CARD, fg=SUB,
                 font=(FONT, 9)).pack()
        tk.Label(body, text="© 2026 AI지원센터. All rights reserved.", bg=CARD, fg=SUB,
                 font=(FONT, 8)).pack(pady=(3, 18))
        tk.Button(body, text="닫기", command=win.destroy, relief="flat", bd=0,
                  bg=NEUTRAL, fg=TEXT, activebackground=NEUTRAL_HOVER,
                  activeforeground=TEXT, cursor="hand2", font=(FONT, 9),
                  padx=28, pady=6).pack()

        # 메인 창 중앙에 배치
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        x = root.winfo_x() + (root.winfo_width() - w) // 2
        y = root.winfo_y() + (root.winfo_height() - h) // 3
        win.geometry(f"+{x}+{y}")

    # ---- 헤더 ----
    header = tk.Frame(root, bg=BG)
    header.pack(fill="x", padx=24, pady=(22, 14))

    title_area = tk.Frame(header, bg=BG)
    title_area.pack(side="left", fill="x", expand=True)
    tk.Label(title_area, text="네이버 플레이스 리뷰 수집기", bg=BG, fg=TEXT,
             font=(FONT, 15, "bold")).pack(anchor="w")
    tk.Label(title_area, text="플레이스 URL을 입력하면 방문자 리뷰를 JSON 파일로 저장합니다.",
             bg=BG, fg=SUB, font=(FONT, 9)).pack(anchor="w", pady=(3, 0))

    meta_area = tk.Frame(header, bg=BG)
    meta_area.pack(side="right", anchor="n")
    tk.Label(meta_area, text=f"v{VERSION}", bg=BG, fg=SUB,
             font=(FONT, 9)).pack(side="left", padx=(0, 8), pady=(3, 0))
    tk.Button(meta_area, text="정보", command=show_about, relief="flat", bd=0,
              bg=NEUTRAL, fg=TEXT, activebackground=NEUTRAL_HOVER,
              activeforeground=TEXT, cursor="hand2", font=(FONT, 9),
              padx=14, pady=4).pack(side="left")

    # ---- 입력 카드 ----
    card = tk.Frame(root, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    card.pack(fill="x", padx=24)
    inner = tk.Frame(card, bg=CARD)
    inner.pack(fill="x", padx=20, pady=18)
    inner.columnconfigure(1, weight=1)

    def field_label(row: int, text: str):
        tk.Label(inner, text=text, bg=CARD, fg=SUB, font=(FONT, 9, "bold"))\
            .grid(row=row, column=0, sticky="w", padx=(0, 16), pady=7)

    def field_entry(var: tk.StringVar) -> tk.Entry:
        return tk.Entry(inner, textvariable=var, relief="flat", bg=FIELD, fg=TEXT,
                        insertbackground=TEXT, font=(FONT, 10),
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=ACCENT)

    field_label(0, "플레이스 URL")
    url_var = tk.StringVar()
    url_entry = field_entry(url_var)
    url_entry.grid(row=0, column=1, columnspan=2, sticky="ew", ipady=6, pady=7)

    field_label(1, "최대 리뷰 수")
    max_var = tk.StringVar(value="100")
    max_spin = tk.Spinbox(inner, from_=10, to=5000, increment=50, textvariable=max_var,
                          width=8, relief="flat", bg=FIELD, fg=TEXT, font=(FONT, 10),
                          highlightthickness=1, highlightbackground=BORDER,
                          highlightcolor=ACCENT, buttonbackground=NEUTRAL)
    max_spin.grid(row=1, column=1, sticky="w", ipady=4, pady=7)

    field_label(2, "저장 폴더")
    dir_var = tk.StringVar(value=str(Path(__file__).parent / "review"))
    dir_entry = field_entry(dir_var)
    dir_entry.grid(row=2, column=1, sticky="ew", ipady=6, pady=7)

    def pick_dir():
        d = filedialog.askdirectory(initialdir=dir_var.get())
        if d:
            dir_var.set(d)

    browse_btn = tk.Button(inner, text="찾아보기", command=pick_dir, relief="flat", bd=0,
                           bg=NEUTRAL, fg=TEXT, activebackground=NEUTRAL_HOVER,
                           activeforeground=TEXT, cursor="hand2", font=(FONT, 9),
                           padx=14, pady=5)
    browse_btn.grid(row=2, column=2, padx=(8, 0))

    # ---- 실행 버튼 ----
    btns = tk.Frame(root, bg=BG)
    btns.pack(fill="x", padx=24, pady=(14, 0))

    def flat_button(parent, text, bg, hover, fg="#FFFFFF"):
        b = tk.Button(parent, text=text, bg=bg, fg=fg, relief="flat", bd=0,
                      activebackground=hover, activeforeground=fg, cursor="hand2",
                      font=(FONT, 10, "bold"), padx=26, pady=9,
                      disabledforeground="#FFFFFF")
        b.normal_bg, b.hover_bg = bg, hover

        def on_enter(_):
            if b["state"] == "normal":
                b.config(bg=b.hover_bg)

        def on_leave(_):
            b.config(bg=b.normal_bg if b["state"] == "normal" else DISABLED)

        b.bind("<Enter>", on_enter)
        b.bind("<Leave>", on_leave)
        return b

    start_btn = flat_button(btns, "수집 시작", ACCENT, ACCENT_HOVER)
    comp_btn = flat_button(btns, "경쟁사 수집", "#F59E0B", "#DE8E06")
    stop_btn = flat_button(btns, "중지", STOP, STOP_HOVER)
    start_btn.pack(side="left")
    comp_btn.pack(side="left", padx=(10, 0))
    stop_btn.pack(side="left", padx=(10, 0))

    def open_prompt_generator():
        import webbrowser
        webbrowser.open(PROMPT_GENERATOR_URL)

    prompt_btn = flat_button(btns, "프롬프트 생성기 ↗", "#4A6CF7", "#3D5CE0")
    prompt_btn.config(command=open_prompt_generator)
    prompt_btn.pack(side="right")

    def set_running(running: bool):
        state["running"] = running
        if running:
            # 동시 작업 방지: 진행 중에는 두 수집 버튼 모두 비활성화
            start_btn.config(state="disabled", bg=DISABLED)
            comp_btn.config(state="disabled", bg=DISABLED)
            stop_btn.config(state="normal", bg=stop_btn.normal_bg)
        else:
            start_btn.config(state="normal", bg=start_btn.normal_bg)
            comp_btn.config(state="normal", bg=comp_btn.normal_bg)
            stop_btn.config(state="disabled", bg=DISABLED)

    # ---- 진행 로그 ----
    log_area = tk.Frame(root, bg=BG)
    log_area.pack(fill="both", expand=True, padx=24, pady=(16, 22))
    tk.Label(log_area, text="진행 로그", bg=BG, fg=SUB, font=(FONT, 9, "bold")).pack(anchor="w")
    log_wrap = tk.Frame(log_area, bg=LOG_BG)
    log_wrap.pack(fill="both", expand=True, pady=(6, 0))
    log_box = tk.Text(log_wrap, bg=LOG_BG, fg=LOG_FG, relief="flat", state="disabled",
                      font=("Consolas", 9), padx=14, pady=12, wrap="word",
                      insertbackground=LOG_FG, selectbackground="#3A4150")
    scroll = ttk.Scrollbar(log_wrap, command=log_box.yview)
    log_box.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    log_box.pack(side="left", fill="both", expand=True)

    def log(msg: str):
        log_q.put(msg)

    def poll_log():
        try:
            while True:
                msg = log_q.get_nowait()
                log_box.configure(state="normal")
                log_box.insert("end", msg + "\n")
                log_box.see("end")
                log_box.configure(state="disabled")
        except queue.Empty:
            pass
        root.after(150, poll_log)

    def worker(url: str, max_n: int, out_dir: Path, competitor: bool):
        try:
            crawler = Crawler(log=log, stop_event=stop_event)
            result = crawler.crawl(url, max_n)
            if result["리뷰수"] == 0:
                log("수집된 리뷰가 없습니다. URL을 확인해 주세요.")
            else:
                result = {"구분": "경쟁사" if competitor else "본업체", **result}
                prefix = "경쟁사리뷰" if competitor else "리뷰"
                path = save_json(result, out_dir, prefix=prefix)
                log(f"완료! 리뷰 {result['리뷰수']}개 저장:")
                log(f"  {path}")
        except Exception as e:
            log(f"오류: {e}")
        finally:
            root.after(0, lambda: set_running(False))

    def on_start(competitor: bool = False):
        if state["running"]:
            return  # 동시 작업 방지
        url = url_var.get().strip()
        if not url:
            messagebox.showwarning("입력 필요", "플레이스 URL을 입력해 주세요.")
            return
        try:
            max_n = max(1, int(max_var.get()))
        except ValueError:
            messagebox.showwarning("입력 오류", "최대 리뷰 수는 숫자여야 합니다.")
            return
        out_dir = Path(dir_var.get())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            messagebox.showwarning("경로 오류", "저장 폴더를 만들 수 없습니다. 경로를 확인해 주세요.")
            return
        stop_event.clear()
        set_running(True)
        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        log_box.configure(state="disabled")
        if competitor:
            log("[경쟁사 수집 모드]")
        threading.Thread(target=worker, args=(url, max_n, out_dir, competitor), daemon=True).start()

    def on_stop():
        stop_event.set()
        log("중지 요청됨... 잠시 기다려 주세요.")

    start_btn.config(command=lambda: on_start(False))
    comp_btn.config(command=lambda: on_start(True))
    stop_btn.config(command=on_stop)
    set_running(False)
    url_entry.focus()
    poll_log()
    root.mainloop()


# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--cli":
        url = sys.argv[2]
        max_n = int(sys.argv[3]) if len(sys.argv) >= 4 else 50
        crawler = Crawler()
        result = crawler.crawl(url, max_n)
        path = save_json(result, Path(__file__).parent / "review")
        print(f"저장: {path} (리뷰 {result['리뷰수']}개)")
    else:
        run_gui()


if __name__ == "__main__":
    main()
