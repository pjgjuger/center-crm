# -*- coding: utf-8 -*-
"""
센터 고객 CRM — 플레이스 자동 수집 통합판
- 옵시디언 볼트의 고객 .md 카드를 직접 읽고 쓰는 CRM 화면(crm_ui.html)을
  pywebview 데스크톱 창으로 띄우고, 파일 입출력과 리뷰 수집을 파이썬에서 처리합니다.
- 고객 카드에 '플레이스 URL'을 넣고 [플레이스에서 자동 채우기]를 누르면
  naver_review_crawler.Crawler 가 업체 정보·통계·리뷰를 수집해
  상호/업종/지역/소개를 자동으로 채우고, 카드 본문에
  '## 플레이스 진단' 요약과 '## 플레이스 리뷰'(수집한 리뷰)를 넣어 줍니다.
- 수집 원본(JSON)은 기존 리뷰수집기와 같은 review 폴더에도 보관됩니다.

사용법: python crm_app.py        (GUI 실행)
       python crm_app.py --selftest  (파이썬 로직만 점검, 창 없이)
"""

import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

import naver_review_crawler as core
import form_sync
import place_lookup

# 일반 실행(.py)과 패키지 실행(PyInstaller exe) 모두 지원
FROZEN = getattr(sys, "frozen", False)
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))  # 읽기 전용 번들 자원(html/js/브라우저)
APPDIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent  # 쓰기 가능(설정·보고서, exe 옆)
HERE = BUNDLE
UI_FILE = BUNDLE / "crm_ui.html"
CONFIG = APPDIR / "crm_config.json"
REVIEW_DIR = APPDIR / "review"

# 패키지 실행 시: 함께 넣은 크로미움 브라우저를 쓰도록 경로 지정(파이썬 설치 없이 동작)
if FROZEN:
    _pw = BUNDLE / "pw-browsers"
    if _pw.is_dir():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_pw))

VERSION = "1.0.0"

STATES = ["발굴", "상담", "등록", "관리중", "보류"]
# 머리말(프런트매터) 키 순서 — 기존 CRM.html 서식과 호환되게 앞쪽은 동일하게 둔다.
KEYORDER = [
    "구분", "상호", "업종", "지역", "연락처", "이메일주소", "담당", "상태", "최근접촉",
    "다음할일", "다음날짜", "진단점수", "플레이스",
    "플레이스ID", "평균별점", "방문자리뷰수", "블로그리뷰수", "리뷰수집일", "리뷰파일", "등록일",
    "SEO차수", "SEO발행일", "다음발행예정", "KT상품",
]

# KT 통신상품 가입자 — 접수부터 개통까지 이력 관리(고객 CRM 과 분리)
# 상품에 따라 개통 단계가 갈린다:
#  - 하이오더: 개통을 '사전개통 → 본개통' 두 단계로 구분
#  - 인터넷·TV·전화 등: 단일 '개통' (개통일만 기록)
KT_PRODUCTS = ["하이오더", "인터넷", "TV", "모바일", "유심", "전화", "인터넷+TV", "인터넷+TV+전화"]
KT_STAGES_DEFAULT = ["접수", "서류확인", "설치예약", "개통", "완료"]
KT_STAGES_HIORDER = ["접수", "서류확인", "설치예약", "사전개통", "본개통", "완료"]
KT_STATES = KT_STAGES_DEFAULT
KT_STATES_ALL = ["접수", "서류확인", "설치예약", "개통", "사전개통", "본개통", "완료", "보류", "취소"]
KT_KEYORDER = [
    "구분", "상호", "상품", "지역", "담당", "상태",
    "접수번호", "접수일", "개통일", "사전개통일", "본개통일", "다음할일", "다음날짜", "등록일",
]

BAD_NAME = re.compile(r'[\\/:*?"<>|]')
PII = re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}|[\w.+-]+@[\w-]+\.[\w.]+")


def validate_store_fields(data):
    """설문 매장 정보는 한 줄로 저장하고, 선택 입력인 연락 정보를 검사한다."""
    for key in ("상호", "지역", "업종", "연락처", "이메일주소"):
        value = data.get(key) or ""
        if not isinstance(value, str) or any(c in value for c in ("\r", "\n", "\x00")):
            return f"「{key}」는 한 줄로 입력해 주세요."
    phone = (data.get("연락처") or "").strip()
    if phone and not re.fullmatch(r"\+?[0-9() .-]{7,30}", phone):
        return "연락처는 숫자와 +, -, 괄호, 공백으로 입력해 주세요."
    email = (data.get("이메일주소") or "").strip()
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return "이메일주소 형식을 확인해 주세요."
    return None


# ---------------------------------------------------------------------------
# 머리말(프런트매터) 읽기 / 쓰기  — 한 줄짜리 '키: 값'
# ---------------------------------------------------------------------------

