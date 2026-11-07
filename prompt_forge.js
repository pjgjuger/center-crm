/* ============================================================
   PROMPT FORGE — 네이버 플레이스 수집 JSON → SEO/GEO/AEO 프롬프트
   출처: idea1478.tistory.com/20 의 'SEO 프롬프트 생성기 V2.1' 로직을
   CRM 내장용으로 순수 함수만 추출(화면·업로드 코드 제외)한 모듈.
   crm_app.py 가 crm_ui.html 의 PROMPT_FORGE 주입 자리에 끼워 넣습니다.
   사용: const {prompt} = PromptForge.generate(수집결과JSON, {modes:['seo'],depth:'standard',industry:''});
   ============================================================ */
(function () {
const MODE_META = {
  seo: { name: 'SEO 검색엔진 최적화', engine: '네이버·구글 검색 알고리즘' },
  geo: { name: 'GEO 생성형 AI 최적화', engine: 'ChatGPT·Gemini·Perplexity 등 생성형 엔진' },
  aeo: { name: 'AEO 답변엔진 최적화', engine: '음성검색·AI 스니펫·즉답 박스' } };
const ALGO_2026 = `# 2026 네이버 플레이스 최신 환경 (진단·권고에 반드시 반영)
1. **별점 공개 시행 (2026.7.9~)** — 5년 만에 별점 부활. 평균 별점 + 사용자별 개별 별점이 플레이스 주요 영역에 공개됨. 공개 여부는 사업주가 스마트플레이스에서 ON/OFF 선택 (2021.10 이후 개업은 미노출이 기본값). 공개 평균은 2021.10.25 이전 누적분 + 2026.4월부터 신규 수집분 합산. 어뷰징 방지책: 리뷰 작성 후 3개월 이내만 수정 가능, 합리적 설명 없는 3점 미만 부여 금지(별점 테러 제재), 리뷰어 본인의 평균 별점도 타 사용자에게 공개. → 아래 별점 데이터를 근거로 이 업체의 **별점 공개 ON/OFF 전략과 별점 관리 방안**을 반드시 권고할 것.
2. **상위노출 → 맞춤노출 패러다임** — 개인화 신호(검색자 위치·방문 이력·저장 장소·시간대·요일)에 따라 사용자마다 다른 결과 노출. '막연한 1등'이 아니라 '타깃 고객이 검색하는 순간의 1등' 전략으로 진단할 것.
3. **4대 뼈대 (유·인·거·실)** — 유사도(검색어-업체 의미 매칭) / 인기도(클릭·저장·길찾기·전화·예약·리뷰 등 행동데이터 누적) / 거리(인기도로 상쇄 가능) / 충실성(영업시간·메뉴·사진·편의시설 빈칸 제로).
4. **네이버 클립(숏폼) 연동** — 클립 등록 매장은 검색 결과 클릭률이 크게 상승하며 장소 리뷰와 직접 연동됨. 15~30초, 주 1~3회 업로드 권고 여부를 판단할 것.
5. **어뷰징 필터 강화** — D.I.A.+ 기반 유사 문장·단기간 몰린 리뷰·키워드 도배 탐지 시 역효과. 어뷰징성 전술은 절대 권고 금지하고, 하면 안 되는 행위를 명시할 것.
`;
const MODE_FOCUS = {
  seo: { role: '네이버 로컬 SEO 및 검색 상위노출 전문 컨설턴트 (2026 별점 공개·맞춤노출 로직 숙지)',
    pillars: ['C-Rank(콘텐츠 신뢰도·인기도)', 'D.I.A.+(문서 의도·경험 반영)', '별점 공개(2026.7.9) 대응·평판 관리', '개인화(맞춤노출) 신호 확보 — 저장·길찾기·재방문', 'NAP 일관성', '영수증·블로그 리뷰 균형', '플레이스 정보 완성도(충실성)', '소식·클립(숏폼) 등 콘텐츠 활동성'] },
  geo: { role: '생성형 AI 검색(GEO) 최적화 전문가',
    pillars: ['엔티티(Entity) 명확성·일관성 (플레이스·SNS·홈페이지 교차)', '인용 가능 권위 콘텐츠 구조', '고유 사실 정보(통계·수치·메뉴·가격)', '외부 언급·리뷰 신뢰 신호', 'AI 추출 용이한 문장 구조'] },
  aeo: { role: '답변엔진(AEO)·음성검색 최적화 전문가',
    pillars: ['질문 의도 매칭', 'FAQ·Q&A 구조화', 'Schema 마크업(LocalBusiness/FAQPage 등)', '즉답형 답변+근거', '음성검색 자연어 대응'] } };
const INDUSTRIES = [
  { id: 'restaurant', ico: '🍽️', nm: '음식점·외식', en: 'F&B', kw: '지역명+음식종류, 맛집, 배달, 예약, 메뉴',
    match: ['음식', '식당', '회', '탕', '고기', '분식', '한식', '중식', '일식', '양식', '카페', '치킨', '피자', '횟집', '해물', '국밥', '면', '국수', '뷔페', '밀면', '냉면', '샤브', '구이', '찜'],
    crit: ['플레이스 정보 완성도(충실성)', '영수증 리뷰 수·최신성', '별점 공개 대응(평균별점·분포·ON/OFF 전략)', '메뉴/가격 등록', '사진 품질·구성', '소식·이벤트 활동성', '클립(숏폼)·콘텐츠', '리뷰 답글율·답글 품질', '블로그 리뷰 확산', '예약/주문 연동·행동데이터(저장·길찾기)'] },
  { id: 'academy', ico: '📚', nm: '학원·교육', en: 'EDU', kw: '지역명+과목, 입시, 보습, 1:1, 내신',
    match: ['학원', '교육', '과외', '어학', '입시', '음악', '미술', '피아노', '태권도', '코딩'],
    crit: ['플레이스 정보', '수강후기 리뷰', '별점 공개 대응', '커리큘럼·강사 소개', '수업료·시간표', '블로그 합격수기', '소식·콘텐츠 활동성', '리뷰 답글율', '상담 예약'] },
  { id: 'beauty', ico: '💇', nm: '미용·뷰티', en: 'BEAUTY', kw: '지역명+시술, 헤어/네일/피부, 예약',
    match: ['미용', '헤어', '네일', '피부', '왁싱', '속눈썹', '뷰티', '에스테틱', '메이크업', '바버'],
    crit: ['플레이스·예약연동', '시술 포트폴리오', '별점 공개 대응', '영수증 리뷰', '디자이너 소개', '시술 메뉴·가격', '소식·프로모션', '리뷰 답글율', '블로그 후기'] },
  { id: 'medical', ico: '🏥', nm: '병의원·한의원', en: 'CLINIC', kw: '지역명+진료과목, 증상명, 예약',
    match: ['의원', '병원', '한의원', '치과', '피부과', '정형외과', '내과', 'clinic', '약국'],
    crit: ['플레이스·진료시간', '진료과목/의료진', '의료광고 규정 준수', '환자 후기·별점 대응', '건강정보 콘텐츠', '예약/문의', '리뷰 답글율', '지도·주차'] },
  { id: 'fitness', ico: '🏋️', nm: '헬스·필라테스', en: 'FITNESS', kw: '지역명+PT/필라테스/요가, 체험',
    match: ['헬스', '피트니스', '필라테스', '요가', 'pt', '크로스핏', '복싱', '운동', '짐'],
    crit: ['플레이스 정보', '시설·기구 사진', '회원 후기/변화', '별점 공개 대응', '트레이너 소개', '이용권·가격', '체험 예약', '소식·콘텐츠', '리뷰 답글율'] },
  { id: 'lodging', ico: '🏨', nm: '숙박·펜션', en: 'STAY', kw: '지역명+펜션/풀빌라/독채, 예약, 뷰',
    match: ['펜션', '풀빌라', '호텔', '모텔', '게스트', '숙박', '리조트', '독채', '캠핑', '글램핑'],
    crit: ['예약플랫폼 정보', '객실·전경 사진', '투숙 후기·별점 대응', '부대시설', '시즌 가격·패키지', 'SNS 콘텐츠', '예약 연동', '리뷰 답글율'] },
  { id: 'retail', ico: '🛍️', nm: '소매·판매점', en: 'RETAIL', kw: '지역명+품목, 매장, 정품, 당일배송',
    match: ['판매', '매장', '샵', '마트', '상점', '편의점', '문구', '꽃', '가구', '전자'],
    crit: ['플레이스 정보', '상품 진열 사진', '구매 후기·별점 대응', '취급 품목', '가격 경쟁력', '할인 이벤트·소식', '스마트스토어 연동', '리뷰 답글율'] },
  { id: 'service', ico: '🔧', nm: '생활서비스·기타', en: 'SERVICE', kw: '지역명+서비스종류, 출장, 견적, 후기',
    match: ['수리', '청소', '세탁', '이사', '인테리어', '시공', '정비', '출장', '서비스'],
    crit: ['플레이스·서비스 범위', '시공 포트폴리오', '고객 후기·별점 대응', '서비스/견적', '출장 지역', '자격·인증', '사례 콘텐츠·소식', '리뷰 답글율'] }];
const DEPTH_SPEC = {
  quick: { label: '간단 진단', detail: '핵심 항목만 점검하고 즉시 실행 가능한 개선안 3~5가지를 우선순위로 제시. A4 1페이지 이내.' },
  standard: { label: '표준 보고서', detail: '평가 항목별 100점 점수와 근거, 별점 공개 ON/OFF 판단, 우선순위 액션플랜 포함. 클라이언트 제출용.' },
  deep: { label: '종합 컨설팅', detail: '표준 보고서 + 리뷰 감성분석 + 별점분포 해석·공개 ON/OFF 전략 + 충실성·활동성 정밀 진단 + 3계층 키워드 전략 + 경쟁사 비교(실측 데이터 우선)·SWOT + 30일 로드맵 + 복붙 실행키트 + KPI·시나리오 시뮬레이션.' } };
const POS = ['맛있', '맛나', '맛납', '신선', '친절', '푸짐', '넉넉', '만족', '최고', '강추', '추천', '깔끔', '훌륭', '좋', '행복', '별미', '완벽', '감사', '재방문', '단골', '정성', '퀄리티', '넓', '대만족', '즐겁', '유쾌', '감칠맛', '풍성', '잘먹', '잘 먹', '고소', '쫄깃', '깨끗', '시원', '든든'];
const NEG = ['최악', '별로', '불친절', '실망', '짜', '싱거', '덜익', '안익', '비린', '냄새', '당황', '아쉽', '그냥 그', '웨이팅', '오래', '떡져', '덩어리', '포장비', '기분 나', '마인드', '없었', '바뀜', '받으심', '이상한맛', '비싸', '불편'];

const state = { industry: 'restaurant', industryAuto: true, depth: 'standard', modes: ['seo'], main: null, competitors: [] };

/* ---- 날짜 ---- */
function refDateOf(store) {
  const c = store && store.collectedAt;
  if (c) { const m = String(c).match(/(\d{4})-(\d{1,2})-(\d{1,2})/); if (m) return new Date(+m[1], +m[2] - 1, +m[3]); }
  return new Date();
}
function parseNaverDate(s, ref) {
  if (!s) return null; s = String(s).trim();
  let m = s.match(/^(\d{2})\.(\d{1,2})\.(\d{1,2})/);
  if (m) return { y: 2000 + +m[1], mo: +m[2], d: +m[3] };
  m = s.match(/(\d{4})[-.](\d{1,2})[-.](\d{1,2})/);
  if (m) return { y: +m[1], mo: +m[2], d: +m[3] };
  m = s.match(/^(\d{1,2})\.(\d{1,2})\./);
  if (m) { let y = ref.getFullYear(); if (new Date(y, +m[1] - 1, +m[2]) > ref) y -= 1; return { y, mo: +m[1], d: +m[2] }; }
  return null;
}
function dstr(o) { return o ? `${o.y}.${String(o.mo).padStart(2, '0')}.${String(o.d).padStart(2, '0')}` : ''; }
function daysBetween(o, ref) { return Math.max(0, Math.round((ref - new Date(o.y, o.mo - 1, o.d)) / 86400000)); }

/* ---- 리뷰 분석 ---- */
function analyzeReviews(rows, store) {
  const ref = refDateOf(store);
  const a = { total: rows.length };
  const texted = rows.filter(r => String(r.body || '').trim().length > 1);
  a.textedCount = texted.length; a.emptyCount = rows.length - texted.length; a.hasBody = texted.length > 0;
  const nums = rows.map(r => parseFloat(r.rating)).filter(n => !isNaN(n) && n > 0 && n <= 5);
  if (nums.length) { a.avgRating = (nums.reduce((x, y) => x + y, 0) / nums.length).toFixed(2); a.ratingCount = nums.length; }
  a.noRatingCount = rows.length - (a.ratingCount || 0);
  if (a.hasBody) {
    let pos = 0, neg = 0, neu = 0; const posS = [], negS = [];
    texted.forEach(r => {
      const t = String(r.body); let p = 0, n = 0;
      POS.forEach(w => { if (t.includes(w)) p++; }); NEG.forEach(w => { if (t.includes(w)) n++; });
      if (p > n) { pos++; if (posS.length < 4) posS.push(t.replace(/\n/g, ' ').slice(0, 60)); }
      else if (n > p) { neg++; if (negS.length < 5) negS.push(t.replace(/\n/g, ' ').slice(0, 90)); }
      else neu++;
    });
    a.pos = pos; a.neg = neg; a.neu = neu; a.posRate = Math.round(pos / texted.length * 100);
    a.negRate = Math.round(neg / texted.length * 100); a.posSamples = posS; a.negSamples = negS;
    a.estScore = (3 + (pos - neg) / texted.length * 2).toFixed(2); a.sentimentOK = true;
    const stop = new Set(['그리고', '너무', '정말', '진짜', '조금', '약간', '그냥', '다시', '여기', '거기', '이곳', '매우', '아주', '정도', '하고', '해서', '했어요', '합니다', '있어요', '같아요', '먹고', '먹었', '이제', '오늘', '다음', '방문', '사장', '사장님', '우리', '저희', '있는', '있고', '합니', '해요', '근데', '그래서', '하지만', '고객', '고객님']);
    const freq = {}; texted.forEach(r => { (String(r.body).match(/[가-힣]{2,}/g) || []).forEach(w => { if (!stop.has(w) && w.length <= 5) freq[w] = (freq[w] || 0) + 1; }); });
    a.topWords = Object.entries(freq).sort((x, y) => y[1] - x[1]).slice(0, 15);
  } else a.sentimentOK = false;
  const kw = {}; rows.forEach(r => (r.keywords || []).forEach(k => { kw[k] = (kw[k] || 0) + 1; }));
  a.reviewKeywords = Object.entries(kw).sort((x, y) => y[1] - x[1]);
  const ds = rows.map(r => parseNaverDate(r.created || r.visited, ref)).filter(Boolean).sort((x, y) => (x.y - y.y) || (x.mo - y.mo) || (x.d - y.d));
  if (ds.length) {
    a.oldest = dstr(ds[0]); a.recent = dstr(ds[ds.length - 1]);
    a.daysSinceLast = daysBetween(ds[ds.length - 1], ref);
    const cut = new Date(ref); cut.setDate(cut.getDate() - 90);
    a.recent90 = ds.filter(o => new Date(o.y, o.mo - 1, o.d) >= cut).length;
    const cut1y = new Date(ref); cut1y.setFullYear(cut1y.getFullYear() - 1);
    a.recent365 = ds.filter(o => new Date(o.y, o.mo - 1, o.d) >= cut1y).length;
  }
  const od = {}; rows.forEach(r => { const v = String(r.originType || '').trim(); if (v) od[v] = (od[v] || 0) + 1; });
  a.originDist = Object.keys(od).length ? od : null;
  if (rows.some(r => r.mediaCount != null)) {
    const wm = rows.filter(r => (+r.mediaCount || 0) > 0).length;
    a.mediaRate = Math.round(wm / rows.length * 100);
    a.mediaTotal = rows.reduce((s, r) => s + (+r.mediaCount || 0), 0);
  }
  const withVC = rows.filter(r => r.visitCount != null && r.visitCount !== '');
  if (withVC.length) {
    const re = withVC.filter(r => (+r.visitCount || 0) > 1).length;
    a.revisitRate = Math.round(re / withVC.length * 100);
    a.maxVisit = Math.max(...withVC.map(r => +r.visitCount || 0));
  }
  if (rows.some(r => 'ownerReply' in r)) {
    const replied = rows.filter(r => String(r.ownerReply || '').trim());
    a.replyCount = replied.length;
    a.replyRate = rows.length ? Math.round(replied.length / rows.length * 100) : 0;
    a.replySamples = replied.slice(0, 2).map(r => String(r.ownerReply).replace(/\n/g, ' ').slice(0, 90));
    a.negNoReply = texted.filter(r => {
      const t = String(r.body); let p = 0, n = 0;
      POS.forEach(w => { if (t.includes(w)) p++; }); NEG.forEach(w => { if (t.includes(w)) n++; });
      return n > p && !String(r.ownerReply || '').trim();
    }).map(r => String(r.body).replace(/\n/g, ' ').slice(0, 80)).slice(0, 3);
    a.lowNoReply = rows.filter(r => { const n = parseFloat(r.rating); return !isNaN(n) && n < 4 && !String(r.ownerReply || '').trim(); }).length;
  }
  const nm = {}; rows.forEach(r => { const v = String(r.businessName || '').trim(); if (v) nm[v] = (nm[v] || 0) + 1; });
  a.nameVariants = Object.entries(nm).sort((x, y) => y[1] - x[1]);
  return a;
}

/* ---- 충실성 ---- */
function completeness(s) {
  if (!s) return null;
  const items = [
    ['전화번호', !!s.phone],
    ['영업시간', (s.bizHours && s.bizHours.length > 0) || undefined],
    ['라스트오더', s.bizHours ? s.bizHours.some(h => h.lastOrder) : undefined],
    ['소개문', !!s.description],
    ['편의시설', (s.conveniences || []).length > 0],
    ['홈페이지/SNS', !!s.homepage || (s.snsList || []).length > 0],
    ['네이버 예약', 'bookable' in s ? s.bookable : undefined],
    ['톡톡 문의', 'talkTalk' in s ? s.talkTalk : undefined],
    ['쿠폰', 'coupon' in s ? s.coupon : undefined],
    ['네이버주문', 'naverOrder' in s ? s.naverOrder : undefined],
    ['메뉴 등록', (s.menus || []).length > 0],
    ['대표메뉴 지정', (s.menus || []).some(m => m.recommend) || undefined],
    ['클립(숏폼)', 'clipRegistered' in s ? s.clipRegistered : undefined],
    ['소식 게시', s.newsCount != null ? s.newsCount > 0 : undefined],
  ].filter(([, v]) => v !== undefined);
  const done = items.filter(([, v]) => v).length;
  return { items, done, total: items.length, rate: items.length ? Math.round(done / items.length * 100) : 0 };
}
function newsActivity(s) {
  if (!s || s.newsCount == null) return null;
  const ref = refDateOf(s);
  const n = { count: s.newsCount, latest: s.newsLatest || '' };
  if (s.newsLatest) { const d = parseNaverDate(s.newsLatest, ref); if (d) n.daysSince = daysBetween(d, ref); }
  if (s.news && s.news.length > 1) {
    const ds = s.news.map(x => parseNaverDate(x.date, ref)).filter(Boolean).sort((a, b) => (a.y - b.y) || (a.mo - b.mo) || (a.d - b.d));
    if (ds.length > 1) {
      const span = Math.max(1, daysBetween(ds[0], ref) - daysBetween(ds[ds.length - 1], ref));
      n.perMonth = (s.news.length / (span / 30.4)).toFixed(1);
    }
    const cat = {}; s.news.forEach(x => { if (x.cat) cat[x.cat] = (cat[x.cat] || 0) + 1; }); n.catDist = cat;
    n.pinned = s.news.filter(x => x.pinned).map(x => x.title).slice(0, 2);
    n.recentTitles = s.news.slice(0, 5).map(x => `${x.date} ${x.title}`);
  }
  return n;
}

/* ---- 수집 JSON → store/rows/analysis ---- */
function ingestUnified(d, fname) {
  const info = d.업체정보 || {}, stat = d.리뷰통계 || {}, photo = d.사진통계 || {}, newsStat = d.소식통계 || {};
  const pct = v => { if (v == null) return null; const n = parseFloat(String(v).replace('%', '')); return isNaN(n) ? null : n; };
  const store = {
    role: String(d.구분 || '본업체'),
    name: d.업체명 || '', placeId: d.플레이스ID || '', placeUrl: d.URL || '', collectedAt: d.수집일시 || '',
    category: info.카테고리 || '', address: info.주소 || '', roadAddress: info.도로명주소 || '',
    phone: info.전화번호 || '', conveniences: info.편의시설 || [], description: info.소개 || '',
    homepage: info.홈페이지 || '',
    bizStatus: info.영업상태 || '',
    snsList: (info.홈페이지목록 || []).map(h => ({ type: h.유형 || '', url: h.URL || '', main: h.대표 === true })),
    visitorReviewsScore: stat.평균별점 != null ? stat.평균별점 : null,
    visitorReviewsTotal: stat.방문자리뷰수 != null ? stat.방문자리뷰수 : null,
    photoReviewTotal: stat.사진리뷰수 != null ? stat.사진리뷰수 : null,
    blogReviewTotal: stat.블로그리뷰수 != null ? stat.블로그리뷰수 : null,
    reviewThemes: (stat.키워드리뷰 || []).map(k => ({ label: k.키워드, count: k.선택수 })),
    ratingDist: (stat.별점분포 || []).map(r => ({ star: String(r.별점), count: +r.개수 || 0 })),
    replyCountSampled: stat.답글수_수집리뷰중 != null ? stat.답글수_수집리뷰중 : null,
    replyRateSampled: pct(stat.답글율_수집리뷰중),
    receiptCountSampled: stat.영수증리뷰수_수집리뷰중 != null ? stat.영수증리뷰수_수집리뷰중 : null,
    receiptRateSampled: pct(stat.영수증리뷰비중_수집리뷰중),
    photoReviewSampled: stat.사진첨부리뷰수_수집리뷰중 != null ? stat.사진첨부리뷰수_수집리뷰중 : null,
    photoTotal: photo.전체사진수 != null ? photo.전체사진수 : null,
    photoMix: photo.대표사진구성 || null,
    visitorPhotoTotal: photo.방문자등록사진수 != null ? photo.방문자등록사진수 : null,
    menus: (d.메뉴 || []).map(m => ({ name: m.메뉴명 || '', price: m.가격, desc: m.설명 || '', recommend: m.대표메뉴 === true })),
    newsCount: newsStat.소식수_수집기준 != null ? newsStat.소식수_수집기준 : null,
    newsLatest: newsStat.최근소식일 || '',
    news: (d.소식 || []).map(n => ({ title: n.제목 || '', body: n.내용 || '', cat: n.분류 || '', date: n.작성일 || '', pinned: n.고정 === true })),
    extractedCount: d.리뷰수 != null ? d.리뷰수 : null
  };
  if ('톡톡문의' in info) { store.talkTalk = info.톡톡문의 === true; store.talkUrl = info.톡톡URL || ''; }
  if ('예약가능' in info) { store.bookable = info.예약가능 === true; store.bookUrl = info.예약URL || ''; }
  if ('네이버주문' in info) store.naverOrder = Array.isArray(info.네이버주문) ? info.네이버주문.length > 0 : !!info.네이버주문;
  if ('쿠폰' in info) store.coupon = info.쿠폰 === true;
  if ('영업시간' in info) store.bizHours = (info.영업시간 || []).map(h => ({ day: h.요일 || '', hours: h.영업시간 || '', lastOrder: h.라스트오더 || '', breakTime: h.브레이크타임 || '' }));
  if ('클립등록' in photo) store.clipRegistered = photo.클립등록 === true;
  const rows = (Array.isArray(d.리뷰) ? d.리뷰 : []).map(r => ({
    body: r.본문 || '', rating: r.별점, created: r.작성일 || '', visited: r.방문일 || '',
    visitCount: r.방문차수, mediaCount: r.미디어수 != null ? r.미디어수 : null, originType: r.리뷰출처 || '', businessName: '',
    ownerReply: String(r.사장님답글 || ''), keywords: Array.isArray(r.키워드) ? r.키워드 : []
  }));
  const rec = { store, rows, analysis: null, srcName: fname };
  if (rows.length) rec.analysis = analyzeReviews(rows, store);
  return rec;
}
function pickIndustry(s) {
  if (!s) return null;
  const hay = ((s.category || '') + ' ' + (s.name || '') + ' ' + (s.keywordList || []).join(' ')).toLowerCase();
  for (const ind of INDUSTRIES) {
    if (ind.match.some(m => hay.includes(m.toLowerCase()))) return ind.id;
  }
  return null;
}

/* ---- 프롬프트 섹션 ---- */
function storeSection(rec, idx, isComp) {
  const s = rec.store, a = rec.analysis;
  if (!s) return '';
  let p = '';
  const tag = isComp ? `경쟁사 ${idx}` : '본업체';
  p += `\n## [${tag}] ${s.name || ''}\n`;
  p += `- 업종(카테고리): ${s.category || ''}${s.placeId ? ` / 플레이스 ID: ${s.placeId}` : ''}\n`;
  if (s.roadAddress || s.address) p += `- 주소: ${s.roadAddress || s.address}\n`;
  if (!isComp) {
    p += `- 전화: ${s.phone || '미등록(확인 필요)'}\n`;
    if (s.bizHours && s.bizHours.length) {
      p += `- 영업시간: ${s.bizHours.map(h => `${h.day} ${h.hours}${h.lastOrder ? ` (라스트오더 ${h.lastOrder})` : ''}${h.breakTime ? ` (브레이크 ${h.breakTime})` : ''}`).join(' / ')}\n`;
    } else if ('bizHours' in s) p += `- 영업시간: 미등록(확인 필요)\n`;
    if (s.bizStatus) p += `- 수집 시점 영업상태: ${s.bizStatus}\n`;
    if (s.conveniences && s.conveniences.length) p += `- 편의/시설: ${s.conveniences.join(', ')}\n`;
    if (s.description) p += `- 매장 소개문: "${String(s.description).replace(/\n/g, ' ').slice(0, 160)}"\n`;
    if (s.snsList && s.snsList.length) p += `- 연결 채널: ${s.snsList.map(x => `${x.type}${x.main ? '(대표)' : ''} ${x.url}`).join(' / ')}\n`;
    else if (s.homepage) p += `- 홈페이지: ${s.homepage}\n`;
    if (s.collectedAt) p += `- 데이터 수집일시: ${s.collectedAt} (모든 '최근' 판단의 기준일)\n`;
    const comp = completeness(s);
    if (comp && comp.items.length > 4) {
      p += `\n### 플레이스 충실성 체크 (자동 점검: ${comp.done}/${comp.total}항목 등록, ${comp.rate}%)\n`;
      p += `- 등록됨: ${comp.items.filter(([, v]) => v).map(([k]) => k).join(', ') || '없음'}\n`;
      const miss = comp.items.filter(([, v]) => !v).map(([k]) => k);
      p += `- 미등록: ${miss.length ? miss.join(', ') : '없음'}\n`;
      if (miss.length) p += `  → 미등록 항목은 충실성(실) 감점 요인입니다. 항목별로 등록 실익과 우선순위를 판단하세요.\n`;
    }
  }
  p += `\n### 리뷰·노출 통계 (플레이스 공식 수치)\n`;
  if (s.visitorReviewsScore != null) p += `- 평균 별점: ${s.visitorReviewsScore}/5.0\n`;
  if (s.visitorReviewsTotal != null) p += `- 방문자 리뷰 총수: ${(+s.visitorReviewsTotal).toLocaleString()}건\n`;
  if (s.photoReviewTotal != null) p += `- 사진 리뷰 총수: ${(+s.photoReviewTotal).toLocaleString()}건\n`;
  if (s.blogReviewTotal != null) p += `- 블로그 리뷰 총수: ${(+s.blogReviewTotal).toLocaleString()}건\n`;
  const rs = s.reviewStats || {};
  if (rs.imageReviewCount != null) p += `- 사진(이미지) 리뷰: ${rs.imageReviewCount}건 / 전체 ${rs.totalCount || '?'}건\n`;
  if (s.replyRateSampled != null) p += `- 사장님 답글율(수집 리뷰 기준): ${s.replyRateSampled}% (${s.replyCountSampled}건)\n`;
  if (s.receiptRateSampled != null) p += `- 영수증 리뷰 비중(수집 리뷰 기준): ${s.receiptRateSampled}% (${s.receiptCountSampled}건)\n`;
  if (s.ratingDist && s.ratingDist.length) {
    p += `\n### 별점 분포\n`;
    const tot = s.ratingDist.reduce((x, r) => x + r.count, 0) || 1;
    s.ratingDist.slice().sort((x, y) => parseFloat(y.star) - parseFloat(x.star))
      .forEach(r => p += `- ${r.star}점: ${r.count}건 (${Math.round(r.count / tot * 100)}%)\n`);
    if (!isComp) {
      const low = s.ratingDist.filter(r => parseFloat(r.star) < 4).reduce((x, r) => x + r.count, 0);
      p += `  → 4점 미만 ${low}건(${Math.round(low / tot * 100)}%). 분포의 형태를 해석하고, 2026.7.9 별점 공개 환경에서 노출 시 유리한지/불리한지 판단해 **별점 공개 ON/OFF 권고와 근거**를 제시하세요. 3점 미만 리뷰가 있다면 별점 테러 방지 정책(합리적 설명 없는 3점 미만 금지) 활용 가능성도 검토하세요.\n`;
    }
  }
  if (s.photoTotal != null || s.clipRegistered != null) {
    p += `\n### 사진·클립(숏폼) 현황\n`;
    if (s.photoTotal != null) p += `- 플레이스 전체 사진: ${(+s.photoTotal).toLocaleString()}장\n`;
    if (s.photoMix) p += `- 대표사진 구성: 업체 ${s.photoMix.업체 || 0}장 / 클립 ${s.photoMix.클립 || 0}장 / 방문자 ${s.photoMix.방문자 || 0}장\n`;
    if (s.visitorPhotoTotal != null) p += `- 방문자 등록 사진: ${(+s.visitorPhotoTotal).toLocaleString()}장\n`;
    if ('clipRegistered' in s) p += `- 클립(숏폼) 등록: ${s.clipRegistered ? '있음' : '없음'}\n`;
    if (!isComp) {
      if (s.photoMix && (s.photoMix.업체 || 0) < (s.photoMix.방문자 || 0)) p += `  → 대표사진에서 업체 등록분이 방문자분보다 적습니다. 대표사진 통제권(첫인상 관리) 관점에서 진단하세요.\n`;
      p += `  → 클립은 2026 로직의 클릭률 핵심 변수입니다. ${s.clipRegistered ? '등록되어 있으므로 업로드 주기·품질을' : '미등록이므로 도입 우선순위를'} 진단하세요.\n`;
    }
  }
  const na = newsActivity(s);
  if (na) {
    p += `\n### 소식(게시글) 활동성\n`;
    p += `- 소식 수(수집 기준): ${na.count}건${na.latest ? ` / 최근 게시일: ${na.latest}${na.daysSince != null ? ` (수집일 기준 ${na.daysSince}일 전)` : ''}` : ''}\n`;
    if (na.perMonth) p += `- 게시 빈도: 월평균 약 ${na.perMonth}건\n`;
    if (na.catDist) p += `- 분류: ${Object.entries(na.catDist).map(([k, v]) => `${k} ${v}건`).join(', ')}\n`;
    if (na.pinned && na.pinned.length) p += `- 고정 소식: ${na.pinned.map(t => `"${t}"`).join(', ')}\n`;
    if (!isComp && na.recentTitles) p += `- 최근 소식 제목: ${na.recentTitles.map(t => `"${t}"`).join(' / ')}\n  → 소식의 주제·키워드 활용도(지역명+메뉴 삽입 여부)와 게시 주기의 적정성을 진단하세요.\n`;
  }
  if (s.keywordList && s.keywordList.length) p += `\n### 대표 키워드(네이버 등록)\n- ${s.keywordList.join(', ')}\n`;
  if (s.reviewThemes && s.reviewThemes.length) p += `\n### 키워드 리뷰 분포 (고객이 선택한 항목 Top)\n- ${s.reviewThemes.slice(0, isComp ? 6 : 12).map(t => `${t.label}(${t.count})`).join(', ')}\n${isComp ? '' : '  → 상위 항목은 검색 노출·소개문·소식 콘텐츠에 재활용할 \'고객 인증 강점\'입니다.\n'}`;
  if (s.reviewMenus && s.reviewMenus.length) p += `\n### 리뷰에서 언급된 메뉴 TOP\n- ${s.reviewMenus.slice(0, 10).map(m => `${m.label}(${m.count})`).join(', ')}\n`;
  if (s.menus && s.menus.length) {
    p += `\n### 등록 메뉴/가격 (${s.menus.length}개${s.menus.some(m => m.recommend) ? `, 대표 ${s.menus.filter(m => m.recommend).length}개` : ''})\n`;
    const list = isComp ? s.menus.filter(m => m.recommend).slice(0, 5) : s.menus.slice(0, 14);
    list.forEach(m => p += `- ${m.name}: ${m.price ? (+m.price).toLocaleString() + '원' : '가격미상'}${m.recommend ? ' [대표]' : ''}${m.desc && !isComp ? ` — ${String(m.desc).slice(0, 40)}` : ''}\n`);
    if (!isComp && s.menus.length > 14) p += `…(외 ${s.menus.length - 14}개)\n`;
  }
  return p;
}
function reviewSection(rec) {
  const a = rec.analysis;
  if (!a || !a.total) return '';
  let p = `\n# ② 추출 리뷰 원문 분석 (본업체 · ${a.total}건 표본)\n`;
  p += `- 텍스트 작성 리뷰 ${a.textedCount}건 / 텍스트 없음 ${a.emptyCount}건\n`;
  if (a.avgRating) p += `- 추출 표본 평균 별점: ${a.avgRating}/5.0 (별점 기재 ${a.ratingCount}건, 미기재 ${a.noRatingCount}건)\n`;
  if (a.sentimentOK) p += `- **감성분석 추정 만족도: ${a.estScore}/5.0** — 긍정 ${a.pos}건(${a.posRate}%), 부정 ${a.neg}건(${a.negRate}%), 중립 ${a.neu}건\n`;
  else p += `- 감성분석: 리뷰 본문 없음 → 측정 불가 (정량 지표만 활용)\n`;
  if (a.recent) p += `- 리뷰 기간: ${a.oldest} ~ ${a.recent} (수집일 기준 최신 리뷰 약 ${a.daysSinceLast}일 전 · 최근 90일 ${a.recent90}건 · 최근 1년 ${a.recent365}건)\n`;
  if (a.originDist) p += `- 리뷰 출처 분포: ${Object.entries(a.originDist).map(([k, v]) => `${k} ${v}건`).join(', ')} → 영수증·예약 리뷰는 방문 인증 신뢰 신호입니다.\n`;
  if (a.mediaRate != null) p += `- 사진 첨부율: ${a.mediaRate}% (총 ${a.mediaTotal}장)\n`;
  if (a.revisitRate != null) p += `- 재방문(방문차수 2회 이상) 리뷰 비율: ${a.revisitRate}%${a.maxVisit > 1 ? ` (최대 방문차수 ${a.maxVisit}회)` : ''}\n`;
  if (a.replyRate != null) {
    p += `- 사장님 답글율(표본): ${a.replyRate}% (${a.replyCount}/${a.total}건)${a.lowNoReply ? ` / ⚠ 저별점(4점 미만) 미답글 ${a.lowNoReply}건` : ''}\n`;
    if (a.replySamples && a.replySamples.length) p += `- 기존 답글 스타일 예시: ${a.replySamples.map(s => `"${s}…"`).join(' / ')}\n  → 답글 톤·품질을 평가하고, 답글 템플릿 제안 시 이 톤과의 일관성을 고려하세요.\n`;
    if (a.negNoReply && a.negNoReply.length) p += `- 답글 없는 부정 리뷰(우선 대응 대상): ${a.negNoReply.map(s => `"${s}…"`).join(' / ')}\n`;
  }
  if (a.reviewKeywords && a.reviewKeywords.length) p += `\n## 추출 리뷰에서 고객이 직접 선택한 키워드\n- ${a.reviewKeywords.slice(0, 15).map(([w, c]) => `${w}(${c})`).join(', ')}\n  → 위 ①의 키워드 리뷰 분포와 교차 검증해 일관된 강점/누락된 강점을 찾으세요.\n`;
  if (a.nameVariants && a.nameVariants.length > 1) {
    p += `\n## ⚠ 상호명 변동 감지 (NAP 일관성 위험)\n`;
    a.nameVariants.forEach(([n, c]) => p += `- "${n}": ${c}건\n`);
  }
  if (a.topWords && a.topWords.length) p += `\n## 리뷰 본문 빈출 키워드\n- ${a.topWords.map(([w, c]) => `${w}(${c})`).join(', ')}\n  → 고객이 인식하는 매장 정체성이자 검색 유입 키워드 후보.\n`;
  if (a.posSamples && a.posSamples.length) p += `\n## 대표 긍정 리뷰\n${a.posSamples.map(s => `- "${s}…"`).join('\n')}\n`;
  if (a.negSamples && a.negSamples.length) p += `\n## 대표 부정 리뷰 (답변 전략 수립에 활용)\n${a.negSamples.map(s => `- "${s}…"`).join('\n')}\n`;
  const lim = state.depth === 'deep' ? 40 : state.depth === 'standard' ? 25 : 12;
  const texted = rec.rows.filter(r => String(r.body || '').trim());
  if (texted.length) {
    p += `\n## 원본 리뷰 본문 (직접 인용용)\n`;
    texted.slice(0, lim).forEach(r => {
      const kw = (r.keywords && r.keywords.length) ? `|키워드:${r.keywords.slice(0, 3).join(',')}` : '';
      const src = r.originType ? `|${r.originType}` : '';
      const rep = ('ownerReply' in r) ? (String(r.ownerReply || '').trim() ? '|답글O' : '|답글X') : '';
      p += `- [${r.created || ''}|별점 ${r.rating !== '' && r.rating != null ? r.rating : '미기재'}|방문 ${r.visitCount != null ? r.visitCount : '?'}회차${src}${rep}${kw}] ${String(r.body).replace(/\n/g, ' ').slice(0, 180)}\n`;
    });
    if (texted.length > lim) p += `…(외 ${texted.length - lim}건, 전체 ${texted.length}건)\n`;
  }
  return p;
}

/* ---- 프롬프트 본체 ---- */
function buildPrompt() {
  const ind = INDUSTRIES.find(i => i.id === state.industry) || INDUSTRIES[0];
  const dep = DEPTH_SPEC[state.depth];
  const modeNames = state.modes.map(m => MODE_META[m].name).join(' + ');
  const roles = state.modes.map(m => MODE_FOCUS[m].role);
  const m = state.main, s = m && m.store, a = m && m.analysis;
  const comps = state.competitors;
  const bizName = (s && s.name) || '[업체명]';

  let p = `# 역할(Role)
당신은 한국 로컬 비즈니스 전문 디지털 마케팅 컨설턴트입니다. 다음 전문성을 보유합니다:
${roles.map(r => '- ' + r).join('\n')}
대상 검색 환경: ${state.modes.map(mm => MODE_META[mm].engine).join(' / ')}

# 과업(Task)
아래 **네이버 플레이스 실제 수집 데이터(업체정보·충실성·사진/클립·소식·메뉴·리뷰통계·리뷰 원문${comps.length ? ' + 경쟁사 실측 데이터' : ''})** 를 근거로, 「${ind.nm}」 업종 「${bizName}」에 대한 **${modeNames}** 진단 보고서를 작성하세요.
보고서 깊이: **${dep.label}** — ${dep.detail}

⚠️ 중요: 추측이 아니라 아래 제공된 실제 수치·리뷰 문장을 인용·근거로 사용하세요.

` + ALGO_2026;

  if (s) {
    p += `\n# ① 업체 데이터 (네이버 플레이스 실측)`;
    p += storeSection(m, 0, false);
  }
  if (m) p += reviewSection(m);

  if (comps.length) {
    p += `\n# ③ 경쟁사 실측 데이터 (${comps.length}곳 · 동일 방식 수집)\n`;
    comps.forEach((c, i) => {
      p += storeSection(c, i + 1, true);
      const ca = c.analysis;
      if (ca && ca.total) {
        p += `\n### [경쟁사 ${i + 1}] 추출 리뷰 요약 (${ca.total}건)\n`;
        if (ca.avgRating) p += `- 추출 평균 별점 ${ca.avgRating}/5.0`;
        if (ca.sentimentOK) p += ` / 긍정 ${ca.posRate}% · 부정 ${ca.negRate}%`;
        p += '\n';
        if (ca.replyRate != null) p += `- 답글율 ${ca.replyRate}%`;
        if (ca.revisitRate != null) p += ` / 재방문 리뷰 ${ca.revisitRate}%`;
        if (ca.recent90 != null) p += ` / 최근 90일 리뷰 ${ca.recent90}건`;
        p += '\n';
        if (ca.reviewKeywords && ca.reviewKeywords.length) p += `- 고객 선택 키워드 Top: ${ca.reviewKeywords.slice(0, 5).map(([w, cc]) => `${w}(${cc})`).join(', ')}\n`;
        if (ca.topWords && ca.topWords.length) p += `- 리뷰 빈출어: ${ca.topWords.slice(0, 8).map(([w, cc]) => `${w}(${cc})`).join(', ')}\n`;
      }
    });
    p += `\n→ **경쟁사 비교는 위 실측 데이터로 수행하세요 (가정 금지).** 평균별점·리뷰량·답글율·충실성·활동성·키워드리뷰를 항목별 매트릭스로 비교하고, 본업체만의 차별화 포지셔닝과 경쟁사가 놓친 '비어 있는 키워드'를 도출하세요.\n`;
  }

  if (!s && !(a && a.total)) p += `\n# 데이터\n- (JSON 미업로드 — 일반 ${ind.nm} 기준으로 작성하고 필요한 데이터를 보고서 말미에 요청)\n`;

  p += `\n# 평가 프레임워크\n`;
  state.modes.forEach(mm => { p += `\n## ${MODE_META[mm].name} 핵심 평가 축\n`; MODE_FOCUS[mm].pillars.forEach(x => p += `- ${x}\n`); });
  p += `\n## 「${ind.nm}」 업종별 세부 평가 항목 (각 100점 환산)\n`;
  ind.crit.forEach((c, i) => p += `${i + 1}. ${c}\n`);
  p += `\n키워드 전략 기준: ${ind.kw}\n`;

  p += `\n# 출력 형식\n`;
  if (state.depth === 'quick') {
    p += `1. 한 줄 종합 진단\n2. 핵심 5개 항목 ⭕/⚠️/❌ 점검 (위 수치·리뷰 근거 포함)\n3. 지금 당장 할 일 TOP 3~5 (효과 큰 순)\n4. A4 1페이지 이내\n`;
  } else if (state.depth === 'standard') {
    p += `1. 종합 점수(100점) + 등급(S/A/B/C/D)\n2. 항목별 진단표: 점수/현재상태(데이터 근거)/문제점/개선방향 (표)\n3. **리뷰·매장 인사이트**: 평균별점·별점분포·키워드리뷰·감성·답글율·재방문율을 근거로 강점/약점 도출\n4. **별점 공개 대응 판단**: 위 별점 데이터 기준 ON/OFF 권고 + 별점 관리 루틴\n5. 우선순위 액션플랜 (High/Mid/Low + 예상효과 + 난이도 + 담당: 사장님 직접/외부 지원)\n6. 사장님용 쉬운 요약 3~4문장 (전문용어 없이)\n`;
  } else {
    p += `1. **Executive Summary**: 종합 점수(100점)·등급(S/A/B/C/D) + 현황 진단 핵심 3문장 + 핵심 기회 영역 Top 3\n2. **항목별 정밀 진단표** (점수/데이터 근거/문제/개선안) — 충실성 체크·사진/클립·소식 활동성·답글율을 각각 독립 항목으로 채점\n3. **리뷰 심층 분석**: ▸별점분포 해석 + 별점 공개 ON/OFF 권고 ▸감성·긍정/부정 패턴 ▸키워드리뷰 강약점 ▸답글율·미답글 부정리뷰 대응 ▸재방문율·최신성·출처(영수증/예약) 신뢰도 ▸빈출 키워드로 본 고객 인식\n4. **키워드 전략 (3계층)**: ▸지역+메뉴형 ▸메뉴+트렌드형 ▸고민해결형 — 키워드리뷰·등록 메뉴(대표메뉴·가격)·소식 제목을 교차해 설계하고 우선순위 매트릭스로 제시\n5. **경쟁사 비교 + SWOT**${comps.length ? ' — 위 ③ 실측 데이터 기반 매트릭스 (가정 금지)' : ' (같은 지역·업종 상위 2~3곳 가정, 강약점 매트릭스)'} → 차별화 포지셔닝 + 비어 있는 키워드\n6. **30일 실행 로드맵** (주차별 과제 + 담당 구분: 사장님 직접/외부 지원 + 예상 소요시간)\n7. **복사·붙여넣기 실행 키트**: ▸업체 소개문구 1개(키워드 자연 삽입) ▸소식 게시글 2개(기존 소식 톤 참고) ▸리뷰 답변 템플릿 3개(긍정/중립/저별점 — 기존 답글 톤과 일관되게, 위 미답글 부정 리뷰 모범답변 포함) ▸리뷰·별점 요청 멘트 1개(어뷰징 없이)\n8. **KPI 및 시나리오**: 추적 지표(평균별점·별점분포·리뷰수·답글율·최근90일 유입·재방문율·저장·길찾기·블로그리뷰·클립) + 측정 방법 + 30/60/90일 낙관·기본·보수 시나리오\n`;
  }
  if (state.modes.includes('geo'))
    p += `\n# GEO 추가 지침\n- 위 키워드리뷰·빈출어·메뉴를 '엔티티 신호'로 활용해 AI가 이 매장을 어떤 업체로 인식할지 분석. 연결 채널(SNS·홈페이지)과 플레이스 정보의 엔티티 일관성도 점검\n- AI가 인용하기 좋은 고유 사실(평균별점 ${(s && s.visitorReviewsScore) != null ? s.visitorReviewsScore : (a && a.estScore) || ''}, 방문자리뷰 ${(s && s.visitorReviewsTotal) != null ? s.visitorReviewsTotal : (a && a.total) || ''}건, 블로그리뷰 ${(s && s.blogReviewTotal) != null ? s.blogReviewTotal : ''}건, 대표메뉴·가격, 대표 강점 '${(s && s.reviewThemes && s.reviewThemes[0] && s.reviewThemes[0].label) || ''}' 등)을 콘텐츠에 심는 방법 제안\n`;
  if (state.modes.includes('aeo'))
    p += `\n# AEO 추가 지침\n- 키워드리뷰·메뉴·편의시설(주차·유아의자·단체석 등)을 바탕으로 음성검색 예상 질문 10개 + 40자 이내 즉답 설계\n- 적용할 Schema 명시 (LocalBusiness, Restaurant, FAQPage, Review, AggregateRating, Menu 등)\n`;

  p += `\n# 작성 원칙
- 모든 진단은 위 통계·리뷰 문장을 근거로 인용하세요. (예: "평균별점 ${(s && s.visitorReviewsScore) != null ? s.visitorReviewsScore : 'X'}점, 키워드리뷰 1위 '${(s && s.reviewThemes && s.reviewThemes[0] && s.reviewThemes[0].label) || '음식이 맛있어요'}' ${(s && s.reviewThemes && s.reviewThemes[0] && s.reviewThemes[0].count) || ''}회")
- 데이터에 없는 항목은 추측하지 말고 '확인 필요(스마트플레이스 관리자 화면에서 확인)'로 명시하세요. 출처 없는 통계·수치를 만들어내지 마세요.
- '최근/최신' 판단은 반드시 데이터 수집일(${(s && s.collectedAt) ? String(s.collectedAt).slice(0, 10) : '수집일 미상'}) 기준으로 하세요. 별점 공개(2026.7.9)는 이미 시행된 사건으로 다루세요.
- 모든 권고는 측정 가능한 수치·빈도로 제시하세요. "사진 많이"(X) → "음식 사진 30장 + 매장 20장"(O). "꾸준히 노력" 같은 두루뭉술한 표현 금지.
- 어뷰징(가짜 리뷰, 유사 문장 복붙, 키워드 도배, 단기간 리뷰 몰기)은 절대 권고하지 말고, 하면 안 되는 행위로 명시하세요.
- 한국 ${ind.nm} 시장과 네이버 생태계 특성(C-Rank, D.I.A.+, 별점 공개, 맞춤노출, 영수증·블로그 리뷰, 소식, 클립, 예약)을 반영하세요.
- 클라이언트(사장님) 제출용 전문 보고서 어조로 작성하되, 전문 용어는 쉬운 말+괄호 병기로 풀어 쓰세요.

지금부터 위 데이터를 근거로 보고서를 작성해 주세요.`;
  return p;
}

/* ---- 외부 진입점 ---- */
function generate(resultJson, opts) {
  opts = opts || {};
  state.modes = (opts.modes && opts.modes.length) ? opts.modes : ['seo'];
  state.depth = opts.depth || 'standard';
  const rec = ingestUnified(resultJson || {}, (resultJson && resultJson.업체명) || 'place');
  state.main = rec; state.competitors = [];
  (opts.competitors || []).forEach(cj => { state.competitors.push(ingestUnified(cj, (cj && cj.업체명) || 'comp')); });
  if (opts.industry) state.industry = opts.industry;
  else { const id = pickIndustry(rec.store); if (id) state.industry = id; }
  return { prompt: buildPrompt(), industry: state.industry, store: rec.store, analysis: rec.analysis };
}

const PF = { generate, ingestUnified, buildPrompt, pickIndustry, INDUSTRIES, DEPTH_SPEC, MODE_META, MODE_FOCUS, state };
if (typeof window !== 'undefined') window.PromptForge = PF;
if (typeof module !== 'undefined' && module.exports) module.exports = PF;
})();
