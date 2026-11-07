"""Durable owner-scoped storage. No customer data is written to the app filesystem."""
import copy
import gzip
import hashlib
import json
import uuid
from datetime import datetime, timezone

from google.cloud import firestore
from google.oauth2 import service_account


class ConflictError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identity(fm, kind="customer"):
    return digest(json.dumps([kind] + [str(fm.get(k) or "").strip().casefold()
                  for k in ("상호", "지역", "연락처", "이메일주소")], ensure_ascii=False))


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, credentials, owner, database="(default)"):
        creds = service_account.Credentials.from_service_account_info(dict(credentials))
        self.client = firestore.Client(project=credentials["project_id"], credentials=creds, database=database)
        self.root = self.client.collection("crm_owners").document(digest(owner.strip().casefold()))
        self.cards = self.root.collection("cards")
        self.surveys = self.root.collection("surveys")
        self.identities = self.root.collection("identities")

    def list_cards(self, kind="customer", deleted=False):
        values = [{"id": snap.id, **snap.to_dict()} for snap in self.cards.stream()]
        return sorted((v for v in values if v.get("kind", "customer") == kind and bool(v.get("deleted")) == deleted),
                      key=lambda v: v.get("fm", {}).get("상호", ""))

    def get(self, ident):
        snap = self.cards.document(ident).get()
        return {"id": snap.id, **snap.to_dict()} if snap.exists else None

    def create(self, fm, body="", kind="customer", source_id=None, legacy_id=None, deleted=False):
        fm = copy.deepcopy(fm)
        if not str(fm.get("상호", "")).strip():
            raise ValueError("매장명을 입력해 주세요.")
        ref = self.cards.document(legacy_id or ("form_" + source_id if source_id else uuid.uuid4().hex))
        identity_ref = self.identities.document(identity(fm, kind))
        source_ref = self.surveys.document(source_id) if source_id else None
        transaction = self.client.transaction()

        @firestore.transactional
        def commit(tx):
            old = ref.get(transaction=tx)
            existing_identity = identity_ref.get(transaction=tx)
            previous_source = source_ref.get(transaction=tx) if source_ref else None
            if previous_source and previous_source.exists and not legacy_id:
                return previous_source.to_dict()["card_id"], False
            if old.exists:
                return ref.id, False
            if existing_identity.exists and not legacy_id:
                existing_id = existing_identity.to_dict()["card_id"]
                if source_ref:
                    tx.set(source_ref, {"card_id": existing_id, "created_at": timestamp()})
                return existing_id, False
            data = {"fm": fm, "body": body, "kind": kind, "deleted": deleted,
                    "revision": 1, "created_at": timestamp(), "updated_at": timestamp()}
            if len(json.dumps(data, ensure_ascii=False).encode()) > 850_000:
                raise ValueError("카드 본문이 너무 큽니다. 전체 보고서는 보고서 보관함에 저장해 주세요.")
            tx.create(ref, data)
            if not existing_identity.exists:
                tx.set(identity_ref, {"card_id": ref.id})
            if source_ref and (not previous_source.exists or not deleted):
                tx.set(source_ref, {"card_id": ref.id, "created_at": timestamp()})
            return ref.id, True
        return commit(transaction)

    def update(self, ident, expected_revision, fm=None, body=None, deleted=None):
        ref = self.cards.document(ident)
        transaction = self.client.transaction()

        @firestore.transactional
        def commit(tx):
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise ValueError("카드를 찾을 수 없습니다.")
            old = snap.to_dict()
            if old["revision"] != expected_revision:
                raise ConflictError("다른 화면에서 수정되었습니다. 다시 읽고 변경 내용을 확인해 주세요.")
            value = copy.deepcopy(old)
            if fm is not None:
                value["fm"] = copy.deepcopy(fm)
            if body is not None:
                value["body"] = body
            if deleted is not None:
                value["deleted"] = deleted
                value["deleted_at"] = timestamp() if deleted else ""
            value["revision"] += 1
            value["updated_at"] = timestamp()
            if len(json.dumps(value, ensure_ascii=False).encode()) > 850_000:
                raise ValueError("카드 본문이 너무 큽니다.")
            old_key = identity(old["fm"], old.get("kind", "customer"))
            new_key = identity(value["fm"], value.get("kind", "customer"))
            old_identity = self.identities.document(old_key)
            new_identity = self.identities.document(new_key)
            previous_index = old_identity.get(transaction=tx) if old_key != new_key else None
            next_index = new_identity.get(transaction=tx) if old_key != new_key else None
            if next_index and next_index.exists and next_index.to_dict()["card_id"] != ident:
                raise ConflictError("동일한 매장·연락 정보로 등록된 카드가 있습니다.")
            tx.set(ref, value)
            if old_key != new_key:
                if previous_index.exists and previous_index.to_dict()["card_id"] == ident:
                    tx.delete(old_identity)
                tx.set(new_identity, {"card_id": ident})
            return {"id": ident, **value}
        return commit(transaction)

    def put_asset(self, name, raw, content_type="application/octet-stream", category="file"):
        packed = gzip.compress(raw)
        ident = digest(category + ":" + name + ":" + hashlib.sha256(raw).hexdigest())
        ref = self.root.collection("assets").document(ident)
        if ref.get().exists:
            return ident
        chunks = [packed[i:i + 400_000] for i in range(0, len(packed), 400_000)] or [b""]
        if len(packed) > 8_000_000:
            raise ValueError("보관 파일은 압축 후 8MB 이하여야 합니다.")
        batch = self.client.batch()
        for number, chunk in enumerate(chunks):
            batch.set(ref.collection("chunks").document(str(number)), {"data": chunk})
        batch.set(ref, {"name": name, "content_type": content_type, "category": category,
                        "chunks": len(chunks), "sha256": hashlib.sha256(raw).hexdigest(), "created_at": timestamp()})
        batch.commit()
        return ident

    def list_assets(self):
        return [{"id": v.id, **v.to_dict()} for v in self.root.collection("assets").stream()]

    def get_asset(self, ident):
        ref = self.root.collection("assets").document(ident)
        meta = ref.get().to_dict()
        if not meta:
            raise ValueError("보관 파일을 찾지 못했습니다.")
        raw = gzip.decompress(b"".join(ref.collection("chunks").document(str(i)).get().to_dict()["data"]
                                       for i in range(meta["chunks"])))
        if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
            raise ValueError("보관 파일 무결성 확인에 실패했습니다.")
        return meta, raw

    def survey_state(self):
        return {v.id: v.to_dict() for v in self.surveys.stream()}
