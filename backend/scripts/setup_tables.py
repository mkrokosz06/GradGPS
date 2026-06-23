"""
Creates all DynamoDB tables.
Run once against LocalStack before development, and once against real AWS before production.

Usage:
    python scripts/setup_tables.py
"""

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import boto3
from dotenv import load_dotenv
load_dotenv()

dynamo_url = os.getenv("DYNAMODB_ENDPOINT")
s3_url     = os.getenv("S3_ENDPOINT")
region     = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

dynamo_kwargs = dict(region_name=region)
if dynamo_url:
    dynamo_kwargs["endpoint_url"] = dynamo_url

s3_kwargs = dict(region_name=region)
if s3_url:
    s3_kwargs["endpoint_url"] = s3_url

dynamodb = boto3.client("dynamodb", **dynamo_kwargs)
s3       = boto3.client("s3", **s3_kwargs)


# ── 1. requirements ──────────────────────────────────────────────────────────
# PK: program_name   SK: group_course  (requirement_group + "#" + course_code)
# Query: all rows for a major → KeyConditionExpression PK = "Forensic Science, B.S."
# GSI on course_code for reverse lookup (which programs need CHEM 110?)

try:
    dynamodb.create_table(
        TableName="requirements",
        KeySchema=[
            {"AttributeName": "program_name", "KeyType": "HASH"},
            {"AttributeName": "group_course",  "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "program_name", "AttributeType": "S"},
            {"AttributeName": "group_course",  "AttributeType": "S"},
            {"AttributeName": "course_code",   "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "course_code-index",
                "KeySchema": [
                    {"AttributeName": "course_code", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    print("Created table: requirements")
except dynamodb.exceptions.ResourceInUseException:
    print("Table already exists: requirements")


# ── 2. users ─────────────────────────────────────────────────────────────────
# PK: user_id  (Google/Apple sub claim — unique per user)

try:
    dynamodb.create_table(
        TableName="users",
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    print("Created table: users")
except dynamodb.exceptions.ResourceInUseException:
    print("Table already exists: users")


# ── 3. transcript_courses ────────────────────────────────────────────────────
# PK: user_id   SK: course_code
# One row per course per student. Re-upload overwrites (PutItem upsert).

try:
    dynamodb.create_table(
        TableName="transcript_courses",
        KeySchema=[
            {"AttributeName": "user_id",     "KeyType": "HASH"},
            {"AttributeName": "course_code",  "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id",     "AttributeType": "S"},
            {"AttributeName": "course_code",  "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    print("Created table: transcript_courses")
except dynamodb.exceptions.ResourceInUseException:
    print("Table already exists: transcript_courses")


# ── 4. S3 bucket for transcript PDFs ─────────────────────────────────────────

bucket = os.getenv("S3_BUCKET", "degreecheck-transcripts")
try:
    s3.create_bucket(Bucket=bucket)
    print(f"Created S3 bucket: {bucket}")
except s3.exceptions.BucketAlreadyOwnedByYou:
    print(f"S3 bucket already exists: {bucket}")
except Exception as e:
    print(f"S3 bucket note: {e}")

print("\nAll tables and buckets ready.")
