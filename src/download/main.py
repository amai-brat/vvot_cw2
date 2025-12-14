import json
import logging
import boto3
import boto3.exceptions
import boto3.session
import ydb
import uuid
from dotenv import load_dotenv
from config import Config
import requests
from io import BytesIO

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def add_doc_to_db(config: Config, name: str, url: str) -> str:
    logger.info(f"Saving to database")

    id = uuid.uuid4()

    driver_config = ydb.DriverConfig(
        config.ydb_endpoint, 
        config.ydb_database, 
        credentials=ydb.credentials_from_env_variables(),
        root_certificates=ydb.load_ydb_root_certificate(),
    )

    with ydb.Driver(driver_config) as driver:
        try:
            driver.wait(timeout=5)
            with ydb.QuerySessionPool(driver) as pool:
                pool.execute_with_retries(
                    f"""
                    UPSERT INTO `{config.ydb_docs_table_name}` (
                        doc_id, name, url
                    ) VALUES (
                        $docId,
                        $name,
                        $url
                    );
                    """,
                    {
                        "$docId": (id, ydb.PrimitiveType.UUID),
                        "$name": (name, ydb.PrimitiveType.Utf8),
                        "$url": (url, ydb.PrimitiveType.Utf8),
                    }
                )
        except TimeoutError:
            logger.warning(f"Connect failed to YDB. Last reported errors by discovery: {driver.discovery_debug_details()}")
            exit(1)
    return str(id)


def download_doc_to_s3(config: Config, doc_id: str, doc_name: str, url: str):
    logger.info(f"Downloading {url} to bucket {config.s3_bucket_name}")
    
    MAX_SIZE = 10 * 1024 * 1024
    
    session = boto3.session.Session()
    s3 = session.client(
        service_name='s3',
        endpoint_url="https://storage.yandexcloud.net",
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )
    
    error_message = None
    
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        content_length = response.headers.get('content-length')
        if content_length:
            file_size = int(content_length)
            if file_size > MAX_SIZE:
                error_message = f"File size ({file_size} bytes) exceeds 10MB limit"
                raise Exception(error_message)
        
        file_buffer = BytesIO(response.content)
        s3.upload_fileobj(
            file_buffer,
            config.s3_bucket_name,
            doc_id,
            ExtraArgs={
                'ContentType': response.headers.get('content-type', 'application/octet-stream'),
                'ContentDisposition': f'attachment; filename="{doc_name}"'
            }
        )
        
        logger.info(f"Successfully uploaded {doc_id} to S3")
        return doc_id
        
    except Exception as e:
        if not error_message:
            if isinstance(e, requests.exceptions.RequestException):
                error_message = f"Failed to download from URL: {str(e)}"
            elif isinstance(e, boto3.exceptions.S3UploadFailedError):
                error_message = f"S3 upload failed: {str(e)}"
            else:
                error_message = f"Failed to process document: {str(e)}"
        
        logger.error(error_message)
        
        try:
            error_buffer = BytesIO(error_message.encode('utf-8'))
            s3.upload_fileobj(
                error_buffer,
                config.s3_bucket_name,
                doc_id,
                ExtraArgs={
                    'ContentType': 'text/plain',
                    'ContentDisposition': f'attachment; filename="{doc_id}_error.txt"'
                }
            )
            logger.info(f"Error message uploaded to S3 for document {doc_id}")
        except Exception as s3_error:
            logger.error(f"Failed to upload error message to S3: {str(s3_error)}")


def handler(event, context):
    try:
        logger.info(f"Event: {json.dumps(event, ensure_ascii=False)}")
        load_dotenv(".env")
        config = Config()
        
        for message in event["messages"]:
            body = json.loads(message['details']['message']['body'])
            name = body['name']
            url = body['url']

            if not name or not url:
                return { 
                    'statusCode': 400,  
                    'headers': {
                        'Content-Type': 'text/plain'
                    },
                    'body': 'name or url are not set' 
                }
            
            logger.info(f"Received data: name={name}, url={url}")
            
            doc_id = add_doc_to_db(config, name, url)

            download_doc_to_s3(config, doc_id, name, url)

        return { 'statusCode': 200 }
        
    except Exception as e:
        logger.error(f"Error in handler: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'text/plain'
            },
            'body': f'Error occurred: {str(e)}'
        }