def parse_card(text: str):
    """.md 텍스트에서 (머리말 dict, 본문 str, 머리말있음 bool) 반환."""
    m = re.match(r"^﻿?---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        return {}, text, False
    fm = {}
    for line in m.group(1).splitlines():
        k = re.match(r"^([^:#\s][^:]*):\s?(.*)$", line)
        if k:
            fm[k.group(1).strip()] = k.group(2).strip()
    return fm, text[m.end():], True


def build_card(fm: dict, body: str, order: list = None) -> str:
    order = order or KEYORDER
    keys = [k for k in order if k in fm] + [k for k in fm if k not in order]
    lines = [f"{k}: {'' if fm.get(k) is None else fm[k]}" for k in keys]
    return "---\n" + "\n".join(lines) + "\n---\n" + body


# ---------------------------------------------------------------------------
# 수집 결과 → 카드에 쓸 값 다듬기
# ---------------------------------------------------------------------------

def category_short(category: str) -> str:
    """'돈까스,우동' / '한식>국밥' 같은 카테고리에서 대표 업종 한 개만."""
    if not category:
        return ""
    first = re.split(r"[,/>·|]", category)[0]
    return first.strip()


def region_from_address(addr: str, road: str = "") -> str:
    """주소에서 '구리 인창동'처럼 시·군·구 + 읍·면·동 을 뽑는다(최선노력)."""
    for src in (addr, road):
        if not src:
            continue
        toks = src.split()
        city = next((t for t in toks if re.search(r"(시|군|구)$", t) and not t.endswith("특별시")
                     and not t.endswith("광역시") and not t.endswith("도")), "")
        if not city:
            city = next((t for t in toks if re.search(r"(시|군|구)$", t)), "")
        dong = next((t for t in toks if re.search(r"(동|읍|면|가|리)$", t)
                     and not re.search(r"(시|군|구|도)$", t)), "")
        city = re.sub(r"(특별시|광역시)$", "", city)
        city = re.sub(r"시$", "", city) if city.endswith("시") else city
        parts = [p for p in (city, dong) if p]
        if parts:
            return " ".join(parts)
    return ""


def _fmt_int(v) -> str:
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def build_diagnosis(result: dict) -> str:
    """수집 결과에서 '## 플레이스 진단' 본문(여러 줄 '- ...')을 만든다."""
    info = result.get("업체정보", {}) or {}
    stats = result.get("리뷰통계", {}) or {}
    photo = result.get("사진통계", {}) or {}
    lines = []

    star = stats.get("평균별점")
    rv = stats.get("방문자리뷰수")
    blog = stats.get("블로그리뷰수")
    if star or rv:
        extra = []
        if rv:
            extra.append(f"방문자 {_fmt_int(rv)}")
        if blog:
            extra.append(f"블로그 {_fmt_int(blog)}")
        tail = f" ({' · '.join(extra)})" if extra else ""
        head = f"평균 별점 {star}" if star else "평균 별점 –"
        lines.append(f"- {head}{tail}")

    if stats.get("답글율_수집리뷰중"):
        lines.append(f"- 사장님 답글율 {stats['답글율_수집리뷰중']} (수집 {result.get('리뷰수', 0)}개 기준)")

    kws = stats.get("키워드리뷰") or []
    if kws:
        top = " · ".join(k.get("키워드", "") for k in kws[:5] if k.get("키워드"))
        if top:
            lines.append(f"- 대표 키워드: {top}")

    ph = []
    if photo.get("업체등록사진수") is not None:
        ph.append(f"업체 {_fmt_int(photo['업체등록사진수'])}")
    if photo.get("방문자등록사진수") is not None:
        ph.append(f"방문자 {_fmt_int(photo['방문자등록사진수'])}")
    if ph:
        clip = " · 클립 있음" if photo.get("클립등록") else ""
        lines.append(f"- 사진: {' / '.join(ph)}{clip}")

    chan = []
    if info.get("예약가능"):
        chan.append("예약")
    order = info.get("네이버주문") or []
    if order:
        chan.append("/".join(order))
    if info.get("톡톡문의"):
        chan.append("톡톡문의")
    if info.get("쿠폰"):
        chan.append("쿠폰")
    if chan:
        lines.append(f"- 채널: {' · '.join(chan)}")

    if info.get("영업상태"):
        lines.append(f"- 영업: {info['영업상태']}")

    menus = result.get("메뉴") or []
    if menus:
        names = " · ".join(m.get("메뉴명", "") for m in menus[:5] if m.get("메뉴명"))
        if names:
            lines.append(f"- 메뉴: {names}" + (" …" if len(menus) > 5 else ""))

    lines.append(f"- 수집일: {result.get('수집일시', '')[:10]} · 수집 리뷰 {result.get('리뷰수', 0)}개")
    return "\n".join(lines)


def _clean_line(t: str) -> str:
    """리뷰 본문을 한 줄로 — 줄바꿈/마크다운 깨짐 방지."""
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    t = t.replace("###", "#").lstrip("#-> ").strip()
    return t


def build_reviews_md(result: dict, cap: int = 100) -> str:
    """수집 리뷰를 '## 플레이스 리뷰' 본문 마크다운으로 만든다."""
    reviews = result.get("리뷰") or []
    star = result.get("리뷰통계", {}).get("평균별점", "")
    head = (f"<!-- 수집 {result.get('수집일시','')[:10]} · {len(reviews)}개"
            + (f" · 평균 {star}" if star else "") + " -->")
    blocks = [head, ""]
    for r in reviews[:cap]:
        s = str(r.get("별점", "")).strip()
        stars = "★" * int(float(s)) if re.match(r"^\d", s) else ""
        date = (r.get("작성일") or r.get("방문일") or "").strip()
        visit = r.get("방문차수")
        htitle = " · ".join(x for x in (stars or f"별점 {s}" if s else "", date,
                                        (f"{visit}" if visit else "")) if x)
        blocks.append(f"### {htitle or '리뷰'}")
        body = _clean_line(r.get("본문", ""))
        if body:
            blocks.append(body)
        kws = r.get("키워드") or []
        if kws:
            blocks.append("- 키워드: " + " · ".join(kws))
        reply = _clean_line(r.get("사장님답글", ""))
        if reply:
            blocks.append("- 답글: " + reply)
        blocks.append("")
    return "\n".join(blocks).strip() + "\n"


def collect_payload(result: dict) -> dict:
    """수집 결과를 UI(폼 자동채움 + 미리보기)에 넘길 형태로 요약."""
    info = result.get("업체정보", {}) or {}
    stats = result.get("리뷰통계", {}) or {}
    photo = result.get("사진통계", {}) or {}
    intro = info.get("한줄소개") or info.get("소개") or ""
    region = region_from_address(info.get("주소", ""), info.get("도로명주소", ""))
    reviews = result.get("리뷰") or []
    preview = [
        {
            "별점": r.get("별점", ""),
            "작성일": r.get("작성일") or r.get("방문일") or "",
            "본문": _clean_line(r.get("본문", "")),
            "키워드": r.get("키워드") or [],
            "답글": bool(_clean_line(r.get("사장님답글", ""))),
        }
        for r in reviews
    ]
    return {
        "업체명": result.get("업체명", ""),
        "플레이스ID": result.get("플레이스ID", ""),
        "URL": result.get("URL", ""),
        "업종": category_short(info.get("카테고리", "")),
        "지역": region,
        "소개": intro,
        "주소": info.get("도로명주소") or info.get("주소", ""),
        "평균별점": stats.get("평균별점", ""),
        "방문자리뷰수": stats.get("방문자리뷰수", ""),
        "블로그리뷰수": stats.get("블로그리뷰수", ""),
        "답글율": stats.get("답글율_수집리뷰중", ""),
        "사진": photo,
        "리뷰수": len(reviews),
        "리뷰미리보기": preview[:40],
        "진단": build_diagnosis(result),
        "리뷰본문": build_reviews_md(result),
    }


# ---------------------------------------------------------------------------
# 카드 본문 조립 / 수정
# ---------------------------------------------------------------------------

SECTION_ORDER = ["이 집은 어떤 집인가", "플레이스 진단", "지금 상태", "오간 이야기", "플레이스 리뷰", "메모"]


def split_sections(body: str) -> dict:
    out = {}
    for b in re.split(r"\n(?=## )", body):
        m = re.match(r"^## ([^\n]+)\r?\n?([\s\S]*)$", b)
        if m:
            out[m.group(1).strip()] = m.group(2).rstrip()
    return out


def assemble_body(title: str, secs: dict) -> str:
    parts = [f"\n# {title}\n"]
    for name in SECTION_ORDER:
        if name in secs:
            parts.append(f"## {name}\n{secs[name].strip()}\n")
    # 알 수 없는 섹션은 뒤에 보존
    for name, val in secs.items():
        if name not in SECTION_ORDER:
            parts.append(f"## {name}\n{val.strip()}\n")
    return "\n".join(parts).rstrip() + "\n"


def apply_collection_to_body(body: str, title: str, payload: dict) -> str:
    """기존 본문에 진단/리뷰 섹션을 넣거나 교체한다."""
    secs = split_sections(body)
    if "이 집은 어떤 집인가" not in secs and payload.get("소개"):
        secs["이 집은 어떤 집인가"] = payload["소개"]
    secs["플레이스 진단"] = payload.get("진단", "")
    secs["플레이스 리뷰"] = payload.get("리뷰본문", "")
    secs.setdefault("지금 상태", "- 플레이스 진단 참고")
    secs.setdefault("오간 이야기", "")
    secs.setdefault("메모", "")
    return assemble_body(title or "고객", secs)


# ---------------------------------------------------------------------------
# pywebview 백엔드 API
# ---------------------------------------------------------------------------

class Api:
    def __init__(self):
        self._window = None
        self.stop_event = threading.Event()
        self.running = False
        self.review_dir = REVIEW_DIR  # 수집 원본 JSON 보관 폴더(볼트 지정 시 그 안으로 바뀜)
        self.kt_dir = None            # KT 가입자 .md 폴더(볼트 지정 시 작업폴더/KT가입자)
        self._form_lock = threading.Lock()

    # ---- Python → JS ----
    def _js(self, fn: str, *args):
        if not self._window:
            return
        payload = ",".join(json.dumps(a, ensure_ascii=False) for a in args)
        try:
            self._window.evaluate_js(f"window.CRM&&CRM.{fn}&&CRM.{fn}({payload})")
        except Exception:
            pass

    # ---- 설정 / 폴더 ----
    def get_info(self):
        cfg = self._load_config()
        root = self._root_from_cfg(cfg)
        if cfg.get("review") and Path(cfg["review"]).is_dir():
            self.review_dir = Path(cfg["review"])
        elif root:
            try:
                rv = root / "review"
                rv.mkdir(parents=True, exist_ok=True)
                self.review_dir = rv
                cfg["review"] = str(rv)
                self._save_config(cfg)
            except OSError:
                pass
        self._ktdir()  # KT가입자 폴더 보정(구버전 설정이면 여기서 생성·저장)
        return {
            "version": VERSION, "states": STATES, "kt_states": KT_STATES_ALL,
            "kt_products": KT_PRODUCTS,
            "kt_stages_default": KT_STAGES_DEFAULT, "kt_stages_hiorder": KT_STAGES_HIORDER,
            "vault": cfg.get("vault", ""), "workspace": cfg.get("workspace", ""),
        }

    def _load_config(self) -> dict:
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_config(self, cfg: dict):
        try:
            CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def pick_vault(self):
        import webview
        folder = getattr(webview, "FOLDER_DIALOG", None)
        if folder is None:
            folder = webview.FileDialog.FOLDER
        try:
            res = self._window.create_file_dialog(folder)
        except Exception:
            return {"ok": False}
        if not res:
            return {"ok": False}
        path = res[0] if isinstance(res, (list, tuple)) else str(res)
        return self.set_vault(path)

    def set_vault(self, path):
        """폴더를 지정하면 그 안에 관리 폴더(고객/·review/)를 데이터베이스처럼 만든다.

        - 고른 폴더에 .md 카드가 바로 있으면 그 폴더를 고객 폴더로 그대로 쓴다.
        - '고객' 하위 폴더가 이미 있으면 그걸 쓴다.
        - 둘 다 아니면 고른 폴더를 작업 폴더로 삼아 그 안에 '고객' 폴더를 새로 만든다.
        - 어느 경우든 작업 폴더 밑에 수집 원본용 'review' 폴더를 만들어 둔다.
        """
        if self._form_lock.locked():
            return {"ok": False, "error": "설문 응답을 가져오는 중입니다. 완료 후 폴더를 변경해 주세요."}
        p = Path(path)
        if not p.is_dir():
            return {"ok": False, "error": "폴더를 찾을 수 없습니다."}

        created = []
        if any(p.glob("*.md")):            # 이미 카드가 있는 폴더를 바로 지정한 경우
            vault, root = p, p
        else:
            existing = next((p / s for s in ("고객", "customers", "Customers")
                             if (p / s).is_dir()), None)
            root = p
            if existing:
                vault = existing
            else:
                vault = p / "고객"
                vault.mkdir(parents=True, exist_ok=True)
                created.append("고객")

        review = root / "review"
        if not review.is_dir():
            review.mkdir(parents=True, exist_ok=True)
            created.append("review")
        self.review_dir = review

        kt = root / "KT가입자"
        if not kt.is_dir():
            kt.mkdir(parents=True, exist_ok=True)
            created.append("KT가입자")
        self.kt_dir = kt

        cfg = self._load_config()
        cfg["vault"] = str(vault)
        cfg["workspace"] = str(root)
        cfg["review"] = str(review)
        cfg["kt"] = str(kt)
        self._save_config(cfg)
        return {"ok": True, "vault": str(vault), "workspace": str(root),
                "created": created, "cards": self.list_cards(), "kt": self.list_kt()}

    def open_vault(self):
        cfg = self._load_config()
        v = cfg.get("vault")
        if v and Path(v).is_dir():
            try:
                os.startfile(v)  # noqa: S606 (Windows 탐색기)
                return True
            except OSError:
                return False
        return False

    # ---- 카드 읽기/쓰기 ----
    def _vault(self) -> Path | None:
        v = self._load_config().get("vault")
        return Path(v) if v and Path(v).is_dir() else None

    def list_cards(self):
        v = self._vault()
        if not v:
            return []
        cards = []
        for f in sorted(v.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            fm, body, ok = parse_card(text)
            if not ok:
                continue
            if fm.get("구분") and fm["구분"] != "고객":
                continue
            cards.append({"name": f.name, "fm": fm, "body": body})
        cards.sort(key=lambda c: c["fm"].get("상호") or c["name"])
        return cards

    def read_card(self, name):
        v = self._vault()
        if not v:
            return None
        f = v / name
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            return None
        fm, body, _ = parse_card(text)
        return {"name": name, "fm": fm, "body": body}

    def _card_path(self, name):
        root = self._vault()
        if not root or not isinstance(name, str) or Path(name).name != name or not name.lower().endswith(".md"):
            return None
        path = root / name
        if path.is_symlink() or path.resolve().parent != root.resolve():
            return None
        return path

    def list_deleted_cards(self):
        root = self._vault()
        if not root:
            return []
        if (root / ".crm-trash").is_symlink():
            return []
        out = []
        for folder in sorted((root / ".crm-trash").glob("*"), reverse=True):
            if not re.fullmatch(r"\d{14}_[0-9a-f]{32}", folder.name) or folder.is_symlink():
                continue
            for path in folder.glob("*.md"):
                if path.is_symlink():
                    continue
                try:
                    fm, _, _ = parse_card(path.read_text(encoding="utf-8"))
                    out.append({"id": folder.name, "name": path.name, "fm": fm,
                                "deleted_at": datetime.strptime(folder.name[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")})
                except (OSError, ValueError):
                    continue
        return out

    def delete_card(self, name):
        if not self._form_lock.acquire(blocking=False):
            return {"ok": False, "error": "설문 처리 중입니다. 잠시 후 다시 삭제해 주세요."}
        try:
            source = self._card_path(name)
            if not source or not source.is_file():
                return {"ok": False, "error": "삭제할 고객 카드를 찾지 못했습니다."}
            token = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex
            trash = source.parent / ".crm-trash"
            if trash.is_symlink():
                return {"ok": False, "error": "휴지통 경로를 확인해 주세요."}
            folder = trash / token
            folder.mkdir(parents=True)
            source.rename(folder / source.name)
            return {"ok": True, "id": token}
        except OSError:
            return {"ok": False, "error": "삭제하지 못했습니다. 파일 사용 여부와 폴더 권한을 확인해 주세요."}
        finally:
            self._form_lock.release()

    def restore_card(self, token):
        if not self._form_lock.acquire(blocking=False):
            return {"ok": False, "error": "설문 처리 중입니다. 잠시 후 다시 복구해 주세요."}
        try:
            entry = next((c for c in self.list_deleted_cards() if c["id"] == token), None)
            if not entry:
                return {"ok": False, "error": "복구할 카드를 찾지 못했습니다."}
            target = self._card_path(entry["name"])
            if not target or target.exists():
                return {"ok": False, "error": "같은 이름의 카드가 있어 복구할 수 없습니다. 기존 카드 이름을 먼저 변경해 주세요."}
            source = target.parent / ".crm-trash" / token / entry["name"]
            source.rename(target)
            return {"ok": True, "name": entry["name"]}
        except OSError:
            return {"ok": False, "error": "복구하지 못했습니다. 폴더 권한을 확인해 주세요."}
        finally:
            self._form_lock.release()

    def save_card(self, name, fm, body):
        v = self._vault()
        if not v:
            return {"ok": False, "error": "볼트 폴더가 설정되지 않았습니다."}
        path = self._card_path(name)
        if not path or not path.is_file():
            return {"ok": False, "error": "카드가 삭제되었거나 이동되었습니다. 목록을 다시 읽어 주세요."}
        error = validate_store_fields(fm)
        if error:
            return {"ok": False, "error": error}
        try:
            path.write_text(build_card(fm, body), encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": f"저장 실패: {e}"}
        return {"ok": True}

    def find_card_place(self, name, force=False):
        card = self.read_card(name) if self._card_path(name) else None
        if not card:
            return {"ok": False, "error": "카드를 찾지 못했습니다."}
        fm = card["fm"]
        if fm.get("플레이스") and not force:
            return {"ok": True, "existing": fm["플레이스"]}
        if str(fm.get("플레이스ID", "")).isdigit() and not force:
            ident = str(fm["플레이스ID"])
            return {"ok": True, "auto": {"id": ident, "name": fm.get("상호", ""),
                    "url": f"https://m.place.naver.com/place/{ident}/home", "address": fm.get("지역", "")}}
        try:
            return {"ok": True, **place_lookup.search(fm.get("상호", ""), fm.get("지역", ""))}
        except Exception:
            return {"ok": False, "error": "플레이스 주소를 찾지 못했습니다. 잠시 후 주소 찾기를 다시 눌러 주세요."}

    def set_card_place(self, name, url):
        ident = place_lookup.place_id(url)
        if not ident:
            return {"ok": False, "error": "네이버 플레이스 매장 주소를 확인해 주세요."}
        card = self.read_card(name) if self._card_path(name) else None
        if not card:
            return {"ok": False, "error": "카드를 찾지 못했습니다."}
        card["fm"]["플레이스"] = f"https://m.place.naver.com/place/{ident}/home"
        card["fm"]["플레이스ID"] = ident
        result = self.save_card(name, card["fm"], card["body"])
        return {**result, "url": card["fm"]["플레이스"], "id": ident}

    def create_card(self, data):
        """새 카드 생성. data: 폼 값 + (있으면) 수집 payload."""
        v = self._vault()
        if not v:
            return {"ok": False, "error": "볼트 폴더가 설정되지 않았습니다."}

        data = dict(data)
        data["업종"] = (data.get("업종") or "").strip() or "미분류"
        error = validate_store_fields(data)
        if error:
            return {"ok": False, "error": error}
        for k in ("상호", "지역", "다음할일", "다음날짜"):
            if not (data.get(k) or "").strip():
                label = {"다음할일": "다음 할 일", "다음날짜": "다음 날짜"}.get(k, k)
                return {"ok": False, "error": f"「{label}」 칸이 비어 있습니다."}
        for k in ("상호", "업종", "지역", "담당", "다음할일", "플레이스"):
            if re.search(r":\s", data.get(k, "") or ""):
                return {"ok": False, "error": f"「{k}」에 콜론(:)이 있으면 표가 깨집니다. 빼 주세요."}
        for k in ("상호", "업종", "지역", "담당", "다음할일", "소개", "메모"):
            if PII.search(data.get(k, "") or ""):
                return {"ok": False, "error": "전화번호·이메일 같은 개인정보는 카드에 넣지 않습니다."}

        base = BAD_NAME.sub("", (data.get("상호") or "").strip()).strip()
        if not base:
            return {"ok": False, "error": "상호로 파일 이름을 만들 수 없습니다."}
        name = base + ".md"
        if (v / name).exists():
            if data.get("설문응답ID"):
                name = base + "_" + data["설문응답ID"][:16] + ".md"
            else:
                tail = (data.get("지역") or "").split()[-1] if data.get("지역") else ""
                name = base + ("_" + BAD_NAME.sub("", tail) if tail else "_2") + ".md"
            if (v / name).exists():
                return {"ok": False, "error": f"같은 이름의 카드가 이미 있습니다 ({name})."}

        payload = data.get("수집") or {}
        fm = {
            "구분": "고객", "상호": data["상호"], "업종": data["업종"], "지역": data["지역"],
            "연락처": (data.get("연락처") or "").strip(),
            "이메일주소": (data.get("이메일주소") or "").strip(),
            "담당": data.get("담당", ""), "상태": "발굴", "최근접촉": "",
            "다음할일": data["다음할일"], "다음날짜": data["다음날짜"],
            "진단점수": "", "플레이스": data.get("플레이스", ""),
            "등록일": datetime.now().strftime("%Y-%m-%d"),
        }
        if payload:
            fm["플레이스ID"] = payload.get("플레이스ID", "")
            fm["평균별점"] = payload.get("평균별점", "")
            fm["방문자리뷰수"] = payload.get("방문자리뷰수", "")
            if payload.get("블로그리뷰수"):
                fm["블로그리뷰수"] = payload["블로그리뷰수"]
            if payload.get("리뷰파일"):
                fm["리뷰파일"] = payload["리뷰파일"]
            fm["리뷰수집일"] = datetime.now().strftime("%Y-%m-%d")

        if data.get("설문응답ID"):
            fm["설문응답ID"] = data["설문응답ID"]
            fm["설문접수일시"] = (data.get("설문접수일시") or "").replace("\n", " ").replace("\r", " ")
            fm["등록경로"] = "Google 폼 — SEO보고서 신청"
        secs = {
            "이 집은 어떤 집인가": (data.get("소개") or payload.get("소개") or "").strip() or "—",
            "지금 상태": "- 아직 진단 전 — 첫 방문 때 10항목 채점",
            "오간 이야기": "",
            "메모": (data.get("메모") or "").strip(),
        }
        if payload:
            secs["플레이스 진단"] = payload.get("진단", "")
            secs["플레이스 리뷰"] = payload.get("리뷰본문", "")
            secs["지금 상태"] = "- 플레이스 진단 참고 (첫 방문 때 10항목 채점)"
        body = assemble_body(data["상호"], secs)

        try:
            (v / name).write_text(build_card(fm, body), encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": f"만들지 못했습니다: {e}"}
        return {"ok": True, "name": name, "card": {"name": name, "fm": fm, "body": body}}

    def apply_collection(self, name, payload):
        """기존 카드에 수집 결과(진단/리뷰/통계)를 반영해 저장."""
        card = self.read_card(name)
        if not card:
            return {"ok": False, "error": "카드를 찾을 수 없습니다."}
        fm = dict(card["fm"])
        fm["플레이스ID"] = payload.get("플레이스ID", fm.get("플레이스ID", ""))
        if payload.get("평균별점"):
            fm["평균별점"] = payload["평균별점"]
        if payload.get("방문자리뷰수"):
            fm["방문자리뷰수"] = payload["방문자리뷰수"]
        if payload.get("블로그리뷰수"):
            fm["블로그리뷰수"] = payload["블로그리뷰수"]
        if payload.get("URL") and not fm.get("플레이스"):
            fm["플레이스"] = payload["URL"]
        if payload.get("리뷰파일"):
            fm["리뷰파일"] = payload["리뷰파일"]
        fm["리뷰수집일"] = datetime.now().strftime("%Y-%m-%d")
        body = apply_collection_to_body(card["body"], fm.get("상호") or name[:-3], payload)
        res = self.save_card(name, fm, body)
        if not res.get("ok"):
            return res
        return {"ok": True, "card": {"name": name, "fm": fm, "body": body}}

    # ---- 프롬프트 생성용 데이터 ----
    def get_place_data(self, name):
        """카드에 연결된 수집 원본 JSON을 찾아 그대로 돌려준다(프롬프트 생성용)."""
        card = self.read_card(name)
        if not card:
            return {"ok": False, "error": "카드를 찾을 수 없습니다."}
        fm = card["fm"]
        rv = self.review_dir
        if not rv or not Path(rv).is_dir():
            return {"ok": False, "error": "수집 폴더(review)를 찾지 못했습니다. 먼저 리뷰를 수집해 주세요."}
        rv = Path(rv)
        cand = None
        f = (fm.get("리뷰파일") or "").strip()
        if f and (rv / f).exists():
            cand = rv / f
        else:
            pid = str(fm.get("플레이스ID") or "").strip()
            nm = (fm.get("상호") or "").strip()
            for jf in sorted(rv.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    d = json.loads(jf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if (pid and str(d.get("플레이스ID")) == pid) or (nm and d.get("업체명") == nm):
                    cand = jf
                    break
        if not cand:
            return {"ok": False, "error": "이 카드의 수집 데이터(JSON)를 찾지 못했습니다. [리뷰 수집]을 먼저 실행해 주세요."}
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except Exception as e:
            return {"ok": False, "error": f"데이터 읽기 실패: {e}"}
        return {"ok": True, "data": data, "file": cand.name}

    def save_prompt(self, name, text, suffix=""):
        """생성한 프롬프트를 작업 폴더의 '프롬프트' 폴더에 .md 로 저장한다."""
        v = self._vault()
        if not v:
            return {"ok": False, "error": "볼트 폴더가 설정되지 않았습니다."}
        root = Path(self._load_config().get("workspace") or v.parent)
        outdir = root / "프롬프트"
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "error": f"폴더 생성 실패: {e}"}
        base = BAD_NAME.sub("", (name or "프롬프트").replace(".md", "")).strip() or "프롬프트"
        safe_suffix = BAD_NAME.sub("", suffix).strip()
        fn = base + (("_" + safe_suffix) if safe_suffix else "") + ".md"
        try:
            (outdir / fn).write_text(text or "", encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": f"저장 실패: {e}"}
        return {"ok": True, "path": str(outdir / fn)}

    # ---- SEO 보고서 저장 (고객카드) + 2차 발행 알람 ----
    def _reportdir(self):
        root = self._root_from_cfg(self._load_config())
        if not root:
            return None
        d = root / "보고서"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return d

    def save_seo_report(self, name, data):
        """AI 가 만든 SEO 보고서를 저장한다.

        - 전체 보고서는 작업폴더 '보고서' 폴더에 .md 파일로 저장(카드 본문 깨짐 방지)
        - 요약본은 카드 본문 '## SEO 보고서'에 차수·날짜와 함께 기록
        - set_alarm 이면 다음 할 일/날짜를 '다음 차수 SEO 보고서 발행'로 걸어 알람 역할
        """
        card = self.read_card(name)
        if not card:
            return {"ok": False, "error": "카드를 찾을 수 없습니다."}
        report = (data.get("report") or "").strip()
        if not report:
            return {"ok": False, "error": "보고서 내용이 비어 있습니다. AI 결과를 붙여넣어 주세요."}
        try:
            cha = max(1, int(data.get("cha") or 1))
        except (TypeError, ValueError):
            cha = 1
        rdir = self._reportdir()
        if not rdir:
            return {"ok": False, "error": "작업 폴더를 찾지 못했습니다. 볼트 폴더를 지정해 주세요."}

        today = datetime.now().strftime("%Y-%m-%d")
        base = BAD_NAME.sub("", (card["fm"].get("상호") or name[:-3])).strip() or "보고서"
        fname = f"{base}_{cha}차_SEO_{datetime.now().strftime('%Y%m%d')}.md"
        try:
            (rdir / fname).write_text(report, encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": f"보고서 파일 저장 실패: {e}"}

        # 요약 정리 — 제목 기호 제거(카드 섹션 파싱 보호). 비면 보고서 앞부분에서 추출
        summary = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", (data.get("summary") or "").strip())
        if not summary:
            lines = [l.strip() for l in report.splitlines()
                     if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("---")]
            summary = " ".join(lines[:3])[:300]
        summary = re.sub(r"(?m)^\s*---\s*$", "", summary).strip() or "(요약 없음)"

        entry = (f"### {today} · {cha}차 SEO 보고서\n{summary}\n\n"
                 f"- 전체 보고서 파일: {fname}\n\n")
        body = card["body"]
        at = body.find("## SEO 보고서")
        if at >= 0:
            nl = body.find("\n", at)
            body = body[:nl + 1] + "\n" + entry + body[nl + 1:].lstrip("\n")
        else:
            body = body.rstrip() + "\n\n## SEO 보고서\n\n" + entry

        fm = dict(card["fm"])
        fm["SEO차수"] = str(cha)
        fm["SEO발행일"] = today
        if data.get("set_alarm", True):
            nd = (data.get("다음날짜") or "").strip()
            fm["다음발행예정"] = nd
            fm["다음할일"] = f"{cha + 1}차 SEO 보고서 발행 (요약본 포함)"
            if nd:
                fm["다음날짜"] = nd
        res = self.save_card(name, fm, body)
        if not res.get("ok"):
            return res
        return {"ok": True, "card": {"name": name, "fm": fm, "body": body}, "file": fname}

    def open_report(self, filename):
        """저장된 전체 보고서 파일을 탐색기/기본 앱으로 연다."""
        rdir = self._reportdir()
        if not rdir:
            return {"ok": False, "error": "작업 폴더를 찾지 못했습니다."}
        p = rdir / filename
        if not p.exists():
            return {"ok": False, "error": "보고서 파일이 없습니다."}
        try:
            os.startfile(str(p))  # noqa: S606
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    # ---- KT 가입자 (접수→개통 이력 관리) ----
    def _root_from_cfg(self, cfg):
        """설정에서 작업(루트) 폴더를 찾는다. workspace 가 없던 구버전 설정도 보정."""
        ws = cfg.get("workspace")
        if ws and Path(ws).is_dir():
            return Path(ws)
        v = cfg.get("vault")
        if v and Path(v).is_dir():
            vp = Path(v)
            return vp.parent if vp.name in ("고객", "customers", "Customers") else vp
        return None

    def _ktdir(self):
        """KT가입자 폴더. 설정에 없으면 작업폴더 기준으로 만들어서 돌려준다(구버전 자동 보정)."""
        if self.kt_dir and Path(self.kt_dir).is_dir():
            return Path(self.kt_dir)
        cfg = self._load_config()
        d = cfg.get("kt")
        if d and Path(d).is_dir():
            self.kt_dir = Path(d)
            return self.kt_dir
        root = self._root_from_cfg(cfg)
        if not root:
            return None
        kt = root / "KT가입자"
        try:
            kt.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        cfg["kt"] = str(kt)
        if not cfg.get("workspace"):
            cfg["workspace"] = str(root)
        self._save_config(cfg)
        self.kt_dir = kt
        return kt

    def list_kt(self):
        d = self._ktdir()
        if not d:
            return []
        out = []
        for f in sorted(d.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            fm, body, ok = parse_card(text)
            if not ok or fm.get("구분") != "KT가입자":
                continue
            out.append({"name": f.name, "fm": fm, "body": body})
        out.sort(key=lambda c: c["fm"].get("상호") or c["name"])
        return out

    def read_kt(self, name):
        d = self._ktdir()
        if not d:
            return None
        try:
            text = (d / name).read_text(encoding="utf-8")
        except Exception:
            return None
        fm, body, _ = parse_card(text)
        return {"name": name, "fm": fm, "body": body}

    def save_kt(self, name, fm, body):
        d = self._ktdir()
        if not d:
            return {"ok": False, "error": "KT가입자 폴더가 설정되지 않았습니다."}
        try:
            (d / name).write_text(build_card(fm, body, KT_KEYORDER), encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": f"저장 실패: {e}"}
        return {"ok": True}

    def create_kt(self, data):
        d = self._ktdir()
        if not d:
            return {"ok": False, "error": "먼저 볼트(작업) 폴더를 지정해 주세요."}
        for k in ("상호", "상품"):
            if not (data.get(k) or "").strip():
                return {"ok": False, "error": f"「{k}」 칸이 비어 있습니다."}
        for k in ("상호", "상품", "지역", "담당", "다음할일", "접수번호", "메모"):
            if PII.search(data.get(k, "") or ""):
                return {"ok": False, "error": "전화번호·이메일 같은 개인정보는 카드에 넣지 않습니다. 계약·연락 정보는 회사 시스템에 보관하세요."}
        for k in ("상호", "상품", "지역", "담당", "다음할일", "접수번호"):
            if re.search(r":\s", data.get(k, "") or ""):
                return {"ok": False, "error": f"「{k}」에 콜론(:)이 있으면 표가 깨집니다. 빼 주세요."}

        base = BAD_NAME.sub("", (data.get("상호") or "").strip()).strip()
        if not base:
            return {"ok": False, "error": "상호로 파일 이름을 만들 수 없습니다."}
        name = base + ".md"
        if (d / name).exists():
            tail = BAD_NAME.sub("", (data.get("접수번호") or data.get("지역") or "2").strip()).replace(" ", "")
            name = base + "_" + (tail or "2") + ".md"
            if (d / name).exists():
                return {"ok": False, "error": f"같은 이름의 카드가 이미 있습니다 ({name})."}

        접수일 = (data.get("접수일") or "").strip() or datetime.now().strftime("%Y-%m-%d")
        fm = {
            "구분": "KT가입자", "상호": data["상호"], "상품": data["상품"],
            "지역": data.get("지역", ""), "담당": data.get("담당", ""), "상태": "접수",
            "접수번호": data.get("접수번호", ""), "접수일": 접수일, "개통일": "",
            "다음할일": data.get("다음할일", ""), "다음날짜": data.get("다음날짜", ""),
            "등록일": datetime.now().strftime("%Y-%m-%d"),
        }
        body = (
            "\n# " + data["상호"] + "\n\n"
            "## 가입 정보\n"
            "- 상품: " + data["상품"] + "\n"
            + ("- 접수번호: " + data["접수번호"] + "\n" if data.get("접수번호") else "")
            + "\n## 처리 이력\n"
            "### " + 접수일 + " · 접수\n- " + (data.get("메모") or "접수 등록").strip() + "\n\n"
            "## 메모\n" + (data.get("메모2") or "").strip() + "\n"
        )
        try:
            (d / name).write_text(build_card(fm, body, KT_KEYORDER), encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": f"만들지 못했습니다: {e}"}
        return {"ok": True, "name": name, "card": {"name": name, "fm": fm, "body": body}}

    # ---- 리뷰 수집 ----
    def _form_cache_path(self, url):
        ident = form_sync.sheet_id(url)
        return APPDIR / ("form_responses_" + ident + ".json")

    def _store_form_rows(self, url, rows):
        form_sync.parse_rows(rows, url)
        payload = {"rows": rows, "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        target = self._form_cache_path(url)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
        return payload

    def preview_form_responses(self, refresh=True):
        cfg = self._load_config().get("form_sync", {})
        url = cfg.get("url", form_sync.DEFAULT_SHEET)
        warning = ""
        cached = False
        try:
            payload = None
            if refresh:
                try:
                    rows = form_sync.fetch_rows(url, cfg.get("key_file", ""), cfg.get("tab", ""))
                    payload = self._store_form_rows(url, rows)
                except Exception as exc:
                    warning = str(exc) if isinstance(exc, ValueError) else "최신 응답을 읽지 못했습니다. 연결 설정을 확인해 주세요."
            if payload is None:
                cached = True
                path = self._form_cache_path(url)
                payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rows": [], "updated": ""}
            existing = self.list_cards()
            deleted_ids = {c["fm"].get("설문응답ID") for c in self.list_deleted_cards()}
            records = []
            identity = lambda fm: tuple((fm.get(k) or "").strip().casefold() for k in ("상호", "지역", "연락처", "이메일주소"))
            deleted_contacts = {identity(c["fm"]) for c in self.list_deleted_cards()}
            for number, data, digest in (form_sync.parse_rows(payload["rows"], url) if payload["rows"] else []):
                match = next((c for c in existing if c["fm"].get("설문응답ID") == digest or identity(c["fm"]) == identity(data)), None)
                records.append({"id": digest, "row": number, "data": data,
                                "deleted": not match and (digest in deleted_ids or identity(data) in deleted_contacts),
                                "registered": bool(match), "card": match["name"] if match else "",
                                "error": validate_store_fields(data) or ""})
            return {"ok": True, "records": records, "cached": cached,
                    "updated": payload["updated"], "warning": warning}
        except Exception:
            return {"ok": False, "error": "설문 자료를 읽지 못했습니다. 응답 CSV를 불러오거나 연결 설정을 확인해 주세요."}

    def load_form_csv(self):
        import csv
        import webview
        dialog = getattr(webview, "OPEN_DIALOG", None)
        if dialog is None:
            dialog = webview.FileDialog.OPEN
        try:
            chosen = self._window.create_file_dialog(dialog, allow_multiple=False, file_types=("설문 응답 CSV (*.csv)",))
            if not chosen:
                return {"ok": False, "cancelled": True}
            with open(chosen[0], encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
            url = self._load_config().get("form_sync", {}).get("url", form_sync.DEFAULT_SHEET)
            self._store_form_rows(url, rows)
            return {"ok": True}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            return {"ok": False, "error": "CSV를 읽지 못했습니다. 응답 시트에서 내려받은 UTF-8 CSV를 선택해 주세요."}

    def register_form_responses(self, selected_ids):
        if not self._form_lock.acquire(blocking=False):
            return {"ok": False, "error": "설문을 처리 중입니다. 잠시 후 다시 시도해 주세요."}
        try:
            preview = self.preview_form_responses(False)
            if not preview.get("ok"):
                return preview
            added, skipped, errors = 0, 0, []
            for record in preview["records"]:
                if record["id"] not in selected_ids:
                    continue
                if record["registered"] or record.get("deleted"):
                    skipped += 1
                    continue
                # 같은 파일 안에 반복된 응답도 재검사한다.
                keys = ("상호", "지역", "연락처", "이메일주소")
                if any(c["fm"].get("설문응답ID") == record["id"] or
                       all((c["fm"].get(k) or "").strip().casefold() ==
                           (record["data"].get(k) or "").strip().casefold() for k in keys)
                       for c in self.list_cards()):
                    skipped += 1
                    continue
                result = self.create_card({**record["data"], "설문응답ID": record["id"],
                    "다음할일": "SEO보고서 신청 확인 및 상담", "다음날짜": datetime.now().strftime("%Y-%m-%d")})
                if result.get("ok"):
                    added += 1
                else:
                    errors.append({"row": record["row"], "error": result.get("error", "등록 실패")})
            return {"ok": True, "added": added, "skipped": skipped, "errors": errors}
        finally:
            self._form_lock.release()

    def get_form_settings(self):
        cfg = self._load_config().get("form_sync", {})
        email = ""
        if cfg.get("key_file"):
            try:
                email = form_sync.credential_info(cfg["key_file"])["client_email"]
            except Exception:
                pass
        return {"url": cfg.get("url", form_sync.DEFAULT_SHEET),
                "tab": cfg.get("tab", ""), "enabled": cfg.get("enabled", True),
                "email": email, "authenticated": bool(email)}

    def save_form_settings(self, url, tab, enabled):
        try:
            form_sync.sheet_id(url)
            cfg = self._load_config()
            settings = cfg.setdefault("form_sync", {})
            settings.update(url=url.strip(), tab=tab.strip(), enabled=bool(enabled))
            CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True}
        except Exception:
            return {"ok": False, "error": "응답 시트 링크 또는 설정 파일 쓰기 권한을 확인해 주세요."}

    def pick_form_credentials(self):
        import webview
        dialog = getattr(webview, "OPEN_DIALOG", None)
        if dialog is None:
            dialog = webview.FileDialog.OPEN
        try:
            chosen = self._window.create_file_dialog(dialog, allow_multiple=False,
                                                     file_types=("Google 서비스 계정 (*.json)",))
            if not chosen:
                return {"ok": False, "cancelled": True}
            path = str(chosen[0])
            info = form_sync.credential_info(path)
            cfg = self._load_config()
            cfg.setdefault("form_sync", {})["key_file"] = path
            CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True, "email": info["client_email"]}
        except Exception:
            return {"ok": False, "error": "인증 파일을 읽거나 설정을 저장하지 못했습니다. Google 서비스 계정 JSON 키 파일인지 확인해 주세요."}

    def sync_form_responses(self, manual=False):
        if not self._form_lock.acquire(blocking=False):
            return {"ok": False, "busy": True}
        try:
            cfg = self._load_config().get("form_sync", {})
            if not manual and not cfg.get("enabled", True):
                return {"ok": True, "disabled": True}
            if not self._vault():
                return {"ok": False, "error": "먼저 고객 카드를 저장할 볼트 폴더를 선택해 주세요."}
            url = cfg.get("url", form_sync.DEFAULT_SHEET)
            rows = form_sync.fetch_rows(url, cfg.get("key_file", ""), cfg.get("tab", ""))
            records = form_sync.parse_rows(rows, url)
            self._store_form_rows(url, rows)
            existing = self.list_cards()
            seen = {c["fm"].get("설문응답ID") for c in existing}
            seen.update(c["fm"].get("설문응답ID") for c in self.list_deleted_cards())
            identity = lambda fm: tuple((fm.get(k) or "").strip().casefold() for k in ("상호", "지역", "연락처", "이메일주소"))
            contacts = {identity(c["fm"]) for c in existing}
            contacts.update(identity(c["fm"]) for c in self.list_deleted_cards())
            added, skipped, errors = 0, 0, []
            for number, data, digest in records:
                if digest in seen or identity(data) in contacts:
                    skipped += 1
                    continue
                result = self.create_card({**data, "설문응답ID": digest,
                    "다음할일": "SEO보고서 신청 확인 및 상담",
                    "다음날짜": datetime.now().strftime("%Y-%m-%d")})
                if result.get("ok"):
                    seen.add(digest)
                    contacts.add(identity(data))
                    added += 1
                else:
                    errors.append({"row": number, "error": result.get("error", "등록 실패")})
            return {"ok": True, "added": added, "skipped": skipped, "errors": errors}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception:
            return {"ok": False, "error": "응답 시트를 읽지 못했습니다. 인터넷 연결·Google 인증·시트 보기 권한을 확인해 주세요."}
        finally:
            self._form_lock.release()

    def stop_collect(self):
        self.stop_event.set()
        self._js("onCollectLog", "중지 요청됨... 잠시 기다려 주세요.")
        return True

    def start_collect(self, url, max_n=100):
        if self.running:
            return {"ok": False, "error": "이미 수집이 진행 중입니다."}
        url = (url or "").strip()
        if not url:
            return {"ok": False, "error": "플레이스 URL을 입력해 주세요."}
        try:
            max_n = max(1, int(max_n))
        except (TypeError, ValueError):
            max_n = 100
        self.stop_event.clear()
        self.running = True
        threading.Thread(target=self._collect_worker, args=(url, max_n), daemon=True).start()
        return {"ok": True}

    def _collect_worker(self, url, max_n):
        def log(msg):
            self._js("onCollectLog", str(msg))

        try:
            crawler = core.Crawler(log=log, stop_event=self.stop_event)
            result = crawler.crawl(url, max_n)
            if result.get("리뷰수", 0) == 0 and not result.get("업체명"):
                self._js("onCollectError", "업체 정보를 찾지 못했습니다. URL을 확인해 주세요.")
                return
            # 원본 JSON 보관 (기존 리뷰수집기와 동일한 review 폴더) — 프롬프트 생성에 재사용
            jsonname = ""
            try:
                jp = core.save_json({"구분": "본업체", **result}, self.review_dir, prefix="리뷰")
                jsonname = jp.name
            except OSError:
                pass
            pay = collect_payload(result)
            pay["리뷰파일"] = jsonname
            self._js("onCollectDone", pay)
        except Exception as e:
            self._js("onCollectError", str(e))
        finally:
            self.running = False


# ---------------------------------------------------------------------------

def _selftest():
    """창 없이 파이썬 로직만 점검."""
    sample = (
        "---\n구분: 고객\n상호: 마루커피\n업종: 카페\n지역: 구리 수택동\n"
        "상태: 관리중\n다음할일: 사진 받기\n다음날짜: 2026-11-07\n---\n"
        "\n# 마루커피\n\n## 이 집은 어떤 집인가\n골목 카페.\n\n## 오간 이야기\n"
        "### 2026-10-23 · 전화\n- 보고서 받음.\n\n## 메모\n오전 통화 선호.\n"
    )
    fm, body, ok = parse_card(sample)
    assert ok and fm["상호"] == "마루커피", fm
    secs = split_sections(body)
    assert "오간 이야기" in secs and "메모" in secs, list(secs)
    rebuilt = build_card(fm, body)
    fm2, _, ok2 = parse_card(rebuilt)
    assert ok2 and fm2 == fm, (fm, fm2)

    assert category_short("돈까스,우동") == "돈까스"
    assert region_from_address("경기도 구리시 인창동 123-4") == "구리 인창동", region_from_address("경기도 구리시 인창동 123-4")
    assert region_from_address("서울특별시 강남구 역삼동 1") == "강남구 역삼동", region_from_address("서울특별시 강남구 역삼동 1")

    fake = {
        "업체명": "테스트식당", "플레이스ID": "123", "URL": "u", "수집일시": "2026-11-01 10:00:00",
        "업체정보": {"카테고리": "한식,국밥", "주소": "경기 구리시 인창동 1", "도로명주소": "경기 구리시 인창로 1",
                     "한줄소개": "줄서는 국밥집", "예약가능": True, "네이버주문": ["포장"], "톡톡문의": True,
                     "영업상태": "영업 중 · 21:00에 영업 종료"},
        "리뷰통계": {"평균별점": "4.52", "방문자리뷰수": 1234, "블로그리뷰수": 56,
                     "답글율_수집리뷰중": "60.0%", "키워드리뷰": [{"키워드": "친절해요", "선택수": 10}]},
        "사진통계": {"업체등록사진수": 12, "방문자등록사진수": 300, "클립등록": True},
        "메뉴": [{"메뉴명": "소국밥"}, {"메뉴명": "특국밥"}],
        "리뷰수": 2,
        "리뷰": [
            {"별점": "5", "작성일": "2026-10-29", "본문": "국물이\n진하고 좋아요", "키워드": ["친절해요"], "사장님답글": "감사합니다"},
            {"별점": "4", "방문일": "2026-10-20", "본문": "재방문", "키워드": [], "사장님답글": ""},
        ],
    }
    pay = collect_payload(fake)
    assert pay["업종"] == "한식" and pay["지역"] == "구리 인창동", pay
    assert "평균 별점 4.52" in pay["진단"], pay["진단"]
    assert "### ★★★★★" in pay["리뷰본문"] and "국물이 진하고 좋아요" in pay["리뷰본문"], pay["리뷰본문"]

    newbody = apply_collection_to_body(body, "마루커피", pay)
    s2 = split_sections(newbody)
    assert "플레이스 진단" in s2 and "플레이스 리뷰" in s2 and "오간 이야기" in s2, list(s2)
    assert "보고서 받음" in s2["오간 이야기"], s2["오간 이야기"]  # 기존 대화 보존
    print("selftest OK")


def _check():
    """패키지 실행 점검 — 번들 자원과 크로미움 브라우저가 실제로 뜨는지 확인(결과는 파일에도 기록)."""
    lines = [
        f"frozen: {FROZEN}",
        f"UI: {UI_FILE.exists()} {UI_FILE}",
        f"forge: {(BUNDLE / 'prompt_forge.js').exists()}",
        f"PLAYWRIGHT_BROWSERS_PATH: {os.environ.get('PLAYWRIGHT_BROWSERS_PATH')}",
    ]
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            pg = b.new_page()
            pg.goto("about:blank", timeout=20000)
            b.close()
        lines.append("CHECK OK — 크로미움 정상 구동")
    except Exception as e:
        lines.append(f"CHECK FAIL: {e}")
    text = "\n".join(lines)
    try:
        (APPDIR / "_check_result.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        print(text)
    except Exception:
        pass


def main():
    if "--check" in sys.argv:
        _check()
        return
    if "--selftest" in sys.argv:
        _selftest()
        return
    if not UI_FILE.exists():
        print(f"UI 파일이 없습니다: {UI_FILE}")
        return
    try:
        import webview
    except ImportError:
        print("pywebview가 설치되어 있지 않습니다. 설치.bat 을 실행해 주세요.")
        return

    html = UI_FILE.read_text(encoding="utf-8")
    forge = HERE / "prompt_forge.js"
    if forge.exists():
        html = html.replace("/*__PROMPT_FORGE__*/", forge.read_text(encoding="utf-8"))

    api = Api()
    window = webview.create_window(
        "센터 고객 CRM — 플레이스 자동 수집",
        html=html,
        js_api=api,
        width=1480,
        height=960,
        min_size=(1080, 720),
        background_color="#EAEDF0",
    )
    api._window = window
    webview.start()


if __name__ == "__main__":
    main()
