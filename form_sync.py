"""Google Forms 응답 시트를 읽기 전용으로 가져온다."""
import hashlib
import json
import re
from urllib.parse import quote

DEFAULT_SHEET = "https://docs.google.com/spreadsheets/d/1Wql05aN_5xveslwXTu2aGv-hMl8W0JJaFUVBSn_F2KA/edit"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def sheet_id(url):
    match = re.fullmatch(r"https://docs\.google\.com/spreadsheets/d/([\w-]+)(?:[/#?].*)?", url.strip())
    if not match:
        raise ValueError("Google 응답 스프레드시트 링크를 입력해 주세요.")
    return match[1]


def credential_info(path):
    with open(path, encoding="utf-8") as stream:
        info = json.load(stream)
    if (info.get("type") != "service_account" or not info.get("client_email")
            or not info.get("private_key")
            or info.get("token_uri") != "https://oauth2.googleapis.com/token"):
        raise ValueError("Google 서비스 계정 JSON 키 파일을 선택해 주세요.")
    return info


def fetch_rows(url, key_file, tab_name=""):
    ident = sheet_id(url)
    if not key_file:
        raise ValueError("비공개 응답 시트입니다. [인증 파일 선택] 후 표시되는 서비스 계정에 시트 보기 권한을 주세요.")
    info = credential_info(key_file)
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
    except ImportError:
        raise ValueError("Google 연결 부품이 없습니다. 설치.bat을 다시 실행해 주세요.") from None
    credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    # 인증 세션은 토큰을 메모리에만 보관한다.
    with AuthorizedSession(credentials) as session:
        if not tab_name.strip():
            meta = session.get(f"https://sheets.googleapis.com/v4/spreadsheets/{ident}",
                               params={"fields": "sheets.properties.title"}, timeout=30)
            check_response(meta)
            tabs = meta.json().get("sheets", [])
            if len(tabs) != 1:
                raise ValueError("시트 탭이 여러 개입니다. 응답 탭 이름을 입력해 주세요.")
            tab_name = tabs[0]["properties"]["title"]
        cell_range = "'" + tab_name.replace("'", "''") + "'!A:ZZ"
        response = session.get(
            f"https://sheets.googleapis.com/v4/spreadsheets/{ident}/values/{quote(cell_range, safe='')}",
            params={"valueRenderOption": "FORMATTED_VALUE"}, timeout=30)
        check_response(response)
        return response.json().get("values", [])


def check_response(response):
    if response.status_code in (401, 403, 404):
        raise ValueError("시트를 읽을 수 없습니다. Google Sheets API 활성화와 서비스 계정의 시트 보기 권한을 확인해 주세요.")
    if response.status_code != 200:
        raise ValueError(f"Google 응답 시트 읽기 실패 (HTTP {response.status_code}). 잠시 후 다시 시도해 주세요.")


def parse_rows(rows, url):
    if not rows:
        raise ValueError("응답 시트가 비어 있습니다. 첫 행의 설문 항목을 확인해 주세요.")
    normalize = lambda v: re.sub(r"\s+", "", str(v)).lstrip("\ufeff")
    headers = [normalize(v) for v in rows[0]]
    aliases = {
        "상호": ["매장명", "상호"], "지역": ["지역명(시,군,구)", "지역명(시·군·구)", "지역명", "지역"],
        "연락처": ["연락처", "전화번호"], "이메일주소": ["이메일주소", "이메일"],
        "설문접수일시": ["타임스탬프", "Timestamp"],
    }
    columns = {}
    for key, names in aliases.items():
        positions = [i for i, name in enumerate(headers) if name in names]
        if len(positions) > 1:
            raise ValueError(f"「{key}」에 해당하는 열이 여러 개입니다. 시트 제목 행을 확인해 주세요.")
        if positions:
            columns[key] = positions[0]
        elif key != "설문접수일시":
            raise ValueError(f"응답 시트에 「{names[0]}」 열이 없습니다. 응답 탭 이름을 확인해 주세요.")
    records = []
    for number, row in enumerate(rows[1:], 2):
        if not any(str(value).strip() for value in row):
            continue
        data = {key: str(row[index]).strip() if index < len(row) else "" for key, index in columns.items()}
        # 행 순서가 바뀌거나 재시작해도 동일한 응답은 동일한 ID를 갖는다.
        digest = hashlib.sha256(json.dumps([sheet_id(url), data], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        records.append((number, data, digest))
    return records
