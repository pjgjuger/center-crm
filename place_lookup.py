"""네이버 공개 검색 결과에 표시되는 매장 링크로 플레이스 주소를 찾는다."""
import re
from html.parser import HTMLParser
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


def place_id(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ("map.naver.com", "m.place.naver.com", "pcmap.place.naver.com"):
        return None
    match = re.search(r"/(?:entry/place|place|restaurant|cafe|hospital|hairshop|beauty|accommodation|attraction|pharmacy|clinic)/(\d+)(?:/|$)", parsed.path)
    return match.group(1) if match else None


def normalized(text):
    return re.sub(r"[\W_]", "", text).removesuffix("점").casefold().replace("또레오레", "또래오래")


def same_store_name(left, right, region):
    left, right = normalized(left), normalized(right)
    if left == right:
        return True
    # 지점명에 시·군 이름이 추가된 경우만 비교에서 제거한다.
    for token in region.split():
        root = re.sub(r"(?:특별자치도|특별자치시|특별시|광역시|도|시|군|구|읍|면|동)$", "", token)
        root = normalized(root)
        if len(root) >= 2:
            left, right = left.replace(root, ""), right.replace(root, "")
    return len(left) >= 2 and left == right


class SearchParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.addresses = {}
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        title = attrs.get("data-line-title")
        address = attrs.get("data-line-description")
        if title and address:
            self.addresses[normalized(title)] = address
        if tag == "a":
            ident = place_id(attrs.get("href", ""))
            self.anchor = {"id": ident, "text": []} if ident else None

    def handle_data(self, text):
        if self.anchor:
            self.anchor["text"].append(text)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor:
            title = " ".join("".join(self.anchor["text"]).split())
            if title:
                self.links.append((self.anchor["id"], title))
            self.anchor = None


def parse_results(html, name, region):
    parser = SearchParser()
    parser.feed(html)
    wanted = normalized(name)
    candidates = {}
    for ident, title in parser.links:
        actual = normalized(title)
        if not wanted or not (wanted in actual or actual in wanted or same_store_name(name, title, region)):
            continue
        address = parser.addresses.get(actual, "")
        result = {"id": ident, "name": title, "address": address,
                  "url": f"https://m.place.naver.com/place/{ident}/home"}
        if ident not in candidates or actual == wanted:
            candidates[ident] = result
    results = list(candidates.values())[:10]
    region_tokens = [normalized(t) for t in region.split() if normalized(t)]
    exact = [r for r in results if same_store_name(name, r["name"], region) and region_tokens
             and all(t in normalized(r["address"]) for t in region_tokens)]
    return {"candidates": results, "auto": exact[0] if len(exact) == 1 else None}


def search(name, region):
    query = " ".join((region.strip(), name.strip())).strip()
    if not name.strip():
        raise ValueError("매장명을 먼저 입력해 주세요.")
    url = "https://search.naver.com/search.naver?" + urlencode({"where": "nexearch", "query": query[:200]})
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=25) as response:
        html = response.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
    return {**parse_results(html, name, region), "search_url": url}
