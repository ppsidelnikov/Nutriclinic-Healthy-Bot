import sys
from pathlib import Path
import os, mimetypes, hashlib
import boto3
from botocore.config import Config
S3_ENDPOINT = os.environ.get('S3_ENDPOINT')
S3_BUCKET = os.environ.get('S3_BUCKET')
S3_ACCESS_KEY = os.environ.get('S3_ACCESS_KEY')
S3_SECRET_KEY = os.environ.get('S3_SECRET_KEY')
S3_REGION = os.environ.get('S3_REGION')
S3_FORCE_PATH_STYLE = os.environ.get('S3_FORCE_PATH_STYLE')

session = boto3.session.Session(
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION,
)

cfg = {}
if str(S3_FORCE_PATH_STYLE).lower() == "true":
    cfg["s3"] = {"addressing_style": "path"}

s3 = session.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    config=Config(**cfg) if cfg else None,
)

BUCKET = S3_BUCKET

def ensure_bucket():
    try:
        s3.head_bucket(Bucket=BUCKET)
    except Exception:
        s3.create_bucket(Bucket=BUCKET)

def upload_file(local_path: str, key: str):
    mime, _ = mimetypes.guess_type(local_path)
    if not mime:
        mime = "application/octet-stream"

    with open(local_path, "rb") as f:
        data = f.read()
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=data,
        ContentType=mime,
        Metadata={"sha256": hashlib.sha256(data).hexdigest()},
    )
    return key

def list_keys(prefix: str = ""):
    out = []
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    for obj in resp.get("Contents", []):
        out.append({"key": obj["Key"], "bytes": obj["Size"]})
    return out

def download_bytes(key: str) -> bytes:
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    return obj["Body"].read()

def presigned_get_url(key: str, ttl_sec: int = 3600) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=ttl_sec,
    )

