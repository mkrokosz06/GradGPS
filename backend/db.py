"""
DynamoDB + S3 clients.
Points to local Docker containers in dev (DYNAMODB_ENDPOINT / S3_ENDPOINT set in .env).
Points to real AWS in production (those vars absent).
"""

import os
import boto3
from dotenv import load_dotenv

load_dotenv()

_region       = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
_dynamo_url   = os.getenv("DYNAMODB_ENDPOINT")   # http://localhost:8000 in dev
_s3_url       = os.getenv("S3_ENDPOINT")          # http://localhost:9000 in dev


def get_dynamodb():
    kwargs = dict(region_name=_region)
    if _dynamo_url:
        kwargs["endpoint_url"] = _dynamo_url
    return boto3.resource("dynamodb", **kwargs)


def get_s3():
    kwargs = dict(region_name=_region)
    if _s3_url:
        kwargs["endpoint_url"]              = _s3_url
        kwargs["config"]                    = boto3.session.Config(signature_version="s3v4")
    return boto3.client("s3", **kwargs)


# Pre-built table handles used by routers
_db = get_dynamodb()

requirements_table = _db.Table("requirements")
users_table        = _db.Table("users")
transcript_table   = _db.Table("transcript_courses")
