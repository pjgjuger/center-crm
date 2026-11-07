import copy
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

import form_sync
import legacy_core as core


def today():
    return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


def can_access(user, owner):
    return bool(user.get("email_verified") is True and user.get("email", "").casefold() == owner.casefold())


def load_responses(credentials, url, tab):
    ident = form_sync.sheet_id(url)
    creds = service_account.Credentials.from_service_account_info(dict(credentials), scopes=form_sync.SCOPES)
    cell_range = "'" + tab.replace("'", "''") + "'!A:ZZ"
    with AuthorizedSession(creds) as session:
        r = session.get(f"https://sheets.googleapis.com/v4/spreadsheets/{ident}/values/{quote(cell_range, safe='')}",
                        params={"valueRenderOption": "FORMATTED_VALUE"}, timeout=25)
        form_sync.check_response(r)
        return form_sync.parse_rows(r.json().get("values", []), url)


def survey_card(data):
    fm = {"구분": "고객", "상호": data.get("상호", ""), "지역": data.get("지역", ""),
          "연락처": data.get("연락처", ""), "이메일주소": data.get("이메일주소", ""),
          "업종": "미분류", "상태": "발굴", "등록일": today(), "다음날짜": today(),
          "다음할일": "SEO보고서 신청 확인 및 상담", "등록경로": "Google 폼", "설문접수일시": data.get("설문접수일시", "")}
    error = core.validate_store_fields(fm)
    if not fm["상호"].strip() or not fm["지역"].strip():
        error = "매장명과 지역을 확인해 주세요."
    if error:
        raise ValueError(error)
    body = core.assemble_body(fm["상호"], {"이 집은 어떤 집인가": "—", "오간 이야기": "", "메모": ""})
    return fm, body


def sync_surveys(store, records):
    known = store.survey_state()
    added, errors = 0, []
    for number, data, source_id in records:
        if source_id in known:
            continue
        try:
            fm, body = survey_card(data)
            fm["설문응답ID"] = source_id
            ident, created = store.create(fm, body, source_id=source_id)
            known[source_id] = {"card_id": ident}
            added += int(created)
        except ValueError as exc:
            errors.append({"row": number, "error": str(exc)})
    return {"added": added, "errors": errors, "responses": len(records)}


def add_consultation(card, note, how):
    if not note.strip():
        raise ValueError("상담 내용을 입력해 주세요.")
    sections = core.split_sections(card["body"])
    sections["오간 이야기"] = f"### {today()} · {how}\n{note.strip()}\n\n" + sections.get("오간 이야기", "")
    fm = copy.deepcopy(card["fm"])
    fm["최근접촉"] = today()
    return fm, core.assemble_body(fm["상호"], sections)


def serialize_card(card):
    order = core.KT_KEYORDER if card.get("kind") == "kt" else core.KEYORDER
    return core.build_card(card["fm"], card["body"], order)


def reports_for_card(card, assets):
    """Resolve both cloud report IDs and legacy Markdown/wiki references."""
    latest = card['fm'].get('최근보고서ID')
    references = set()
    section = core.split_sections(card.get('body', '')).get('SEO 보고서', '')
    for value in re.findall(r'(?:보고서:\s*|\[\[)([^\n\]|]+?\.md)', section):
        references.add(value.replace('\\', '/').rsplit('/', 1)[-1].strip())
    for key in ('SEO보고서', '보고서파일', '최근보고서'):
        value = card['fm'].get(key, '')
        if value:
            references.add(value.replace('\\', '/').rsplit('/', 1)[-1].strip())
    matches = [a for a in assets if a['id'] == latest or
               a['name'].replace('\\', '/').rsplit('/', 1)[-1] in references]
    return sorted(matches, key=lambda a: (a['id'] == latest, a.get('created_at', ''), a['name']), reverse=True)
